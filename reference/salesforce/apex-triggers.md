# Apex Triggers Code Review Guide

Review guidance for Apex triggers and their handler classes, including platform event and Change Data Capture triggers: trigger architecture, context variables, 200-record chunks, recursion, order of execution, event subscribers, and trigger tests.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
> Related: [Apex](apex.md) · [Flows](flows.md) · [Validation rules](metadata.md#validation-rules)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Trigger Architecture](#trigger-architecture)
- [Context Variables](#context-variables)
- [Bulk Safety per Chunk](#bulk-safety-per-chunk)
- [Recursion Control](#recursion-control)
- [Order of Execution](#order-of-execution)
- [Platform Event and CDC Triggers](#platform-event-and-cdc-triggers)
- [Testing Triggers](#testing-triggers)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| `triggers/*.trigger` | This guide + [apex.md](apex.md) for the handler and service code |
| Trigger handler classes and frameworks | [Trigger Architecture](#trigger-architecture) + [Class Design](apex.md#class-design) |
| Triggers on platform events (`__e`) or change events (`ChangeEvent`) | [Platform Event and CDC Triggers](#platform-event-and-cdc-triggers) |
| A record-triggered flow on an object that also has a trigger | [flows.md](flows.md) + [Order of Execution](#order-of-execution) |
| Trigger tests | [Testing Triggers](#testing-triggers) + [Testing](apex.md#testing) |

A trigger always runs in system mode, and its own `<apiVersion>` affects only language features; the handler class's sharing keyword and `<apiVersion>` decide how its queries and DML enforce access ([Decide the access mode in the handler, not the trigger](#decide-the-access-mode-in-the-handler-not-the-trigger)).

---

## Trigger Architecture

### One trigger per object, with no logic in it

The platform doesn't guarantee the order of several triggers on the same object and event, so behavior can change between deployments, and trigger bodies can't be unit-tested, reused by Batch or API code, or given a sharing keyword. Keep one trigger per object that declares every event its handler dispatches, and put the logic in a handler built on the framework the project already uses (a base handler class, a dispatcher, fflib domain classes) instead of a second pattern for one object ([Code Reuse Review](../code-quality-universal.md#code-reuse-review)).

```apex
// ❌ A second trigger on the same object, with a query and a rule in its body
trigger InvoiceApprovalTrigger on Invoice__c (before insert) {
    for (Invoice__c inv : Trigger.new) {
        inv.Payment_Terms__c = [SELECT Payment_Terms__c FROM Account WHERE Id = :inv.Account__c].Payment_Terms__c;
    }
}

// ✅ One trigger for every event; the handler follows the project's framework
trigger InvoiceTrigger on Invoice__c (
    before insert, before update, before delete, after insert, after update, after delete, after undelete
) {
    new InvoiceTriggerHandler().run();
}
```

Static analysis: PMD `AvoidLogicInTrigger`, `OperationWithLimitsInLoop`.

### Dispatch on Trigger.operationType (API 43.0+ / Summer '18)

`switch on Trigger.operationType` names each event once and makes a missing branch visible, while nested `isBefore` and `isInsert` checks invite gaps and double execution. Cast the context collections once, in the dispatcher.

```apex
// ❌ Nested flags: easy to miss a combination or to run a branch twice
if (Trigger.isBefore && (Trigger.isInsert || Trigger.isUpdate)) { /* ... */ } else if (Trigger.isUpdate) { /* ... */ }

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

Triggers run in system mode at every API version and can't declare sharing or an access mode; Summer '26 removed the old cases where nested triggers enforced sharing. The handler and the services it calls follow their own keyword and `<apiVersion>`, so a handler at API 67.0+ runs its queries and DML in user mode by default, and automation can start failing for users who can't edit the fields it maintains ([Security Model](platform.md#security-model)). Declare the handler's keyword and write each mode explicitly, with a reason wherever it is system mode ([Data Access Security](apex.md#data-access-security)). Field assignments on `Trigger.new` in a before trigger aren't DML and aren't checked against field-level security.

```apex
// ❌ API 67.0 handler, implicit mode: the roll-up fails for every user who can't edit Open_Balance__c
update accounts;

// ✅ Explicit and justified: Open_Balance__c is automation-owned and read-only for every profile
update as system accounts;
```

---

## Context Variables

### Change the triggering records in before triggers and other records in after triggers

Assigning fields on `Trigger.new` in a before trigger costs no DML and no second save. After triggers are for work that needs the saved Id or committed values (related records, events, jobs); DML on the triggering records from an after trigger runs their whole save again.

```apex
// ❌ After insert: copies of the triggering records saved again re-run every trigger, rule, and flow
update dueDateCopies;

// ✅ Before insert: assign in memory, no DML (termDays comes from Custom Metadata)
for (Invoice__c inv : invoices) {
    if (inv.Due_Date__c == null && inv.Invoice_Date__c != null) {
        inv.Due_Date__c = inv.Invoice_Date__c.addDays(termDays);
    }
}
```

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
if (inv.Status__c == 'Approved') {
    toNotify.add(inv.Id);
}

// ✅ Only the transition into Approved
if (inv.Status__c == 'Approved' && oldById.get(inv.Id).Status__c != 'Approved') {
    toNotify.add(inv.Id);
}
```

### Report validation errors with addError, not exceptions

`addError` on a record, or on one of its fields, blocks that record's save, shows the message next to the field in the UI, and reports it per record to API and partial-success callers; a thrown exception fails the whole chunk with an Apex error. Call it on `Trigger.new` in before insert and update and on `Trigger.old` in before delete; single-record checks without queries usually belong in a validation rule ([Validation Rules](metadata.md#validation-rules)). Never pass `false` as the escape argument with user-controlled text, because the message is then rendered as HTML.

```apex
// ❌ Fails every record in the chunk
if (inv.Amount__c <= 0) {
    throw new InvoiceService.InvoiceException('Amount must be positive');
}

// ✅ A field-level error on the offending record, with a translatable message
if (inv.Amount__c == null || inv.Amount__c <= 0) {
    inv.Amount__c.addError(System.Label.Invoice_Amount_Positive);
}
```

### Never assume one record per trigger

`Trigger.new[0]` works when one user saves one record and silently ignores records 2 to 200 of a data load, an integration call, or a list-view mass edit.

```apex
// ❌ Handles only the first record of the chunk
Invoice__c inv = (Invoice__c) Trigger.new[0];
inv.Due_Date__c = inv.Invoice_Date__c.addDays(termDays);

// ✅ Every record in the chunk
for (Invoice__c inv : (List<Invoice__c>) Trigger.new) {
    if (inv.Invoice_Date__c != null) {
        inv.Due_Date__c = inv.Invoice_Date__c.addDays(termDays);
    }
}
```

Static analysis: PMD `AvoidDirectAccessTriggerMap`.

---

## Bulk Safety per Chunk

A DML statement on N records runs each trigger ⌈N/200⌉ times, once per 200-record chunk, and the chunks share one transaction: governor limits and static variables carry over from chunk to chunk. Bulk API loads differ, because each of their chunks is a separate transaction with fresh limits ([Governor Limits](platform.md#governor-limits) has the entry-point table and a worked budget).

### Budget queries for every chunk, and keep statics for caching, not accumulation

A handler with q queries per chunk spends q × ⌈N/200⌉ queries from one budget, on top of every flow, roll-up, and trigger the save reaches. Keep the per-chunk count constant, load reference data that doesn't change between chunks once per transaction (or keep it in Custom Metadata), and never collect `Trigger.new` into a static list: it grows with every chunk, so chunk 2 re-processes chunk 1.

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

### Keep callouts out of triggers and enqueue at most once per chunk

Triggers can't make synchronous callouts, and an enqueue per record, or an unguarded enqueue per chunk, multiplies with every chunk and every re-entry. Enqueue one job per chunk for that chunk's records and remember what was already enqueued; chunks times jobs must fit the enqueue limit ([Governor Limits](platform.md#governor-limits)), so very large DMLs need Batch Apex or a platform event instead. When one job per transaction is enough, mark the records in the before trigger and enqueue a single job, guarded by a static flag named for its purpose, that selects the marked records after the commit.

```apex
// ✅ At most one job per chunk, never twice for the same records
public with sharing class InvoiceSyncEnqueuer {
    private static Set<Id> enqueuedIds = new Set<Id>();
    public static void enqueueFor(List<Invoice__c> invoices) { // after insert and after update
        Set<Id> toSync = new Set<Id>();
        for (Invoice__c inv : invoices) {
            if (!enqueuedIds.contains(inv.Id)) {
                toSync.add(inv.Id);
            }
        }
        if (!toSync.isEmpty()) {
            System.enqueueJob(new InvoiceSyncJob(toSync, 1)); // implements Database.AllowsCallouts
            enqueuedIds.addAll(toSync);
        }
    }
}
```

---

## Recursion Control

The handler's own DML, workflow field updates, after-save flows, roll-ups, and the platform's partial-success retries all run triggers again in the same transaction, and each nested level counts toward the trigger depth limit ([Governor Limits](platform.md#governor-limits)).

### Guard per record and operation, never with a static Boolean

A static "already ran" Boolean is set by the first chunk, so chunks 2..n of the same DML, and every later DML on the object, skip the logic: records 201 and up of a load silently miss the automation. Prefer change detection; where your own writes re-enter the trigger, remember the Ids handled for each operation (before insert has no Ids yet, so it relies on change detection).

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

### Know where triggers run in the save

For each record save the platform runs these steps in order (the short version is in [Transactions & Execution Contexts](platform.md#transactions--execution-contexts)). Before-save flows run before your before triggers and validation rules run after them, so a before trigger can still fix data that would fail validation, and a before-save flow never sees what the trigger sets.

```text
 1. Load the record (or initialize it for insert and upsert) and apply the new values
 2. System validation: UI saves check layout rules, required fields, and formats; API saves only foreign keys and restricted picklists
 3. Before-save record-triggered flows (fast field updates)
 4. Before triggers
 5. System validation again, custom validation rules, then duplicate rules
 6. Save to the database, not yet committed
 7. After triggers
 8. Assignment, auto-response, workflow, and escalation rules; a workflow field update re-runs update triggers once
 9. Processes and the flows they launch, in no guaranteed order
10. After-save record-triggered flows
11. Entitlement rules
12. Roll-up summaries and cross-object workflow on the parent, then the grandparent (each a full save)
13. Criteria-based sharing evaluation
14. Commit, then post-commit work: emails, enqueued async Apex, asynchronous paths of record-triggered flows
```

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

Event triggers are subscribers, not part of the publisher's save: they run in their own transaction after delivery, as the Automated Process user by default, on batches larger than a DML chunk ([Governor Limits](platform.md#governor-limits)).

### Subscribe with after insert only

Platform event and change event triggers support only `after insert`. Records they create show Automated Process as `CreatedById` and `OwnerId`, and a handler at API 67.0+ that relies on implicit user mode runs with that user's permissions, so decide its access mode explicitly ([Decide the access mode in the handler, not the trigger](#decide-the-access-mode-in-the-handler-not-the-trigger)).

```apex
// ✅ after insert only (before insert isn't supported); the handler processes the whole batch
trigger InvoiceEventTrigger on Invoice_Event__e (after insert) {
    InvoiceEventHandler.handle((List<Invoice_Event__e>) Trigger.new);
}
```

### Configure batch size and running user per org (API 51.0+ / Spring '21)

`PlatformEventSubscriberConfig` gives an expensive handler a smaller batch and a running user other than Automated Process, for platform event and change event triggers. Its `<user>` is a username, and usernames differ between orgs (sandbox usernames carry a suffix), so a username committed to source matches only one org: leave it out or replace it per org at deploy time.

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

`EventBus.TriggerContext.currentContext().setResumeCheckpoint(replayId)` records the last event you finished, so the next execution starts after it; use it to process part of a large batch and leave the rest for a new execution. `EventBus.RetryableException` redelivers the whole batch after a delay and rolls back the failed attempt's DML, and after a fixed number of retries the trigger moves to the error state and stops receiving events until someone resumes it. Retry only transient failures, cap them with `retries`, and log permanent failures instead of throwing.

```apex
// ✅ Bounded work per execution, a checkpoint, and bounded retries for transient failures
public with sharing class InvoiceEventHandler {
    private static final Integer MAX_EVENTS_PER_RUN = 500;
    private static final Integer MAX_RETRIES = 3;
    public static void handle(List<Invoice_Event__e> events) {
        EventBus.TriggerContext context = EventBus.TriggerContext.currentContext();
        List<Invoice_Event__e> slice = new List<Invoice_Event__e>();
        for (Integer i = 0; i < events.size() && i < MAX_EVENTS_PER_RUN; i++) {
            slice.add(events[i]); // events after the checkpoint arrive in a new execution
        }
        try {
            InvoiceEventProcessor.upsertInvoices(slice); // bulk and idempotent
        } catch (DmlException e) {
            if (e.getDmlType(0) == StatusCode.UNABLE_TO_LOCK_ROW && context.retries < MAX_RETRIES) {
                throw new EventBus.RetryableException('Row lock contention: redeliver this batch');
            }
            AppLog.error('InvoiceEventHandler', e.getMessage(), null); // permanent: log, keep the stream moving
        }
        context.setResumeCheckpoint(slice[slice.size() - 1].ReplayId);
    }
}
```

### Make subscribers idempotent

The same business event can reach a subscriber more than once: `RetryableException` redelivers whole batches, and publishers resend after timeouts. Key every write on a business identifier carried in the event, typically an upsert on an External Id field, so a redelivery updates the same row instead of creating another.

```apex
// ❌ One new Payment per delivery, so a redelivered event creates a duplicate
insert as user payments;

// ✅ Upsert on the publisher's key; system mode because the publisher was already authorized to report it
for (Payment_Received__e event : events) {
    payments.add(new Payment__c(External_Id__c = event.Payment_Key__c,
        Invoice__c = event.Invoice_Id__c, Amount__c = event.Amount__c));
}
upsert as system payments Payment__c.External_Id__c;
```

### Read the ChangeEventHeader and handle gap and overflow events

A change event carries a header and only the fields that changed. `changeType` is CREATE, UPDATE, DELETE, UNDELETE, or a gap type (GAP_CREATE, GAP_UPDATE, GAP_DELETE, GAP_UNDELETE, GAP_OVERFLOW); `recordIds` can list several records, and `changedFields` names what changed in an update. Gap events arrive when the platform couldn't build a normal event and carry record Ids but no field data, and overflow events carry only the header. Re-read current state for gap events, resynchronize after an overflow, and don't read a null field in an update event as "cleared" before checking `changedFields`.

```apex
// ✅ Branch on changeType; the sync job re-reads current state for every Id it receives
Set<String> recordIds = new Set<String>();
Boolean resyncAll = false;
for (AccountChangeEvent event : events) {
    EventBus.ChangeEventHeader header = event.ChangeEventHeader;
    if (header.changeType == 'GAP_OVERFLOW') {
        resyncAll = true; // header only: too many changes in one transaction
    } else if (header.changeType.startsWith('GAP_')
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

// ✅ In a second test: delete and undelete the Account's invoices, asserting the roll-up after each
delete invoices;
Assert.areEqual(0, InvoiceTestUtils.balanceOf(acc.Id), 'Deleting the invoices clears the balance');
undelete invoices;
Assert.areNotEqual(0, InvoiceTestUtils.balanceOf(acc.Id), 'Undeleting them restores it');
```

### Test the bypass and least-privilege users through System.runAs

Assert what the trigger changes on other records, that a save of unchanged data changes nothing, and that the bypass really skips the logic. Users and permission set assignments created in the same test as business records cause `MIXED_DML_OPERATION`, so create them inside `System.runAs`, and run the trigger's DML as a user with only the feature's permission sets so the handler's explicit access modes meet real permissions.

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

Platform events published in a test are delivered at `Test.stopTest()` or when the test calls `Test.getEventBus().deliver()`, and change event triggers fire only after `Test.enableChangeDataCapture()` at the start of the test.

```apex
// ✅ A change event test: enable CDC first, then deliver the pending events
@IsTest
static void ratingChangeEnqueuesSync() {
    Test.enableChangeDataCapture();
    Account acc = TestDataFactory.createAccount('Test Account');
    acc.Rating = 'Hot';
    update acc;
    Test.getEventBus().deliver(); // runs AccountChangeTrigger
    Assert.areEqual(1, [SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'AccountSyncJob'],
        'One sync job for the rating change');
}
```

---

## Review Checklist

### Architecture
- [ ] One trigger per object, with no logic in its body, declaring every event the handler dispatches
- [ ] The handler uses the project's existing framework and dispatches with `switch on Trigger.operationType`
- [ ] A bypass exists through a custom permission or Custom Metadata, never profile names, usernames, or Ids
- [ ] The handler declares its sharing keyword and explicit access modes; each system-mode use is commented

### Context & correctness
- [ ] Same-record changes happen in before triggers; related records, events, and jobs in after triggers
- [ ] Context variables are read only in events that provide them; `Trigger.new` isn't changed after the save
- [ ] Update logic compares with `Trigger.oldMap`; validation uses `addError`, never `addError(message, false)` with user data
- [ ] No `Trigger.new[0]`; every record in the chunk is processed

### Bulk & limits
- [ ] Queries and DML per chunk × ⌈N/200⌉ fit the transaction's budget together with the other automation
- [ ] Statics cache and de-duplicate but never accumulate records; no callouts, and at most one guarded enqueue per chunk

### Recursion & automation overlap
- [ ] No static Boolean recursion guard; handled Ids are tracked per operation, and re-entry from workflow field updates, flows, roll-ups, and the handler's own DML is accounted for
- [ ] Each object and field has one automation owner; external side effects wait for the commit

### Event subscribers
- [ ] Event triggers declare only `after insert`; batch size and running user are deliberate, with no org-specific username in source
- [ ] Handlers checkpoint with `setResumeCheckpoint` and throw `EventBus.RetryableException` only for transient failures, with a cap
- [ ] Writes are idempotent (upsert on a business key); CDC handlers branch on `changeType` and handle gap and overflow events

### Tests
- [ ] A test saves 201+ records in one DML; every declared event, including delete and undelete, is exercised
- [ ] Tests assert side effects, a no-op save, and the bypass; setup DML runs inside `System.runAs`
- [ ] Event-trigger tests deliver events with `Test.getEventBus().deliver()`, after `Test.enableChangeDataCapture()` for CDC

---

## References

- [Triggers (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers.htm)
- [Triggers and Order of Execution (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers_order_of_execution.htm)
- [Trigger and Bulk Request Best Practices (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers_bestpract.htm)
- [Bulk DML Exception Handling (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_dml_bulk_exceptions.htm)
- [Triggers run in system mode (Summer '26 Release Notes)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_triggers_system_mode.htm&language=en_US&release=262&type=5)
- [Understanding Trigger.old and Trigger.new (Salesforce Help)](https://help.salesforce.com/s/articleView?id=000384697&language=en_US&type=1)
- [Retry Event Triggers with EventBus.RetryableException (Platform Events Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.platform_events.meta/platform_events/platform_events_subscribe_apex_refire.htm)
- [PlatformEventSubscriberConfig (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_platformeventsubscriberconfig.htm)
- [Change Event Triggers (Change Data Capture Developer Guide)](https://developer.salesforce.com/docs/platform/change-data-capture/guide/cdc-trigger-intro.html)
- [Record-Triggered Automation Decision Guide (Salesforce Architects)](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered)
- [PMD Apex Rules](https://docs.pmd-code.org/latest/pmd_rules_apex.html)
