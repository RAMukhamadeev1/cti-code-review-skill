# Apex Code Review Guide

Review guidance for Apex classes: services, selectors, controllers, Batch, Queueable, and Schedulable jobs, REST resources, and invocable methods. It covers bulkification, language pitfalls, class design, data-access security, transactions, async Apex, callouts, tests, and managed packages, through API 67.0 (Summer '26) and later.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
> Related: [Apex Triggers](apex-triggers.md) · [SOQL & SOSL](soql-sosl.md) · [LWC-Apex contract](lwc.md#the-lwc-apex-contract) · [Invocable Apex](flows.md#invocable-apex-contract)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Bulkification](#bulkification)
- [Language Pitfalls](#language-pitfalls)
- [Class Design](#class-design)
- [Data Access Security](#data-access-security)
- [Transactions & Error Handling](#transactions--error-handling)
- [Async Apex](#async-apex)
- [Callouts & Integrations](#callouts--integrations)
- [Testing](#testing)
- [Managed Packages](#managed-packages)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| Service, selector, domain, and utility classes | This guide |
| `@AuraEnabled` controllers | This guide + [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract) (Aura callers: [Server Actions](aura.md#server-actions)) |
| `@InvocableMethod` actions | This guide + [Invocable Apex Contract](flows.md#invocable-apex-contract) |
| Visualforce controllers and extensions | This guide + [Controller Security](visualforce.md#controller-security) |
| Trigger handlers | This guide + [apex-triggers.md](apex-triggers.md) |
| Batch, Queueable, Schedulable, and `@future` classes | [Async Apex](#async-apex) |
| `@RestResource` classes and outbound callouts | [Callouts & Integrations](#callouts--integrations) |
| Test classes | [Testing](#testing) (+ [Testing Triggers](apex-triggers.md#testing-triggers) for trigger tests) |
| Inline or dynamic SOQL and SOSL | [soql-sosl.md](soql-sosl.md) as well |

Open the class's `-meta.xml` before the code: its `<apiVersion>` decides the default sharing and access mode ([Security Model](platform.md#security-model)) and which language features compile ([API Versions](platform.md#api-versions)). The examples spell access modes out (`WITH USER_MODE`, `as user`), which behaves the same at every version from API 57.0, and they compile at API 57.0+ unless a heading names a later version.

---

## Bulkification

Every Apex entry point can receive a list: triggers deliver up to 200 records per chunk, and Batch, Queueable, invocable, and API callers pass whatever they collected. Per-record SOQL, DML, or callouts turn N records into N operations and end in an uncatchable `LimitException` long before production volumes ([Governor Limits](platform.md#governor-limits)).

> 📖 For the cross-language pattern, see [N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow).

### Keep SOQL, DML, callouts, and enqueues out of loops

Collect the keys first, run one query, index the result in a map, and write all changes with one DML statement. Look inside every method called from a loop as well: a helper that queries or saves one record becomes N+1 when a caller runs it per record, and per-record DML re-runs every trigger and flow on the object each time, so give helpers a bulk signature.

```apex
// ❌ One query and one DML per record: 200 Opportunities cost 200 queries and 200 DML statements
for (Opportunity opp : opportunities) {
    Account acc = [SELECT Rating FROM Account WHERE Id = :opp.AccountId WITH USER_MODE];
    opp.Account_Rating__c = acc.Rating;
    update as user opp;
}

// ✅ Collect Ids, query once into a map, write once
Set<Id> accountIds = new Set<Id>();
for (Opportunity opp : opportunities) {
    accountIds.add(opp.AccountId);
}
Map<Id, Account> accountsById = new Map<Id, Account>([SELECT Id, Rating FROM Account WHERE Id IN :accountIds WITH USER_MODE]);
for (Opportunity opp : opportunities) {
    opp.Account_Rating__c = accountsById.get(opp.AccountId)?.Rating;
}
update as user opportunities;

// ❌ A hidden loop: looks bulk-safe, but getTier() runs one query per call
for (Contact con : contacts) {
    con.Account_Tier__c = AccountService.getTier(con.AccountId);
}

// ✅ Bulk signature: one call with every key, one query inside
Map<Id, String> tierByAccountId = AccountService.getTiers(accountIds);
for (Contact con : contacts) {
    con.Account_Tier__c = tierByAccountId.get(con.AccountId);
}
```

Static analysis: PMD `OperationWithLimitsInLoop` (SOQL, SOSL, DML, `Database` and `Approval` methods, `Messaging.sendEmail`, `System.enqueueJob`, `System.schedule`).

### Index with maps instead of nested loops

Nested loops over two collections cost n × m iterations of CPU time, which is a governor limit too, and `List.contains()` inside a loop is a nested loop as well. Build a map (or a `Set`) keyed by the join field once, or aggregate in SOQL when the rows aren't loaded yet ([Query Shape](soql-sosl.md#query-shape)).

```apex
// ❌ 200 invoices × 2,000 lines = 400,000 iterations
for (Invoice__c inv : invoices) {
    for (Invoice_Line__c line : lines) {
        if (line.Invoice__c == inv.Id) {
            inv.Total__c += line.Amount__c;
        }
    }
}

// ✅ Group once (n + m iterations), then look up
Map<Id, Decimal> totalByInvoiceId = new Map<Id, Decimal>();
for (Invoice_Line__c line : lines) {
    Decimal total = totalByInvoiceId.get(line.Invoice__c);
    totalByInvoiceId.put(line.Invoice__c, (total == null ? 0 : total) + line.Amount__c);
}
for (Invoice__c inv : invoices) {
    inv.Total__c = totalByInvoiceId.containsKey(inv.Id) ? totalByInvoiceId.get(inv.Id) : 0;
}
```

### Write each record once, and only when it changed

Merge the changes that several rules make to one record into a single map entry per Id, compare with the current value, and issue one DML per sObject type. A list that holds the same Id twice fails the whole statement, and every extra or unchanged update still runs the record's triggers, flows, validation rules, and roll-ups ([No-Op Updates](../code-quality-universal.md#no-op-updates)).

```apex
// ❌ Two won Opportunities of one Account add it twice (System.ListException: Duplicate id in list),
//    and Accounts that already show this date are rewritten, re-running all of their automation
List<Account> toUpdate = new List<Account>();
for (Opportunity opp : wonOpportunities) {
    toUpdate.add(new Account(Id = opp.AccountId, Last_Won_Date__c = opp.CloseDate));
}
update as user toUpdate;

// ✅ One entry per Id, only real changes, one DML
Map<Id, Account> toUpdate = new Map<Id, Account>();
for (Opportunity opp : wonOpportunities) { // queried with Account.Last_Won_Date__c
    Account pending = toUpdate.get(opp.AccountId);
    Date current = pending != null ? pending.Last_Won_Date__c : opp.Account?.Last_Won_Date__c;
    if (opp.AccountId != null && (current == null || opp.CloseDate > current)) {
        toUpdate.put(opp.AccountId, new Account(Id = opp.AccountId, Last_Won_Date__c = opp.CloseDate));
    }
}
update as user toUpdate.values();
```

### Keep describes, regex, and serialization out of loops

Some calls cost CPU and heap rather than limits: `Schema.getGlobalDescribe()` and `Schema.describeSObjects()` are slow in large orgs, `getDescribe()` without options loads every child relationship, and `Pattern.compile`, `JSON.serialize`, and `+=` string building repeat work on every pass (collect parts in a `List<String>` and `String.join` once).

```apex
// ❌ A global describe per record
for (Invoice__c inv : invoices) {
    Schema.DescribeFieldResult status = Schema.getGlobalDescribe()
        .get('Invoice__c').getDescribe().fields.getMap().get('Status__c').getDescribe();
    inv.Status_Text__c = PicklistUtils.labelFor(status.getPicklistValues(), inv.Status__c);
}

// ✅ Describe once through the token and build the lookup map before the loop
Map<String, String> statusLabels = new Map<String, String>();
for (Schema.PicklistEntry entry : Invoice__c.Status__c.getDescribe().getPicklistValues()) {
    statusLabels.put(entry.getValue(), entry.getLabel());
}
for (Invoice__c inv : invoices) {
    inv.Status_Text__c = statusLabels.get(inv.Status__c);
}
// ✅ Object describes without eagerly loading child relationships
Schema.DescribeSObjectResult invoiceDescribe = Invoice__c.SObjectType.getDescribe(SObjectDescribeOptions.DEFERRED);
```

Static analysis: PMD `OperationWithHighCostInLoop` (`Schema.getGlobalDescribe()`, `Schema.describeSObjects()`), `EagerlyLoadedDescribeSObjectResult`.

---

## Language Pitfalls

Apex reads Java-like, but strings compare without case while collections keep it, Ids come in two lengths, and many date methods depend on the running user's time zone. These differences pass review and fail on production data.

### Use safe navigation for optional relationships and lookups (API 50.0+ / Winter '21)

A parent relationship is `null` when the lookup is empty, and `Map.get()` returns `null` for a missing key; dereferencing either throws `NullPointerException`, and the uncaught exception rolls back the whole transaction. Use `?.` only where null is a valid state: a missing required value should fail loudly.

```apex
// ❌ NullPointerException when the Account has no parent or no credit-limit row exists
String parentName = opp.Account.Parent.Name;
Decimal creditLimit = creditLimitsByAccountId.get(opp.AccountId).Amount__c;

// ✅ Safe navigation yields null instead of throwing
String parentName = opp.Account?.Parent?.Name;
Decimal creditLimit = creditLimitsByAccountId.get(opp.AccountId)?.Amount__c;
```

### Default missing values with null coalescing (API 60.0+ / Spring '24)

`??` returns its right operand when the left one is null. It compiles only in classes at API 60.0+, can't be the left side of an assignment, and isn't allowed in SOQL bind expressions. Suggest it only in files already at API 60.0+; never bump an apiVersion for syntax alone.

```apex
// ❌ NullPointerException when the setting record or its field is empty
Invoice_Setting__mdt settings = Invoice_Setting__mdt.getInstance('Default');
Decimal net = gross * (1 - settings.Max_Discount__c);

// ✅ API 60.0+
Decimal net = gross * (1 - (settings?.Max_Discount__c ?? 0.0));

// ✅ Before API 60.0
Decimal discount = (settings == null || settings.Max_Discount__c == null) ? 0 : settings.Max_Discount__c;
```

### Normalize String keys before using Maps and Sets

`==` on Strings ignores case, but `String.equals()`, Map keys, and Set elements are case-sensitive. Code that compares with `==` in one place and looks up a map in another treats 'ACME-01' and 'acme-01' as equal and different at the same time.

```apex
// ❌ == matches, but the map lookup misses
accountsByCode.put(acc.Account_Code__c, acc);             // stored as 'ACME-01'
Account match = accountsByCode.get(requestedCode);        // 'acme-01' -> null
Boolean sameCode = acc.Account_Code__c == requestedCode;  // true: == ignores case

// ✅ Normalize on write and on read; use equals() where case is significant
accountsByCode.put(acc.Account_Code__c.toUpperCase(), acc); // Account_Code__c is required
Account match = accountsByCode.get(requestedCode?.toUpperCase());
Boolean tokenMatches = expectedToken.equals(receivedToken);  // case-sensitive on purpose
```

### Compare Ids as Id, not as Strings

An `Id` variable always holds the 18-character form, while a `String` keeps what it was given, often the 15-character form from a report, URL, or spreadsheet. String comparison then fails for the same record and string-keyed collections hold duplicates. Convert at the boundary, where `Id.valueOf` throws `StringException` for malformed input.

```apex
// ❌ Two String forms of one record never match
String storedId = acc.Id;                     // '001000000000001AAA' (18 characters)
String requestedId = params.get('accountId'); // '001000000000001' (15 characters)
Boolean sameRecord = storedId == requestedId; // false

// ✅ Convert once, then compare and key by Id
Id requestedAccountId = Id.valueOf(params.get('accountId'));
Boolean sameRecord = acc.Id == requestedAccountId; // true: both hold the 18-character form
```

### Keep money in Decimal with explicit scale and rounding

Currency fields are `Decimal`. `Double` is binary floating point, so cents drift, and `Integer` division truncates even when the result is assigned to a `Decimal`. Set scale and rounding where the business rule defines them; in multi-currency orgs never add amounts in different currencies ([Dates, Currency & Labels](soql-sosl.md#dates-currency--labels)).

```apex
// ❌ Binary floating point and integer division
Double total = unitPrice + 0.2;                 // Double unitPrice = 0.1: not exactly 0.3
Decimal paidRatio = paidCount / totalCount;     // Integer / Integer: 1 / 3 = 0

// ✅ Decimal arithmetic with a declared scale and rounding mode
Decimal paid = paidCount;                       // widen before dividing
Decimal paidRatio = paid.divide(totalCount, 4, System.RoundingMode.HALF_UP);
Decimal net = (gross * (1 - discount)).setScale(2, System.RoundingMode.HALF_EVEN);
```

### Keep Date and Datetime time zones explicit

`Datetime.now()` is an instant, stored in UTC. `Date.today()`, `Datetime.format()`, `Datetime.date()`, and `Datetime.newInstance()` use the running user's time zone, and async jobs, event subscribers, and integration users may run in a different zone than the person who started the work. Format patterns follow the Java-style `SimpleDateFormat` rules, where `YYYY` is the week-based year.

```apex
// ❌ Implicit time zones and a week-based year
String stamp = Datetime.now().format('YYYY-MM-dd HH:mm'); // user's zone; YYYY is wrong around New Year
Date reportDay = Datetime.now().date();                   // the user's local date, not the UTC date

// ✅ Keep instants; convert at the edge with an explicit zone and yyyy
Datetime startedAt = Datetime.now();
String isoUtc = startedAt.formatGmt('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'');
String branchLocal = startedAt.format('yyyy-MM-dd HH:mm', 'Europe/Berlin');
Date utcDay = startedAt.dateGmt();
```

---

## Class Design

### Keep entry points thin: controller, service, selector

Controllers, trigger handlers, invocables, REST resources, and jobs should parse input, call a service, and shape the response. Rules written inside one entry point can't be reused by the next one (a flow, a batch, an API), and copies drift. Follow the layering the project already uses, such as Apex Enterprise Patterns (fflib) or a plain service and selector split ([Salesforce Architecture](../architecture-review-guide.md#salesforce-architecture)).

```apex
// ❌ Query, rule, and DML inside the @AuraEnabled method
@AuraEnabled
public static void approveInvoice(Id invoiceId) {
    Invoice__c inv = [SELECT Id, Amount__c FROM Invoice__c WHERE Id = :invoiceId];
    inv.Status__c = inv.Amount__c > 10000 ? 'Needs Review' : 'Approved';
    update inv;
}

// ✅ The controller delegates; the service takes a set, so every entry point is bulk-safe
public with sharing class InvoiceController {
    @AuraEnabled
    public static void approveInvoice(Id invoiceId) {
        try {
            InvoiceService.approve(new Set<Id>{ invoiceId });
        } catch (InvoiceService.InvoiceException e) {
            throw new AuraHandledException(e.getMessage()); // error contract: lwc.md
        }
    }
}

public with sharing class InvoiceService {
    public static void approve(Set<Id> invoiceIds) {
        Decimal threshold = InvoiceSettings.reviewThreshold();                // Custom Metadata
        List<Invoice__c> invoices = InvoiceSelector.selectByIds(invoiceIds); // user mode inside
        for (Invoice__c inv : invoices) {
            inv.Status__c = inv.Amount__c > threshold ? 'Needs Review' : 'Approved';
        }
        update as user invoices;
    }
}
```

### Declare the sharing keyword on every class

Check the class's `<apiVersion>` first: the behavior of an undeclared class changed at API 67.0, including for undeclared classes in an inheritance chain ([Security Model](platform.md#security-model)). An explicit keyword keeps the intent reviewable across version bumps: `with sharing` for entry points and services, `inherited sharing` for selectors and utilities shared by many callers (it runs `with sharing` as the entry point), and `without sharing` only as in the next rule. Inner classes don't inherit the outer keyword, so declare one on inner classes that touch data.

```apex
// ❌ No keyword: record access depends on the caller and on the file's apiVersion
public class InvoiceSelector { /* queries */ }

// ✅ One keyword per class, chosen by role
public with sharing class InvoiceController { /* entry point */ }
public with sharing class InvoiceService { /* business rules */ }
public inherited sharing class InvoiceSelector { /* shared queries, WITH USER_MODE */ }
public without sharing class AgentWorkload { /* documented escalation, see the next rule */ }
```

Static analysis: PMD `ApexSharingViolations`.

### Isolate without sharing in small, named, documented classes

When a feature must count or find records the user can't see, put exactly that query in a dedicated `without sharing` class, write the reason in a comment, return the minimum (Ids or counts, not records), and call it from a `with sharing` service. At API 67.0+ also write the system mode explicitly, because implicit operations default to user mode there.

```apex
// ❌ The whole controller escapes sharing to support one lookup
public without sharing class CaseRoutingController { /* every query and DML ignores sharing */ }

// ✅ Without sharing and system mode: round-robin routing must count every agent's open cases,
//    including cases the running user cannot see. Returns counts, never records.
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

`global` is needed only for managed-package APIs and for `@RestResource` and `webservice` classes; older API versions required it for some interfaces such as `Database.Batchable`, current ones don't. Don't widen visibility for tests either: `@TestVisible` exposes a private member to test code only.

```apex
// ❌ global without a package API, and a public field only so a test can read it
global with sharing class DiscountCalculator {
    public static Decimal lastComputedRate;
}

// ✅ Narrowest visibility; tests use @TestVisible
public with sharing class DiscountCalculator {
    @TestVisible
    private static Decimal lastComputedRate;
}
```

Static analysis: PMD `AvoidGlobalModifier`. Package rules: [Managed Packages](#managed-packages).

### Inject dependencies so tests can replace them

A class that constructs its gateway or selector internally can only be tested with real data and real callout mocks, which pushes authors toward `Test.isRunningTest()` branches: production paths that no test runs, plus test-only behavior in production code. Depend on an interface, default to the production implementation, and let tests substitute a fake through a `@TestVisible` field, a `Type.forName` binding stored in Custom Metadata, or the Stub API (`Test.createStub`).

```apex
// ❌ Hard-wired dependency behind a test-only branch
if (!Test.isRunningTest()) {
    new HttpInvoiceGateway().send(invoices);
}

// ✅ Interface with a production default behind a @TestVisible seam
public interface InvoiceGateway {
    void send(List<Invoice__c> invoices);
}

public with sharing class InvoiceSyncService {
    @TestVisible
    private static InvoiceGateway gateway = new HttpInvoiceGateway();
    public static void sync(List<Invoice__c> invoices) {
        gateway.send(invoices);
    }
}

// ✅ The test installs a recording fake
@IsTest
private inherited sharing class InvoiceSyncServiceTest {
    private class RecordingGateway implements InvoiceGateway {
        public List<Invoice__c> sent = new List<Invoice__c>();
        public void send(List<Invoice__c> invoices) {
            sent.addAll(invoices);
        }
    }
    @IsTest
    static void sendsEveryInvoice() {
        RecordingGateway fake = new RecordingGateway();
        InvoiceSyncService.gateway = fake;
        List<Invoice__c> invoices = [SELECT Id FROM Invoice__c];
        InvoiceSyncService.sync(invoices);
        Assert.areEqual(invoices.size(), fake.sent.size(), 'Every invoice reaches the gateway');
    }
}
```

### Read business configuration from Custom Metadata, not constants

Thresholds, feature switches, and mappings change per org and per season; constants force a deployment for every change and invite hard-coded Ids. Keep them in Custom Metadata and resolve records by DeveloperName ([Org-Agnostic Code](platform.md#org-agnostic-code)).

```apex
// ❌ Business values and an org-specific Id in code
private static final Decimal REVIEW_THRESHOLD = 10000;
private static final Id REVIEW_RECORD_TYPE_ID = '012000000000000AAA';

// ✅ Custom Metadata for values, DeveloperName for record types
Decimal reviewThreshold = Invoice_Setting__mdt.getInstance('Default').Review_Threshold__c;
Id reviewRecordTypeId = Schema.SObjectType.Invoice__c
    .getRecordTypeInfosByDeveloperName().get('Review').getRecordTypeId();
```

Static analysis: PMD `AvoidHardcodingId`.

---

## Data Access Security

Check the class's `<apiVersion>` first: the default access mode and sharing changed at API 67.0 ([Security Model](platform.md#security-model) has the full matrix and the enforcement-mechanism table). Query-side modes (`WITH USER_MODE`, `WITH SYSTEM_MODE`, `AccessLevel` on `Database.query*`) are in [Access Mode in Queries](soql-sosl.md#access-mode-in-queries); this section covers writes, sanitizing, escalation, and managed sharing. A sharing keyword controls which records a user reaches, never object or field permissions.

> 📖 Platform-wide checks: [Salesforce Platform Security](../security-review-guide.md#salesforce-platform-security).

### Write in user mode, not with hand-rolled describe checks (API 57.0+ / Spring '23)

User-mode DML enforces the running user's object permissions, field-level security, and sharing on the records being written. Use `as user` on DML statements or `AccessLevel.USER_MODE` on `Database` methods for every write a user causes; at API 67.0+ this is the default, and writing it explicitly keeps the intent visible when classes at different versions call each other. Describe checks (`isCreateable()`, `isUpdateable()`, per-field `isAccessible()`) are the legacy fallback: one forgotten field leaks or overwrites data, so accept them only in code below API 57.0 and for UI decisions such as hiding a button.

```apex
// ❌ API 66.0 class: with sharing limits the records, but this DML ignores CRUD and FLS
insert contacts;

// ❌ Hand-rolled checks: Phone, Title, and every other populated field were never checked
if (Schema.sObjectType.Contact.isCreateable() && Schema.sObjectType.Contact.fields.Email.isCreateable()) {
    insert contacts;
}

// ✅ User-mode DML; access failures throw DmlException (SecurityException before API 58.0)
insert as user contacts;
List<Database.SaveResult> results = Database.insert(contacts, false, AccessLevel.USER_MODE);

// ✅ Before API 57.0: strip the fields the user can't create, then insert
insert Security.stripInaccessible(AccessType.CREATABLE, contacts).getRecords();
```

Static analysis: PMD `ApexCRUDViolation`.

### Sanitize records that cross the client boundary with stripInaccessible (API 48.0+ / Spring '20)

`Security.stripInaccessible` removes the fields a user can't read or write instead of throwing, and reports what it removed. Use it where partial data is acceptable, typically records queried in system mode for a documented reason and then returned to LWC, Aura, or REST. It doesn't check record sharing, and it returns new records: use `getRecords()`, not the original list.

```apex
// ❌ The sanitized copy is discarded; the original records still carry every field
Security.stripInaccessible(AccessType.READABLE, accounts);
return accounts;

// ✅ Return the decision's records and tell the UI which fields were hidden
SObjectAccessDecision decision = Security.stripInaccessible(AccessType.READABLE, accounts);
page.records = (List<Account>) decision.getRecords();
page.hiddenFields = decision.getRemovedFields().get('Account'); // null when nothing was removed
return page;
```

### Justify every system-mode escalation

`WITH SYSTEM_MODE`, `as system`, and `AccessLevel.SYSTEM_MODE` skip CRUD and FLS; record sharing still follows the class keyword, so reaching hidden records also needs `without sharing`. Each escalation needs a comment naming who needs the access and why, the narrowest query or write, and no system-mode data returned to the user unfiltered.

```apex
// ❌ System mode by habit, returning a salary field to the UI
return [SELECT Id, Name, Email, Salary__c FROM Contact WHERE AccountId = :accountId WITH SYSTEM_MODE];

// ✅ User mode for what the user reads
return [SELECT Id, Name, Email FROM Contact WHERE AccountId = :accountId WITH USER_MODE];

// ✅ A documented, narrow escalation for an automation-owned field
// System mode: Last_Survey_Sent__c is read-only for every profile and maintained only by this
// service; users may send the survey but must not edit the field.
Account stamp = new Account(Id = accountId, Last_Survey_Sent__c = System.now());
update as system stamp;
```

### Never trust client-supplied Ids, records, or field lists

Every `@AuraEnabled`, `@RemoteAction`, `@RestResource`, and invocable parameter is attacker-controlled. An Id can point to a record the user may not touch ([IDOR](../security-review-guide.md#idor-insecure-direct-object-reference); the entry-point example is in [Security Model](platform.md#security-model)), and a deserialized sObject can carry fields the UI never showed, such as `OwnerId`. Copy only the fields the action changes onto a new record and let user mode check access.

```apex
// ❌ Mass assignment: the client decides which fields change, in system mode
@AuraEnabled
public static void saveCase(Case record) {
    update record;
}

// ✅ Accept only what the action changes; user mode enforces record and field access
private static final Set<String> ALLOWED_STATUSES = new Set<String>{ 'Working', 'Escalated' };

@AuraEnabled
public static void updateCaseStatus(Id caseId, String status) {
    if (!ALLOWED_STATUSES.contains(status)) {
        throw new AuraHandledException('Unsupported status.');
    }
    Case change = new Case(Id = caseId, Status = status);
    update as user change;
}
```

### Share records programmatically with an Apex sharing reason

When sharing rules can't express who needs access, create `__Share` rows with a custom sharing reason as `RowCause`. Rows with the `Manual` reason are deleted when the record owner changes, while rows with an Apex sharing reason survive and can be recalculated; sharing reasons exist only on custom objects ([Sharing Configuration](metadata.md#sharing-configuration)). Check every result instead of ignoring failures in bulk.

```apex
// ❌ Manual row cause: removed when the owner changes
Invoice__Share share = new Invoice__Share(
    ParentId = inv.Id, UserOrGroupId = reviewerId, AccessLevel = 'Read', RowCause = 'Manual');

// ✅ Without sharing and system mode: reviewers get access by business rule, and the running
//    user usually doesn't own the invoices. Custom sharing reason, one insert, results checked.
public without sharing class InvoiceSharing {
    public static void shareWithReviewers(Map<Id, Id> reviewerIdByInvoiceId) {
        List<Invoice__Share> shares = new List<Invoice__Share>();
        for (Id invoiceId : reviewerIdByInvoiceId.keySet()) {
            shares.add(new Invoice__Share(ParentId = invoiceId, UserOrGroupId = reviewerIdByInvoiceId.get(invoiceId),
                AccessLevel = 'Read', RowCause = Schema.Invoice__Share.RowCause.Reviewer__c));
        }
        List<Database.SaveResult> results = Database.insert(shares, false, AccessLevel.SYSTEM_MODE);
        for (Integer i = 0; i < results.size(); i++) {
            if (!results[i].isSuccess()) {
                AppLog.error('InvoiceSharing', results[i].getErrors()[0].getMessage(), shares[i].ParentId);
            }
        }
    }
}
```

---

## Transactions & Error Handling

A transaction commits only when its entry point finishes without an unhandled exception; any uncaught exception rolls back all of its DML. Catch an exception only to add context, to translate it for the caller, or to continue deliberately after a partial failure.

> 📖 For cross-language principles, see [Error Handling Principles](../cross-cutting/error-handling-principles.md#salesforce-apex).

### Catch specific exceptions, add context, and never swallow them

A catch block that only logs, or does nothing, tells the caller the operation succeeded. Catch the types you can handle and rethrow a custom exception that names what failed and keeps the original as its cause. Custom exception class names must end in `Exception`, and they inherit constructors for a message, a cause, or both; keep user-facing text separate from diagnostic detail when the message reaches the UI ([The LWC-Apex Contract](lwc.md#the-lwc-apex-contract)). `System.LimitException` is the exception that no catch block sees ([Governor Limits](platform.md#governor-limits)).

```apex
// ❌ Swallowed: the caller believes the invoices were created
try {
    insert as user invoices;
} catch (Exception e) {
    System.debug(e.getMessage());
}

// ✅ Specific type, context added, cause preserved
public with sharing class InvoiceService {
    public class InvoiceException extends Exception {}
    public static void create(List<Invoice__c> invoices) {
        try {
            insert as user invoices;
        } catch (DmlException e) {
            throw new InvoiceException('Could not create ' + invoices.size() + ' invoices: ' + e.getDmlMessage(0), e);
        }
    }
}

// ⚠️ catch (Exception e) never runs for "Too many SOQL queries": LimitException can't be caught.
//    Bulkify, or send large inputs to Batch Apex, which gets fresh limits for every chunk.
```

Static analysis: PMD `EmptyCatchBlock` (it flags only empty blocks; a catch that only logs is the same defect).

### Inspect every SaveResult when allowing partial success

`Database.insert`, `update`, and `upsert` with `allOrNone = false` commit the valid records, return one result per input in input order, and throw nothing for the failures. The platform also retries the successful subset and fires triggers again for it, with static variables intact ([Recursion Control](apex-triggers.md#recursion-control)).

```apex
// ❌ Results ignored: failed rows vanish without a trace
Database.update(invoices, false, AccessLevel.USER_MODE);

// ✅ Pair each result with its input and report the failures (AppLog: see the logging rule below)
List<Database.SaveResult> results = Database.update(invoices, false, AccessLevel.USER_MODE);
for (Integer i = 0; i < results.size(); i++) {
    if (!results[i].isSuccess()) {
        AppLog.error('InvoiceService', results[i].getErrors()[0].getMessage(), invoices[i].Id);
    }
}
```

### Use a savepoint when you catch and continue after multi-step writes

An uncaught exception already rolls everything back, so a savepoint matters when code catches the exception and returns normally: an error DTO, a REST status code, an invocable result. Setting and rolling back a savepoint each count as a DML statement, a rollback doesn't revert static variables, and records inserted after the savepoint keep their Ids, so re-inserting the same instances fails.

```apex
// ❌ Returns normally after a partial write: the invoice commits without its lines
try {
    insert as user invoice;
    insert as user lines;
} catch (DmlException e) {
    return e.getDmlMessage(0);
}

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

DML on setup objects (User, UserRole, Group and GroupMember, PermissionSet and PermissionSetAssignment, QueueSObject, territories) and on other objects in the same transaction fails with `MIXED_DML_OPERATION`. Move the setup part to a Queueable (`@future` in legacy code); in tests, wrap the setup DML in `System.runAs`.

```apex
// ❌ Business record and permission assignment in one transaction: MIXED_DML_OPERATION
insert as user onboarding;
insert as user permissionSetAssignment;

// ✅ Commit the business data now; assign access in a separate transaction (permission set by name)
insert as user onboarding;
System.enqueueJob(new PermissionAssignmentJob(new Set<Id>{ userId }, 'Invoice_Clerk'));
```

### Log with levels and without personal data; persist what must survive a rollback

`System.debug` output exists only while someone has a trace flag, costs CPU even when nobody reads it, and often leaks tokens and personal data into logs many admins can read. Use the project's logging utility with levels, and never log credentials, session Ids, full request bodies, or personal data. A log record inserted in a transaction that rolls back disappears with it; a platform event set to publish immediately is delivered even then, so its subscriber can store the entry.

```apex
// ❌ No level, and a token plus a full record in the log
System.debug('Auth: ' + req.getHeader('Authorization') + ' contact=' + JSON.serialize(con));

// ✅ Leveled entries through Log__e, whose publishBehavior is PublishImmediately
public with sharing class AppLog {
    public static void error(String source, String message, Id recordId) {
        publish('ERROR', source, message, recordId);
    }
    private static void publish(String level, String source, String message, Id recordId) {
        Database.SaveResult result = EventBus.publish(new Log__e(
            Level__c = level, Source__c = source, Message__c = message, Record_Id__c = recordId));
        if (!result.isSuccess()) {
            System.debug(LoggingLevel.ERROR, 'Log publish failed: ' + result.getErrors()[0].getMessage());
        }
    }
}
```

Static analysis: PMD `AvoidDebugStatements`, `DebugsShouldUseLoggingLevel`, `ApexDangerousMethods` (flags `System.debug` calls that pass sensitive data).

---

## Async Apex

Async work runs in a new transaction with fresh limits, empty static variables, and possibly a different running user ([Transactions & Execution Contexts](platform.md#transactions--execution-contexts)). Jobs start only after the enqueuing transaction commits, so a rolled-back transaction never starts them.

> 📖 For cross-language principles, see [Async & Concurrency Patterns](../cross-cutting/async-concurrency-patterns.md#salesforce-apex-queueable-finalizer-locking).

### Choose the async tool by the shape of the job

Pick by data volume, chaining, and state; the limits for each context are in [Governor Limits](platform.md#governor-limits).

| Tool | Use it for | State and chaining | Watch for |
|---|---|---|---|
| Queueable | The default for new async work, including callouts (`Database.AllowsCallouts`) | Instance fields carry state; `execute` can enqueue the next job; one Finalizer per job | Enqueue limits per transaction; unbounded chains |
| Batch Apex | One large, query-defined set of records | `start`, `execute` per chunk, `finish`; `Database.Stateful` keeps fields between chunks | A selective `start` query; the scope size; only a few batch jobs run at once |
| Schedulable | Time-based starts of other jobs | Keep `execute` thin: start a Batch or Queueable | Synchronous limits; an active schedule can block deployments of the class |
| `@future` | Legacy code only | Primitive parameters; no job Id, no chaining | Can't be called from Batch or `@future` code |
| Platform event + trigger | Decoupling, fan-out, retries | The subscriber runs in its own transaction, as Automated Process by default | Idempotent subscribers: [Platform Event and CDC Triggers](apex-triggers.md#platform-event-and-cdc-triggers) |
| Apex Cursors (API 66.0+) | Very large result sets processed by chained Queueables | The cursor and a position travel in the job's fields | Cursor and fetch limits: [Pagination & Cursors](soql-sosl.md#pagination--cursors) |

### Enqueue once per transaction, not per record

Each `System.enqueueJob` counts against a small per-transaction limit, smaller still inside async code, and every job uses a daily async execution. Collect the Ids and enqueue one job; from a trigger, enqueue at most once per chunk ([Bulk Safety per Chunk](apex-triggers.md#bulk-safety-per-chunk)).

```apex
// ❌ One job per record: hits the enqueue limit and floods the async queue
for (Invoice__c inv : invoices) {
    System.enqueueJob(new InvoiceSyncJob(new Set<Id>{ inv.Id }, 1));
}

// ✅ One job for the whole set (attempt 1); the job re-queries by Id
System.enqueueJob(new InvoiceSyncJob(new Map<Id, Invoice__c>(invoices).keySet(), 1));
```

Static analysis: PMD `OperationWithLimitsInLoop`.

### Attach a Finalizer to every Queueable (API 52.0+ / Summer '21)

A Queueable that fails, including on an uncatchable `LimitException`, leaves only a failed `AsyncApexJob` row behind. `System.attachFinalizer` registers a `Finalizer` that runs in its own transaction after the job ends, sees the result and the exception, and can log, notify, or enqueue a bounded retry.

```apex
// ✅ InvoiceSyncJob (implements Queueable, Database.AllowsCallouts) attaches the Finalizer first
public void execute(QueueableContext context) {
    System.attachFinalizer(new InvoiceSyncFinalizer(invoiceIds, attempt));
    InvoiceSyncService.syncByIds(invoiceIds); // re-queries current state
}

// ✅ The Finalizer logs the failure and retries a bounded number of times
public with sharing class InvoiceSyncFinalizer implements Finalizer {
    private static final Integer MAX_ATTEMPTS = 3;
    private final Set<Id> invoiceIds;
    private final Integer attempt;
    public InvoiceSyncFinalizer(Set<Id> invoiceIds, Integer attempt) {
        this.invoiceIds = invoiceIds;
        this.attempt = attempt;
    }
    public void execute(FinalizerContext context) {
        if (context.getResult() == ParentJobResult.UNHANDLED_EXCEPTION) {
            AppLog.error('InvoiceSyncJob', context.getException().getMessage(), null);
            if (attempt < MAX_ATTEMPTS) {
                System.enqueueJob(new InvoiceSyncJob(invoiceIds, attempt + 1));
            }
        }
    }
}
```

Static analysis: PMD `QueueableWithoutFinalizer`.

### Bound chains and deduplicate jobs with AsyncOptions (API 59.0+ / Winter '24)

A Queueable that re-enqueues itself until the work is done becomes an endless chain when "done" never happens, and production orgs don't cap chain depth. Set `MaximumQueueableStackDepth` where the chain starts, check `AsyncInfo` before chaining, and give jobs that must not run twice a `QueueableDuplicateSignature`: a second enqueue with the same signature throws `DuplicateMessageException`.

```apex
// ❌ Self-chaining without a cap: runs forever if hasMoreWork() never turns false
if (RecalcService.hasMoreWork(accountId)) {
    System.enqueueJob(new RecalcJob(accountId));
}

// ✅ Cap the depth where the chain starts, and dedupe by purpose and key
AsyncOptions options = new AsyncOptions();
options.MaximumQueueableStackDepth = 20;
options.DuplicateSignature = QueueableDuplicateSignature.Builder()
    .addString('RecalcJob').addId(accountId).build();
try {
    System.enqueueJob(new RecalcJob(accountId), options);
} catch (DuplicateMessageException ignored) {
    // A job with this signature is already queued: nothing to do
}

// ✅ Inside execute(): chain only while below the cap set at the start
if (RecalcService.hasMoreWork(accountId)
        && AsyncInfo.getCurrentQueueableStackDepth() < AsyncInfo.getMaximumQueueableStackDepth()) {
    System.enqueueJob(new RecalcJob(accountId));
}
```

### Keep Batch Apex selective, right-sized, and stateless unless needed

The `start` query defines the job's volume, so it needs a selective filter ([Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes)). Choose the scope deliberately, lower than the default when each chunk makes callouts or fires heavy automation (`Database.executeBatch(job, 100)`). `Database.Stateful` serializes every instance field between chunks, so add it only for small counters or Id sets and never for `Database.SaveResult` lists. Implement `Database.RaisesPlatformEvents` so an unhandled exception publishes a `BatchApexErrorEvent` that a subscriber can log.

```apex
// ❌ Unfiltered start, and SaveResults held in Database.Stateful fields
private List<Database.SaveResult> allResults = new List<Database.SaveResult>();
public Database.QueryLocator start(Database.BatchableContext bc) {
    return Database.getQueryLocator('SELECT Id, Status__c FROM Invoice__c');
}

// ✅ Selective start, no state it doesn't need, error events for failed chunks
public with sharing class InvoiceArchiveBatch implements Database.Batchable<SObject>, Database.RaisesPlatformEvents {
    public Database.QueryLocator start(Database.BatchableContext bc) {
        return Database.getQueryLocator([
            SELECT Id, Status__c FROM Invoice__c
            WHERE Status__c = 'Paid' AND Paid_Date__c < LAST_N_DAYS:365
            WITH USER_MODE
        ]); // runs as the user who started or scheduled the job
    }
    public void execute(Database.BatchableContext bc, List<Invoice__c> scope) {
        for (Invoice__c inv : scope) {
            inv.Status__c = 'Archived';
        }
        update as user scope;
    }
    public void finish(Database.BatchableContext bc) { /* failed chunks arrive as BatchApexErrorEvent */ }
}
```

Static analysis: PMD `AvoidStatefulDatabaseResult`.

### Prefer Queueable over @future in new code

`@future` methods take only primitive parameters, return no job Id, can't chain or attach a Finalizer, and can't be called from Batch or other `@future` code. A Queueable does all of that and holds sObjects or collections in its fields. Existing `@future` code is acceptable; raise it only for new or rewritten code.

```apex
// ❌ New code on the legacy API
@future(callout=true)
public static void syncInvoices(Set<Id> invoiceIds) {
    InvoiceSyncService.syncByIds(invoiceIds);
}

// ✅ A Queueable: callouts, a job Id, chaining, and a Finalizer
Id jobId = System.enqueueJob(new InvoiceSyncJob(invoiceIds, 1));
```

Static analysis: PMD `AvoidFutureAnnotation`.

### Make jobs idempotent and safe to retry

Finalizer retries, platform-event redelivery, a rescheduled job, or a user clicking twice can run the same work again, and data captured at enqueue time is stale when the job runs. Pass Ids, re-query current state in `execute`, skip work already done, and write integration results with `upsert` on an external Id so a repeat can't duplicate records.

```apex
// ❌ Inserts Payments built from rows captured at enqueue time: a retry duplicates them
insert as user payments;

// ✅ Re-read by Id, skip finished rows, upsert on an external Id
List<Payment_Staging__c> pending = [
    SELECT Id, Payment_Key__c, Invoice__c, Amount__c FROM Payment_Staging__c
    WHERE Id IN :stagingIds AND Status__c != 'Imported'
    WITH USER_MODE
];
List<Payment__c> payments = PaymentMapper.toPayments(pending); // External_Id__c = Payment_Key__c
upsert as user payments Payment__c.External_Id__c;
for (Payment_Staging__c row : pending) {
    row.Status__c = 'Imported';
}
update as user pending;
```

### Lock records you read and then write

Two transactions that read a value, compute, and write it back (a counter, a balance, a "claim this record" flag) overwrite each other. `SELECT ... FOR UPDATE` locks the returned rows until the transaction ends; a competing transaction waits and then fails with `UNABLE_TO_LOCK_ROW` on DML (a `QueryException` on its own locking query). Lock the fewest rows for the shortest time, update parents in a consistent order, and retry lock failures later from async code instead of looping ([TOCTOU Race Conditions](../code-quality-universal.md#toctou-race-conditions)).

```apex
// ❌ Read-modify-write without a lock: concurrent jobs lose increments
Account acc = [SELECT Id, Open_Invoice_Count__c FROM Account WHERE Id = :accountId WITH USER_MODE];
acc.Open_Invoice_Count__c += 1;
update as user acc;

// ✅ Lock the row; retry contention in a later transaction
try {
    Account acc = [SELECT Id, Open_Invoice_Count__c FROM Account WHERE Id = :accountId WITH USER_MODE FOR UPDATE];
    acc.Open_Invoice_Count__c = (acc.Open_Invoice_Count__c == null ? 0 : acc.Open_Invoice_Count__c) + 1;
    update as user acc;
} catch (DmlException e) {
    if (e.getDmlType(0) != StatusCode.UNABLE_TO_LOCK_ROW) {
        throw e;
    }
    System.enqueueJob(new InvoiceCountJob(accountId)); // add a delay with AsyncOptions (API 59.0+)
}
```

### Process very large result sets with Apex Cursors (API 66.0+ / Spring '26)

A cursor holds a server-side result set that a chain of Queueables pages through with `fetch(position, count)`, without Batch Apex's fixed shape. The cursor is serializable, so it travels in the job's fields: each job fetches a slice, processes it, and enqueues the next position. Cursor rows, fetch calls, and daily cursors are limited ([Governor Limits](platform.md#governor-limits)); query-side detail is in [Pagination & Cursors](soql-sosl.md#pagination--cursors). Before Spring '26 the feature was Beta.

```apex
// ✅ Open the cursor once and hand it to the first job
Database.Cursor cursor = Database.getCursor(
    'SELECT Id, Email FROM Contact WHERE IsEmailBounced = true', AccessLevel.USER_MODE);
System.enqueueJob(new BouncedContactJob(cursor, 0));

// ✅ Each job fetches one slice and enqueues the next position
public with sharing class BouncedContactJob implements Queueable {
    private static final Integer SLICE_SIZE = 200;
    private final Database.Cursor cursor;
    private final Integer position;
    public BouncedContactJob(Database.Cursor cursor, Integer position) {
        this.cursor = cursor;
        this.position = position;
    }
    public void execute(QueueableContext context) {
        System.attachFinalizer(new JobFailureFinalizer('BouncedContactJob')); // logs unhandled failures
        Integer count = Math.min(SLICE_SIZE, cursor.getNumRecords() - position);
        List<Contact> slice = cursor.fetch(position, count);
        BouncedContactService.clean(slice);
        if (position + count < cursor.getNumRecords()) {
            System.enqueueJob(new BouncedContactJob(cursor, position + count));
        }
    }
}
```

---

## Callouts & Integrations

### Put endpoints and credentials in Named Credentials

A hard-coded URL breaks between sandbox and production, and a key in code, Custom Labels, Custom Metadata, or Custom Settings ends up in source control and every deployment. A Named Credential, with an External Credential for the authentication protocol, keeps the endpoint per org and injects authentication; code addresses it as `callout:Name/path` ([Integration Endpoints & Credentials](metadata.md#integration-endpoints--credentials)).

```apex
// ❌ Endpoint and secret in code, over plain HTTP
req.setEndpoint('http://billing.example.com/api/v1/invoices');
req.setHeader('Authorization', 'Bearer ' + BILLING_API_KEY);

// ✅ Named Credential: per-org endpoint, platform-managed authentication, HTTPS
req.setEndpoint('callout:Billing_API/v1/invoices');
```

Static analysis: PMD `ApexSuggestUsingNamedCred`, `ApexInsecureEndpoint`.

### Set a timeout and handle every response

Set the timeout explicitly, within the callout limits ([Governor Limits](platform.md#governor-limits)). `Http.send` throws `CalloutException` for timeouts and connection failures; for everything else, check the status code before parsing, parse into typed classes, and turn failures into typed exceptions with enough context to act on, without copying response bodies that may hold personal data into messages.

```apex
// ❌ No timeout, no status check, untyped parsing
HttpResponse res = new Http().send(req);
String invoiceNumber = (String) ((Map<String, Object>) JSON.deserializeUntyped(res.getBody())).get('number');

// ✅ Explicit timeout, status check, typed DTO, typed failures
req.setTimeout(20000); // milliseconds
HttpResponse res = new Http().send(req);
if (res.getStatusCode() < 200 || res.getStatusCode() > 299) {
    throw new BillingException('Billing API returned ' + res.getStatusCode() + ' for ' + invoice.Name);
}
try {
    BillingResponse parsed = (BillingResponse) JSON.deserialize(res.getBody(), BillingResponse.class);
    invoice.Billing_Number__c = parsed.invoiceNumber;
} catch (JSONException e) {
    throw new BillingException('Unreadable Billing API response for ' + invoice.Name, e);
}
```

### Make the callout before DML, or move it to a Queueable

A callout after uncommitted DML in the same transaction throws `System.CalloutException: You have uncommitted work pending`. Apex has no explicit commit, so call out first and write afterwards, or commit now and hand the callout to a Queueable that implements `Database.AllowsCallouts` (like `InvoiceSyncJob` above). Triggers can't make synchronous callouts at all ([Bulk Safety per Chunk](apex-triggers.md#bulk-safety-per-chunk)).

```apex
// ❌ DML first, then the callout: "You have uncommitted work pending"
insert as user logEntry;
HttpResponse res = new Http().send(req);

// ✅ Callout first, then write the outcome
HttpResponse res = new Http().send(req);
logEntry.Status__c = String.valueOf(res.getStatusCode());
insert as user logEntry;
```

### Mock every callout in tests

Test methods can't make real callouts. Register an `HttpCalloutMock` with `Test.setMock` and cover the success, error-status, and malformed-body paths. Create test data before `Test.startTest()` and make the callout between `startTest` and `stopTest`, or the test fails with the uncommitted-work error.

```apex
// ✅ A mock that returns a chosen status, and a failure-path test
@IsTest
public inherited sharing class BillingApiMock implements HttpCalloutMock {
    private final Integer status;
    public BillingApiMock(Integer status) {
        this.status = status;
    }
    public HttpResponse respond(HttpRequest req) {
        HttpResponse res = new HttpResponse();
        res.setStatusCode(status);
        res.setBody(status == 200 ? '{"invoiceNumber":"INV-1"}' : '{"error":"unavailable"}');
        return res;
    }
}

Invoice__c invoice = TestDataFactory.createInvoice(); // DML before startTest
Test.setMock(HttpCalloutMock.class, new BillingApiMock(500));
Test.startTest();
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
// ✅ Typed request, validation, user-mode write, explicit status codes, details only in the log
@RestResource(urlMapping='/invoices/*')
global with sharing class InvoiceRestResource {
    public class InvoiceRequest {
        public Id accountId;
        public Decimal amount;
    }

    @HttpPost
    global static void create() {
        RestResponse res = RestContext.response;
        res.statusCode = 400; // until the request is proven valid
        res.responseBody = Blob.valueOf('{"message":"Invalid invoice request."}');
        InvoiceRequest body;
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
}
```

### Publish platform events deliberately

`EventBus.publish` returns a `SaveResult` per event and doesn't throw when publishing fails. The event's publish behavior decides when subscribers see it: Publish After Commit events are delivered only if the transaction commits and count against the DML statement limit; Publish Immediately events go out even if the transaction rolls back and have a separate limit, so subscribers may act on data that was never saved. Keep Publish Immediately for logging and monitoring.

```apex
// ❌ Fire and forget: publish failures are silent
EventBus.publish(events);

// ✅ Check each result; the publish behavior is set on the event (publishBehavior in the __e metadata)
List<Database.SaveResult> results = EventBus.publish(events);
for (Integer i = 0; i < results.size(); i++) {
    if (!results[i].isSuccess()) {
        AppLog.error('InvoiceEvents', results[i].getErrors()[0].getMessage(), null);
    }
}
```

---

## Testing

Test results and coverage are org-side evidence: ask the author or CI for them, and review the test code for what it proves. Test classes declare a sharing keyword too (`@IsTest private inherited sharing class ...`, as in Salesforce's Apex Recipes); fixtures are created in the test's own context, and the code under test is what must enforce access. Dependencies are replaced with fakes through a seam, never with `Test.isRunningTest()` branches ([Inject dependencies so tests can replace them](#inject-dependencies-so-tests-can-replace-them)).

### Assert outcomes with the Assert class (API 56.0+ / Winter '23)

A test without assertions only proves that the code didn't throw, and coverage is a deployment gate (a minimum org-wide percentage and every trigger covered, see [Governor Limits](platform.md#governor-limits)), not a quality signal. Assert the state that matters (field values, record counts, published events, error messages) with messages that explain the failure; `Assert.areEqual`, `isTrue`, `isNull`, `fail`, and `isInstanceOfType` read more clearly than the older `System.assert*` methods. Ask the author or CI for the coverage report instead of estimating it from the diff.

```apex
// ❌ Coverage padding: every line runs, nothing is verified
InvoiceService.approve(invoiceIds);
InvoiceService.recalculate(null);
System.assert(true);

// ✅ Assert the outcome with a message
Test.startTest();
InvoiceService.approve(new Set<Id>{ inv.Id });
Test.stopTest();
Assert.areEqual('Approved', [SELECT Status__c FROM Invoice__c WHERE Id = :inv.Id].Status__c,
    'Invoices below the review threshold are approved directly');
// ✅ Before API 56.0: System.assertEquals(expected, actual, message)
```

Static analysis: PMD `ApexUnitTestClassShouldHaveAsserts`, `ApexAssertionsShouldIncludeMessage` (checks the `System.assert*` forms).

### Build test data in the test, never with SeeAllData=true or org Ids

`@IsTest(SeeAllData=true)` makes tests depend on org data that differs in every sandbox and lets them change real records, and hard-coded Ids, usernames, and record type Ids fail after the next refresh or in CI scratch orgs. Create data in `@TestSetup` through the project's `TestDataFactory` (each test method starts from that state, and everything rolls back afterwards), create users in the test, resolve record types by DeveloperName, and use `Test.getStandardPricebookId()`. The rare APIs that need org data, such as many `ConnectApi` methods, justify an isolated, commented exception.

```apex
// ❌ Org data and org-specific values
@IsTest(SeeAllData=true)
static void calculatesTotals() {
    Id pricebookId = '01s000000000000AAA';
    User owner = [SELECT Id FROM User WHERE Username = 'jane.doe@example.com'];
}

// ✅ Own data created once per class, and org-agnostic lookups
@TestSetup
static void setup() {
    Account acc = TestDataFactory.createAccount('Test Account');
    TestDataFactory.createInvoices(acc.Id, 200);
}

@IsTest
static void pricesInvoiceLines() {
    Id pricebookId = Test.getStandardPricebookId();
    User owner = TestDataFactory.createUser('Invoice_Clerk');
}
```

Static analysis: PMD `ApexUnitTestShouldNotUseSeeAllDataTrue`, `AvoidHardcodingId`.

### Cover bulk, negative, and least-privilege paths

A single happy-path record hides every loop defect. Each changed entry point needs a bulk case (at least 200 records, one full trigger chunk; trigger tests need 201+, see [Testing Triggers](apex-triggers.md#testing-triggers)), a negative case that asserts the error, and a `System.runAs` case with a user who has only the permission sets the feature grants. `runAs` enforces record sharing only; CRUD and FLS apply where the code uses user mode, which is what a least-privilege test proves.

```apex
// ✅ Least privilege: a read-only user can't approve, and nothing changes
@IsTest
static void viewerCannotApprove() {
    User viewer = TestDataFactory.createUser('Invoice_Viewer'); // read-only permission set
    Set<Id> invoiceIds = new Map<Id, Invoice__c>([SELECT Id FROM Invoice__c]).keySet();
    System.runAs(viewer) {
        try {
            InvoiceService.approve(invoiceIds);
            Assert.fail('A read-only user must not approve invoices');
        } catch (DmlException expected) {
            // user-mode DML rejected the write
        }
    }
    Assert.areEqual(0, [SELECT COUNT() FROM Invoice__c WHERE Status__c = 'Approved'], 'No invoice was approved');
}
```

Static analysis: PMD `ApexUnitTestClassShouldHaveRunAs`.

### Wrap the call under test in Test.startTest() and Test.stopTest()

Code between `startTest` and `stopTest` gets a fresh set of governor limits, so setup work doesn't hide a limit problem, and async work enqueued inside (Queueable, Batch, `@future`, platform events) runs when `stopTest` is called; assert after it. A Queueable that enqueues a child fails in tests with "Maximum stack depth has been reached", so let the test switch chaining off through a `@TestVisible` field and test the next link separately.

```apex
// ❌ Asserts before the Queueable has run
InvoiceSyncService.enqueueSync(invoiceIds);
Assert.areEqual(0, [SELECT COUNT() FROM Invoice__c WHERE Sync_Status__c != 'Synced'], 'All invoices synced');

// ✅ stopTest runs the job; assert afterwards
Test.setMock(HttpCalloutMock.class, new BillingApiMock(200));
Test.startTest();
InvoiceSyncService.enqueueSync(invoiceIds);
Test.stopTest();
Assert.areEqual(0, [SELECT COUNT() FROM Invoice__c WHERE Sync_Status__c != 'Synced'], 'All invoices synced');
```

### Treat RunRelevantTests annotations as opt-in (API 66.0+ / Spring '26, Beta)

The Beta `RunRelevantTests` test level runs only the tests related to the deployed components. On a test class, `testFor` names what the class covers and `critical=true` makes it run on every deployment. If the project deploys with this level, check that new test classes list accurate `testFor` values; don't block a change for missing annotations while the feature is Beta.

```apex
// ✅ API 66.0+: the test class declares what it covers
@IsTest(testFor='ApexClass:InvoiceService, ApexTrigger:InvoiceTrigger')
private inherited sharing class InvoiceServiceTest {
    // test methods as usual
}
```

---

## Managed Packages

Code shipped in a managed package runs in subscriber orgs you don't control, and its public surface can't shrink once released. Certified packages get their own counters for most limits ([Governor Limits](platform.md#governor-limits)).

### Treat every released global member as permanent

Once a managed package version is released, its `global` classes, methods, properties, and interfaces can't be removed or change signature, and subscribers may call them in ways you never planned. Add `global` only for a deliberate API, share code between packages of the same namespace with `public` plus `@NamespaceAccessible`, and deprecate instead of deleting.

```apex
// ❌ An internal helper exposed forever
global static void recalculateInternal(Set<Id> invoiceIds) {
    InvoiceService.recalculate(invoiceIds);
}

// ✅ A deliberate global API; code shared across the namespace stays public
global with sharing class InvoiceApi {
    global static void recalculate(Set<Id> invoiceIds) {
        InvoiceService.recalculate(invoiceIds);
    }
}

@NamespaceAccessible
public with sharing class InvoiceService {
    @NamespaceAccessible
    public static void recalculate(Set<Id> invoiceIds) { /* visible to this namespace's packages only */ }
}
```

Static analysis: PMD `AvoidGlobalModifier`.

### Reference packaged schema through tokens, not strings

In subscriber orgs the package's objects and fields carry its namespace prefix (`ns__Invoice__c`). Static references are checked by the compiler, which adds the namespace, while names inside strings (dynamic SOQL, `sObject.get('Field__c')`, describe-map keys) are resolved only at run time. Build strings from tokens, where `getName()` includes the namespace and `getLocalName()` omits it, and keep binds in the dynamic query ([SOQL Injection](soql-sosl.md#soql-injection)).

```apex
// ❌ String names: typos, renames, and namespace prefixes surface only at run time
Decimal amount = (Decimal) record.get('Amount__c');

// ✅ Tokens: compile-checked, namespace included
Decimal amount = (Decimal) record.get(Invoice__c.Amount__c);
String amountField = Invoice__c.Amount__c.getDescribe().getName(); // 'ns__Amount__c' in the package
```

### Change released code in upgrade-safe steps

Subscribers upgrade on their own schedule, and their integrations depend on today's behavior. Add overloads instead of changing signatures, mark retired globals `@Deprecated` (existing subscriber code keeps working, new code can't reference them), branch on `System.requestVersion()` when behavior must differ by the version a subscriber calls, and test against subscriber-like conditions: other triggers, validation rules, and data volumes you didn't write ([Salesforce Architecture](../architecture-review-guide.md#salesforce-architecture)).

```apex
// ❌ The released recalculate(Set<Id>) was changed in place: the package version upload fails
global static void recalculate(Set<Id> invoiceIds, Boolean includeCredits) {
    InvoiceService.recalculate(invoiceIds, includeCredits);
}

// ✅ Keep the released signature, add an overload, deprecate deliberately
@Deprecated
global static void recalculate(Set<Id> invoiceIds) {
    recalculate(invoiceIds, false);
}
global static void recalculate(Set<Id> invoiceIds, Boolean includeCredits) {
    InvoiceService.recalculate(invoiceIds, includeCredits);
}
```

---

## Review Checklist

### Bulkification & limits
- [ ] No SOQL, DML, callouts, or enqueues inside loops, including inside helpers called from loops
- [ ] Keys are collected first and results indexed in maps; no nested loops over two collections
- [ ] Each sObject type is written once, deduplicated by Id, and only for records that changed
- [ ] Describes, `Pattern.compile`, and serialization are hoisted out of loops
- [ ] The limit math for the largest expected input fits [Governor Limits](platform.md#governor-limits)

### Language & design
- [ ] Optional relationships and map lookups are null-safe; `??` appears only in files at API 60.0+
- [ ] String keys are normalized, Ids are compared as `Id`, money is `Decimal` with explicit rounding, and time zones are explicit
- [ ] Entry points delegate to services and selectors that accept collections
- [ ] Every class declares a sharing keyword; `without sharing` classes are small, named, and commented
- [ ] No unnecessary `global`; dependencies are injectable; configuration comes from Custom Metadata

### Data access security
- [ ] The class's `<apiVersion>` was checked against the [Security Model](platform.md#security-model) matrix
- [ ] Writes use `as user` or `AccessLevel.USER_MODE` (below API 57.0: `stripInaccessible` or complete describe checks)
- [ ] `stripInaccessible` results are used through `getRecords()`
- [ ] Every system-mode escalation and every `without sharing` class has a comment with the reason and the narrowest scope
- [ ] Client-supplied Ids and records are never trusted; managed sharing uses a custom sharing reason and checks results

### Transactions & errors
- [ ] No empty or log-only catch blocks; exceptions are specific, typed, and keep their cause
- [ ] Partial-success DML inspects every `SaveResult`; catch-and-continue paths roll back to a savepoint
- [ ] Setup-object DML is separated from business DML; nothing relies on catching `LimitException`
- [ ] Logs have levels and no secrets or personal data; logs that must survive a rollback use a Publish Immediately event

### Async & callouts
- [ ] The async tool fits the job; no new `@future`; one enqueue per transaction or chunk
- [ ] Every Queueable attaches a Finalizer; chains are bounded and deduplicated with `AsyncOptions` where needed
- [ ] Batch `start` queries are selective, scopes are deliberate, and `Database.Stateful` holds no result objects
- [ ] Jobs re-query by Id and tolerate retries; read-modify-write sections lock with `FOR UPDATE`
- [ ] Callouts use Named Credentials, set timeouts, check status codes, parse into typed classes, and never follow DML in the same transaction
- [ ] REST resources validate input, write in user mode, and return precise status codes without internals
- [ ] `EventBus.publish` results are checked and the publish behavior is deliberate

### Tests
- [ ] Tests assert outcomes with messages, build their own data, and never use `SeeAllData=true`
- [ ] Each changed entry point has bulk, negative, and least-privilege (`System.runAs`) cases
- [ ] The call under test sits between `Test.startTest()` and `Test.stopTest()`; callouts are mocked
- [ ] No `Test.isRunningTest()` branches in production code and no hard-coded Ids or usernames
- [ ] Test results and coverage come from the author or CI

---

## References

- [Execution Governors and Limits (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm)
- [Using the with sharing, without sharing, and inherited sharing Keywords (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_keywords_sharing.htm)
- [Set an Access Mode for Database Operations (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_enforce_usermode.htm)
- [Enforce Security with the stripInaccessible Method (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_with_security_stripInaccessible.htm)
- [Bulk DML Exception Handling (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_dml_bulk_exceptions.htm)
- [DML Operations on Setup and Non-Setup Objects (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_dml_non_mix_sobjects.htm)
- [Queueable Apex (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_queueing_jobs.htm)
- [Transaction Finalizers (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_transaction_finalizers.htm)
- [AsyncOptions Class (Apex Reference Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexref.meta/apexref/apex_class_System_AsyncOptions.htm)
- [Using Batch Apex (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_batch_interface.htm)
- [Apex Cursors (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_cursors.htm)
- [Named Credentials as Callout Endpoints (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_callouts_named_credentials.htm)
- [Performing DML Operations and Mock Callouts (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_restful_http_testing_dml.htm)
- [Publish Events with Apex (Platform Events Developer Guide)](https://developer.salesforce.com/docs/platform/platform-events/guide/platform-events-publish-apex.html)
- [Using the runAs Method (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_testing_tools_runas.htm)
- [Assert Class (Apex Reference Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexref.meta/apexref/apex_class_System_Assert.htm)
- [PMD Apex Rules](https://docs.pmd-code.org/latest/pmd_rules_apex.html)
- [Apex Recipes (trailheadapps)](https://github.com/trailheadapps/apex-recipes)
