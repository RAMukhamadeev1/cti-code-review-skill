# Apex Triggers Code Review Guide

Review rules for Apex triggers and their handlers, including platform-event and Change Data Capture triggers: trigger architecture, context variables, per-chunk rules, recursion, automation overlap, event subscribers, and trigger tests.

> Load [platform.md](platform.md) first (limits and chunk math, order of execution, security model, severity) and [apex.md](apex.md) for handler code. Related: [Flows](flows.md) · [Validation rules](metadata.md#validation-rules)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Architecture → [Trigger Architecture](#trigger-architecture)

- [ ] One trigger per object, no logic in its body, dispatching through the repo's existing handler framework
- [ ] A bypass uses a custom permission or Custom Metadata, never profile names, usernames, or Ids
- [ ] Queries and DML in the trigger body and handler state their access mode; each system-mode use is commented (trigger bodies run in user mode from API 67.0)
- [ ] A `.trigger-meta.xml` bump across 67.0 was reviewed as a behavior change

### Context → [Context Variables](#context-variables)

- [ ] Same-record changes happen in before triggers; related records, events, and jobs in after triggers
- [ ] Context variables are read only in events that provide them; `Trigger.new` isn't changed after the save; no `Trigger.new[0]`
- [ ] Update logic compares with `Trigger.oldMap`; validation uses `addError`, never `addError(message, false)` with user text

### Chunks → [Bulk Safety per Chunk](#bulk-safety-per-chunk)

- [ ] Queries and DML per chunk × chunks fit the transaction with the other automation
- [ ] Statics cache and deduplicate but never accumulate records; no callouts
- [ ] Enqueues happen once per transaction, guarded by `Limits.getQueueableJobs()`, so async callers don't hit their limit of one

### Recursion → [Recursion Control](#recursion-control)

- [ ] No static Boolean gates per-record logic; handled Ids are tracked per operation
- [ ] Re-entry from workflow field updates, flows, roll-ups, and the handler's own DML is accounted for

### Automation → [Order of Execution](#order-of-execution)

- [ ] When the PR adds automation, each object and field keeps one automation owner; external side effects wait for the commit

### Events → [Platform Event and CDC Triggers](#platform-event-and-cdc-triggers)

- [ ] Event triggers declare only `after insert`; batch size and running user are deliberate, with no org-specific username in source
- [ ] Progress is checkpointed; `EventBus.RetryableException` is used only for transient failures, with a cap, and not mixed with checkpoints
- [ ] Writes are idempotent and the payload is validated before any system-mode write; CDC handlers branch on `changeType` and handle gap and overflow events

### Tests → [Testing Triggers](#testing-triggers)

- [ ] A test saves 201+ records in one DML; every declared event, including delete and undelete, is exercised
- [ ] Tests assert side effects, a no-op save, and the bypass; setup DML runs inside `System.runAs`
- [ ] Event tests deliver with `Test.getEventBus().deliver()`, after `Test.enableChangeDataCapture()` for CDC; results: ask the author

---

## Trigger Architecture

Triggers run `without sharing` at every API version, but from API 67.0 database operations in the trigger body run in user mode unless they state otherwise ([Security Model](platform.md#security-model)).

### One trigger per object, with no logic in it

The platform doesn't order several triggers on the same object and event, so behavior can change between deployments, and trigger bodies can't be unit-tested, reused by Batch or API code, or given a sharing keyword. Keep one trigger per object that declares every event its handler dispatches, and put the logic in a handler built on the framework the repo already uses (a base handler class, a dispatcher, fflib domain classes) rather than a second pattern for one object ([Code Reuse Review](../code-quality-universal.md#code-reuse-review)). Exception: a managed package's trigger on the same object isn't yours to merge.

```apex
// ❌ A second trigger on the same object, with a query and a rule in its body
trigger InvoiceApprovalTrigger on Invoice__c (before insert) {
    for (Invoice__c inv : Trigger.new) {
        inv.Payment_Terms__c = [SELECT Payment_Terms__c FROM Account WHERE Id = :inv.Account__c].Payment_Terms__c;
    }
}

// ✅ One trigger; it declares exactly the events the handler below dispatches
trigger InvoiceTrigger on Invoice__c (
    before insert, before update, after insert, after update, after delete, after undelete
) {
    new InvoiceTriggerHandler().run();
}
```

Static analysis: PMD `AvoidLogicInTrigger`, `OperationWithLimitsInLoop`.

### Dispatch on Trigger.operationType (API 43.0+)

`switch on Trigger.operationType` names each event once and makes a missing branch visible, while nested `isBefore` and `isInsert` checks invite gaps and double execution. Cast the context collections once, in the dispatcher. When the repo's framework dispatches another way, follow it.

```apex
// ✅ One branch per event, after the bypass check
public with sharing class InvoiceTriggerHandler {
    public void run() {
        if (TriggerBypass.isBypassed('Invoice')) { return; }
        switch on Trigger.operationType {
            when BEFORE_INSERT, BEFORE_UPDATE {
                InvoiceDefaults.apply((List<Invoice__c>) Trigger.new, (Map<Id, Invoice__c>) Trigger.oldMap);
            }
            when AFTER_INSERT, AFTER_UPDATE, AFTER_DELETE, AFTER_UNDELETE {
                // Trigger.new is null on delete; Trigger.old is null on insert and undelete
                InvoiceRollups.recalculate(InvoiceRollups.accountIdsOf(Trigger.new, Trigger.old));
            }
        }
    }
}
```

### Offer a bypass through a custom permission or Custom Metadata

Data loads, migrations, and integrations sometimes need to skip automation. Check a custom permission granted through a permission set, or a Custom Metadata switch per object, never profile names, usernames, or Ids, which differ per org and can't be granted or revoked cleanly. Cover every bypass with a test ([Testing Triggers](#testing-triggers)).

```apex
// ❌ Org-specific identity checks
Boolean skip = UserInfo.getUserName() == 'etl@example.com' || UserInfo.getProfileId() == '00e000000000000AAA';

// ✅ A custom permission for people and integrations, Custom Metadata to switch an object off
public inherited sharing class TriggerBypass {
    public static Boolean isBypassed(String objectKey) {
        Trigger_Setting__mdt setting = Trigger_Setting__mdt.getInstance(objectKey);
        return FeatureManagement.checkPermission('Bypass_Triggers') || (setting != null && setting.Disabled__c);
    }
}
```

### Decide the access mode in the handler, not the trigger

A trigger can't declare a sharing keyword or an access mode, and its own context is `without sharing` at every API version (Summer '26 removed the nested-trigger cases that enforced sharing). From API 67.0 the trigger's own `<apiVersion>` matters as well: database operations written in the trigger body run in user mode unless they say `WITH SYSTEM_MODE`, `as system`, or `AccessLevel.SYSTEM_MODE`, and user mode overrides the trigger's `without sharing` context, so CRUD, FLS, and sharing all apply. Handlers and the services they call follow their own keyword and `<apiVersion>`, so a 67.0 handler also runs implicit operations in user mode. Either way, automation can start failing for users who can't edit the fields it maintains. Keep logic in the handler, write each access mode explicitly with a reason wherever it is system mode ([Data Access Security](apex.md#data-access-security)), and review a `.trigger-meta.xml` bump across 67.0 as a behavior change. Field assignments on `Trigger.new` in a before trigger aren't DML and aren't checked against field-level security.

```apex
// ❌ API 67.0 handler or trigger body, implicit mode: the roll-up fails for every user who can't edit Open_Balance__c
update accounts;

// ✅ Explicit and justified: Open_Balance__c is automation-owned and read-only for every profile
update as system accounts;
```

---

## Context Variables

### Change the triggering records in before triggers and other records in after triggers

Assigning fields on `Trigger.new` in a before trigger costs no DML and no second save. After triggers are for work that needs the saved Id or committed values (related records, events, jobs); DML on the triggering records from an after trigger runs their whole save again, including every trigger, rule, and flow.

### Use each context variable only in the events that provide it

Reading a variable that is null for the current event throws `NullPointerException`, and changing a field on `Trigger.new` after the save throws `System.FinalException: Record is read-only`. A merge deletes the losing records, whose `Trigger.old` rows carry `MasterRecordId` in after delete, and updates the winner; child records moved to the winner don't fire their own triggers, so roll-ups kept by child triggers need merge handling.

| Event | `Trigger.new` | `Trigger.newMap` | `Trigger.old`, `Trigger.oldMap` | Fields on `Trigger.new` writable |
|---|---|---|---|---|
| before insert | Yes | No (no Ids yet) | No | Yes |
| before update | Yes | Yes | Yes | Yes |
| before delete | No | No | Yes | No: call `addError` on `Trigger.old` |
| after insert | Yes | Yes | No | No |
| after update | Yes | Yes | Yes | No |
| after delete | No | No | Yes | No |
| after undelete | Yes | Yes | No | No |

### Act only on real field changes

Update triggers fire for every save, including saves that didn't touch the fields your logic cares about: edits of other fields, integrations resending identical values, and the platform's own re-saves. Compare with `Trigger.oldMap` and act only on the transition; this also makes most re-entry harmless ([Recursion Control](#recursion-control) covers the exception).

```apex
// ❌ Notifies again on every later save of an approved invoice
if (inv.Status__c == 'Approved') { toNotify.add(inv.Id); }

// ✅ Only the transition into Approved
if (inv.Status__c == 'Approved' && oldById.get(inv.Id).Status__c != 'Approved') { toNotify.add(inv.Id); }
```

### Report validation errors with addError, not exceptions

`addError` on a record, or on one of its fields, blocks that record's save, shows the message next to the field in the UI, and reports it per record to API and partial-success callers; a thrown exception fails the whole chunk with an Apex error. Call it on `Trigger.new` in before insert and update and on `Trigger.old` in before delete. Single-record checks without queries usually belong in a validation rule ([Validation Rules](metadata.md#validation-rules)). Never pass `false` as the escape argument with user-controlled text, because the message is then rendered as HTML.

```apex
// ❌ Fails every record in the chunk
if (inv.Amount__c <= 0) { throw new InvoiceService.InvoiceException('Amount must be positive'); }

// ✅ A field-level error on the offending record, with a translatable message
if (inv.Amount__c == null || inv.Amount__c <= 0) { inv.Amount__c.addError(System.Label.Invoice_Amount_Positive); }
```

### Never assume one record per trigger

`Trigger.new[0]` works when one user saves one record and silently ignores records 2 to 200 of a data load, an integration call, or a list-view mass edit. Loop over every record in the chunk. Static analysis: PMD `AvoidDirectAccessTriggerMap`.

---

## Bulk Safety per Chunk

A DML of N records runs the trigger once per 200-record chunk, and the chunks share one transaction; the chunk math, a worked budget, and the Bulk API exception are in [Count per transaction](platform.md#governor-limits).

### Budget queries for every chunk, and keep statics for caching, not accumulation

A handler with q queries per chunk spends q × chunks queries from one budget, on top of every flow, roll-up, and trigger the save reaches. Keep the per-chunk count constant, load reference data that doesn't change between chunks once per transaction (or keep it in Custom Metadata), and never collect `Trigger.new` into a static list: it grows with every chunk, so chunk 2 re-processes chunk 1.

```apex
// ❌ A static list that grows with every chunk: chunk 2 notifies chunk 1's owners again
private static List<Invoice__c> pending = new List<Invoice__c>();
public static void afterInsert(List<Invoice__c> invoices) {
    pending.addAll(invoices);
    InvoiceNotifier.notifyOwners(pending);
}

// ✅ Reference data loaded once per transaction; each chunk handles only its own records
private static List<Pricing_Rule__c> activeRules;
public static void beforeInsert(List<Invoice__c> invoices) {
    if (activeRules == null) {
        activeRules = [SELECT Region__c, Discount__c FROM Pricing_Rule__c WHERE Active__c = true WITH USER_MODE];
    }
    InvoicePricing.apply(invoices, activeRules);
}
```

### Keep callouts out of triggers and enqueue once per transaction

Triggers can't make synchronous callouts. Enqueues multiply with chunks and re-entry, and the limit depends on the caller: 50 per synchronous transaction, but one when the DML runs inside Batch `execute`, a Queueable, or `@future` ([Governor Limits](platform.md#governor-limits)), so a per-chunk enqueue throws an uncatchable `LimitException` on the second chunk of a 201-record DML from async Apex. Mark the records in the before trigger (`Sync_Pending__c = true`) and enqueue one job per transaction that selects the marked records after the commit, guarded by `Limits.getQueueableJobs()`; when no enqueue is left, the marked records wait for the next job or a scheduled sweep. That purpose-named flag is a once-per-transaction side-effect guard, not a recursion guard ([Severity Calibration](platform.md#severity-calibration), row 10).

```apex
// ✅ One job per transaction; the job re-selects Sync_Pending__c = true records after the commit
public with sharing class InvoiceSyncEnqueuer {
    private static Boolean syncJobEnqueued = false; // side-effect guard, not a recursion guard
    public static void enqueueOnce() {             // called from after insert and after update
        if (syncJobEnqueued || Limits.getQueueableJobs() >= Limits.getLimitQueueableJobs()) {
            return;                                 // marked records wait for the next job or the sweep
        }
        System.enqueueJob(new InvoiceSyncJob());    // implements Database.AllowsCallouts
        syncJobEnqueued = true;
    }
}
```

---

## Recursion Control

The handler's own DML, workflow field updates, after-save flows, roll-ups, and the platform's partial-success retries all run triggers again in the same transaction, and each nested level counts toward the trigger depth limit ([Governor Limits](platform.md#governor-limits)).

### Guard per record and operation, never with a static Boolean

A static "already ran" Boolean is set by the first chunk, so chunks 2..n of the same DML, and every later DML on the object, skip the logic: records 201 and up of a load silently miss the automation. Prefer change detection; where your own writes re-enter the trigger, remember the Ids handled for each operation (before insert has no Ids yet, so it relies on change detection). A purpose-named flag that only prevents a second side effect, such as the one guarded enqueue above, is fine.

```apex
// ❌ Chunk 1 sets the flag; records 201+ are never processed
private static Boolean hasRun = false;
public void run() {
    if (hasRun) { return; }
    hasRun = true;
}

// ✅ Each record is handled once per operation, in every chunk
public inherited sharing class TriggerRecursion {
    private static Map<TriggerOperation, Set<Id>> handled = new Map<TriggerOperation, Set<Id>>();
    public static Set<Id> firstVisits(List<SObject> records) {
        if (!handled.containsKey(Trigger.operationType)) {
            handled.put(Trigger.operationType, new Set<Id>());
        }
        Set<Id> seen = handled.get(Trigger.operationType);
        Set<Id> fresh = new Set<Id>();
        for (SObject record : records) {
            if (seen.add(record.Id)) {
                fresh.add(record.Id);
            }
        }
        return fresh;
    }
}
// ⚠️ Statics survive the partial-success retry (allOrNone = false, API loads): the first attempt's work is
//    rolled back but its Ids stay handled. Keep guarded work idempotent and test that path.
```

### Expect re-entry from other automation

A workflow field update re-runs before and after update triggers once more, and in that re-run `Trigger.old` still holds the values from before the original update, so change detection sees the same change twice and only an Id guard stops it. After-save flows that update the triggering record, roll-up summaries and cross-object workflow that save the parent, and the handler's own after-trigger DML re-enter too: list every automation that writes the object before approving recursion logic.

```text
❌ Account after update -> updates Contacts -> Contact trigger updates the Account -> Account after update -> ...
❌ Invoice insert -> the roll-up summary saves the Account -> Account triggers and flows run inside the Invoice DML
✅ Every writer of the object is known, each write needs a real change, and an Id guard covers workflow re-fires
```

---

## Order of Execution

The step-by-step order, including where before-save flows, validation rules, and workflow re-fires sit, is in [One DML fans out through the order of execution](platform.md#transactions--execution-contexts). These rules apply it to triggers.

### Give each object and field one automation owner

The platform doesn't order several triggers on one object and event, and a trigger, a record-triggered flow, and a legacy workflow rule writing the same field fight over its final value. Choose one owner per object and field, set flow trigger order where several flows remain ([Entry Conditions & Recursion](flows.md#entry-conditions--recursion)), and treat Workflow Rules and Process Builder (end of support Dec 31, 2025) as migration debt ([Salesforce Architecture](../architecture-review-guide.md#salesforce-architecture)).

```text
❌ Invoice__c.Status__c is written by InvoiceTrigger, the "Invoice Status" after-save flow, and a workflow field update
✅ Invoice__c.Status__c is written only by InvoiceTriggerHandler; the flow sends notifications; the workflow rule is retired
```

### Release side effects only after the commit

Emails, enqueued jobs, and Publish After Commit events are released only if the transaction commits, while a Publish Immediately event goes out even when the save rolls back. Tell other systems about a save through a Queueable or a Publish After Commit event, and check the publish results ([Callouts & Integrations](apex.md#callouts--integrations)).

```text
❌ The trigger publishes a Publish Immediately event: the ERP hears about an invoice that may still roll back
✅ The trigger publishes a PublishAfterCommit event or enqueues a Queueable: other systems hear only about commits
```

---

## Platform Event and CDC Triggers

Event triggers are subscribers, not part of the publisher's save: they run in their own transaction after delivery, with synchronous limits, as the Automated Process user by default, on batches of up to 2,000 events ([Governor Limits](platform.md#governor-limits)). Unlike object triggers, a platform-event trigger keeps the DML it did before an uncaught exception, including a `LimitException`: only `EventBus.RetryableException` and the 10-minute execution limit roll it back, and the uncaught exception stops the batch, so the rest of its events aren't processed unless a checkpoint was set.

### Subscribe with after insert only

Platform event and change event triggers support only `after insert`. Records they create show the running user (Automated Process by default) as `CreatedById` and `OwnerId`. At API 67.0+ implicit user mode runs with that user's permissions, and Automated Process fails object and field checks unless permission sets are explicitly assigned to it, so decide the access mode explicitly ([Decide the access mode in the handler, not the trigger](#decide-the-access-mode-in-the-handler-not-the-trigger)).

```apex
// ✅ after insert only (before insert isn't supported); the handler processes the whole batch
trigger InvoiceEventTrigger on Invoice_Event__e (after insert) {
    InvoiceEventHandler.handle((List<Invoice_Event__e>) Trigger.new);
}
```

### Configure batch size and running user per org (API 51.0+)

`PlatformEventSubscriberConfig` gives an expensive handler a smaller batch (1 to 2,000) and a running user other than Automated Process, for platform event and change event triggers. Its `<user>` is a username, and usernames differ between orgs (sandbox usernames carry a suffix), so a username committed to source matches only one org: leave it out or replace it per org at deploy time.

```xml
<!-- ❌ <user>integration@example.com</user> in source: a username that exists in only one org -->

<!-- ✅ A batch size chosen for the handler's cost, and no org-specific username -->
<PlatformEventSubscriberConfig xmlns="http://soap.sforce.com/2006/04/metadata">
    <batchSize>200</batchSize>
    <masterLabel>InvoiceEventTriggerConfig</masterLabel>
    <platformEventConsumer>InvoiceEventTrigger</platformEventConsumer>
</PlatformEventSubscriberConfig>
```

### Checkpoint progress and retry only transient failures

`EventBus.TriggerContext.currentContext().setResumeCheckpoint(replayId)` records the last event you finished: when the trigger stops, intentionally or on an uncaught exception, the next execution starts after it, and the checkpointed work stays committed. Set it after each processed event or bulk step; use it to cap the work per execution. `EventBus.RetryableException` instead rolls back the attempt's DML and redelivers the whole batch after a delay; after nine retries the trigger enters the error state and stops receiving events until someone resumes it. Retry only transient failures, cap them with `retries`, and log permanent failures instead of throwing. Pick one mechanism per trigger: the Platform Events Developer Guide supports combining them only through its Trailhead trigger template.

```apex
// ✅ Checkpoints: bounded work per execution, one bulk step, then the checkpoint on its last event
public with sharing class InvoiceEventHandler {
    private static final Integer MAX_EVENTS_PER_RUN = 500;
    public static void handle(List<Invoice_Event__e> events) {
        List<Invoice_Event__e> slice = new List<Invoice_Event__e>();
        for (Integer i = 0; i < events.size() && i < MAX_EVENTS_PER_RUN; i++) {
            slice.add(events[i]);
        }
        InvoiceEventProcessor.upsertInvoices(slice); // bulk, idempotent, partial success: failed rows are logged
        EventBus.TriggerContext.currentContext().setResumeCheckpoint(slice[slice.size() - 1].ReplayId);
    }   // events after the checkpoint arrive in a new execution
}

// ✅ Retries, in a trigger that sets no checkpoints: only a transient failure redelivers the batch
try {
    PaymentEventProcessor.apply(events); // bulk and idempotent
} catch (DmlException e) {
    if (e.getDmlType(0) == StatusCode.UNABLE_TO_LOCK_ROW
            && EventBus.TriggerContext.currentContext().retries < MAX_RETRIES) {
        throw new EventBus.RetryableException('Row lock contention: redeliver this batch');
    }
    AppLog.error('PaymentEventHandler', e.getMessage(), null); // permanent: log, keep the stream moving
}
```

### Make subscribers idempotent

The same business event can reach a subscriber more than once (`RetryableException` redelivers whole batches, publishers resend after timeouts), so key every write on a business identifier from the event, typically an upsert on an External Id ([Make jobs idempotent and safe to retry](apex.md#make-jobs-idempotent-and-safe-to-retry)). The payload is untrusted input: any publisher (Apex that publishes the event, API users with Create on it) chooses its values. Validate what an event references (the invoice exists, the amount is in range) before any system-mode write, and keep that write narrow and commented.

```apex
// ❌ Trusts the payload: whoever publishes the event decides which invoice gets a payment
upsert as system payments Payment__c.External_Id__c;

// ✅ Only events that reference an existing invoice with a positive amount, upserted on the publisher's key
List<Payment__c> payments = PaymentEvents.validPayments(events); // queries the referenced invoices once
upsert as system payments Payment__c.External_Id__c; // system mode: Automated Process; inputs checked above
```

### Read the ChangeEventHeader and handle gap and overflow events

A change event carries a header and only the fields that changed. `changeType` is CREATE, UPDATE, DELETE, UNDELETE, or a gap type (GAP_CREATE, GAP_UPDATE, GAP_DELETE, GAP_UNDELETE, GAP_OVERFLOW); `recordIds` can list several records, and `changedFields` names what changed in an update. Several DML operations on one record in one transaction produce a single event of the initial type, so an insert followed by an update arrives as one CREATE. Gap events arrive when the platform couldn't build a normal event and carry record Ids but no field data; overflow events (changes beyond the first 100,000 in one transaction) carry only the header. Re-read current state for gap events, resynchronize after an overflow, and don't read a null field in an update event as "cleared" before checking `changedFields`.

```apex
// ✅ Branch on changeType; the sync job re-reads current state for every Id it receives
Set<String> recordIds = new Set<String>();
Boolean resyncAll = false;
for (AccountChangeEvent event : events) {
    EventBus.ChangeEventHeader header = event.ChangeEventHeader;
    if (header.changeType == 'GAP_OVERFLOW') {
        resyncAll = true; // header only: too many changes in one transaction
    } else if (header.changeType == 'CREATE' || header.changeType.startsWith('GAP_')
            || (header.changeType == 'UPDATE' && header.changedFields.contains('Rating'))) {
        recordIds.addAll(header.recordIds);
    }
}
if (resyncAll || !recordIds.isEmpty()) {
    System.enqueueJob(new AccountSyncJob(resyncAll ? null : recordIds)); // null means a full resync
}
```

---

## Testing Triggers

Trigger tests prove the chunk, recursion, and bypass behavior that a static review can only reason about; ask the author or CI for the results. The general rules are in [Testing](apex.md#testing).

### Save 201+ records in one DML and cover every declared event

Most chunk defects (static Boolean guards, statics that accumulate, per-chunk query budgets, `Trigger.new[0]`) appear only when a second chunk runs, so insert or update at least 201 records in one DML and assert on the second chunk too. A trigger that declares delete and undelete needs tests that delete and undelete records, and a roll-up needs a reparenting case, where both the old and the new parent change.

```apex
// ✅ 201 records in one DML: the trigger runs for two chunks
@IsTest
static void appliesDefaultsAcrossChunks() {
    List<Invoice__c> invoices = TestDataFactory.buildInvoices([SELECT Id FROM Account LIMIT 1].Id, 201);
    Test.startTest();
    insert invoices;
    Test.stopTest();
    Assert.areEqual(0, [SELECT COUNT() FROM Invoice__c WHERE Due_Date__c = null],
        'Every record, including the 201st, gets a due date');
}
```

### Test the bypass and least-privilege users through System.runAs

Assert what the trigger changes on other records, that a save of unchanged data changes nothing, and that the bypass really skips the logic. Create users and permission set assignments inside `System.runAs` so they don't mix with business DML (`MIXED_DML_OPERATION`, [Transactions & Execution Contexts](platform.md#transactions--execution-contexts)), and run the trigger's DML as a user with only the feature's permission sets so the explicit access modes meet real permissions.

```apex
// ✅ Setup DML inside runAs; the bypass user's inserts get no defaults
@IsTest
static void bypassPermissionSkipsDefaults() {
    User loader = TestDataFactory.buildUser('data.loader');
    System.runAs(new User(Id = UserInfo.getUserId())) {
        insert loader;
        insert new PermissionSetAssignment(AssigneeId = loader.Id,
            PermissionSetId = [SELECT Id FROM PermissionSet WHERE Name = 'Trigger_Bypass'].Id);
    }
    List<Invoice__c> invoices = TestDataFactory.buildInvoices([SELECT Id FROM Account LIMIT 1].Id, 5);
    System.runAs(loader) {
        insert invoices;
    }
    Assert.areEqual(5, [SELECT COUNT() FROM Invoice__c WHERE Id IN :invoices AND Due_Date__c = null],
        'Inserts by a user with Bypass_Triggers get no defaults');
}
```

### Deliver events explicitly in event-trigger tests

Platform events published in a test are delivered at `Test.stopTest()` or when the test calls `Test.getEventBus().deliver()`. Call `Test.enableChangeDataCapture()` at the start of a change-event test so the triggers fire whatever entities are selected in Setup. A test that inserts and then updates the same record in one transaction gets one CREATE event, not an UPDATE, so assert on the event type the test really produces.

```apex
// ✅ A change event test: enable CDC first, insert, then deliver the pending CREATE event
@IsTest
static void newAccountEnqueuesSync() {
    Test.enableChangeDataCapture();
    TestDataFactory.createAccount('Test Account');
    Test.getEventBus().deliver(); // runs AccountChangeTrigger
    Assert.areEqual(1, [SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'AccountSyncJob'],
        'One sync job for the new account');
}
```

---

## References

- [Triggers and Order of Execution (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers_order_of_execution.htm)
- [Apex Triggers Always Run in a "without sharing" Context (Summer '26 release notes)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_triggers_system_mode.htm&language=en_US&release=262&type=5)
- [Retry Event Triggers with EventBus.RetryableException (Platform Events Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.platform_events.meta/platform_events/platform_events_subscribe_apex_refire.htm)
- [PlatformEventSubscriberConfig (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_platformeventsubscriberconfig.htm)
- [Change Event Triggers (Change Data Capture Developer Guide)](https://developer.salesforce.com/docs/platform/change-data-capture/guide/cdc-trigger-intro.html)
