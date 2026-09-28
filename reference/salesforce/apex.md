# Apex Code Review Guide

Review rules for Apex classes: services, selectors, controllers, Batch, Queueable, and Schedulable jobs, REST resources, invocable methods, and tests. The examples spell out access modes (`WITH USER_MODE`, `as user`), which behave the same at every version from API 57.0.

> Load [platform.md](platform.md) first (limits, transactions, security model, API versions, severity). Related: [Apex Triggers](apex-triggers.md) · [SOQL & SOSL](soql-sosl.md) · [LWC-Apex contract](lwc.md#the-lwc-apex-contract) · [Invocable Apex](flows.md#invocable-apex-contract)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Bulk → [Bulkification](#bulkification)

- [ ] No SOQL, DML, callout, or enqueue inside a loop, including inside helpers called from loops
- [ ] Keys are collected first and results indexed in maps; no nested loops over two collections
- [ ] Each record is written once per DML, only when a value changed; describes, regex, and serialization are hoisted out of loops

### Language → [Language Pitfalls](#language-pitfalls)

- [ ] Optional relationships and map lookups are null-safe; `??` appears only in files at API 60.0+
- [ ] String keys are normalized, Ids compared as `Id`, money kept in `Decimal` with explicit rounding, time zones explicit

### Design → [Class Design](#class-design)

- [ ] Every new or changed class declares a sharing keyword; `without sharing` classes are small, named, and commented
- [ ] No new `global` outside a package API or a REST or `webservice` class; no `Test.isRunningTest()` branches

### Data access → [Data Access Security](#data-access-security)

- [ ] Writes a user causes run in user mode (explicit, or implicit at 67.0+); system mode is explicit, narrow, and commented
- [ ] `stripInaccessible` results are used through `getRecords()`; client-supplied Ids, records, and field lists are never trusted
- [ ] Managed sharing uses an Apex sharing reason and checks every result

### Errors → [Transactions & Error Handling](#transactions--error-handling)

- [ ] No empty or log-only catch blocks; exceptions are specific and keep their cause
- [ ] Partial-success DML inspects every result; catch-and-continue paths roll back to a savepoint
- [ ] Logs have levels and no secrets or personal data

### Async → [Async Apex](#async-apex)

- [ ] The async tool fits the job; no new `@future`; one guarded enqueue per transaction
- [ ] Self-chaining jobs have a depth cap; jobs that must not run twice have a duplicate signature
- [ ] Batch `start` queries are selective, scopes deliberate, and `Database.Stateful` holds no result objects
- [ ] Jobs re-query by Id and tolerate retries; read-modify-write code locks with `FOR UPDATE` and handles the lock timeout

### Callouts → [Callouts & Integrations](#callouts--integrations)

- [ ] Named Credentials, explicit timeouts, status checks before typed parsing, no callout after uncommitted DML
- [ ] REST resources validate input, write in user mode, and return precise status codes; `EventBus.publish` results are checked

### Tests → [Testing](#testing)

- [ ] Changed code has tests with asserts and messages, their own data, and bulk, negative, and `System.runAs` cases
- [ ] The call under test sits between `Test.startTest()` and `Test.stopTest()`; callouts are mocked; results and coverage: ask the author

### Packages → [Managed Packages](#managed-packages)

- [ ] When `sfdx-project.json` declares a namespace: new `global` members are deliberate, released signatures unchanged, schema referenced through tokens

---

## Bulkification

Every entry point can receive a list ([records per entry point](platform.md#governor-limits)), and per-record SOQL, DML, or callouts turn N records into N operations that end in an uncatchable `LimitException`. Cross-language pattern: [N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow).

### Keep SOQL, DML, callouts, and enqueues out of loops

Collect the keys, run one query into a map, and write all changes with one DML statement. Look inside methods called from loops too: a helper that queries or saves one record is N+1 per caller, and per-record DML re-runs the object's triggers and flows each time, so give helpers a bulk signature (`AccountService.getTiers(accountIds)` instead of `getTier(con.AccountId)` in a loop). Exception: a small, fixed loop bound such as a few Custom Metadata rows ([Severity Calibration](platform.md#severity-calibration), row 1).

```apex
// ❌ 200 Opportunities cost 200 queries and 200 DML statements
for (Opportunity opp : opportunities) {
    opp.Account_Rating__c = [SELECT Rating FROM Account WHERE Id = :opp.AccountId WITH USER_MODE].Rating;
    update as user opp;
}

// ✅ Account Ids collected first, one query into a map, one DML
Map<Id, Account> accountsById = new Map<Id, Account>([SELECT Id, Rating FROM Account WHERE Id IN :accountIds WITH USER_MODE]);
for (Opportunity opp : opportunities) {
    opp.Account_Rating__c = accountsById.get(opp.AccountId)?.Rating;
}
update as user opportunities;
```

Static analysis: PMD `OperationWithLimitsInLoop` (SOQL, SOSL, DML, `Database` and `Approval` methods, `Messaging.sendEmail`, `System.enqueueJob`, `System.schedule`).

### Index with maps instead of nested loops

Nested loops over two collections cost n × m iterations of CPU time (200 invoices × 2,000 lines = 400,000), and `List.contains()` inside a loop is a nested loop as well. Group once into a `Map` or `Set` keyed by the join field (n + m iterations), or aggregate in SOQL when the rows aren't loaded yet ([Query Shape](soql-sosl.md#query-shape)).

### Write each record once, and only when it changed

A DML list that holds one Id twice fails the whole statement (`System.ListException: Duplicate id in list`), and every extra or unchanged update still runs the record's triggers, flows, validation rules, and roll-ups ([No-Op Updates](../code-quality-universal.md#no-op-updates)). Merge the changes several rules make to one record into one map entry per Id, compare with the current value, and issue one DML per sObject type.

```apex
// ✅ One entry per Id, only real changes (opportunities queried with Account.Last_Won_Date__c)
Account pending = toUpdateById.get(opp.AccountId);
Date current = pending != null ? pending.Last_Won_Date__c : opp.Account?.Last_Won_Date__c;
if (opp.AccountId != null && (current == null || opp.CloseDate > current)) {
    toUpdateById.put(opp.AccountId, new Account(Id = opp.AccountId, Last_Won_Date__c = opp.CloseDate));
}
```

### Keep describes, regex, and serialization out of loops

`Schema.getGlobalDescribe()` and `Schema.describeSObjects()` are slow in large orgs, `getDescribe()` without options loads every child relationship, and `Pattern.compile`, `JSON.serialize`, and `+=` string building repeat work on every pass. Describe once through the token before the loop (`Invoice__c.Status__c.getDescribe().getPicklistValues()` into a value-to-label map), use `getDescribe(SObjectDescribeOptions.DEFERRED)` for object describes, and `String.join` a `List<String>`. Static analysis: PMD `OperationWithHighCostInLoop`, `EagerlyLoadedDescribeSObjectResult`.

---

## Language Pitfalls

### Use safe navigation for optional relationships and lookups (API 50.0+)

A parent relationship is `null` when the lookup is empty, and `Map.get()` returns `null` for a missing key; dereferencing either throws `NullPointerException`, which rolls back the whole transaction. Use `?.` (`opp.Account?.Parent?.Name`, `limitsByAccountId.get(opp.AccountId)?.Amount__c`) only where null is a valid state: a missing required value should fail loudly.

### Default missing values with null coalescing (API 60.0+)

`??` returns its right operand when the left one is null (`settings?.Max_Discount__c ?? 0`). It compiles only in classes at API 60.0+, can't be the left side of an assignment, and isn't allowed in SOQL bind expressions. Suggest it only in files already at 60.0+; never bump an apiVersion for syntax alone.

### Normalize String keys before using Maps and Sets

`==` on Strings ignores case, but `String.equals()`, Map keys, and Set elements are case-sensitive: `==` treats 'ACME-01' and 'acme-01' as equal, while `accountsByCode.get()` treats them as different keys. Normalize on write and on read (`toUpperCase()`), and use `equals()` where case is significant, such as tokens.

### Compare Ids as Id, not as Strings

An `Id` variable always holds the 18-character form, while a `String` keeps what it was given, often the 15-character form from a report, URL, or spreadsheet: string comparison fails for the same record, and string-keyed collections hold duplicates. Convert at the boundary with `Id.valueOf`, which throws `StringException` for malformed input, and compare and key by `Id`.

### Keep money in Decimal with explicit scale and rounding

`Double` is binary floating point, so cents drift (0.1 + 0.2 isn't exactly 0.3), and `Integer / Integer` truncates even when assigned to a `Decimal` (1 / 3 = 0). Widen before dividing and set scale and rounding where the business rule defines them: `paid.divide(totalCount, 4, System.RoundingMode.HALF_UP)`, `amount.setScale(2, System.RoundingMode.HALF_EVEN)`. In multi-currency orgs never add amounts in different currencies ([Dates, Currency & Labels](soql-sosl.md#dates-currency--labels)).

### Keep Date and Datetime time zones explicit

`Datetime.now()` is an instant. `Date.today()`, `Datetime.format()`, `Datetime.date()`, and `Datetime.newInstance()` use the running user's time zone, and async jobs, event subscribers, and integration users may run in another zone than the person who started the work. In format patterns `YYYY` is the week-based year, wrong around New Year. Convert at the edge: `formatGmt('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'')`, `format('yyyy-MM-dd HH:mm', 'Europe/Berlin')`, `dateGmt()`.

---

## Class Design

### Keep entry points thin: controller, service, selector

Controllers, trigger handlers, invocables, REST resources, and jobs should parse input, call a service that accepts collections, and shape the response: a query, a business rule, and DML inside an `@AuraEnabled` method can't be reused by the next entry point (a flow, a batch, an API), and copies drift. The fix is a one-line delegation such as `InvoiceService.approve(new Set<Id>{ invoiceId })`. Follow the layering the repo already uses (Apex Enterprise Patterns, or a plain service and selector split); a deviation is a finding only when the repo already follows a pattern ([Salesforce Architecture](../architecture-review-guide.md#salesforce-architecture)). Translate every exception the service can throw, `DmlException` included, at the boundary ([The LWC-Apex Contract](lwc.md#the-lwc-apex-contract)).

### Declare the sharing keyword on every class

A class's effective mode is its own keyword, else its parent's (an undeclared class that extends another takes the parent's mode), else the default of its `<apiVersion>`, which changed at API 67.0 ([Security Model](platform.md#security-model)); inner classes don't adopt the outer class's keyword. Without a keyword, record access depends on the caller, the parent class, and the file's apiVersion. Use `with sharing` for entry points and services, `inherited sharing` for selectors and utilities shared by many callers (it runs `with sharing` as the entry point), and `without sharing` only as in the next rule. Scope: new and changed classes; an undeclared pre-existing class is a finding only when the change makes it newly reachable or crosses API 67.0 ([Severity Calibration](platform.md#severity-calibration), row 5). Static analysis: PMD `ApexSharingViolations`.

### Isolate without sharing in small, named, documented classes

When a feature must count or find records the user can't see, put exactly that query in a dedicated `without sharing` class, write the reason in a comment, return the minimum (Ids or counts, not records), and call it from a `with sharing` service; a whole controller that escapes sharing for one lookup is the defect. At API 67.0+ `without sharing` alone changes nothing for implicit operations, because user mode overrides the class's sharing declaration, so write the system mode explicitly ([Severity Calibration](platform.md#severity-calibration), row 21).

```apex
// ✅ Round-robin routing must count every agent's open cases, including cases the running user
//    can't see. Explicit system mode, and counts only, never records.
public without sharing class AgentWorkload {
    public static Map<Id, Integer> openCaseCounts(Set<Id> agentIds) {
        Map<Id, Integer> counts = new Map<Id, Integer>();
        for (AggregateResult row : [
            SELECT OwnerId, COUNT(Id) total FROM Case
            WHERE OwnerId IN :agentIds AND IsClosed = false
            WITH SYSTEM_MODE
            GROUP BY OwnerId
        ]) {
            counts.put((Id) row.get('OwnerId'), (Integer) row.get('total'));
        }
        return counts;
    }
}
```

### Keep global for real public APIs; reach private code from tests with @TestVisible

`global` is needed only for managed-package APIs and for `@RestResource` and `webservice` classes. Don't widen visibility for tests either: `@TestVisible private` exposes a member to test code only. Static analysis: PMD `AvoidGlobalModifier`. Package rules: [Managed Packages](#managed-packages).

### Inject dependencies so tests can replace them

A class that constructs its gateway or selector internally can only be tested with real data and real callout mocks, which pushes authors toward `if (!Test.isRunningTest()) { ... }` branches: production paths no test runs. Depend on an interface with a production default that a test can replace, such as `@TestVisible private static InvoiceGateway gateway = new HttpInvoiceGateway();`, a `Type.forName` binding stored in Custom Metadata, or the Stub API (`Test.createStub`); when the repo already has a seam style, use it.

### Read business configuration from Custom Metadata, not constants

Thresholds, feature switches, and mappings change per org and per season; constants force a deployment for every change and invite hard-coded Ids. The rules and a null-safe example are in [Org-Agnostic Code](platform.md#org-agnostic-code). Static analysis: PMD `AvoidHardcodingId`.

---

## Data Access Security

Defaults by API version, the enforcement-mechanism table, and entry-point rules are in [Security Model](platform.md#security-model); query-side modes are in [Access Mode in Queries](soql-sosl.md#access-mode-in-queries). This section covers writes, sanitizing, escalation, and managed sharing. Platform-wide checks: [Salesforce Platform Security](../security-review-guide.md#salesforce-platform-security).

### Write in user mode, not with hand-rolled describe checks (API 57.0+)

User-mode DML enforces the running user's object permissions, field-level security, and sharing on the records being written. Use `as user` on DML statements or `AccessLevel.USER_MODE` on `Database` methods for every write a user causes; it is the default at API 67.0+, and writing it keeps the intent visible across versions. Access failures throw `DmlException` (from API 58.0; `SecurityException` before), and `getDmlFieldNames()` lists the fields. Describe checks (`isCreateable()`, `isUpdateable()`, per-field `isAccessible()`) are the legacy fallback: one forgotten field leaks or overwrites data, so accept them only in code below API 57.0 and for UI decisions such as hiding a button.

```apex
// ❌ API 66.0 class: the DML ignores CRUD and FLS, and the check never looks at Phone, Title, or other fields
if (Schema.sObjectType.Contact.fields.Email.isCreateable()) { insert contacts; }

// ✅ User-mode DML (below API 57.0: insert Security.stripInaccessible(AccessType.CREATABLE, contacts).getRecords();)
insert as user contacts;
```

Static analysis: PMD `ApexCRUDViolation`.

### Sanitize records that cross the client boundary with stripInaccessible (API 48.0+)

`Security.stripInaccessible` removes the fields a user can't read or write instead of throwing, and reports what it removed (`getRemovedFields()`). Use it where partial data is acceptable, typically records queried in system mode for a documented reason and then returned to LWC, Aura, or REST; at API 67.0+ that query must say `WITH SYSTEM_MODE`, or the implicit user-mode query throws for the hidden fields before anything is stripped. It doesn't check record sharing, and it returns new records: use `getRecords()`, not the original list.

```apex
// ❌ The sanitized copy is discarded; the original records still carry every field
Security.stripInaccessible(AccessType.READABLE, accounts);
return accounts;

// ✅ Return the decision's records
return (List<Account>) Security.stripInaccessible(AccessType.READABLE, accounts).getRecords();
```

### Justify every system-mode escalation

`WITH SYSTEM_MODE`, `as system`, and `AccessLevel.SYSTEM_MODE` skip CRUD and FLS; record access then follows the class keyword, so reaching hidden records also needs `without sharing`. Each escalation needs a comment naming who needs the access and why, the narrowest query or write, and no system-mode data returned to the user unfiltered ([Severity Calibration](platform.md#severity-calibration), row 4).

```apex
// ❌ System mode by habit, returning a salary field to the UI
return [SELECT Id, Name, Email, Salary__c FROM Contact WHERE AccountId = :accountId WITH SYSTEM_MODE];

// ✅ System mode: Last_Survey_Sent__c is read-only for every profile and maintained only by this service
Account stamp = new Account(Id = accountId, Last_Survey_Sent__c = System.now());
update as system stamp;
```

### Never trust client-supplied Ids, records, or field lists

Every `@AuraEnabled`, `@RemoteAction`, `@RestResource`, and invocable parameter is attacker-controlled. An Id can point to a record the user may not touch ([IDOR](../security-review-guide.md#idor-insecure-direct-object-reference)), and a deserialized sObject can carry fields the UI never showed, such as `OwnerId`, so `@AuraEnabled saveCase(Case record) { update record; }` is mass assignment. Copy only the fields the action changes onto a new record, allowlist values, and let user mode check access.

```apex
// ✅ Accept only what the action changes; user mode enforces record and field access
if (!ALLOWED_STATUSES.contains(status)) { // Set<String>{ 'Working', 'Escalated' }
    throw new AuraHandledException('Unsupported status.');
}
Case change = new Case(Id = caseId, Status = status);
update as user change;
```

### Share records programmatically with an Apex sharing reason

When sharing rules can't express who needs access, insert `__Share` rows with a custom Apex sharing reason as `RowCause` (`Schema.Invoice__Share.RowCause.Reviewer__c`). Rows with the `Manual` reason are deleted when the record owner changes, while rows with an Apex sharing reason survive and can be recalculated; sharing reasons exist only on custom objects ([Sharing Configuration](metadata.md#sharing-configuration)). The class is `without sharing` and inserts with `Database.insert(shares, false, AccessLevel.SYSTEM_MODE)`, because the running user usually doesn't own the records, and it checks every result instead of ignoring failures in bulk.

---

## Transactions & Error Handling

Transaction boundaries, mixed DML, callout-after-DML, and the other runtime-failure rules are in [Transactions & Execution Contexts](platform.md#transactions--execution-contexts). A transaction commits only when its entry point finishes without an unhandled exception; catch an exception only to add context, to translate it for the caller, or to continue deliberately after a partial failure. Cross-language principles: [Error Handling Principles](../cross-cutting/error-handling-principles.md#salesforce-apex).

### Catch specific exceptions, add context, and never swallow them

A catch block that only logs, or does nothing, tells the caller the operation succeeded. Catch the types you can handle and rethrow a custom exception (its class name ends in `Exception`) that names what failed and keeps the original as its cause; keep user-facing text separate from diagnostic detail ([The LWC-Apex Contract](lwc.md#the-lwc-apex-contract)). `catch (Exception e)` never sees `System.LimitException`: bulkify, or send large inputs to Batch Apex. Exception: a deliberate best-effort step, such as optional logging, may catch and continue with a comment.

```apex
// ❌ Swallowed: the caller believes the invoices were created
try { insert as user invoices; } catch (Exception e) { System.debug(e.getMessage()); }

// ✅ Specific type, context added, cause preserved
try {
    insert as user invoices;
} catch (DmlException e) {
    throw new InvoiceException('Could not create ' + invoices.size() + ' invoices: ' + e.getDmlMessage(0), e);
}
```

Static analysis: PMD `EmptyCatchBlock` (it flags only empty blocks; a catch that only logs is the same defect).

### Inspect every SaveResult when allowing partial success

`Database.insert`, `update`, and `upsert` with `allOrNone = false` save the valid records, return one result per input in input order, and throw nothing for the failures, so ignored results make failed rows vanish. The platform also retries the successful subset and fires triggers again for it, with static variables intact ([Recursion Control](apex-triggers.md#recursion-control)).

```apex
// ✅ Pair each result with its input and report the failures
List<Database.SaveResult> results = Database.update(invoices, false, AccessLevel.USER_MODE);
for (Integer i = 0; i < results.size(); i++) {
    if (!results[i].isSuccess()) {
        AppLog.error('InvoiceService', results[i].getErrors()[0].getMessage(), invoices[i].Id);
    }
}
```

### Use a savepoint when you catch and continue after multi-step writes

An uncaught exception already rolls everything back, so a savepoint matters when code catches the exception and returns normally (an error DTO, a REST status code, an invocable result): without a rollback, the first write commits alone. Setting and rolling back a savepoint each count as a DML statement, a rollback doesn't revert static variables, and records inserted after the savepoint keep their Ids, so re-inserting the same instances fails.

```apex
// ✅ Undo both steps before returning the error
Savepoint sp = Database.setSavepoint();
try {
    insert as user invoice;
    List<Invoice_Line__c> linked = InvoiceLines.linkTo(invoice.Id, lines);
    insert as user linked;
} catch (DmlException e) {
    Database.rollback(sp); // invoice keeps its rolled-back Id: use invoice.clone(false) to retry
    return e.getDmlMessage(0);
}
```

### Keep setup-object DML out of business transactions

The rule and its fix (`MIXED_DML_OPERATION`: a separate Queueable, or `System.runAs` in tests) are in [Transactions & Execution Contexts](platform.md#transactions--execution-contexts).

### Log with levels and without personal data; persist what must survive a rollback

`System.debug` output exists only under a trace flag, costs CPU even when nobody reads it, and often leaks tokens and personal data into logs many admins can read (`System.debug('Auth: ' + req.getHeader('Authorization'))`). Use the project's leveled logger (the examples call it `AppLog`), and never log credentials, session Ids, full request bodies, or personal data. A log record inserted in a transaction that rolls back disappears with it; a Publish Immediately platform event (such as a `Log__e`) is delivered even then, so its subscriber can store the entry; check the publish `SaveResult`. Static analysis: PMD `AvoidDebugStatements`, `DebugsShouldUseLoggingLevel`, `ApexDangerousMethods`.

---

## Async Apex

Async work runs in a new transaction with fresh limits, static variables at their initial values, and possibly a different running user, and only after the enqueuing transaction commits, so a rolled-back transaction never starts it ([Transactions & Execution Contexts](platform.md#transactions--execution-contexts)). Cross-language principles: [Async & Concurrency Patterns](../cross-cutting/async-concurrency-patterns.md#salesforce-apex-queueable-finalizer-locking).

### Choose the async tool by the shape of the job

| Tool | Use it for | Watch for |
|---|---|---|
| Queueable | The default for new async work, callouts included (`Database.AllowsCallouts`); fields carry state; one child job per execution | Enqueue limits; unbounded chains |
| Batch Apex | One large, query-defined record set; `Database.Stateful` keeps fields between chunks | A selective `start`, the scope size, few concurrent jobs |
| Schedulable | Time-based starts: a thin `execute` that starts a Batch or Queueable | Synchronous limits; an active schedule can block deploying the class |
| `@future` | Legacy only: primitive parameters, no job Id, no chaining | Not callable from Batch or `@future` |
| Platform event + trigger | Decoupling, fan-out, retries | [Platform Event and CDC Triggers](apex-triggers.md#platform-event-and-cdc-triggers) |
| Apex Cursors (API 66.0+) | Very large result sets paged by chained Queueables | [Pagination & Cursors](soql-sosl.md#pagination--cursors) |

### Enqueue once per transaction, not per record

`System.enqueueJob` is limited to 50 per transaction, and to one inside async Apex (Batch `execute`, a Queueable, `@future`) ([Governor Limits](platform.md#governor-limits)); every job also uses a daily async execution. Collect the Ids and enqueue one job, and where async code can reach the enqueue, check `Limits.getQueueableJobs() < Limits.getLimitQueueableJobs()` first. Triggers: [Keep callouts out of triggers and enqueue once per transaction](apex-triggers.md#keep-callouts-out-of-triggers-and-enqueue-once-per-transaction).

```apex
// ❌ One job per record: hits the enqueue limit and floods the async queue
for (Invoice__c inv : invoices) {
    System.enqueueJob(new InvoiceSyncJob(new Set<Id>{ inv.Id }, 1));
}

// ✅ One job for the whole set (attempt 1); the job re-queries by Id
System.enqueueJob(new InvoiceSyncJob(new Map<Id, Invoice__c>(invoices).keySet(), 1));
```

Static analysis: PMD `OperationWithLimitsInLoop`.

### Handle Queueable failures with a Finalizer where a failure needs a reaction (API 52.0+)

A Queueable that fails, including on an uncatchable `LimitException`, leaves only a failed `AsyncApexJob` row behind. When someone must react (integrations, callouts, work whose loss nobody would notice), call `System.attachFinalizer` at the start of `execute`: the `Finalizer` runs in its own transaction after the job ends, sees `ParentJobResult` and the exception, and can log, notify, or enqueue one bounded retry (a finalizer can re-enqueue a failed job at most five consecutive times). One Finalizer per job. A missing Finalizer is a 💡 suggestion (PMD `QueueableWithoutFinalizer`), not a defect: jobs whose failure is harmless or already monitored don't need one.

```apex
// ✅ In the Finalizer's execute(FinalizerContext context): log the failure, retry a bounded number of times
if (context.getResult() == ParentJobResult.UNHANDLED_EXCEPTION) {
    AppLog.error('InvoiceSyncJob', context.getException().getMessage(), null);
    if (attempt < MAX_ATTEMPTS) {
        System.enqueueJob(new InvoiceSyncJob(invoiceIds, attempt + 1));
    }
}
```

### Bound chains and deduplicate jobs with AsyncOptions (API 59.0+)

A Queueable that re-enqueues itself until the work is done becomes an endless chain when "done" never happens, and production orgs don't cap chain depth. Set `MaximumQueueableStackDepth` wherever a chain can start (retries included), check `AsyncInfo` before chaining, and give jobs that must not run twice a `QueueableDuplicateSignature`: a second enqueue with the same signature throws `DuplicateMessageException`.

```apex
// ✅ Where the chain starts: cap the depth and dedupe by purpose and key
AsyncOptions options = new AsyncOptions();
options.MaximumQueueableStackDepth = 20;
options.DuplicateSignature = QueueableDuplicateSignature.Builder().addString('RecalcJob').addId(accountId).build();
System.enqueueJob(new RecalcJob(accountId), options); // DuplicateMessageException if a twin is already queued

// ✅ Inside execute(): chain only below the cap; a chain started without one stops instead of running forever
if (RecalcService.hasMoreWork(accountId) && AsyncInfo.hasMaxStackDepth()
        && AsyncInfo.getCurrentQueueableStackDepth() < AsyncInfo.getMaximumQueueableStackDepth()) {
    System.enqueueJob(new RecalcJob(accountId));
}
```

### Keep Batch Apex selective, right-sized, and stateless unless needed

The `start` query defines the job's volume, so it needs a selective filter ([Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes)): an unfiltered `Database.getQueryLocator('SELECT Id FROM Invoice__c')` is the defect, and a `WITH USER_MODE` query there runs as the user who started or scheduled the job. Choose the scope deliberately, lower than the default when each chunk makes callouts or fires heavy automation (`Database.executeBatch(job, 100)`). `Database.Stateful` serializes every instance field between chunks, so add it only for small counters or Id sets and never for `Database.SaveResult` lists. Implement `Database.RaisesPlatformEvents` so an unhandled exception publishes a `BatchApexErrorEvent` that a subscriber can log. Static analysis: PMD `AvoidStatefulDatabaseResult`.

### Prefer Queueable over @future in new code

`@future` methods take only primitive parameters, return no job Id, can't chain or attach a Finalizer, and can't be called from Batch or other `@future` code; a Queueable does all of that. Existing `@future` code is acceptable; raise it only for new or rewritten code ([Severity Calibration](platform.md#severity-calibration), row 19). Static analysis: PMD `AvoidFutureAnnotation`.

### Make jobs idempotent and safe to retry

This rule owns idempotency for every Salesforce guide. Finalizer retries, platform-event redelivery, a rescheduled job, or a user clicking twice can run the same work again, and data captured at enqueue time is stale when the job runs. Pass Ids, re-query current state in `execute`, skip work already done, and write integration results with `upsert` on an external Id so a repeat can't duplicate records.

```apex
// ❌ Inserts Payments built from rows captured at enqueue time: a retry duplicates them
insert as user payments;

// ✅ Re-read by Id, skip finished rows, upsert on an external Id, then mark the rows Imported
List<Payment_Staging__c> pending = [
    SELECT Id, Payment_Key__c, Invoice__c, Amount__c FROM Payment_Staging__c
    WHERE Id IN :stagingIds AND Status__c != 'Imported' WITH USER_MODE
];
List<Payment__c> payments = PaymentMapper.toPayments(pending); // External_Id__c = Payment_Key__c
upsert as user payments Payment__c.External_Id__c;
```

### Lock records you read and then write

Two transactions that read a value, compute, and write it back (a counter, a balance, a "claim this record" flag) overwrite each other. `SELECT ... FOR UPDATE` locks the returned rows until the transaction ends. A competing locking query waits up to 10 seconds and then throws `QueryException`; a competing update of a locked row throws `DmlException` with `UNABLE_TO_LOCK_ROW`. Lock the fewest rows for the shortest time (a locking query can't use `ORDER BY`), update parents in a consistent order, and retry contention later from async code, bounded, instead of looping ([TOCTOU Race Conditions](../code-quality-universal.md#toctou-race-conditions)).

```apex
// ✅ Lock the row; a lock wait over 10 seconds surfaces as a QueryException at the locking query
try {
    Account acc = [SELECT Id, Open_Invoice_Count__c FROM Account WHERE Id = :accountId WITH USER_MODE FOR UPDATE];
    acc.Open_Invoice_Count__c = (acc.Open_Invoice_Count__c == null ? 0 : acc.Open_Invoice_Count__c) + 1;
    update as user acc;
} catch (QueryException e) { // also raised for user-mode access errors, so the retry is bounded
    if (attempt < MAX_ATTEMPTS && Limits.getQueueableJobs() < Limits.getLimitQueueableJobs()) {
        System.enqueueJob(new InvoiceCountJob(accountId, attempt + 1));
    }
}
```

### Process very large result sets with Apex Cursors (API 66.0+)

A cursor (`Database.getCursor(query, AccessLevel.USER_MODE)`) holds a server-side result set that a chain of Queueables pages through with `fetch(position, count)`; it is serializable, so it travels in the job's fields with the next position. Each `fetch` counts as a SOQL query and its rows count toward the SOQL row limit ([Governor Limits](platform.md#governor-limits); query side in [Pagination & Cursors](soql-sosl.md#pagination--cursors)). Check that each job bounds `count` by `cursor.getNumRecords() - position`, stops at the end, and handles failure.

---

## Callouts & Integrations

### Put endpoints and credentials in Named Credentials

A hard-coded URL breaks between sandbox and production, and a key in code, Custom Labels, Custom Metadata, or Custom Settings ends up in source control and every deployment. A Named Credential, with an External Credential for the authentication protocol, keeps the endpoint per org and injects authentication: `req.setEndpoint('callout:Billing_API/v1/invoices')` replaces an `http://` URL plus an `Authorization` header built from a stored key ([Integration Endpoints & Credentials](metadata.md#integration-endpoints--credentials)). Static analysis: PMD `ApexSuggestUsingNamedCred`, `ApexInsecureEndpoint`.

### Set a timeout and handle every response

Set the timeout explicitly (`req.setTimeout(20000)`), within the callout limits ([Governor Limits](platform.md#governor-limits)). `Http.send` throws `CalloutException` for timeouts and connection failures; for everything else, check the status code (outside 200 to 299, throw a typed exception such as `BillingException` naming the status and the record) before parsing, parse into typed classes (`JSON.deserialize(res.getBody(), BillingResponse.class)`, catching `JSONException`) rather than casting `JSON.deserializeUntyped` output, and never copy response bodies that may hold personal data into messages.

### Make the callout before DML, or move it to a Queueable

A callout after uncommitted DML in the same transaction throws `System.CalloutException: You have uncommitted work pending`, and triggers can't make synchronous callouts at all ([Transactions & Execution Contexts](platform.md#transactions--execution-contexts)). Apex has no explicit commit: call out first and write the outcome afterwards, or commit now and hand the callout to a Queueable that implements `Database.AllowsCallouts`.

### Mock every callout in tests

Test methods can't make real callouts. Register an `HttpCalloutMock` with `Test.setMock` and cover the success, error-status, and malformed-body paths. When the test inserts data first, the documented order is: the DML, then `Test.startTest()`, then `Test.setMock`, then the callout, then `Test.stopTest()`; DML inside the startTest block before the callout fails with the uncommitted-work error.

```apex
// ✅ DML, then startTest, then setMock, then the callout
Invoice__c invoice = TestDataFactory.createInvoice();
Test.startTest();
Test.setMock(HttpCalloutMock.class, new BillingApiMock(500)); // respond() returns the given status
try {
    BillingService.submit(invoice);
    Assert.fail('Expected a BillingException');
} catch (BillingService.BillingException expected) {
    Assert.isTrue(expected.getMessage().contains('500'), 'The status code reaches the message');
}
Test.stopTest();
```

### Validate input and control the response in @RestResource classes

An Apex REST class is a public endpoint that runs as the authenticated caller. Deserializing the body straight into an sObject lets the caller set any field, and an uncaught exception returns the raw Apex error. Declare the class `global with sharing` (REST resources must be `global`), parse into a typed request, validate it, write in user mode, and return precise status codes with safe messages. Returning normally commits the transaction, so error paths must not leave partial writes behind.

```apex
// ✅ Pessimistic default status, typed request, validation, user-mode write, details only in the log
@HttpPost
global static void create() {
    RestResponse res = RestContext.response;
    res.statusCode = 400; // until the request is proven valid
    res.responseBody = Blob.valueOf('{"message":"Invalid invoice request."}');
    InvoiceRequest body; // inner class: public Id accountId; public Decimal amount;
    try {
        body = (InvoiceRequest) JSON.deserialize(RestContext.request.requestBody.toString(), InvoiceRequest.class);
    } catch (JSONException e) {
        return;
    }
    if (body?.accountId == null || body.amount == null || body.amount <= 0) {
        return;
    }
    Invoice__c inv = new Invoice__c(Account__c = body.accountId, Amount__c = body.amount);
    try {
        insert as user inv;
        res.statusCode = 201;
        res.responseBody = Blob.valueOf(JSON.serialize(new Map<String, String>{ 'id' => inv.Id }));
    } catch (DmlException e) {
        AppLog.error('InvoiceRestResource', e.getMessage(), null);
    }
}
```

### Publish platform events deliberately

`EventBus.publish` returns a `SaveResult` per event and doesn't throw when publishing fails, so check each result. The event's publish behavior (`publishBehavior` in the `__e` metadata) decides when subscribers see it: Publish After Commit events are delivered only if the transaction commits and count against the DML statement limit; Publish Immediately events go out even if the transaction rolls back and have a separate limit, so subscribers may act on data that was never saved. Keep Publish Immediately for logging and monitoring.

---

## Testing

Test results and coverage are org-side evidence: ask the author or CI for them, and review the test code for what it proves. The code under test, not the fixtures, must enforce access, and fakes come through a seam ([Inject dependencies so tests can replace them](#inject-dependencies-so-tests-can-replace-them)). House conventions such as a sharing keyword on test classes or a `TestDataFactory` apply only when the repo already follows them. Trigger tests: [Testing Triggers](apex-triggers.md#testing-triggers).

### Assert outcomes with the Assert class (API 56.0+)

A test without assertions only proves that the code didn't throw (`System.assert(true)` after the call is coverage padding), and coverage is a deployment gate ([Governor Limits](platform.md#governor-limits)), not a quality signal. Assert the state that matters (field values, record counts, published events, error messages) with messages that explain the failure. `Assert.areEqual`, `isTrue`, `isNull`, `fail`, and `isInstanceOfType` read more clearly than `System.assert*`, which stays valid ([Severity Calibration](platform.md#severity-calibration), row 19). Static analysis: PMD `ApexUnitTestClassShouldHaveAsserts`, `ApexAssertionsShouldIncludeMessage`.

### Build test data in the test, never with SeeAllData=true or org Ids

`@IsTest(SeeAllData=true)` makes tests depend on org data that differs in every sandbox and lets them change real records, and hard-coded Ids, usernames, and record type Ids fail after the next refresh or in CI scratch orgs. Create data in `@TestSetup` (each test method starts from that state), create users in the test, resolve record types by developer name, and use `Test.getStandardPricebookId()`. Exception: the rare APIs that need org data, such as many `ConnectApi` methods, in an isolated, commented test. Static analysis: PMD `ApexUnitTestShouldNotUseSeeAllDataTrue`, `AvoidHardcodingId`.

### Cover bulk, negative, and least-privilege paths

A single happy-path record hides every loop defect. Each changed entry point needs a bulk case (200+ records; trigger tests need 201+), a negative case that asserts the error, and a `System.runAs` case with a user who has only the permission sets the feature grants. `runAs` enforces record sharing only; CRUD and FLS apply where the code uses user mode, which is what a least-privilege test proves. Static analysis: PMD `ApexUnitTestClassShouldHaveRunAs`.

```apex
// ✅ Least privilege: a read-only user can't approve (the invoices are shared with the viewer)
System.runAs(TestDataFactory.createUser('Invoice_Viewer')) {
    try {
        InvoiceService.approve(invoiceIds);
        Assert.fail('A read-only user must not approve invoices');
    } catch (DmlException expected) {
        // user-mode DML rejected the write
    }
}
```

### Wrap the call under test in Test.startTest() and Test.stopTest()

Code between `startTest` and `stopTest` gets a fresh set of governor limits, so setup work doesn't hide a limit problem, and async work enqueued inside (Queueable, Batch, `@future`, platform events) runs when `stopTest` is called: assert after it, never before. A Queueable that chains a child has thrown "Maximum stack depth has been reached" in tests; the Apex Developer Guide now says chained jobs can be tested with an appropriate `MaximumQueueableStackDepth` (verify in the author's CI), and otherwise a `@TestVisible` switch turns chaining off so the next link is tested on its own.

### Treat RunRelevantTests annotations as opt-in (API 66.0+, Beta)

The Beta `RunRelevantTests` test level runs only the tests related to the deployed components. On a test class, `@IsTest(testFor='ApexClass:InvoiceService,ApexTrigger:InvoiceTrigger')` names what the class covers, and `@IsTest(critical=true)` makes it run on every deployment. If the project deploys with this level, check that new test classes list accurate `testFor` values; don't block a change for missing annotations while the feature is Beta.

---

## Managed Packages

Applies only when `sfdx-project.json` declares a namespace. Code shipped in a managed package runs in subscriber orgs you don't control, and its public surface can't shrink once released. Certified packages get their own counters for most limits ([Governor Limits](platform.md#governor-limits)).

### Treat every released global member as permanent

Once a managed package version is released, its `global` classes, methods, properties, and interfaces can't be removed or change signature. Add `global` only for a deliberate API ([Severity Calibration](platform.md#severity-calibration), row 18), share code between packages of the same namespace with `public` plus `@NamespaceAccessible`, and deprecate instead of deleting. Static analysis: PMD `AvoidGlobalModifier`.

### Reference packaged schema through tokens, not strings

In subscriber orgs the package's objects and fields carry its namespace prefix (`ns__Invoice__c`). Static references are checked by the compiler, which adds the namespace, while names inside strings (dynamic SOQL, `sObject.get('Field__c')`, describe-map keys) are resolved only at run time. Build strings from tokens: `record.get(Invoice__c.Amount__c)`, and `Invoice__c.Amount__c.getDescribe().getName()` includes the namespace while `getLocalName()` omits it. Keep binds in the dynamic query ([SOQL Injection](soql-sosl.md#soql-injection)).

### Change released code in upgrade-safe steps

Add overloads instead of changing a released signature (the package version upload fails otherwise), mark retired globals `@Deprecated` (existing subscriber code keeps working, new code can't reference them), branch on `System.requestVersion()` when behavior must differ by the version a subscriber calls, and test against subscriber-like conditions: other triggers, validation rules, and data volumes you didn't write ([Salesforce Architecture](../architecture-review-guide.md#salesforce-architecture)).

---

## References

- [Using the with sharing, without sharing, and inherited sharing Keywords (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_keywords_sharing.htm)
- [Set an Access Mode for Database Operations (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_enforce_usermode.htm)
- [Queueable Apex (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_queueing_jobs.htm)
- [Transaction Finalizers (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_transaction_finalizers.htm)
- [Performing DML Operations and Mock Callouts (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_restful_http_testing_dml.htm)
