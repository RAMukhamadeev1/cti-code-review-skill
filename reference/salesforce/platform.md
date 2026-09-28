# Salesforce Platform Code Review Guide

The shared foundation for every Salesforce review: governor limits, transactions and order of execution, the security model and API-version rules, org-agnostic configuration, tooling, and severity calibration. Current for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs.

> Load this guide first for every Salesforce change; [SKILL.md](../../SKILL.md#salesforce-review-path) routes each changed file type to its guide. Related: [Security](../security-review-guide.md#salesforce-platform-security) · [Performance](../performance-review-guide.md#salesforce-platform-performance) · [Architecture](../architecture-review-guide.md#salesforce-architecture) · [Universal Quality](../code-quality-universal.md#salesforce-mapping)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Scope → [Static Review Only](#static-review-only)

- [ ] Only local reads were used: no deploy, retrieve, anonymous Apex, test runs, data or `sf org` commands, or org URLs
- [ ] The base and head `<apiVersion>` of every changed `-meta.xml` was read before any sharing, access, or syntax finding
- [ ] Test runs, coverage, query plans, data volumes, org-only automation, and user permissions: ask the author

### Limits → [Governor Limits](#governor-limits)

- [ ] Limit math per transaction at bulk volume (200 per trigger chunk, up to 2,000 per event batch, the Batch scope), including downstream triggers, flows, and roll-ups
- [ ] Enqueues and `@future` calls fit their context (one enqueue in async Apex); `Limits` checks only stop or defer work
- [ ] Heap-heavy code fits 6 MB / 12 MB while any target org is still on Summer '26

### Transactions → [Transactions & Execution Contexts](#transactions--execution-contexts)

- [ ] No callout after uncommitted DML; setup-object DML runs in its own transaction
- [ ] Async jobs get their input through constructors or payloads, not statics
- [ ] When the PR adds automation to an object, other triggers, flows, and workflow on it were checked against the order of execution

### Security → [Security Model](#security-model)

- [ ] Effective sharing per class: its keyword, else its parent's, else its apiVersion default
- [ ] Access mode per query and DML: explicit, or the default of the file's apiVersion, trigger bodies included
- [ ] At 67.0+ every intended bypass uses explicit system mode; `without sharing` alone doesn't relax implicit operations
- [ ] Entry points validate input; guest-reachable code runs `with sharing` in user mode
- [ ] Every class or trigger bump across 67.0 was reviewed as a behavior change

### Versions → [API Versions](#api-versions)

- [ ] No blocking finding asks for a feature newer than the file's apiVersion; versioned syntax matches it

### Configuration → [Org-Agnostic Code](#org-agnostic-code)

- [ ] No hard-coded record Ids, org URLs, usernames, or endpoints in new or changed code

### Severity → [Severity Calibration](#severity-calibration)

- [ ] Each tier comes from the table, adjusted once for exposure; limit findings show the math
- [ ] Analyzer hits, if any ([Tooling](#tooling)), were confirmed in the code and translated into review tiers

---

## Static Review Only

A Salesforce review reads files and diffs and never needs an org. [SKILL.md](../../SKILL.md#salesforce-review-path) sets the safety rules; this table is the reference.

| Never run | Why |
|---|---|
| `sf project deploy`, `retrieve`, or `delete` | Change org metadata or overwrite the reviewed source |
| `sf apex run`, `sf apex run test`, anonymous Apex such as `scripts/apex/*.apex` | Execute code in the org; anonymous Apex commits its DML |
| `sf apex tail log`, `sf apex get log` | Need a live session; tailing creates trace flags |
| `sf data …`, `sf org …` (including `sf org display`), `sf package …`, legacy `sfdx force:*` | Touch org data, print an access token, or create package versions |
| Anything with `-o` / `--target-org`, or falling back to the default org (the ApexGuru engine, [Tooling](#tooling)) | Reaches whichever org the CLI is logged in to |
| Requests to `*.my.salesforce.com` or `*.lightning.force.com` | Live org endpoints |

Search with the Grep tool: for example, Grep for `WITH SECURITY_ENFORCED` in `*.cls`, or for `<apiVersion>` in the changed `-meta.xml` files. For triage, run the skill's analyzer as SKILL.md describes. Install nothing without asking.

Ask the author for org-side evidence: the test run (failures and per-class coverage of the changed classes and triggers), Query Plan results and record counts for large objects, limit usage from a 200+ record run, automation outside the repo (managed-package triggers, org-only flows and validation rules), and the running or integration user's permission sets.

---

## Governor Limits

Limits are hard failures. `System.LimitException` can't be caught, and it rolls back the whole transaction, including every trigger, flow, and DML statement in it. Exception: in platform-event triggers, DML done before an uncaught exception stays committed ([Platform Event and CDC Triggers](apex-triggers.md#platform-event-and-cdc-triggers)).

### Know the per-transaction limits

Values from the Apex Developer Guide for Winter '27 (API 68.0); re-check them each release.

| Limit | Synchronous | Asynchronous | Notes |
|---|---|---|---|
| SOQL queries | 100 | 200 | `Database.query`, `queryWithBinds`, `countQuery`, `getQueryLocator`, and each `Cursor.fetch` count; custom metadata queries don't. Parent-child subqueries have their own limit of 3 times the base (300 / 600) |
| Records retrieved by SOQL | 50,000 | 50,000 | Subquery and cursor-fetch rows count too |
| Records retrieved by `Database.getQueryLocator` | 10,000 | 10,000 | A Batch Apex `start` locator can return 50 million |
| SOSL queries | 20 | 20 | 2,000 records per query |
| DML statements | 150 | 150 | Also `Approval.process`, `Database.convertLead`, `emptyRecycleBin`, `setSavepoint`, `rollback`, `System.runAs`, and `EventBus.publish` of publish-after-commit events |
| Records processed by DML | 10,000 | 10,000 | Includes `Approval.process` and `emptyRecycleBin` |
| Recursive trigger depth | 16 | 16 | "maximum trigger depth exceeded" |
| Callouts | 100 | 100 | 120 s cumulative timeout; each callout defaults to 10 s, `setTimeout` accepts up to 120,000 ms |
| `@future` calls | 50 | 50 in Queueable; 0 in Batch and `@future` | |
| `System.enqueueJob` | 50 | 1 | One child job per async transaction |
| `Messaging.sendEmail` calls | 10 | 10 | |
| Publish Immediately `EventBus.publish` calls | 150 | 150 | Separate counter: `Limits.getPublishImmediateDML()` |
| Heap | 10 MB | 25 MB | Winter '27; 6 MB / 12 MB in orgs still on Summer '26 |
| CPU time | 10,000 ms | 60,000 ms | Database time and callout waits don't count |
| Transaction execution time | 10 min | 10 min | |

- Heap: each org gets the Winter '27 limit with its release upgrade (every org from Spring '27), and Winter '27 non-production orgs can enable "Enforce the Summer '26 Apex heap limit". Until every target org is upgraded, design for 6 MB / 12 MB; adaptive code reads `Limits.getLimitHeapSize()`.
- Scheduled Apex gets the synchronous limits; Bulk API and Bulk API 2.0 transactions get the higher of the two values; each test method gets its own set.
- Certified managed packages get their own counters for most limits, up to 11 times the base across namespaces; shared limits such as CPU time stay shared by the whole transaction.

### Count per transaction, not per method

This is the one copy of the chunk math. One DML statement fans out through triggers, flows, and roll-ups, and every query in that chain draws on the same budget. A DML of N records runs each trigger ⌈N/200⌉ times in one transaction, and limits and static variables carry over between those chunks. Bulk API chunks are separate transactions with fresh limits.

```text
❌ "AccountTriggerHandler runs only 3 queries, far below 100"

   One Apex DML updates 1,000 Accounts          → ⌈1,000 / 200⌉ = 5 Account trigger chunks, one transaction
   AccountTriggerHandler, 3 queries per chunk   → 15 queries
   The handler updates 3,000 related Contacts   → ⌈3,000 / 200⌉ = 15 Contact trigger chunks
   ContactTriggerHandler, 4 queries per chunk   → 60 queries
   Contact after-save flow, 1 Get Records/chunk → 15 queries
   Total                                        → 90 of 100 before anything else runs; query 101 throws

✅ Sum (queries per chunk × chunks) over every trigger, flow, and roll-up the DML reaches,
   against one shared limit; ask the author which automation fires when the repo can't show it
```

### Know how many records each entry point delivers

| Entry point | Records per invocation | Transaction |
|---|---|---|
| Apex trigger (Apex DML, the UI, or an API call) | Up to 200 per chunk | All chunks of one DML share one transaction |
| SOAP API calls, REST sObject Collections | Up to 200 records per call | One per call |
| Bulk API, Bulk API 2.0 | 200-record chunks | One per chunk, with fresh limits |
| Platform-event and Change Data Capture triggers | Up to 2,000 events per batch; `PlatformEventSubscriberConfig` sets a smaller batch size and the running user | Their own, with synchronous limits |
| Batch Apex `execute` | `scope`: default 200; at most 2,000 with a QueryLocator; no cap with an Iterable | One async transaction per `execute` |
| Queueable, `@future` | Whatever the caller passes; bound it | A new async transaction |
| Scheduled Apex | Whatever `execute` queries | A new transaction, synchronous limits |
| `@AuraEnabled`, `@RemoteAction`, `@RestResource`, `webservice` | Whatever the client sends; cap list sizes on the server | Synchronous limits |
| Record-triggered flow | The triggering chunk; interviews run bulkified at each data element | The triggering transaction |
| `@InvocableMethod` | One list element per flow interview in the batch | The caller's transaction |

### Know the async and org-wide limits

| Limit | Value |
|---|---|
| Async Apex executions (Batch, Queueable, `@future`, Scheduled) per rolling 24 hours | 250,000 or 200 per user license, whichever is greater |
| Batch Apex jobs | 5 queued or active, 100 more in the flex queue, 1 `start` at a time, 5 submitted in a running test |
| Queueable chain depth | No limit in production; 5 in Developer Edition and trial orgs; `AsyncOptions.MaximumQueueableStackDepth` sets your own cap |
| Apex Cursors | 50 million rows and 100 `Cursor.fetch` calls per transaction; 10,000 cursors per 24 hours |
| Apex pagination cursors | 100,000 rows and 50 instances per transaction; 2,000 rows per page; 200,000 instances per 24 hours |
| New cursor and pagination-cursor rows | 100 million per 24 hours, combined |
| Concurrent long-running synchronous transactions (over 5 s) | 1 per 100 licenses, minimum 10, maximum 50 |
| Production deployment | At least 75% org-wide Apex coverage, every trigger covered, all tests passing |

### Use Limits methods only for graceful degradation

`Limits.getQueries()` against `Limits.getLimitQueries()` (and the CPU, DML, callout, queueable, and heap pairs) tells code how much budget is left. Use it to stop early or hand the rest to a new transaction, never to paper over a loop that should be bulkified.

```apex
// ❌ A limit check hides the loop instead of fixing it: accounts past the budget are silently skipped
for (Account acc : accountList) {
    if (Limits.getQueries() < Limits.getLimitQueries()) {
        acc.Open_Cases__c = [SELECT COUNT() FROM Case WHERE AccountId = :acc.Id AND IsClosed = false];
    }
}

// ✅ Bulkify first; defer optional work only when the budget is short and an enqueue is still allowed
if (Limits.getLimitQueries() - Limits.getQueries() >= QUERIES_NEEDED) {
    AccountEnrichment.enrich(accountIds);                    // three bulk queries, one DML, no loops
} else if (Limits.getQueueableJobs() < Limits.getLimitQueueableJobs()) {
    System.enqueueJob(new AccountEnrichmentJob(accountIds)); // fresh limits after commit
}                                                            // else: the records stay flagged for a later sweep
```

---

## Transactions & Execution Contexts

A transaction is everything one entry point starts, up to commit or rollback. Every trigger, flow, and class it reaches shares one set of limits and static variables, and all of it rolls back together.

### One DML fans out through the order of execution

This is the one copy of the order of execution; trigger-specific rules are in [Order of Execution](apex-triggers.md#order-of-execution).

```text
 1. Load the record (or initialize it for insert and upsert) and apply the new values
 2. System validation: UI edit pages check layout rules, required fields, field formats, and maximum lengths;
    Apex and API saves check foreign keys, field formats, maximum field lengths, and restricted picklists
 3. Before-save record-triggered flows
 4. Before triggers
 5. System validation again, custom validation rules, then duplicate rules
 6. Save to the database, not yet committed
 7. After triggers
 8. Assignment, auto-response, and workflow rules (a workflow field update re-runs before and after update
    triggers once more), then escalation rules
 9. Processes and flows launched by workflow rules, in no guaranteed order
10. After-save record-triggered flows
11. Entitlement rules
12. Roll-up summaries and cross-object workflow save the parent, then the grandparent (each a full save)
13. Criteria-based sharing evaluation
14. Commit, then post-commit work: emails, enqueued async Apex, asynchronous paths of record-triggered flows
```

- Before-save flows run ahead of the before triggers, and validation rules after both: a before trigger can still fix data that would fail validation, and a before-save flow never sees what the trigger sets.
- A recursive save of the same record skips steps 8 to 12 (steps 9 to 17 in the Apex Developer Guide's numbering).
- In the workflow re-run, `Trigger.old` still holds the values from before the original update.
- Several triggers on one object and event run in no guaranteed order.

### Async work runs in a new transaction

Async jobs and event subscribers start fresh: new limits, static variables back at their initial values, and sometimes a different running user. A job that reads a static set filled by the enqueuing trigger sees it empty; pass everything it needs through its constructor or the event payload ([Async Apex](apex.md#async-apex)).

| Context | Limits | Running user | Starts |
|---|---|---|---|
| Queueable, `@future`, Batch `execute` | Asynchronous | The user who enqueued or submitted the job | After the enqueuing transaction commits |
| Scheduled Apex | Synchronous | The user who scheduled the job | At the scheduled time |
| Platform-event and Change Data Capture triggers | Synchronous | Automated Process, unless `PlatformEventSubscriberConfig` names a user | After the event is published; publish-after-commit events and change events only after the commit |

### Runtime-failure rules at a glance

| Rule | Symptom | Fix |
|---|---|---|
| No callout after uncommitted DML in the same transaction | `System.CalloutException: You have uncommitted work pending` | Call out first, or commit and call out from a Queueable that implements `Database.AllowsCallouts` ([Callouts & Integrations](apex.md#callouts--integrations)) |
| No DML on setup objects mixed with other DML: UserRole, Group and GroupMember, PermissionSet and PermissionSetAssignment, QueueSObject, territories, and User (inserting one with a role, or changing its role, profile, username, or active flag) | `MIXED_DML_OPERATION` | Move the setup part to a Queueable (`@future` in legacy code); in tests, wrap the setup DML in `System.runAs` |
| Triggers recurse at most 16 levels | "maximum trigger depth exceeded" | [Recursion Control](apex-triggers.md#recursion-control) |
| Stay inside every governor limit | `System.LimitException` (for example "Too many SOQL queries: 101"), which can't be caught | [Governor Limits](#governor-limits) |
| `Trigger.new` is read-only in after triggers | `System.FinalException: Record is read-only` | [Context Variables](apex-triggers.md#context-variables) |
| A query assigned to a single sObject must return exactly one row | `System.QueryException: List has no rows for assignment to SObject` | [Result Handling](soql-sosl.md#result-handling) |
| Row locks last until commit | `UNABLE_TO_LOCK_ROW` on DML; `QueryException` when a `FOR UPDATE` wait exceeds 10 seconds | [Async Apex](apex.md#async-apex) |

---

## Security Model

Check the file's `<apiVersion>` before judging any sharing or CRUD/FLS finding: Summer '26 (API 67.0) changed the defaults for classes and trigger bodies saved at 67.0 and later.

### Three layers: CRUD, FLS, and sharing

| Layer | Controls | Enforced in Apex by |
|---|---|---|
| Object permissions (CRUD) | Read, create, edit, or delete per object | User mode, `Security.stripInaccessible`, describe checks |
| Field-level security (FLS) | Read or edit per field | User mode, `Security.stripInaccessible`, describe checks |
| Record sharing | Which records the user sees and edits | `with sharing` or `inherited sharing`, user mode |

A sharing keyword never checks CRUD or FLS, and a field check never filters records, so name the layer in every finding: below API 67.0, a `with sharing` controller whose query has no access mode hides records the user can't see, yet still returns `Salary__c` to users without FLS on it. Object-level View All and Modify All, and the View All Data and Modify All Data permissions, bypass sharing ([Permission Sets, Groups & Profiles](metadata.md#permission-sets-groups--profiles)).

### Defaults depend on surface and API version (API 67.0+ / Summer '26, behavior change)

Each class's and trigger's own `<apiVersion>` in its `-meta.xml` decides, not the org, the caller, or `sourceApiVersion`. Explicit modes behave the same at every version.

| Surface | API 66.0 and earlier | API 67.0 and later |
|---|---|---|
| Class with no sharing keyword | `without sharing` as an entry point (REST, Visualforce controller, async job) and the caller's mode otherwise; `with sharing` for Aura controllers and `@AuraEnabled` methods called from LWC, and when any class in its inheritance chain is saved at 67.0+ | `with sharing`, except that an undeclared class that extends another takes its parent's mode: a subclass of a `without sharing` class runs `without sharing` |
| Inner classes | Don't adopt the outer class's keyword; an undeclared one follows the row above | Same: an undeclared inner class runs `with sharing` unless it extends a class |
| SOQL, SOSL, DML, and `Database` / `Search` methods with no access mode | System mode: CRUD and FLS ignored, records per the class's sharing | User mode: the running user's CRUD, FLS, and sharing. User mode overrides the class's sharing declaration |
| `without sharing` | Skips record sharing; CRUD and FLS are skipped anyway in system mode | Affects only explicit system-mode operations; implicit ones enforce sharing regardless. An intended bypass needs `WITH SYSTEM_MODE`, `as system`, or `AccessLevel.SYSTEM_MODE` |
| `inherited sharing` | The caller's mode; `with sharing` as an entry point, and always for async jobs | Same |
| Explicit `WITH USER_MODE` / `WITH SYSTEM_MODE`, `as user` / `as system`, `AccessLevel` (API 57.0+) | As written; system mode takes record access from the class's keyword | Same |
| `WITH SECURITY_ENFORCED` | Compiles; checks read access on selected fields and objects and stops at the first error | Doesn't compile: use `WITH USER_MODE`. Inside a dynamic query string the outcome is undocumented (verify) |
| Triggers | Always `without sharing`; no sharing keyword or access mode can be declared on a trigger. Implicit operations in the trigger body run in system mode | The trigger stays `without sharing`, but database operations in the trigger body run in user mode unless they state system mode, and user mode enforces CRUD, FLS, and sharing. Handler classes follow their own keyword and apiVersion |
| Anonymous Apex (`*.apex` scripts) | Always `with sharing`, as the running user; the block fails to compile if it violates the user's object or field permissions | Same. There is no `-meta.xml`: the access-mode default follows the API version of the executing call (verify) |
| LDS, UI API (`lightning/uiRecordApi`, `lightning-record-*-form`), Visualforce standard controller | The user's CRUD, FLS, and sharing, always | Same; a controller extension's own Apex follows its class |
| Flows (`<runInMode>`) | Record-, schedule-, and platform-event-triggered flows: system context without sharing; screen and autolaunched flows on `DefaultMode` take the launch context; `SystemModeWithSharing` and `SystemModeWithoutSharing` override | Not tied to Apex versions. Screen and autolaunched flows at API 68.0+ can declare `<runInMode>UserMode</runInMode>`: the user's access applies even under a system-context caller ([Run Context & Security](flows.md#run-context--security)) |

```apex
// ❌ At 67.0 an undeclared subclass takes its parent's mode: AccountSelector runs without sharing
public abstract without sharing class BaseSelector { }
public class AccountSelector extends BaseSelector { }

// ✅ Declare a keyword on every class so neither the parent nor a version bump changes access silently
public abstract inherited sharing class BaseSelector { }
public with sharing class AccountSelector extends BaseSelector { }
```

### Review an API version bump across 67.0 as a behavior change

A one-line `-meta.xml` diff from 66.0 or lower to 67.0+ on a class or a trigger can change what every query and DML statement in it returns or allows. Review it like a code change:

- Queries can return fewer rows (sharing) or throw `System.QueryException` for fields and objects the running user can't read (`getInaccessibleFields()` lists them).
- DML can fail for users without create or edit access on the object or its fields (`DmlException`).
- Undeclared classes start running `with sharing`, including undeclared 66.0 subclasses of a bumped base class; an undeclared subclass of a declared parent keeps the parent's mode.
- `WITH SECURITY_ENFORCED` has to become `WITH USER_MODE` before the class compiles.
- A `.trigger-meta.xml` bump across 67.0 moves the trigger body's implicit queries and DML to user mode, with sharing.
- Trigger handlers, invocables called from record-triggered flows, async jobs, and event subscribers now enforce their running user's access: integration users, site guest users, job owners, and Automated Process (which fails object and field checks without explicitly assigned permission sets) need access, or the code opts into system mode explicitly, with a reason.
- Tests need `System.runAs` with realistic least-privilege users; tests that only run as an administrator hide the change.

```apex
// ❌ Unchanged source; only the -meta.xml moved from 66.0 (caller's sharing, system mode)
//    to 67.0 (with sharing, user mode): fewer rows, and a QueryException without FLS on AnnualRevenue
public class AccountSelector {
    public static List<Account> byOwner(Id ownerId) {
        return [SELECT Id, Name, AnnualRevenue FROM Account WHERE OwnerId = :ownerId];
    }
}

// ✅ Explicit keyword and access mode: the bump changes nothing, and the intent is visible
public with sharing class AccountSelector {
    public static List<Account> byOwner(Id ownerId) {
        return [SELECT Id, Name, AnnualRevenue FROM Account WHERE OwnerId = :ownerId WITH USER_MODE];
    }
}
```

### Entry points are the trust boundary

Every way into Apex is a public endpoint that runs with the caller's arguments. Validate input and enforce access on the server; checks in the UI are cosmetic.

| Entry point | Reachable by |
|---|---|
| `@AuraEnabled` (LWC, Aura) | Any user granted the class, with any arguments, without going through the component |
| `@RemoteAction` | Users with access to the Visualforce page and the class |
| `@RestResource`, `webservice` | API-enabled users and integrations; guest users when exposed through a site |
| `@InvocableMethod` | Flows (screen flows run as their user, possibly a guest) and REST API calls to invocable actions |
| Visualforce controllers and extensions | Users with page access; every URL parameter is attacker-controlled, and the `<apex:page action>` method runs on a GET (CSRF, row 7 of [Severity Calibration](#severity-calibration)) |
| Email services (`Messaging.InboundEmailHandler`) | Anyone allowed to send to the address; the handler runs as the service's context user |
| Platform-event and Change Data Capture triggers | Any publisher: Apex that publishes the event, API users with Create on it, anyone who changes a tracked record; the trigger runs as Automated Process unless configured |

```apex
// ❌ API 66.0: trusts the client, so any user with access to the class can close any case by Id
public without sharing class CaseController {
    @AuraEnabled
    public static void closeCase(Id caseId) {
        update new Case(Id = caseId, Status = 'Closed');
    }
}

// ✅ Validate the input, then let sharing, CRUD, and FLS decide in user mode
public with sharing class CaseController {
    @AuraEnabled
    public static void closeCase(Id caseId) {
        if (caseId == null || caseId.getSObjectType() != Case.SObjectType) {
            throw new AuraHandledException('Choose a valid case.');
        }
        Case target = new Case(Id = caseId, Status = 'Closed');
        update as user target;
    }
}
```

Static analysis: PMD `ApexCRUDViolation`, `ApexSharingViolations`.

### Guest and Experience Cloud users

Guest-reachable code serves anonymous internet users, so a sharing or FLS gap there is a data breach. An Experience Cloud target (an LWC `.js-meta.xml` targeting `lightningCommunity__Page`, see [Component Configuration](lwc.md#component-configuration), or an Aura component implementing `forceCommunity:availableForAllPageTypes`) puts a component on a site page, but its Apex is guest-reachable only when the guest user's profile or a permission set assigned to the guest user grants the class in `classAccesses` (the release update that restricts `@AuraEnabled` methods for guest and portal users). Other guest paths: a Visualforce page served on a Salesforce Site, a screen flow on a public page, and an Apex REST class exposed through a site. When the guest profile and permission sets aren't in the repo, report the code as possibly guest-reachable and ask the author which profile or permission set grants the class. Apex that a flow calls follows the flow's access, granted through Run Flows or `flowAccesses` (enforced in Winter '26), rather than `classAccesses` (verify).

The platform already limits guests: no View All or Modify All; no edit or delete object permissions, even through permission sets; guest sharing rules grant Read at most; secure guest record access is enforced; guests can't own new records, join public groups or queues, or have View All Users. Code that works around these limits with `without sharing` or system mode reopens what the platform closed. Guest-reachable code runs `with sharing` in user mode, selects only the fields the page shows, bounds every result with `LIMIT`, and rejects search terms too short to be selective; a confirmed gap raises severity one tier ([Severity Calibration](#severity-calibration)).

### Choose an enforcement mechanism

| Situation | Use | Notes |
|---|---|---|
| Reads and writes on behalf of a user (the default) | User mode: `WITH USER_MODE`, `insert as user`, `AccessLevel.USER_MODE` (API 57.0+); implicit at API 67.0+ | Enforces all three layers and reports every inaccessible field |
| Records going to or coming from the client, where hidden fields should be dropped instead of failing | `Security.stripInaccessible` (API 48.0+) | Removes inaccessible fields; pair it with a sharing keyword. At 67.0+ the query that feeds it needs explicit system mode, or user mode throws first |
| Simple record CRUD in LWC or Aura | LDS and UI API | No Apex to secure |
| Code below API 57.0 | Describe checks (`isAccessible()`, `isCreateable()`, `isUpdateable()`) | Legacy and easy to leave incomplete; migrate when the file is touched |
| Logic that must see or change data the user can't | Explicit system mode, plus `without sharing` for records | A comment with the reason, the narrowest scope, a small isolated class, no raw results to the UI or guests |

Mechanics: [Data Access Security](apex.md#data-access-security) (writes, escalation), [Access Mode in Queries](soql-sosl.md#access-mode-in-queries) (queries), [Class Design](apex.md#class-design) (an isolated `without sharing` class).

---

## API Versions

Every Apex class and trigger, LWC and Aura bundle, Visualforce page, and flow carries its own API version, and versioned behavior follows it.

### Review against each file's own apiVersion

- Read `<apiVersion>` in `.cls-meta.xml`, `.trigger-meta.xml`, `.js-meta.xml`, `.cmp-meta.xml`, and `.page-meta.xml`, and inside `.flow-meta.xml`; when it changed, compare base and head.
- `sourceApiVersion` in `sfdx-project.json` is the version the source format uses for deploy and retrieve; runtime behavior follows each file's own `<apiVersion>`.
- Never raise a blocking finding for not using a feature newer than the file's version: a 59.0 class without `??` is correct code. Suggest upgrades separately as 🟢, with the retest they need.
- Versioned syntax doesn't compile below its minimum: `??` in a 59.0 class fails the deployment.
- Treat every bump as a behavior change, and a class or trigger bump across 67.0 as a security change ([Review an API version bump across 67.0](#review-an-api-version-bump-across-670-as-a-behavior-change)).

### API version quick reference

| Feature | Available from | Review note |
|---|---|---|
| `switch on`, `Trigger.operationType` | API 43.0 | |
| `inherited sharing` | API 44.0 | Runs `with sharing` when the class is the entry point |
| `Security.stripInaccessible` | API 48.0 | |
| Safe navigation `?.` | API 50.0 | |
| Transaction Finalizers (`System.Finalizer`) | API 52.0 | One finalizer per Queueable |
| `Assert` class | API 56.0 | Prefer it in new tests; `System.assert*` stays valid |
| User mode: `WITH USER_MODE`, `as user`, `AccessLevel`; `Database.queryWithBinds` and its siblings | API 57.0 | User-mode DML failures throw `DmlException` from API 58.0 |
| Flows without the 2,000 executed-elements limit | API 57.0 (the flow's version) | The CPU limit still applies |
| Parent-to-child subqueries nested up to 5 levels | API 58.0 | |
| `AsyncOptions`, `QueueableDuplicateSignature` | API 59.0 | |
| Null coalescing `??` | API 60.0 | Doesn't compile below 60.0 |
| Apex Cursors (`Database.Cursor`) | API 66.0 | |
| `RunRelevantTests`, `@IsTest(critical=true)`, `@IsTest(testFor=...)` | API 66.0, Beta | Suggest, never require |
| Secure by default: implicit user mode (trigger bodies included), implicit `with sharing`, no `WITH SECURITY_ENFORCED` | API 67.0 | Behavior change for every class and trigger saved at 67.0+ |
| Flow `<runInMode>UserMode</runInMode>` | API 68.0 | Screen and autolaunched flows |
| `lwc:if` / `lwc:elseif` / `lwc:else`, `lwc:ref` | Spring '23 | `if:true` / `if:false` still work but are legacy |
| Dynamic components (`lwc:component` with `lwc:is`) | Winter '24 | Component apiVersion 55.0+, Lightning Web Security, `lightning__dynamicComponent` capability |
| Complex template expressions in LWC | Winter '27 (GA) | Component apiVersion 66.0+ |
| Workflow Rules and Process Builder | End of support Dec 31, 2025 | No new ones; migrate to Flow |

---

## Org-Agnostic Code

Code moves through scratch orgs, sandboxes, and production, where record Ids, hosts, and users differ. Anything environment-specific belongs in metadata that deploys, not in source. This section owns configuration for every Salesforce guide.

### No hard-coded record IDs, org URLs, or usernames

Hard-coded values break silently after deployment or in the next sandbox refresh. Resolve record types by developer name (`Schema.SObjectType.Lead.getRecordTypeInfosByDeveloperName().get('Partner').getRecordTypeId()`), queues and groups by querying `Group` by `DeveloperName` once outside any loop, links with `URL.getOrgDomainUrl()`, and identity-based exceptions with a custom permission (`FeatureManagement.checkPermission('Bypass_Lead_Routing')`). Exception: Ids a test creates itself.

```apex
// ❌ Values that only exist in one org
Id partnerTypeId = '012000000000000AAA';
String recordLink = 'https://example.my.salesforce.com/' + recordId;
Boolean canBypass = UserInfo.getUserName() == 'integration@example.com';
```

Static analysis: PMD `AvoidHardcodingId`.

### Keep configuration in Custom Metadata

Thresholds, feature switches, mappings, and tunables belong in Custom Metadata: records deploy with the code, are visible in tests without `SeeAllData`, and `getInstance()` and `getAll()` read cached metadata without a SOQL query (they return at most 255 characters of a long text area field). Endpoints belong in Named Credentials and user-facing text in Custom Labels; choosing between Custom Metadata, Custom Settings, and Labels is in [Configuration Metadata](metadata.md#configuration-metadata). `getInstance()` returns null for a missing record, so read it null-safely.

```apex
// ❌ Business values compiled into the class: every change is a deployment
private static final Decimal REVIEW_THRESHOLD = 10000;

// ✅ Custom Metadata by developer name; a missing record fails loudly instead of throwing a NullPointerException
Invoice_Setting__mdt setting = Invoice_Setting__mdt.getInstance('Default');
if (setting?.Review_Threshold__c == null) {
    throw new InvoiceException('Invoice_Setting__mdt.Default needs a Review_Threshold__c');
}
```

---

## Tooling

Static analysis output is input to the review, not a verdict: confirm each hit in the code and calibrate it with [Severity Calibration](#severity-calibration). Findings a configured linter already enforces in CI aren't review findings.

### Run Salesforce Code Analyzer on local paths

Code Analyzer is optional local analysis: use it only when it is already installed, and install nothing without asking. Code Analyzer v5 (`sf code-analyzer`) replaced v4 (`sf scanner`, retired in August 2025); a CI script or README still calling `sf scanner` is out of date.

- Scan only local paths, with selectors that stay on local engines: `Recommended` (the default), `Security`, or an engine- or rule-scoped selector such as `flow` or `pmd:ApexSOQLInjection`.
- Never pass `--target-org`, and never select `all`, `apexguru`, or a severity-only selector such as `2` or `High`: those pull in ApexGuru rules, and the ApexGuru engine connects to an org, falling back to the CLI's default org when no `--target-org` is given. ApexGuru rules carry only the `apex-guru` tag, so `Recommended` and `Security` never select them.
- A `code-analyzer.yml` in the workspace is applied automatically; check that it doesn't configure the ApexGuru engine or retag its rules.
- Linters load repository configuration files, and loading them executes repository code (an `eslint.config.js`, or custom rules and plugins a config points to): run Code Analyzer and ESLint only on code you trust.
- Engines that need a local runtime (a JDK for PMD and CPD, Python 3.10+ for the Flow Scanner) fail without it; skip them rather than install anything.
- Code Analyzer's own severities aren't review tiers: it rates `OperationWithLimitsInLoop` Moderate, while a query in a trigger loop is 🔴 here.
- LWC and Aura bundles use the repo's own ESLint config (`@salesforce/eslint-config-lwc` v4+ needs ESLint 9 flat config); ask why a diff disables `@lwc/lwc/*` rules ([Linting & Tooling](../javascript.md#linting--tooling), [Testing with Jest](lwc.md#testing-with-jest)).

### Map PMD hits to the guide that owns the rule

Each Salesforce guide names the PMD 7 rules next to the review rule they support (for example `OperationWithLimitsInLoop` under [Bulkification](apex.md#bulkification), `ApexSOQLInjection` in [SOQL & SOSL](soql-sosl.md), the XSS and CSRF rules in [Visualforce](visualforce.md)); `ApexBadCrypto` belongs to [Cryptography](../security-review-guide.md#cryptography). `QueueableWithoutFinalizer` is a 💡 suggestion, not a defect. PMD 7 removed `AvoidSoqlInLoops`, `AvoidSoslInLoops`, and `AvoidDmlStatementsInLoops` (replaced by `OperationWithLimitsInLoop`), so rulesets and suppressions that still name them do nothing. Code Analyzer can lag PMD releases.

---

## Severity Calibration

Tiers: 🔴 [blocking] (fix before merge), 🟡 [important] (should fix, discuss if you disagree), 🟢 [nit] (optional); 💡 [suggestion] marks an optional alternative. This table is the Salesforce source of truth: other guides link to its rows instead of restating them.

Before assigning a tier:

- Judge sharing and CRUD/FLS against the file's effective defaults ([Security Model](#security-model)): the class's keyword, else its parent's, else its apiVersion.
- Review the change. Pre-existing code isn't a finding unless the change makes it worse or newly reachable.
- House conventions (a trigger framework, fflib layers, `Assert` over `System.assert*`) apply only when the repo already follows them.
- Items a configured linter or formatter enforces aren't findings.
- A finding that needs org evidence (coverage, data volumes, reachability metadata outside the repo) is a question to the author until the evidence arrives.

| # | Finding | Default | Adjust |
|---|---|---|---|
| 1 | SOQL, DML, callout, or `enqueueJob` inside a loop on a trigger, batch, or list path (Apex or Flow); an unguarded enqueue per trigger chunk that async Apex can reach | 🔴 | 🟡 if the loop bound is small and fixed (a few Custom Metadata rows) |
| 2 | Dynamic SOQL or SOSL concatenating caller input without binds or an allowlist | 🔴 | — |
| 3 | New or changed data access in a user-reachable entry point (`@AuraEnabled`, `@RemoteAction`, `@RestResource`, `webservice`, Visualforce controller, screen-flow invocable) lacking sharing or CRUD/FLS under its effective defaults | 🔴 | 🟡 for documented admin-only tooling; implicit user mode at 67.0+ already satisfies it; untouched pre-existing access isn't a finding |
| 4 | System-mode escalation (`without sharing` with explicit system mode, `WITH SYSTEM_MODE`, `AccessLevel.SYSTEM_MODE`, `as system`, flow system context without sharing) that is unjustified or broader than needed | 🟡 | 🔴 if confirmed guest-reachable, or if the data is returned to the UI |
| 5 | Entry-point class with no sharing keyword | 🟡 when its effective mode is `without sharing` (66.0 and earlier, or a subclass of a `without sharing` parent) | 🔴 if confirmed guest-reachable; 🟢 when the effective mode is already `with sharing` (an explicit keyword is still preferred) |
| 6 | XSS escape hatch with user data (Visualforce `escape="false"` or an unencoded JS or URL merge field; `lwc:dom="manual"` with `innerHTML`; `aura:unescapedHtml`) | 🔴 | 🟡 for admin-authored, sanitized content |
| 7 | DML on Visualforce page load through the `<apex:page action=...>` method or anything it calls: it runs on a GET, the CSRF case. Judge a method by how it is invoked, not by a name such as `init()` | 🔴 | 🟡 when the page sets `<confirmationTokenRequired>true</confirmationTokenRequired>`; 🟡 for DML in a constructor or getter, a functional bug that throws "DML currently not allowed"; no finding for a method only a user-submitted form or button invokes |
| 8 | Secret, token, or password in code, labels, Custom Metadata, custom settings, static resources, or metadata XML | 🔴 | — |
| 9 | Callout after uncommitted DML, or a synchronous callout from a trigger | 🔴 | — |
| 10 | Static Boolean that gates per-record logic (a recursion guard), or logic that skips records after the first 200-record chunk | 🔴 | No finding for a purpose-named, once-per-transaction side-effect flag, such as one guarded enqueue |
| 11 | High-risk grant: Modify All Data, View All Data, Author Apex, Customize Application, Manage Users, object View All or Modify All, a loosened org-wide default, guest access, a Remote Site with protocol security disabled | 🔴 | 🟡 for a documented integration or admin permission set group |
| 12 | Destructive change, field narrowing, or a new required or unique field without a data plan | 🔴 | 🟡 when there is no production data yet |
| 13 | Hard-coded record Ids, org URLs, or usernames | 🟡 | 🔴 if used in authorization logic |
| 14 | Swallowed exception, or ignored `Database.SaveResult` errors | 🟡 | 🔴 if it hides data loss in an integration or batch |
| 15 | Logic in the trigger body, or a second trigger on the same object | 🟡 | No finding for a managed package's trigger you don't own |
| 16 | Changed Apex without meaningful tests (no asserts, `SeeAllData=true`, no bulk, negative, or `runAs` case) | 🟡 | 🔴 only when CI or the author shows coverage below the deployment gate or an uncovered trigger; otherwise ask for the coverage |
| 17 | New field without FLS; record-triggered flow without entry conditions; flow element without a fault path | 🟡 | No FLS finding for required or master-detail fields, which can't carry `fieldPermissions` ([Ship field-level security](metadata.md#ship-field-level-security-with-every-new-field)); entry conditions matter only when the flow does real work on saves that don't need it, so a before-save flow that stamps every record is fine ([Entry Conditions & Recursion](flows.md#entry-conditions--recursion)); fault paths matter for DML, actions, and callouts in screen flows and integration paths, and a Get Records without one is 🟢 ([Fault Handling](flows.md#fault-handling)) |
| 18 | New `global` member in a released managed package | 🟡: confirm it is a deliberate, permanent API | 🔴 if it exposes internals or unsafe operations; 🟢 in unlocked or unmanaged code |
| 19 | Legacy-but-valid idioms in new code (`if:true`, `@track` on primitives, `@future`, asserts without messages) | 🟢 | 💡 when the file's apiVersion is old |
| 20 | Class or trigger bump across API 67.0 without reviewing the new defaults (queries, DML, inheritance chain, trigger bodies, least-privilege tests) | 🟡 | 🔴 if `WITH SECURITY_ENFORCED` remains, or a guest, integration, or event-subscriber path loses access it needs |
| 21 | `without sharing` class at 67.0+ whose intended bypass relies on implicit operations (user mode overrides the keyword, so the bypass never happens) | 🟡 | 🔴 if it breaks a guest, integration, or event-subscriber path |

### Escalate or de-escalate by exposure

Apply a row's Adjust column first. Where it doesn't cover the situation, move the tier once for exposure, and never above 🔴 or below 🟢. Show the numbers behind every limit finding.

- Confirmed guest or external reachability (the guest profile or a guest permission set grants the class in `classAccesses`, a public site page, a public REST endpoint) raises a finding one tier. Possibly guest-reachable code, where that metadata isn't in the repo, keeps its tier until the author confirms.
- Documented, admin-only internal tooling lowers one tier.
- A problem confined to test code (for example a query in a loop inside a test method) lowers one tier; test quality itself is row 16.

```text
🔴 [blocking] AccountTriggerHandler.cls:42 runs a SOQL query inside the loop over Trigger.new.
   200 records per chunk → 200 queries → System.LimitException at query 101
   ("Too many SOQL queries: 101") on the first bulk update. Collect the AccountIds,
   query once before the loop, and read from a Map (see apex.md, Bulkification).
```

---

## References

- [Execution Governors and Limits (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm)
- [Database Operations Run in User Mode by Default (Summer '26)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_default_user_mode.htm&language=en_US&release=262&type=5)
- [Apex Classes Enforce Sharing Rules by Default (Summer '26)](https://help.salesforce.com/s/articleView?language=en_US&id=release-notes.rn_apex_default_enforce_sharing.htm&release=262&type=5)
- [Apex Triggers Always Run in a "without sharing" Context (Summer '26)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_triggers_system_mode.htm&language=en_US&release=262&type=5)
- [The WITH SECURITY_ENFORCED SOQL Clause is Removed (Summer '26)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_removed_withSecurityEnforced.htm&language=en_US&release=262&type=5)
