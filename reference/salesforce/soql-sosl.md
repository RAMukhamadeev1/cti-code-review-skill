# SOQL & SOSL Code Review Guide

Review guidance for SOQL and SOSL in Apex (inline `[SELECT ...]` and `[FIND ...]`, dynamic `Database.query*`, `Database.getCursor*`, and `Search.query`) and in `.soql` files: injection, access mode, selectivity, query shape, results, pagination, and search. Examples compile at API 57.0+ unless a heading names a later version.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
> Related: [Apex bulkification](apex.md#bulkification) · [Apex data access](apex.md#data-access-security) · [SQL Injection Prevention](../cross-cutting/sql-injection-prevention.md#salesforce-apex-soqlsosl)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [SOQL Injection](#soql-injection)
- [Access Mode in Queries](#access-mode-in-queries)
- [Selectivity & Large Data Volumes](#selectivity--large-data-volumes)
- [Query Shape](#query-shape)
- [Result Handling](#result-handling)
- [Pagination & Cursors](#pagination--cursors)
- [SOSL](#sosl)
- [Dates, Currency & Labels](#dates-currency--labels)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| Inline `[SELECT ...]` or `[FIND ...]` in classes, trigger handlers, and selectors | This guide + [apex.md](apex.md) |
| `Database.query*`, `countQuery*`, `getQueryLocator*`, `getCursor*`, `Search.query` | This guide, starting with [SOQL Injection](#soql-injection) |
| `WITH SECURITY_ENFORCED`, `WITH SYSTEM_MODE`, `AccessLevel`, or a class moving across API 67.0 | [Access Mode in Queries](#access-mode-in-queries) + [Security Model](platform.md#security-model) |
| Queries in loops or per trigger chunk; Batch and cursor jobs | [Bulkification](apex.md#bulkification), [Bulk Safety per Chunk](apex-triggers.md#bulk-safety-per-chunk), [Async Apex](apex.md#async-apex) |
| Standalone `.soql` files (for example `scripts/soql/`) | This guide: review the text, never run it against an org |

Open the class's `-meta.xml` first: its `<apiVersion>` decides whether a query without an access mode runs in user or system mode. Record counts and query plans live in the org, so ask the author for them ([Static Review Only](platform.md#static-review-only)).

---

## SOQL Injection

Only a query built from a string can be injected; a bind in inline SOQL or SOSL is always data. Every string passed to `Database.query*`, `countQuery*`, `getQueryLocator*`, `getCursor*`, or `Search.query` needs one of these defenses.

> 📖 Cross-language background: [SQL Injection Prevention](../cross-cutting/sql-injection-prevention.md#salesforce-apex-soqlsosl).

### Prefer static SOQL with bind variables

A bind can't change the query's structure, so static SOQL removes the problem instead of mitigating it.

```apex
// ❌ name = "' OR Name != '" builds WHERE Name LIKE '' OR Name != '%' and returns every account
return Database.query('SELECT Id, Name FROM Account WHERE Name LIKE \'' + name + '%\'');

// ✅ Static SOQL: the bind is data, never syntax
public with sharing class AccountLookupController {
    @AuraEnabled(cacheable=true)
    public static List<Account> findByName(String name) {
        if (String.isBlank(name)) { return new List<Account>(); }
        String prefix = name.trim() + '%'; // 💡 % and _ typed by the user still act as wildcards
        return [SELECT Id, Name FROM Account WHERE Name LIKE :prefix WITH USER_MODE ORDER BY Name LIMIT 50];
    }
}
```

Static analysis: PMD `ApexSOQLInjection`.

### Use Database.queryWithBinds for dynamic SOQL (API 57.0+ / Spring '23)

When the text must be built at runtime, keep values out of it. `queryWithBinds` resolves binds from a map, so they work even when a builder assembles the string in one method and runs it in another, and its `AccessLevel` argument is mandatory; `Database.query` resolves only simple local variables in scope, never `:record.Field__c`.

```apex
// ❌ Values stitched into the string, including a hand-joined Id list
String soql = 'SELECT Id FROM Contact WHERE AccountId IN (\'' + String.join(idStrings, '\',\'') + '\') AND LastName = \'' + lastName + '\'';

// ✅ Structure in the string, values in the bind map, access mode explicit
String soql = 'SELECT Id, Name FROM Contact WHERE AccountId IN :accountIds AND LastName = :lastName LIMIT 500';
Map<String, Object> binds = new Map<String, Object>{ 'accountIds' => accountIds, 'lastName' => lastName };
List<Contact> contacts = Database.queryWithBinds(soql, binds, AccessLevel.USER_MODE);
// ✅ Before API 57.0: bind local variables by name (:accountIds, :lastName); never concatenate values
```

### Allowlist identifiers; escaping covers quoted literals only

`String.escapeSingleQuotes` backslash-escapes single quotes, so it protects only values inside a quoted literal. Numbers, field and object names, sort directions, and `LIMIT` values sit outside quotes: parse numbers to their type and bind them, resolve field names through Schema describe, accept only known directions, and keep an explicit map of supported objects (client-supplied field lists: [Data Access Security](apex.md#data-access-security)).

```apex
// ❌ Escaped and still injectable: minAmount = '0 OR Name != null' returns every row
String soql = 'SELECT Id FROM Opportunity WHERE Amount > ' + String.escapeSingleQuotes(minAmount) + ' ORDER BY ' + sortField;

// ✅ Only real, sortable fields and ASC or DESC; the describe's own name goes into the query
Schema.SObjectField field = String.isBlank(sortField) ? null
    : Schema.SObjectType.Opportunity.fields.getMap().get(sortField); // keys are case-insensitive
String direction = sortDir?.toUpperCase();
if (field == null || !field.getDescribe().isSortable() || !new Set<String>{ 'ASC', 'DESC' }.contains(direction)) {
    throw new IllegalArgumentException('Unsupported sort');
}
String soql = 'SELECT Id, Name, Amount FROM Opportunity WHERE AccountId IN :accountIds ORDER BY '
    + field.getDescribe().getName() + ' ' + direction + ', Id LIMIT 200';
List<Opportunity> rows = Database.queryWithBinds(soql, new Map<String, Object>{ 'accountIds' => accountIds }, AccessLevel.USER_MODE);
```

### Never concatenate raw search terms into dynamic SOSL

In dynamic SOSL the term sits inside the quoted `FIND` literal, so a quote in the input ends the literal and lets the caller rewrite the rest, `RETURNING` included. Prefer static SOSL with `FIND :term` ([SOSL](#sosl)); when the targets really are chosen at runtime, allowlist the `RETURNING` clause, validate and escape the term, and pass the access level.

```apex
// ❌ Raw term and object name in a dynamic search
List<List<SObject>> hits = Search.query('FIND \'' + term + '\' IN NAME FIELDS RETURNING ' + objectName + '(Id, Name)');

// ✅ Allowlisted RETURNING clause (a constant map such as 'account' => 'Account(Id, Name LIMIT 20)'), validated and escaped term
String returning = RETURNING_BY_TARGET.get(target?.toLowerCase());
if (returning == null) { throw new IllegalArgumentException('Unsupported search target'); }
String term = String.escapeSingleQuotes(SearchTerms.clean(rawTerm));
List<List<SObject>> hits = Search.query('FIND \'' + term + '\' IN NAME FIELDS RETURNING ' + returning, AccessLevel.USER_MODE);
```

---

## Access Mode in Queries

Check the class's `<apiVersion>` first ([Security Model](platform.md#security-model) has the matrix): a query with no access mode runs in system mode at API 66.0 and earlier (CRUD and FLS ignored, records per the sharing keyword) and in user mode at API 67.0+, which enforces the running user's object permissions, FLS, and sharing. The DML side is in [Data Access Security](apex.md#data-access-security).

### Put WITH USER_MODE on queries that serve a user (API 57.0+ / Spring '23)

`with sharing` filters records, not fields, so below API 67.0 a query without user mode hands the page fields the user can't read. At 67.0+ it is the default; spelling it out keeps the intent visible when code moves between classes. If some callers legitimately lack a field, select only what all of them may read, or strip instead of failing ([Data Access Security](apex.md#data-access-security)).

```apex
// ❌ API 66.0: with sharing filters the invoices, but Internal_Margin__c still reaches the page
return [SELECT Id, Name, Internal_Margin__c FROM Invoice__c WHERE Account__c = :accountId LIMIT 200];

// ✅ Object access and FLS checked in every clause, WHERE included
public with sharing class InvoiceController {
    @AuraEnabled(cacheable=true)
    public static List<Invoice__c> openInvoices(Id accountId) {
        // ⚠️ Throws QueryException if the user can't read a field; getInaccessibleFields() lists them all
        return [SELECT Id, Name, Internal_Margin__c FROM Invoice__c WHERE Account__c = :accountId WITH USER_MODE ORDER BY Name LIMIT 200];
    }
}
```

Static analysis: PMD `ApexCRUDViolation`.

### Replace WITH SECURITY_ENFORCED before a class moves to API 67.0 (removed in API 67.0)

The older clause checks only the SELECT and FROM clauses, rejects polymorphic traversal such as `What.Name` and TYPEOF with ELSE, and stops a class saved at API 67.0+ from compiling. Below 67.0 it still works, so suggest the swap; a diff that moves the class to 67.0 must make it. The compiler can't see inside dynamic query strings, so search those too.

```apex
// ❌ Won't compile at API 67.0+; WHERE fields go unchecked; What.Name traversal is rejected
List<Task> tasks = [SELECT Id, Subject, What.Name FROM Task WHERE OwnerId IN :ownerIds WITH SECURITY_ENFORCED];

// ✅ Checks every clause, supports polymorphic fields, reports every inaccessible field
List<Task> tasks = [SELECT Id, Subject, What.Name FROM Task WHERE OwnerId IN :ownerIds WITH USER_MODE LIMIT 200];
```

### Pass the access level to dynamic queries, and escalate only explicitly

`Database.query`, `countQuery`, `getQueryLocator`, `getCursor`, `getPaginationCursor`, and `Search.query` accept an `AccessLevel`; every `WithBinds` variant requires one. At API 67.0+ a query skips CRUD and FLS only when it says `WITH SYSTEM_MODE` or passes `AccessLevel.SYSTEM_MODE`, and `without sharing` alone doesn't change that. Each escalation also needs the reason, narrow scope, and filtered output described in [Data Access Security](apex.md#data-access-security).

```apex
// ❌ API 66.0: system mode, and nothing at the call site says so
Integer openCases = Database.countQuery(countSoql);

// ✅ The mode is an argument where the dynamic query runs
Integer openCases = Database.countQueryWithBinds(countSoql, binds, AccessLevel.USER_MODE);
// ✅ The escalation is in the query, with its reason beside it
public without sharing class SeatCounter {
    // System mode: agents may see how many seats an account uses; Seat__c records stay private to the account team
    public static Integer activeSeats(Id accountId) {
        return [SELECT COUNT() FROM Seat__c WHERE Account__c = :accountId AND Active__c = true WITH SYSTEM_MODE];
    }
}
```

---

## Selectivity & Large Data Volumes

On a large object, a query without a selective filter scans the table: slow everywhere, and inside a trigger it fails with `System.QueryException: Non-selective query against large object type (more than 200000 rows)`. A diff doesn't show volumes, so check filter shapes and ask for record counts and Query Plan output (a plan cost above 1 means the query isn't selective). Batch `start` queries follow the same rules ([Async Apex](apex.md#async-apex)).

> 📖 Platform performance context: [Salesforce Platform Performance](../performance-review-guide.md#salesforce-platform-performance).

### Filter large objects on an indexed field that narrows the result

The optimizer uses an index only when the field is indexed and the filter matches few enough rows; among ANDed filters, one selective filter is enough.

| Index | Fields | Selective when the filter matches fewer rows than |
|---|---|---|
| Standard | `Id`, `Name`, `OwnerId`, lookup and master-detail fields, `CreatedDate`, `SystemModstamp` (not `LastModifiedDate`), `RecordTypeId` on standard objects | 30% of the first million records plus 15% of the rest, up to 1,000,000 |
| Custom | External ID and unique fields, and indexes Salesforce Support adds on request; none on multi-select picklists, long text, currency fields in multi-currency orgs, or some formula fields | 10% of the first million records plus 5% of the rest, up to 333,333 |

```apex
// ❌ Only an unindexed picklist filter: every trigger chunk scans all of Payment__c
List<Payment__c> open = [SELECT Id, Invoice__c FROM Payment__c WHERE Status__c = 'Open' WITH USER_MODE];

// ✅ Filter on the indexed lookup the handler already has; the picklist condition can stay
List<Payment__c> open = [SELECT Id, Invoice__c FROM Payment__c WHERE Invoice__c IN :invoiceIds AND Status__c = 'Open' WITH USER_MODE];
```

### Avoid filter shapes that can't use an index

Even on an indexed field these force a scan: negative operators, a leading wildcard, a match on null or empty values (an index holds no null rows unless Support builds one that does), and formula fields, which have no index by default. Filtering nulls out (`!= null`) is fine and can help.

```sql
-- ❌ Each of these scans a large object
SELECT Id FROM Case WHERE Status != 'Closed'
SELECT Id FROM Contact WHERE Email LIKE '%@example.com'
SELECT Id FROM Account WHERE Region__c = null
SELECT Id FROM Contact WHERE Email_Domain__c = 'example.com'       -- formula over Email

-- ✅ Positive filters on indexed fields; other conditions can ride along
SELECT Id FROM Case WHERE CreatedDate = LAST_N_DAYS:30 AND Status IN ('New', 'Working')
SELECT Id FROM Contact WHERE Email_Domain_Key__c = 'example.com'   -- stored copy, marked External ID
SELECT Id FROM Account WHERE Region__c != null AND CreatedDate = THIS_YEAR
```

### Bound every query and select exactly the fields the code reads

A query with neither a selective WHERE clause nor a LIMIT grows with the org until it hits the row limit ([Governor Limits](platform.md#governor-limits)). Each extra field costs heap and, in user mode, is one more field every caller must be able to read; a missing one throws `System.SObjectException: SObject row was retrieved via SOQL without querying the requested field` when a caller reads it, so check each field a diff starts reading against the query that produced the record. `FIELDS(ALL)` and `FIELDS(CUSTOM)` aren't supported in Apex, inline or dynamic; `FIELDS(STANDARD)` compiles but, like a SELECT list built from `getMap().keySet()`, pulls fields nobody reads. In `.soql` files and API calls, `FIELDS(ALL)` needs `LIMIT 200` or less.

```apex
// ❌ Unbounded rows and every standard field; elsewhere a caller reads a field the selector never queried
List<Account> accounts = [SELECT FIELDS(STANDARD) FROM Account WITH USER_MODE];
String segment = AccountSelector.forPicker(accountIds)[0].Industry; // SELECT Id, Name ... -> SObjectException

// ✅ Bounded by the records in play, or narrowed and limited for display; exactly the fields used
List<Account> forSummary = [SELECT Id, Name, Industry FROM Account WHERE Id IN :accountIds WITH USER_MODE];
List<Account> forPicker = [SELECT Id, Name FROM Account WHERE OwnerId = :UserInfo.getUserId() WITH USER_MODE ORDER BY Name LIMIT 50];
```

Static analysis: PMD `AvoidNonRestrictiveQueries`.

### Watch for data skew and lock contention

One parent or owner with a very large number of records turns routine saves into lock waits and slow sharing recalculation. Look for code that funnels records to one catch-all parent or owner; record locking in async code is in [Async Apex](apex.md#async-apex).

| Skew | Threshold | Signal in the diff | What breaks |
|---|---|---|---|
| Account or lookup skew | More than 10,000 child records under one parent | Records parented to a catch-all record, such as a default "Unassigned" account | Each child save locks the parent: `UNABLE_TO_LOCK_ROW` under concurrent loads, slow sharing recalculation |
| Ownership skew | More than 10,000 records owned by one user | Integrations or jobs that assign every record to one integration user | Slow sharing recalculation when that user's role or group membership changes |

---

## Query Shape

Let the database join, filter, and aggregate; the loop rules (no SOQL in loops, collect Ids first) are in [Bulkification](apex.md#bulkification).

> 📖 Cross-language background: [N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow).

### Load related records in the same query

A parent-child subquery returns children with their parents, and dot notation reads parent fields. Subqueries count against a separate aggregate-query limit and their rows toward the row limit ([Governor Limits](platform.md#governor-limits)). One query holds up to 20 subqueries (nested up to five levels at API 58.0+, two before) and up to 55 child-to-parent relationships, each at most five levels deep.

```apex
// ❌ One query per account
for (Account acc : accounts) { contacts.addAll([SELECT Id, Email FROM Contact WHERE AccountId = :acc.Id WITH USER_MODE]); }

// ✅ Children through a subquery, parent values through the relationship
List<Account> accounts = [SELECT Id, Name, Owner.Email, (SELECT Id, Email FROM Contacts WHERE Email != null ORDER BY LastName LIMIT 50)
    FROM Account WHERE Id IN :accountIds WITH USER_MODE];
```

### Filter with semi-joins and anti-joins instead of a second query

`WHERE Id IN (SELECT ...)` filters in the database without loading the subquery rows into Apex. At most two semi-join or anti-join subqueries per WHERE clause; the left side is `Id` or a lookup field without dot notation; the subquery selects one lookup field and can't query the outer object; no nesting and no `NOT` in front. `NOT IN` is a negative filter, so keep a selective filter beside it.

```apex
// ❌ Query the Ids, loop, then query again
for (Opportunity o : [SELECT AccountId FROM Opportunity WHERE AccountId IN :accountIds AND IsClosed = false WITH USER_MODE]) { withOpen.add(o.AccountId); }

// ✅ The database evaluates the subqueries
List<Account> withOpenDeals = [SELECT Id, Name FROM Account WHERE Id IN :accountIds
    AND Id IN (SELECT AccountId FROM Opportunity WHERE IsClosed = false) WITH USER_MODE];
List<Account> withoutContacts = [SELECT Id, Name FROM Account WHERE Id IN :accountIds
    AND Id NOT IN (SELECT AccountId FROM Contact) WITH USER_MODE];
```

### Aggregate in SOQL instead of summing in Apex

`GROUP BY` with `SUM`, `COUNT`, `MIN`, `MAX`, or `AVG` returns one row per group. Every row that feeds `SUM`, `AVG`, `MIN`, or `MAX` still counts toward the query row limit, while `COUNT()` counts as one row (one per group with `GROUP BY`). Aggregate queries don't support `queryMore`, so a SOQL for loop over one that returns more than 2,000 rows throws; assign the result to a list.

```apex
// ❌ Loads every won opportunity to add up amounts on the heap
for (Opportunity o : [SELECT AccountId, Amount FROM Opportunity WHERE AccountId IN :accountIds AND IsWon = true WITH USER_MODE]) {
    totals.put(o.AccountId, (totals.containsKey(o.AccountId) ? totals.get(o.AccountId) : 0) + o.Amount);
}

// ✅ One row per account, assigned to a list
List<AggregateResult> rows = [SELECT AccountId, SUM(Amount) total FROM Opportunity
    WHERE AccountId IN :accountIds AND IsWon = true WITH USER_MODE GROUP BY AccountId];
for (AggregateResult row : rows) {
    totals.put((Id) row.get('AccountId'), (Decimal) row.get('total'));
}
```

### Use TYPEOF for polymorphic fields (API 46.0+ / Summer '19)

Polymorphic lookups (`What`, `Who`, `Owner`) point to several objects. `TYPEOF` picks fields per runtime type, the `Type` qualifier filters by type, and `instanceof` plus a cast reads the result.

```apex
// ❌ Query the tasks, split WhatIds by key prefix, then query Account and Opportunity separately
List<Task> tasks = [SELECT Id, WhatId FROM Task WHERE OwnerId = :userId AND IsClosed = false WITH USER_MODE];

// ✅ One query picks the fields for each type; read them with instanceof and a cast: (Opportunity) t.What
List<Task> tasks = [SELECT Id, Subject, TYPEOF What WHEN Account THEN Name, Industry WHEN Opportunity THEN Name, Amount END
    FROM Task WHERE OwnerId = :userId AND IsClosed = false AND What.Type IN ('Account', 'Opportunity')
    WITH USER_MODE LIMIT 200];
```

---

## Result Handling

A result can be empty or larger than expected. Fields a query didn't select are covered under [Selectivity & Large Data Volumes](#selectivity--large-data-volumes), and null-safe access to optional relationships (`acc.Parent?.Name`) under [Language Pitfalls](apex.md#language-pitfalls).

### Assign a query to a single record only when exactly one row is certain

Assigning a query to a single sObject throws `System.QueryException: List has no rows for assignment to SObject` when nothing matches, and also throws when more than one row does. Lookups by Id fail this way when the record was deleted or isn't shared with the user.

```apex
// ❌ Throws when the record is gone or hidden from this user
Account acc = [SELECT Id, Name FROM Account WHERE Id = :recordId WITH USER_MODE];

// ✅ API 60.0+: null coalescing returns its right operand when the query finds no row
Account acc = [SELECT Id, Name FROM Account WHERE Id = :recordId WITH USER_MODE LIMIT 1] ?? null;
// ⚠️ One query per ?? statement: Salesforce advises against several SOQL queries in one

// ✅ Before API 60.0: query into a list and check it
List<Account> rows = [SELECT Id, Name FROM Account WHERE Id = :recordId WITH USER_MODE LIMIT 1];
Account acc = rows.isEmpty() ? null : rows[0];
```

### Stream large results with a SOQL for loop

A SOQL for loop fetches rows in chunks instead of holding the whole result on the heap (the list form hands over 200 records per iteration); the rows still count toward the row limit. Iterate a parent's child list instead of assigning it or calling `size()`: with 200 or more children that throws `Aggregate query has too many rows for direct assignment, use FOR loop`.

```apex
// ❌ The whole result on the heap, and a child list assigned directly
List<Account> accounts = [SELECT Id, (SELECT Email FROM Contacts) FROM Account WHERE Id IN :accountIds WITH USER_MODE];
List<Contact> contacts = accounts[0].Contacts; // throws for an account with 200+ contacts

// ✅ Chunked iteration, and child rows read through a nested loop
for (Account acc : [SELECT Id, (SELECT Email FROM Contacts WHERE Email != null) FROM Account WHERE Id IN :accountIds WITH USER_MODE]) {
    for (Contact c : acc.Contacts) {
        emails.add(c.Email.toLowerCase());
    }
}
```

---

## Pagination & Cursors

### Order by a unique key, and page with keyset filters instead of OFFSET

Without `ORDER BY`, row order is stable but undefined and can change, so "the first row" is arbitrary: order by the business key plus a unique tiebreaker such as `Id`. `OFFSET` stops at 2,000 rows (larger values fail with `NUMBER_OUTSIDE_VALID_RANGE`), isn't allowed in Bulk API queries, and recomputes the page on every call, so rows shift when data changes. Filter past the last row seen instead.

```apex
// ❌ "The latest case" is whichever row comes back first; deep OFFSET pages fail and shift
List<Case> latest = [SELECT Id, Subject FROM Case WHERE AccountId = :accountId WITH USER_MODE LIMIT 1];
List<Case> page = [SELECT Id, Subject FROM Case WHERE Status = 'New' WITH USER_MODE ORDER BY CreatedDate LIMIT 50 OFFSET :offsetRows];

// ✅ A unique tiebreaker, and keyset paging where the client sends back the last Id it received
List<Case> latest = [SELECT Id, Subject FROM Case WHERE AccountId = :accountId WITH USER_MODE ORDER BY CreatedDate DESC, Id DESC LIMIT 1];
List<Case> page = lastSeenId == null
    ? [SELECT Id, Subject FROM Case WHERE Status = 'New' WITH USER_MODE ORDER BY Id LIMIT 50]
    : [SELECT Id, Subject FROM Case WHERE Status = 'New' AND Id > :lastSeenId WITH USER_MODE ORDER BY Id LIMIT 50];
// ✅ Non-unique sort key: WHERE CreatedDate > :lastDate OR (CreatedDate = :lastDate AND Id > :lastId) ORDER BY CreatedDate, Id
```

### Open cursors with an access level and re-check each slice (API 66.0+ / Spring '26)

A cursor lets a Queueable chain walk a very large result; the job pattern is in [Async Apex](apex.md#async-apex). Pass an `AccessLevel` to `Database.getCursor` (`getCursorWithBinds` requires one). Each `fetch` counts as a query and its rows toward the row limit, on top of the cursor's own limits ([Governor Limits](platform.md#governor-limits)), and `System.TransientCursorException` can be retried. The set of record Ids is fixed when the cursor opens, so later edits and sharing changes don't remove rows. For UI paging, `Database.getPaginationCursor` with `fetchPage` returns full pages and skips deleted rows.

```apex
// ❌ Acts on fetched rows as if they still matched the filter the cursor was opened with
update as user BouncedContactMapper.blankEmails(cursor.fetch(position, count));

// ✅ Re-check the condition for the slice before writing (a list of sObjects binds as its Ids)
List<Contact> slice = cursor.fetch(position, count);
List<Contact> stillBounced = [SELECT Id, Email FROM Contact WHERE Id IN :slice AND IsEmailBounced = true WITH USER_MODE];
update as user BouncedContactMapper.blankEmails(stillBounced);
```

### Start Batch Apex from a QueryLocator

A `Database.QueryLocator` returned from `start` bypasses the limit on records retrieved by SOQL (it has its own, much higher cap), while an `Iterable` built from a query is still bound by it ([Governor Limits](platform.md#governor-limits)). Build the locator from inline SOQL `WITH USER_MODE`, or pass an `AccessLevel` to `getQueryLocator` or `getQueryLocatorWithBinds`; selectivity, scope, and state are in [Async Apex](apex.md#async-apex).

```apex
// ❌ An Iterable start still hits the query row limit at production volume
public Iterable<SObject> start(Database.BatchableContext bc) { return [SELECT Id FROM Invoice__c WHERE Status__c = 'Paid' WITH USER_MODE]; }

// ✅ A QueryLocator streams the whole result to execute(), in user mode
public Database.QueryLocator start(Database.BatchableContext bc) {
    return Database.getQueryLocator([SELECT Id FROM Invoice__c WHERE Status__c = 'Paid' AND Paid_Date__c < LAST_N_DAYS:365 WITH USER_MODE]);
}
```

---

## SOSL

SOSL searches the search index: tokenized text across objects and fields, ranked by relevance. Injection rules for dynamic SOSL are in [SOQL Injection](#soql-injection).

### Use SOSL for text search and SOQL for exact filters

Choose SOSL when users type words and the object or field holding them isn't known; choose SOQL for known objects, exact or range filters, counts, sorting, and number, date, or checkbox fields. Search results vary by user and change with the index, so never use them as an existence check.

```apex
// ❌ Exact key lookup through the search index: tokenized, relevance-capped, index-dependent
List<List<SObject>> hits = [FIND :invoiceNumber IN ALL FIELDS RETURNING Invoice__c(Id) WITH USER_MODE];

// ✅ Exact match on an indexed (External ID) field; keep SOSL for the search box
List<Invoice__c> matches = [SELECT Id, Name FROM Invoice__c WHERE Invoice_Number__c = :invoiceNumber WITH USER_MODE LIMIT 1];
```

### Search in user mode and cap every RETURNING object

Use `WITH USER_MODE` on inline SOSL and `AccessLevel.USER_MODE` on `Search.query`: in system mode, `IN ALL FIELDS` also matches on fields the user can't read, so a hit reveals hidden data even when the field isn't returned. `RETURNING` is required in Apex; list the fields and give each object a `LIMIT`. Results are capped at 2,000 rows per search; a single-object search returns at most 250 unless it has a `WHERE` or `ORDER BY` clause, and a multi-object search returns up to the smaller of 250 and 2,000 divided by the number of objects.

```apex
// ❌ API 66.0: system mode, no fields, no limits
List<List<SObject>> hits = [FIND :term IN ALL FIELDS RETURNING Account, Contact];

// ✅ Matching and results limited to what the user may read, each object capped
public with sharing class GlobalSearchService {
    public static List<List<SObject>> byName(String rawTerm) {
        String term = SearchTerms.clean(rawTerm);
        return [FIND :term IN NAME FIELDS RETURNING Account(Id, Name WHERE Type = 'Customer' ORDER BY Name LIMIT 20),
                Contact(Id, Name, Email ORDER BY LastName LIMIT 20) WITH USER_MODE LIMIT 40];
    }
}
```

Static analysis: PMD `AvoidNonRestrictiveQueries` (flags SOSL too).

### Validate search terms before searching, and fix search results in tests

A one-character term throws `System.SearchException`; beyond 4,000 characters a term loses its logical operators (AND becomes OR), and beyond 10,000 it returns nothing. The characters `? & | ! { } [ ] ( ) ^ ~ * : \ " ' + -` are reserved and cause errors unless escaped with a backslash, and `*` and `?` act as wildcards: clean terms in one helper before binding or embedding them. In a test method SOSL returns no rows unless the test first calls `Test.setFixedSearchResults(ids)` (the query's WHERE and LIMIT still apply), so a search test without it proves only the empty path.

```apex
// ❌ Raw input straight into the search
List<List<SObject>> hits = [FIND :userInput IN ALL FIELDS RETURNING Account(Id, Name LIMIT 20) WITH USER_MODE];

// ✅ One helper: reserved characters become spaces, length checked and capped
public inherited sharing class SearchTerms {
    private static final String RESERVED = '[?&|!{}\\[\\]()^~*:\\\\"\'+-]'; // also drops the * and ? wildcards

    public static String clean(String raw) {
        String term = raw == null ? '' : raw.replaceAll(RESERVED, ' ').normalizeSpace();
        if (term.length() < 2) {
            throw new IllegalArgumentException('Enter at least two characters to search.');
        }
        return term.left(100);
    }
}

// ✅ In a test: tell the search what to find, then assert on it
Account acme = TestDataFactory.createAccount('Acme Tools');
Test.setFixedSearchResults(new List<Id>{ acme.Id });
Assert.areEqual(acme.Id, GlobalSearchService.byName('acme')[0][0].Id, 'The fixed Account result should be returned');
```

---

## Dates, Currency & Labels

Let SOQL do the locale-aware work; Apex-side date pitfalls are in [Language Pitfalls](apex.md#language-pitfalls).

### Filter with the date literal you mean, and group by the user's day

Date literals follow the running user's locale, which differs for async jobs and integration users. `LAST_N_DAYS:n` includes today (`LAST_N_DAYS:1` is yesterday and today) while `LAST_N_WEEKS:1` doesn't, a date function can't be compared with a date literal, and FISCAL literals fail outside the fiscal years defined in Setup. Date functions work on Datetime values in UTC, so group by the local day with `convertTimezone()`, which is allowed only inside a date function.

```sql
-- ❌ "Created today" that includes yesterday, a date function compared with a literal (fails), UTC grouping
SELECT Id FROM Case WHERE CreatedDate = LAST_N_DAYS:1
SELECT Id FROM Case WHERE CALENDAR_YEAR(CreatedDate) = THIS_YEAR
SELECT DAY_ONLY(CreatedDate) createdDay, COUNT(Id) total FROM Case WHERE CreatedDate = LAST_N_DAYS:30 GROUP BY DAY_ONLY(CreatedDate)

-- ✅ The literal that matches the intent, and grouping by the running user's local date
SELECT Id FROM Case WHERE CreatedDate = TODAY
SELECT Id FROM Case WHERE CreatedDate = THIS_YEAR
SELECT DAY_ONLY(convertTimezone(CreatedDate)) createdDay, COUNT(Id) total FROM Case
WHERE CreatedDate = LAST_N_DAYS:30 GROUP BY DAY_ONLY(convertTimezone(CreatedDate))
```

### Translate and convert in the query, but compare on API values

`toLabel()` returns picklist and record type labels in the user's language, `convertCurrency()` returns amounts in the user's currency in multi-currency orgs, and `FORMAT()` returns locale-formatted text. After `toLabel()` the field holds the label, so branch and filter on API values. `convertCurrency()` isn't allowed in WHERE: compare with an ISO-coded literal such as `Amount > USD5000`, since a bare number compares raw amounts across currencies. Aggregates in `GROUP BY` queries come back in the corporate currency.

```apex
// ❌ After toLabel(), StageName holds the translated label: the check fails for non-English users
for (Opportunity opp : [SELECT Id, toLabel(StageName) FROM Opportunity WHERE AccountId IN :accountIds WITH USER_MODE]) {
    if (opp.StageName == 'Closed Won') { wonIds.add(opp.Id); }
}

// ✅ Filter on API values in the query; translate and convert only for display (multi-currency org)
List<Opportunity> bigWins = [SELECT Id, Name, toLabel(StageName), convertCurrency(Amount) FROM Opportunity
    WHERE AccountId IN :accountIds AND StageName = 'Closed Won' AND Amount > USD5000
    WITH USER_MODE ORDER BY CloseDate DESC LIMIT 100];
```

---

## Review Checklist

### Injection
- [ ] No caller input is concatenated into `Database.query*`, `countQuery*`, `getQueryLocator*`, `getCursor*`, or `Search.query` strings
- [ ] Dynamic values travel as binds (`queryWithBinds` maps or local variables); numbers are parsed to their type first
- [ ] Field, object, and sort names resolve through Schema describe or an allowlist; dynamic SOSL escapes a validated term

### Access mode
- [ ] The class's `<apiVersion>` was checked before judging a query's access
- [ ] Queries that serve a user say `WITH USER_MODE` or pass `AccessLevel.USER_MODE`
- [ ] No `WITH SECURITY_ENFORCED` remains in a class at API 67.0+ or in its dynamic strings
- [ ] Every `WITH SYSTEM_MODE` or `AccessLevel.SYSTEM_MODE` is explicit, has a written reason, and returns nothing raw

### Selectivity & volume
- [ ] Queries on large objects filter on an indexed field that narrows the result, not only on negative, wildcard, null, or formula filters
- [ ] Every query has a selective WHERE clause or a LIMIT, and selects only the fields the code reads (no `FIELDS()` in Apex)
- [ ] Record counts and query plans were requested for new queries on large objects; skewed parents and owners were considered

### Query shape
- [ ] Related records come from subqueries, dot notation, and semi-joins instead of extra queries
- [ ] Totals and counts come from aggregate queries assigned to a list; polymorphic fields use `TYPEOF` or `Type`
- [ ] Date filters use the intended literal and `convertTimezone()`; picklists compare on API values, not `toLabel()` output

### Results & pagination
- [ ] Single-record assignments are certain to find one row, or use a list or `?? null` (API 60.0+)
- [ ] Every field the code reads is in the query that produced the record; child lists are iterated, not assigned
- [ ] Picking one row or paging orders by a unique tiebreaker; large sets page with keyset filters, not `OFFSET`
- [ ] Cursors open with an `AccessLevel` and re-check each slice; Batch `start` returns a `QueryLocator`

### SOSL
- [ ] SOSL serves text search, SOQL serves exact filters, and searches run in user mode
- [ ] `RETURNING` lists fields and a `LIMIT` per object; terms are length-checked and cleaned of reserved characters
- [ ] Tests that search call `Test.setFixedSearchResults`

---

## References

- [SOQL and SOSL Reference (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_sosl_intro.htm)
- [FIELDS() (SOQL and SOSL Reference)](https://developer.salesforce.com/docs/platform/salesforce-soql-sosl/guide/sforce-api-calls-soql-select-fields.html)
- [Dynamic SOQL and queryWithBinds (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_dynamic_soql.htm)
- [SOQL Injection (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/pages_security_tips_soql_injection.htm)
- [Enforce User Mode for Database Operations (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_enforce_usermode.htm)
- [WITH SECURITY_ENFORCED removed in API 67.0 (Summer '26 release notes)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_removed_withSecurityEnforced.htm&language=en_US&release=262&type=5)
- [Apex Cursors (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_cursors.htm)
- [SOQL selectivity thresholds (Salesforce Help)](https://help.salesforce.com/s/articleView?id=000385218&language=en_US&type=1)
- [Indexing with Nulls (Best Practices for Deployments with Large Data Volumes)](https://developer.salesforce.com/docs/atlas.en-us.salesforce_large_data_volumes_bp.meta/salesforce_large_data_volumes_bp/ldv_deployments_case_studies_indexing_with_nulls.htm)
- [Developer Console Query Plan Tool FAQ (Salesforce Help)](https://help.salesforce.com/s/articleView?id=000386864&language=en_US&type=1)
- [Managing Lookup Skew to Avoid Record Lock Exceptions (Salesforce Engineering)](https://developer.salesforce.com/blogs/engineering/2013/04/managing-lookup-skew-to-avoid-record-lock-exceptions)
- [PMD Apex rules](https://docs.pmd-code.org/latest/pmd_rules_apex.html)
