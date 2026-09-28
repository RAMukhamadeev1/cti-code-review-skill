# Salesforce Platform Code Review Guide

The shared foundation for every Salesforce review (Apex, triggers, SOQL/SOSL, LWC, Aura, Visualforce, Flows, and metadata): governor limits, the transaction model, the security model and API-version rules, org-agnostic code, tooling, and severity calibration. Current for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs.

> Load this guide first for any Salesforce change, then the guide for each changed file type (see [When to Use This Guide](#when-to-use-this-guide)).
> Related: [Security Review Guide](../security-review-guide.md#salesforce-platform-security) · [Performance Review Guide](../performance-review-guide.md#salesforce-platform-performance) · [Architecture Review Guide](../architecture-review-guide.md#salesforce-architecture) · [Universal Quality Guide](../code-quality-universal.md#salesforce-mapping)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Static Review Only](#static-review-only)
- [Governor Limits](#governor-limits)
- [Transactions & Execution Contexts](#transactions--execution-contexts)
- [Security Model](#security-model)
- [API Versions](#api-versions)
- [Org-Agnostic Code](#org-agnostic-code)
- [Tooling](#tooling)
- [Severity Calibration](#severity-calibration)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

After this guide, load the guide for each changed file type:

| Changed files | Load | Also load when |
|---|---|---|
| `classes/*.cls`, `*.apex` | [Apex](apex.md) | [SOQL & SOSL](soql-sosl.md) if the diff has `[SELECT`, `[FIND`, `Database.query`, `queryWithBinds`, or `Search.query`; [LWC-Apex contract](lwc.md#the-lwc-apex-contract) for `@AuraEnabled`; [Invocable Apex](flows.md#invocable-apex-contract) for `@InvocableMethod`; [Visualforce](visualforce.md) for page controllers and extensions |
| `triggers/*.trigger` | [Apex Triggers](apex-triggers.md) + [Apex](apex.md) | [SOQL & SOSL](soql-sosl.md) as above |
| Apex test classes | [Apex: Testing](apex.md#testing) | [Testing Triggers](apex-triggers.md#testing-triggers) for trigger tests |
| `*.soql` | [SOQL & SOSL](soql-sosl.md) | |
| `lwc/<bundle>/*` | [LWC](lwc.md) + [JavaScript](../javascript.md) | [TypeScript](../typescript.md) for `.ts` files |
| `aura/<bundle>/*` | [Aura](aura.md) + [JavaScript](../javascript.md) | [LWC-Apex contract](lwc.md#the-lwc-apex-contract) for server actions |
| `*.page`, `*.component` | [Visualforce](visualforce.md) | [Apex](apex.md) for controllers and extensions |
| `*.flow-meta.xml` | [Flows](flows.md) | [Apex](apex.md) for the invocable methods the flow calls |
| Permission sets and groups, profiles, sharing rules, objects and fields, validation rules, named and external credentials, remote sites, CSP trusted sites, connected apps, custom metadata, labels | [Metadata & Permissions](metadata.md) | |
| `sfdx-project.json`, `.forceignore`, `manifest/*.xml`, `destructiveChanges*.xml` | [Deployment Impact](metadata.md#deployment-impact) | |
| Only `<apiVersion>` changes in `*-meta.xml` | [API Versions](#api-versions) | [Security Model](#security-model) when an Apex class crosses API 67.0 |

Each topic has one owning guide; the others link to it instead of repeating it:

| Topic | Owner |
|---|---|
| Limit numbers, records per entry point, transaction contexts, order-of-execution summary, security defaults by API version, API-version rules, org-agnostic code, tooling, severity | This guide |
| Bulkification, DML-side access enforcement, sharing keywords and managed sharing, transactions and logging, async Apex, callouts and event publishing, Apex tests | [Apex](apex.md): [Bulkification](apex.md#bulkification) · [Data Access Security](apex.md#data-access-security) · [Async Apex](apex.md#async-apex) · [Testing](apex.md#testing) |
| Trigger architecture, context variables, per-chunk budgets, recursion, order of execution in detail, platform-event and CDC subscribers | [Apex Triggers](apex-triggers.md) |
| SOQL/SOSL injection, query access modes, selectivity and data skew, query shape, pagination and cursors | [SOQL & SOSL](soql-sosl.md) |
| The LWC-Apex contract (`@AuraEnabled`, `cacheable=true`, error handling), browser security, styling | [LWC](lwc.md) |
| Aura server actions, `$A.getCallback`, events, migration | [Aura](aura.md) |
| Visualforce encoding, CSRF, open redirects, view state, remoting | [Visualforce](visualforce.md) |
| Flow type, entry conditions, loops, fault paths, run context, the invocable Apex contract, activation | [Flows](flows.md) |
| Permissions, sharing configuration, schema changes, validation rules, credentials and endpoints, configuration metadata, deployment impact | [Metadata & Permissions](metadata.md) |
| General JavaScript: async, modules, DOM safety, tests | [JavaScript](../javascript.md) |
| Language-agnostic principles | [N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow) · [Error Handling](../cross-cutting/error-handling-principles.md#salesforce-apex) · [Async & Concurrency](../cross-cutting/async-concurrency-patterns.md#salesforce-apex-queueable-finalizer-locking) · [SQL Injection](../cross-cutting/sql-injection-prevention.md#salesforce-apex-soqlsosl) · [XSS](../cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce) |

---

## Static Review Only

A Salesforce review reads files and diffs. It never needs an org, and several commands that look read-only change org state, print credentials, or overwrite the branch under review.

### Never deploy, execute, or query an org during review

| Never run | Why |
|---|---|
| `sf project deploy …`, `sf project retrieve …`, `sf project delete …` | Change org metadata, or overwrite the reviewed source with the org's copy |
| `sf apex run`, `sf apex run test`, anonymous Apex such as `scripts/apex/*.apex` | Execute code in the org; anonymous Apex commits its DML |
| `sf apex tail log`, `sf apex get log` | Need a live session; tailing also creates trace flags |
| `sf data …` | Reads or writes org data |
| `sf org …`, including `sf org display` | Session and auth commands; `sf org display` prints an access token |
| `sf package …` | Creates or installs package versions |
| `sfdx force:*` | Legacy forms of everything above |
| Anything with `-o` / `--target-org`, or that falls back to the default org (such as the ApexGuru engine, see [Tooling](#tooling)) | Reaches whichever org the CLI is logged in to |
| Requests to `*.my.salesforce.com` or `*.lightning.force.com` (WebFetch, curl, scripts) | Live org endpoints |

```bash
# ✅ Allowed: local and read-only
git diff --stat origin/main...HEAD
git diff origin/main...HEAD | python3 scripts/pr-analyzer.py --stats
git diff origin/main...HEAD -- '*-meta.xml' | grep -n 'apiVersion'
grep -rni 'WITH SECURITY_ENFORCED' force-app/main/default/classes
sf code-analyzer run --target force-app/main/default/classes/AccountService.cls --rule-selector Recommended
npx eslint force-app/main/default/lwc/accountList
```

Use a tool only if it is already set up; do not install CLI plugins or packages without asking.

### Ask the author for org-side evidence

Some conclusions need an org. Request the evidence from the author's sandbox, scratch org, or CI, and review what comes back: the test run (failures and per-class coverage for the changed classes and triggers), Query Plan results and record counts for queries on large objects, limit usage from a 200+ record run (a debug log or `Limits` output), automation that is not in the repo (managed-package triggers, org-only flows and validation rules), and the permission sets of the running or integration user.

---

## Governor Limits

Limits are hard failures. `System.LimitException` cannot be caught, and it rolls back the whole transaction, including every trigger, flow, and DML statement in it. Other Salesforce guides link here instead of repeating the numbers.

### Know the per-transaction limits

Values from the Apex Developer Guide and the limits quick reference as of Summer '26, plus the Winter '27 heap change; re-check them for the current release.

| Limit | Synchronous | Asynchronous | Notes |
|---|---|---|---|
| SOQL queries | 100 | 200 | `Database.query`, `queryWithBinds`, `countQuery`, and `getQueryLocator` count; custom metadata queries do not. Parent-child subqueries use a separate limit of 3 times the base (300 / 600) |
| Records retrieved by SOQL | 50,000 | 50,000 | Subquery rows count too |
| Records retrieved by `Database.getQueryLocator` | 10,000 | 10,000 | A Batch Apex `start` locator can return 50 million |
| SOSL queries | 20 | 20 | 2,000 records per query |
| DML statements | 150 | 150 | Also `Approval.process`, `Database.convertLead`, `emptyRecycleBin`, `setSavepoint`, `rollback`, `System.runAs`, and `EventBus.publish` of publish-after-commit events |
| Records processed by DML | 10,000 | 10,000 | Includes `Approval.process` and `emptyRecycleBin` |
| Recursive trigger depth | 16 | 16 | Fails with "maximum trigger depth exceeded" |
| Callouts | 100 | 100 | 120 s cumulative timeout; each callout defaults to 10 s, `setTimeout` accepts up to 120,000 ms |
| `@future` calls | 50 | 50 in Queueable; 0 in Batch and `@future` | |
| `System.enqueueJob` | 50 | 1 | One child job per async transaction |
| `Messaging.sendEmail` calls | 10 | 10 | |
| Publish Immediately `EventBus.publish` calls | 150 | 150 | Separate counter: `Limits.getPublishImmediateDML()` |
| Heap, orgs on Summer '26 | 6 MB | 12 MB | See the rollout note below |
| Heap, orgs on Winter '27 | 10 MB | 25 MB | |
| CPU time | 10,000 ms | 60,000 ms | Database time and callout waits do not count; unchanged in Winter '27 |
| Transaction execution time | 10 min | 10 min | |

- Heap rollout: the Winter '27 (API 68.0) heap limit turns on automatically as each org is upgraded; production orgs move on Sep 4, Oct 2, or Oct 9, 2026, and every org has it from Spring '27. Non-production orgs can opt to keep enforcing the Summer '26 limit. Until every target org runs Winter '27, design for 6 MB / 12 MB: code that needs more passes in an upgraded sandbox and fails in a production org that is not upgraded yet. Code that adapts at runtime reads `Limits.getLimitHeapSize()`.
- Scheduled Apex gets the synchronous limits; Bulk API and Bulk API 2.0 transactions get the higher of the two values; each test method gets its own set.
- Certified managed packages get their own counters for most limits, up to 11 times the base limit across namespaces; heap, CPU, and execution time stay shared by the whole transaction.

### Count per transaction, not per method

One DML statement fans out through triggers, flows, and roll-ups, and every query in that chain draws on the same budget. A DML of N records runs each trigger ⌈N/200⌉ times in one transaction; the per-chunk rules are in [Bulk Safety per Chunk](apex-triggers.md#bulk-safety-per-chunk).

```text
❌ "AccountTriggerHandler runs only 3 queries, far below 100"

   One Apex DML updates 1,000 Accounts          → ⌈1,000 / 200⌉ = 5 Account trigger chunks, one transaction
   AccountTriggerHandler, 3 queries per chunk   → 15 queries
   The handler updates 3,000 related Contacts   → ⌈3,000 / 200⌉ = 15 Contact trigger chunks
   ContactTriggerHandler, 4 queries per chunk   → 60 queries
   Contact after-save flow, 1 Get Records/chunk → 15 queries
   Total                                        → 90 of 100 before anything else runs; query 101 throws

✅ Sum (queries per chunk × chunks) over every trigger, flow, and roll-up the DML reaches,
   against one shared limit; ask the author which automation fires when the repo cannot show it
```

### Know how many records each entry point delivers

| Entry point | Records per invocation | Transaction |
|---|---|---|
| Apex trigger (Apex DML, the UI, or an API call) | Up to 200 per chunk; a DML of N records runs the trigger ⌈N/200⌉ times | All chunks of one DML share one transaction: limits and static variables carry over |
| SOAP API calls, REST sObject Collections | Up to 200 records per call | One per call |
| Bulk API, Bulk API 2.0 | 200-record chunks | One per chunk, with fresh limits |
| Platform-event and Change Data Capture triggers | Up to 2,000 events per batch; `PlatformEventSubscriberConfig` (API 51.0+) sets a smaller batch size and the running user | Their own, with synchronous limits |
| Batch Apex `execute` | `scope`: default 200; at most 2,000 with a QueryLocator (larger values are cut to 2,000); no cap with an Iterable | One async transaction per `execute` |
| Queueable, `@future` | Whatever the caller passes; bound it | A new async transaction |
| Scheduled Apex | Whatever `execute` queries | A new transaction, synchronous limits |
| `@AuraEnabled`, `@RemoteAction`, `@RestResource`, `webservice` | Whatever the client sends; cap list sizes on the server | Synchronous limits |
| Record-triggered flow | The triggering chunk; interviews run bulkified at each data element | The triggering transaction |
| `@InvocableMethod` | One list element per flow interview in the batch | The caller's transaction |

### Know the async and org-wide limits

| Limit | Value |
|---|---|
| Async Apex executions (Batch, Queueable, `@future`, Scheduled) per rolling 24 hours | 250,000 or 200 per user license, whichever is greater |
| Batch Apex jobs | 5 queued or active at once, 100 more holding in the flex queue, 1 `start` running at a time, 5 submitted in a running test |
| Queueable chain depth | No limit in production; 5 in Developer Edition and trial orgs (the parent and 4 children); `AsyncOptions.MaximumQueueableStackDepth` sets your own cap |
| Apex Cursors | 50 million rows across all cursors per transaction; 100 `Cursor.fetch` calls per transaction, and each call also counts as a SOQL query (its rows count toward the SOQL row limit); 10,000 cursors per 24 hours |
| Apex pagination cursors | 100,000 rows and 50 instances per transaction; 2,000 rows per page; 200,000 instances per 24 hours |
| New cursor and pagination-cursor rows | 100 million per 24 hours, combined |
| Concurrent long-running synchronous transactions (over 5 s) | 1 per 100 licenses, minimum 10, maximum 50 |
| Production deployment | At least 75% org-wide Apex coverage, every trigger covered, all tests passing |

### Use Limits methods only for graceful degradation

`Limits.getQueries()` against `Limits.getLimitQueries()` (and the CPU, DML, callout, and heap pairs) tells code how much budget is left. Use it to stop early or hand the rest to a new transaction, never to paper over a loop that should be bulkified.

```apex
// ❌ A limit check hides the loop instead of fixing it: accounts past the budget are silently skipped
for (Account acc : accountList) {
    if (Limits.getQueries() < Limits.getLimitQueries()) {
        acc.Open_Cases__c = [SELECT COUNT() FROM Case WHERE AccountId = :acc.Id AND IsClosed = false];
    }
}

// ✅ Bulkify first; then use Limits to defer optional work instead of failing the save
public with sharing class AccountEnrichment {
    private static final Integer QUERIES_NEEDED = 3; // enrich() runs three bulk queries

    public static void enrichOrDefer(Set<Id> accountIds) {
        if (Limits.getLimitQueries() - Limits.getQueries() < QUERIES_NEEDED) {
            System.enqueueJob(new AccountEnrichmentJob(accountIds)); // fresh limits after commit
            return;
        }
        enrich(accountIds);
    }

    public static void enrich(Set<Id> accountIds) { /* three bulk queries, one DML, no loops */ }
}
```

---

## Transactions & Execution Contexts

A transaction is everything one entry point starts, up to commit or rollback. Every trigger, flow, and class it reaches shares one set of limits and static variables, and all of it rolls back together.

### One DML fans out through the order of execution

Automation on an object runs in a fixed order, and one save can re-enter it through workflow field updates and roll-ups. The detail, including recursion, is in [Order of Execution](apex-triggers.md#order-of-execution).

```text
 1. Load the record; UI saves run system validation, API saves check only foreign keys and restricted picklists
 2. Before-save record-triggered flows (fast field updates)
 3. Before triggers
 4. System validation again, custom validation rules, then duplicate rules
 5. Save to the database, not yet committed
 6. After triggers
 7. Assignment, auto-response, workflow, and escalation rules; a workflow field update fires update triggers once more
 8. Processes and the flows they launch, then after-save record-triggered flows
 9. Entitlement rules; roll-up summaries and cross-object workflow save the parent, then the grandparent
10. Criteria-based sharing evaluation
11. Commit
12. Post-commit: emails, enqueued async Apex, asynchronous paths of record-triggered flows
```

### Async work runs in a new transaction

Async jobs and event subscribers start fresh: new limits, static variables back at their initial values, and sometimes a different running user. A job that reads a static set filled by the enqueuing trigger sees it empty; pass everything it needs through its constructor or the event payload ([Async Apex](apex.md#async-apex)).

| Context | Limits | Running user | Starts |
|---|---|---|---|
| Queueable, `@future`, Batch `execute` | Asynchronous | The user who enqueued or submitted the job | After the enqueuing transaction commits |
| Scheduled Apex | Synchronous | The user who scheduled the job | At the scheduled time |
| Platform-event and Change Data Capture triggers | Synchronous | Automated Process, unless `PlatformEventSubscriberConfig` names a user | After the event is published; publish-after-commit events and change events only after the commit |

### Runtime-failure rules at a glance

| Rule | Symptom | Details |
|---|---|---|
| No callout after uncommitted DML in the same transaction | `System.CalloutException: You have uncommitted work pending. Please commit or rollback before calling out` | [Callouts & Integrations](apex.md#callouts--integrations) |
| No DML on setup objects (User, UserRole, PermissionSetAssignment, GroupMember, ...) mixed with other DML | `MIXED_DML_OPERATION` | [Transactions & Error Handling](apex.md#transactions--error-handling) |
| Triggers recurse at most 16 levels | "maximum trigger depth exceeded" | [Recursion Control](apex-triggers.md#recursion-control) |
| Stay inside every governor limit | `System.LimitException` (for example "Too many SOQL queries: 101"), which cannot be caught | [Governor Limits](#governor-limits) |
| `Trigger.new` is read-only in after triggers | `System.FinalException: Record is read-only` | [Context Variables](apex-triggers.md#context-variables) |
| A query assigned to a single sObject must return exactly one row | `System.QueryException: List has no rows for assignment to SObject` | [Result Handling](soql-sosl.md#result-handling) |
| Row locks last until commit | `UNABLE_TO_LOCK_ROW` under concurrent updates or data skew | [Async Apex](apex.md#async-apex) |

---

## Security Model

Check the file's `<apiVersion>` before judging any sharing or CRUD/FLS finding: Summer '26 (API 67.0) changed the defaults for classes saved at 67.0 and later. Other guides link here for the full matrix.

### Three layers: CRUD, FLS, and sharing

| Layer | Controls | Configured in | Enforced in Apex by |
|---|---|---|---|
| Object permissions (CRUD) | Whether the user may read, create, edit, or delete the object | Permission sets and profiles (`objectPermissions`) | User mode, `Security.stripInaccessible`, describe checks |
| Field-level security (FLS) | Whether the user may read or edit each field | Permission sets and profiles (`fieldPermissions`) | User mode, `Security.stripInaccessible`, describe checks |
| Record sharing | Which records the user can see and edit | Org-wide defaults, role hierarchy, sharing rules, teams, manual and Apex managed sharing | `with sharing` or `inherited sharing`, user mode |

A sharing keyword never checks CRUD or FLS, and a field check never filters records, so name the layer in every finding: below API 67.0, a `with sharing` controller whose query has no access mode hides records the user cannot see, yet still returns `Salary__c` to users without FLS on it. Object-level View All and Modify All, and the View All Data and Modify All Data permissions, bypass sharing ([Permission Sets, Groups & Profiles](metadata.md#permission-sets-groups--profiles)).

### Defaults depend on surface and API version (API 67.0+ / Summer '26, behavior change)

The class's own `<apiVersion>` in its `-meta.xml` decides, not the org, the caller, or `sourceApiVersion`. A 66.0 class and a 67.0 class in one transaction each keep their own defaults, and explicit modes behave the same at every version.

| Surface | API 66.0 and earlier | API 67.0 and later |
|---|---|---|
| Class with no sharing keyword | Inherits the caller's sharing; runs without sharing as an entry point (REST, Visualforce controller, async job). `@AuraEnabled` controllers run `with sharing` | `with sharing`. If any class in an inheritance chain is saved at 67.0+, every undeclared class in the chain runs `with sharing`. `@AuraEnabled` controllers: unchanged |
| SOQL, SOSL, DML, and `Database` / `Search` methods with no access mode | System mode: CRUD and FLS ignored, records per the class's sharing | User mode: the running user's CRUD, FLS, and sharing enforced |
| `without sharing` | Skips record sharing; CRUD and FLS are skipped anyway in system mode | Still sets record access for explicit system-mode operations. Implicit operations run in user mode, and whether `without sharing` relaxes their record access is not clearly documented (verify): require `WITH SYSTEM_MODE`, `as system`, or `AccessLevel.SYSTEM_MODE` wherever system access is intended |
| `inherited sharing` | The caller's sharing; `with sharing` when it is the entry point | Same |
| Explicit `WITH USER_MODE` / `WITH SYSTEM_MODE`, `as user` / `as system`, `AccessLevel` (API 57.0+) | As written | As written |
| `WITH SECURITY_ENFORCED` | Compiles; checks read access on selected fields and objects and stops at the first error | Removed: the class does not compile; use `WITH USER_MODE`. Inside a dynamic query string the outcome is undocumented (verify) |
| Triggers | System mode at every API version: no sharing, CRUD, or FLS, and no sharing keyword or default access mode can be declared on a trigger (Summer '26 removed the nested-trigger cases that enforced sharing) | Same. Handler classes follow their own apiVersion: a 67.0 handler queries and writes in user mode unless it declares otherwise |
| Inner classes | Do not inherit the outer class's keyword | Same; an undeclared inner class in a 67.0 file is expected to run `with sharing` (verify) |
| LDS and UI API (`lightning/uiRecordApi`, `lightning-record-*-form`) | The user's CRUD, FLS, and sharing, always | Same |
| Visualforce standard controller | The user's CRUD, FLS, and sharing | Same; an extension's own Apex follows its class's defaults |
| Visualforce custom controllers and extensions, `@RemoteAction` | As any class: system mode, sharing per keyword | As any class: user mode, `with sharing` when undeclared |
| Flows (`runInMode`) | Record-, schedule-, and platform-event-triggered flows run in system context without sharing; screen and autolaunched flows on `DefaultMode` take the launcher's context; `SystemModeWithSharing` and `SystemModeWithoutSharing` override | Not tied to Apex versions. Flows at API 68.0+ (Winter '27) can also run in "User Context–Enforces User Permissions" |

```apex
// ❌ BaseSelector.cls-meta.xml moved to 67.0; AccountSelector.cls-meta.xml still says 66.0
public abstract class BaseSelector { }                  // undeclared: now with sharing
public class AccountSelector extends BaseSelector { }   // undeclared: also with sharing now

// ✅ Declare a keyword on every class so no bump changes access silently
public abstract inherited sharing class BaseSelector { }
public with sharing class AccountSelector extends BaseSelector { }
```

### Review an API version bump across 67.0 as a behavior change

A one-line `-meta.xml` diff from 66.0 or lower to 67.0+ can change what every query and DML statement in the class returns or allows. Review it like a code change:

- Queries can return fewer rows (sharing) or throw `System.QueryException` for fields and objects the running user cannot read (`getInaccessibleFields()` lists them).
- DML can fail for users without create or edit access on the object or its fields (`DmlException`).
- Undeclared classes start running `with sharing`, including undeclared 66.0 subclasses of a bumped base class.
- `WITH SECURITY_ENFORCED` has to become `WITH USER_MODE` before the class compiles.
- Trigger handlers, invocables called from record-triggered flows, and async jobs now enforce their running user's access: integration users, site guest users, job owners, and event subscribers' running user (Automated Process unless configured) need access to what the code touches, or the code opts into system mode explicitly, with a reason.
- Tests need `System.runAs` with realistic least-privilege users; tests that only run as an administrator hide the change.

```apex
// ❌ Unchanged source; only AccountSelector.cls-meta.xml moved from 66.0 to 67.0
public class AccountSelector {                          // 66.0: caller's sharing; 67.0: with sharing
    public static List<Account> byOwner(Id ownerId) {
        // 66.0: system mode, every field readable. 67.0: user mode, only shared records,
        // and a QueryException if the running user cannot read AnnualRevenue
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
| `@AuraEnabled` (LWC, Aura) | Any user granted access to the class, with any arguments, without going through the component |
| `@RemoteAction` | Users with access to the Visualforce page and the class |
| `@RestResource`, `webservice` | API-enabled users and integrations; guest users when exposed through a site |
| `@InvocableMethod` | Flows (screen flows run as their user, possibly a guest) and REST API calls to invocable actions |
| Visualforce controllers and extensions | Users with page access; every URL parameter is attacker-controlled |
| Email services (`Messaging.InboundEmailHandler`) | Anyone allowed to send to the address; the handler runs as the service's context user |
| Platform-event and Change Data Capture triggers | Any publisher; the trigger runs as Automated Process unless configured |

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

Guest-reachable code serves anonymous internet users, so a sharing or FLS gap there is a data breach. Treat code as guest-reachable when an LWC `.js-meta.xml` targets `lightningCommunity__Page` ([Component Configuration](lwc.md#component-configuration)), an Aura component implements `forceCommunity:availableForAllPageTypes`, a Visualforce page is served on a Salesforce Site, a screen flow sits on a public page, an Apex REST class is exposed through a site, or the class appears in a guest profile's `classAccesses`.

The platform already limits guests: no View All or Modify All; no edit or delete object permissions, even through permission sets (Spring '21); guest sharing rules grant Read at most; secure guest record access is enforced (Winter '21); guests cannot own new records, join public groups or queues, or have View All Users. Code that works around these limits with `without sharing` or system mode reopens what the platform closed. Guest-reachable code runs `with sharing` in user mode, selects only the fields the page shows, bounds every result with `LIMIT`, and rejects search terms too short to be selective; a gap raises severity one tier.

### Choose an enforcement mechanism

| Situation | Use | Notes |
|---|---|---|
| Reads and writes on behalf of a user (the default) | User mode: `WITH USER_MODE`, `insert as user`, `AccessLevel.USER_MODE` (API 57.0+); implicit at API 67.0+ | Enforces all three layers and reports every inaccessible field |
| Records going to or coming from the client, where hidden fields should be dropped instead of failing | `Security.stripInaccessible` (API 48.0+) | Removes inaccessible fields; pair it with a sharing keyword |
| Simple record CRUD in LWC or Aura | LDS and UI API | No Apex to secure |
| Code below API 57.0 | Describe checks (`isAccessible()`, `isCreateable()`, `isUpdateable()`) | Legacy and easy to leave incomplete; migrate when the file is touched |
| Logic that must see or change data the user cannot | Explicit system mode: `WITH SYSTEM_MODE`, `as system`, `AccessLevel.SYSTEM_MODE`, plus `without sharing` for records | A comment with the reason, the narrowest scope, a small isolated class, and no raw results returned to the UI or to guests |

The mechanics live in [Data Access Security](apex.md#data-access-security) (DML side), [Access Mode in Queries](soql-sosl.md#access-mode-in-queries) (query side), and [Class Design](apex.md#class-design) (isolating `without sharing`).

```apex
// ✅ Deliberate system access: small isolated class, documented reason, no record data returned
public without sharing class DuplicateEmailChecker {
    // System mode on purpose: duplicate detection must see Contacts the running user
    // cannot see. It returns only the emails that already exist, never the records.
    public static Set<String> findExisting(Set<String> emails) {
        Set<String> existing = new Set<String>();
        for (Contact match : [SELECT Email FROM Contact WHERE Email IN :emails WITH SYSTEM_MODE]) {
            existing.add(match.Email);
        }
        return existing;
    }
}
```

---

## API Versions

Every Apex class and trigger, LWC and Aura bundle, Visualforce page, and flow carries its own API version, and versioned behavior follows it.

### Review against each file's own apiVersion

Judge each file by the version in its own metadata, and keep upgrade advice out of the blocking path.

- Read `<apiVersion>` in `.cls-meta.xml`, `.trigger-meta.xml`, `.js-meta.xml`, `.cmp-meta.xml`, and `.page-meta.xml`, and inside `.flow-meta.xml`; when it changed, compare base and head.
- `sourceApiVersion` in `sfdx-project.json` is the API version the source format is compatible with for deploy and retrieve; runtime behavior follows each file's own `<apiVersion>`.
- Never raise a blocking finding for not using a feature newer than the file's version: a 59.0 class without `??` is correct code. Suggest upgrades separately as 🟢, with the retest they need.
- Versioned syntax does not compile below its minimum: `??` in a 59.0 class fails the deployment.
- Treat every bump as a behavior change, and a bump across 67.0 as a security change ([Review an API version bump across 67.0](#review-an-api-version-bump-across-670-as-a-behavior-change)).

### API version quick reference

| Feature | Available from | Review note |
|---|---|---|
| `switch on`, `Trigger.operationType` | API 43.0 / Summer '18 | |
| `inherited sharing` | API 44.0 / Winter '19 | Runs `with sharing` when the class is the entry point |
| `WITH SECURITY_ENFORCED` | API 46.0 / Summer '19; removed in API 67.0 | Replace with `WITH USER_MODE` |
| `Security.stripInaccessible` | API 48.0 / Spring '20 | |
| Safe navigation `?.` | API 50.0 / Winter '21 | |
| Transaction Finalizers (`System.Finalizer`) | API 52.0 / Summer '21 | One finalizer per Queueable |
| `Assert` class | API 56.0 / Winter '23 | Prefer it to `System.assert*` in new tests |
| User mode: `WITH USER_MODE`, `as user`, `AccessLevel` | API 57.0 / Spring '23 | User-mode DML failures throw `DmlException` from API 58.0 |
| `Database.queryWithBinds`, `getQueryLocatorWithBinds`, `countQueryWithBinds` | API 57.0 / Spring '23 | |
| Flows without the 2,000 executed-elements limit | API 57.0 / Spring '23 (the flow's version) | The CPU limit still applies |
| Parent-to-child subqueries nested up to 5 levels | API 58.0 / Summer '23 | |
| `AsyncOptions`, `QueueableDuplicateSignature` | API 59.0 / Winter '24 | |
| Null coalescing `??` | API 60.0 / Spring '24 | Versioned: does not compile below 60.0 |
| Apex Cursors (`Database.Cursor`) | API 66.0 / Spring '26 | GA; beta since Summer '24 |
| `RunRelevantTests`, `@IsTest(critical=true)`, `@IsTest(testFor=...)` | API 66.0 / Spring '26, Beta | Still beta: suggest, never require |
| Secure by default: user mode, implicit `with sharing`, no `WITH SECURITY_ENFORCED` | API 67.0 / Summer '26 | Behavior change for every class saved at 67.0+ |
| Flow run context "User Context–Enforces User Permissions" | API 68.0 / Winter '27 | Screen and autolaunched flows |
| `lwc:if` / `lwc:elseif` / `lwc:else`, `lwc:ref` | Spring '23 | `if:true` / `if:false` still work but are legacy |
| Dynamic components (`lwc:component` with `lwc:is`) | Winter '24 | Component apiVersion 55.0+, Lightning Web Security, `lightning__dynamicComponent` capability |
| Complex template expressions in LWC | Winter '27 (GA) | Component apiVersion 66.0+ |
| Workflow Rules and Process Builder | End of support Dec 31, 2025 | No new ones; migrate to Flow |

---

## Org-Agnostic Code

Code moves through scratch orgs, sandboxes, and production, where record Ids, hosts, and users differ. Anything environment-specific belongs in metadata that deploys, not in source.

### No hard-coded record IDs, org URLs, or usernames

Record Ids, instance hosts, and usernames differ in every org, so hard-coded values break silently after deployment or in the next sandbox refresh.

```apex
// ❌ Values that only exist in one org
Id partnerTypeId = '012000000000000AAA';
String recordLink = 'https://example.my.salesforce.com/' + recordId;
Boolean canBypass = UserInfo.getUserName() == 'integration@example.com';

// ✅ Resolve by developer name, custom permission, and the org's own domain at runtime
// (queues and groups: query Group by DeveloperName once, outside any loop)
public with sharing class LeadRouting {
    public static Id partnerRecordTypeId() {
        return Schema.SObjectType.Lead.getRecordTypeInfosByDeveloperName().get('Partner').getRecordTypeId();
    }

    public static String recordLink(Id recordId) {
        return URL.getOrgDomainUrl().toExternalForm() + '/' + recordId;
    }

    public static Boolean canBypassRouting() {
        return FeatureManagement.checkPermission('Bypass_Lead_Routing');
    }
}
```

Static analysis: PMD `AvoidHardcodingId`.

### Keep configuration in Custom Metadata

Custom Metadata records deploy with the code, are visible in tests without `SeeAllData`, and custom metadata queries do not count against the SOQL query limit. Endpoints belong in Named Credentials, user-facing text in Custom Labels; choosing between Custom Metadata, Custom Settings, and Labels is covered in [Configuration Metadata](metadata.md#configuration-metadata).

```apex
// ❌ Environment values compiled into the class: every change is a deployment
public with sharing class BillingClient {
    private static final String ENDPOINT = 'https://billing.example.com/api/v2/invoices';
    private static final Integer TIMEOUT_MS = 20000;
}

// ✅ Endpoint and auth in a Named Credential, tunables in Custom Metadata
public with sharing class BillingClient {
    public static HttpRequest buildInvoiceRequest(String body) {
        HttpRequest request = new HttpRequest();
        request.setEndpoint('callout:Billing_API/invoices');
        request.setMethod('POST');
        request.setBody(body);
        // getInstance() reads cached metadata and uses no SOQL query
        // ⚠️ getInstance() and getAll() return at most 255 characters of a long text area field
        Billing_Setting__mdt setting = Billing_Setting__mdt.getInstance('Default');
        if (setting != null && setting.Timeout_Ms__c != null) {
            request.setTimeout(setting.Timeout_Ms__c.intValue());
        }
        return request;
    }
}
```

---

## Tooling

Static analysis output is input to the review, not a verdict: confirm each hit in the code and calibrate it with the table in [Severity Calibration](#severity-calibration).

### Run Salesforce Code Analyzer on local paths

Code Analyzer v5 (`sf code-analyzer run`, `rules`, `config`) replaced v4 (`sf scanner`, retired in August 2025); a CI script or README still calling `sf scanner` is out of date. Run it only if it is already installed, only on local paths, and only with selectors that stay on local engines: `Recommended` (the default), `Security`, or an engine- or rule-scoped selector such as `flow` or `pmd:ApexSOQLInjection`.

- Never pass `--target-org`, and never select `all`, `apexguru`, or a severity-only selector such as `2` or `High`: those pull in ApexGuru rules, and the ApexGuru engine connects to an org, falling back to the CLI's default org when no `--target-org` is given. ApexGuru rules carry only the `apex-guru` tag, so `Recommended` and `Security` never select them.
- A `code-analyzer.yml` in the workspace is applied automatically; check that it does not configure the ApexGuru engine or retag its rules.
- RetireJS rules (tagged `Security`) scan static resources (`.resource`, `.zip`) for JavaScript libraries with known vulnerabilities.
- Engines that need a local runtime (a JDK for PMD and CPD, Python 3.10+ for the Flow Scanner) fail without it; skip them rather than install anything.

```bash
# ✅ Local paths only: --workspace gives context, --target limits the report to the changed files
sf code-analyzer run --workspace force-app --rule-selector Recommended --view table \
  --target force-app/main/default/classes/AccountService.cls \
  --target force-app/main/default/triggers/AccountTrigger.trigger

# ✅ Security rules of every local engine, written to a file outside the repository
sf code-analyzer run --workspace force-app --rule-selector Security --output-file /tmp/code-analyzer.html
```

Code Analyzer's own severities are not review tiers: it rates `OperationWithLimitsInLoop` Moderate, while a query in a trigger loop is 🔴 here.

### PMD rule to guide map

| PMD rule (PMD 7) | Catches | Guide |
|---|---|---|
| `OperationWithLimitsInLoop` | SOQL, DML, and other limited operations inside loops | [Bulkification](apex.md#bulkification) |
| `OperationWithHighCostInLoop`, `EagerlyLoadedDescribeSObjectResult` | Expensive describe calls in loops or loaded eagerly | [Bulkification](apex.md#bulkification) |
| `AvoidNonRestrictiveQueries` | SOQL without `WHERE` or `LIMIT` | [Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes) |
| `ApexSOQLInjection` | Dynamic SOQL built from unescaped input | [SOQL Injection](soql-sosl.md#soql-injection) |
| `ApexCRUDViolation` | Data access without object or field checks | [Data Access Security](apex.md#data-access-security) |
| `ApexSharingViolations` | Classes with data access but no sharing keyword | [Class Design](apex.md#class-design) |
| `ApexDangerousMethods` | CRUD-disabling helpers and debug output of sensitive data | [Transactions & Error Handling](apex.md#transactions--error-handling) |
| `ApexInsecureEndpoint`, `ApexSuggestUsingNamedCred` | Plain HTTP endpoints; hard-coded credentials in requests | [Callouts & Integrations](apex.md#callouts--integrations) |
| `ApexBadCrypto` | Hard-coded keys or initialization vectors | [Cryptography](../security-review-guide.md#cryptography) |
| `EmptyCatchBlock`, `AvoidDebugStatements`, `DebugsShouldUseLoggingLevel` | Swallowed exceptions, noisy or unleveled logging | [Transactions & Error Handling](apex.md#transactions--error-handling) |
| `AvoidFutureAnnotation`, `QueueableWithoutFinalizer`, `AvoidStatefulDatabaseResult` | Legacy `@future`, Queueables without a Finalizer, `Database` result objects kept in `Database.Stateful` batch state | [Async Apex](apex.md#async-apex) |
| `AvoidGlobalModifier` | Unnecessary `global` members | [Managed Packages](apex.md#managed-packages) |
| `ApexUnitTestClassShouldHaveAsserts`, `ApexAssertionsShouldIncludeMessage`, `ApexUnitTestShouldNotUseSeeAllDataTrue`, `ApexUnitTestClassShouldHaveRunAs`, `ApexUnitTestMethodShouldHaveIsTestAnnotation` | Tests without asserts, messages, own data, `runAs`, or `@IsTest` | [Testing](apex.md#testing) |
| `AvoidLogicInTrigger` | Business logic in the trigger body | [Trigger Architecture](apex-triggers.md#trigger-architecture) |
| `AvoidDirectAccessTriggerMap` | `Trigger.new[0]`-style single-record assumptions | [Context Variables](apex-triggers.md#context-variables) |
| `ApexXSSFromURLParam`, `ApexXSSFromEscapeFalse`, `VfUnescapeEl`, `VfHtmlStyleTagXss` | Unencoded output in Apex and Visualforce | [Output Encoding](visualforce.md#output-encoding) |
| `ApexCSRF`, `VfCsrf` | DML in constructors, initializers, or page actions | [CSRF & State Changes](visualforce.md#csrf--state-changes) |
| `ApexOpenRedirect` | Redirects to caller-supplied URLs | [Controller Security](visualforce.md#controller-security) |
| `InaccessibleAuraEnabledGetter` | `@AuraEnabled` properties whose getter is private or protected | [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract) |
| `AvoidHardcodingId` | Record Ids in code | [Org-Agnostic Code](#org-agnostic-code) |

PMD 7 removed `AvoidSoqlInLoops`, `AvoidSoslInLoops`, and `AvoidDmlStatementsInLoops` (replaced by `OperationWithLimitsInLoop`), so rulesets and suppressions that still name them do nothing. Code Analyzer can lag PMD releases: rules added after its bundled PMD version may not be available yet.

### Lint LWC and Aura JavaScript

`@salesforce/eslint-config-lwc` v4+ requires ESLint 9 flat config and offers `base`, `recommended`, `extended`, `i18n`, and `ssr` configs (plus `*Ts` variants), with peer dependencies `@lwc/eslint-plugin-lwc`, `@salesforce/eslint-plugin-lightning`, `eslint-plugin-import`, and `eslint-plugin-jest`; Aura bundles use `@salesforce/eslint-plugin-aura`. The trailheadapps/lwc-recipes `eslint.config.js` is a working reference. Ask for a reason when a diff disables `@lwc/lwc/*` rules or adds `eslint-disable` comments. Run the project's own config on the changed bundles only (`npx eslint force-app/main/default/lwc/accountList`). General lint rules are in [Linting & Tooling](../javascript.md#linting--tooling); Jest is in [Testing with Jest](lwc.md#testing-with-jest).

---

## Severity Calibration

Tiers use the skill's labels: 🔴 `[blocking]` (fix before merge), 🟡 `[important]` (should fix, discuss if you disagree), 🟢 `[nit]` (optional); 💡 `[suggestion]` marks an alternative worth considering. Judge "without sharing" or "without CRUD/FLS" against the defaults of the file's apiVersion ([Security Model](#security-model)).

| # | Finding | Default | Adjust |
|---|---|---|---|
| 1 | SOQL, DML, callout, or `enqueueJob` inside a loop on a trigger, batch, or list path (Apex or Flow) | 🔴 | 🟡 if the loop bound is small and fixed (a few Custom Metadata rows) |
| 2 | Dynamic SOQL or SOSL concatenating caller input without binds or an allowlist | 🔴 | — |
| 3 | User-reachable entry point (`@AuraEnabled`, `@RemoteAction`, `@RestResource`, `webservice`, Visualforce controller, screen-flow invocable) reading or writing data without sharing and CRUD/FLS | 🔴 | 🟡 for documented admin-only tooling |
| 4 | System-mode escalation (`without sharing`, `WITH SYSTEM_MODE`, `AccessLevel.SYSTEM_MODE`, `as system`, flow system context without sharing) that is unjustified or broader than needed | 🟡 | 🔴 if guest or Experience Cloud reachable, or if the data is returned to the UI |
| 5 | Entry-point class with no sharing keyword | 🟡 at API 66.0 and earlier | 🔴 if guest-reachable; 🟢 at API 67.0+ (an explicit keyword is still preferred) |
| 6 | XSS escape hatch with user data (Visualforce `escape="false"` or an unencoded JS or URL merge field; `lwc:dom="manual"` with `innerHTML`; `aura:unescapedHtml`) | 🔴 | 🟡 for admin-authored, sanitized content |
| 7 | DML on Visualforce page load (constructor, getter, `action=`) | 🔴 | — |
| 8 | Secret, token, or password in code, labels, Custom Metadata, custom settings, static resources, or metadata XML | 🔴 | — |
| 9 | Callout after uncommitted DML, or a synchronous callout from a trigger | 🔴 | — |
| 10 | Static Boolean recursion guard, or logic that skips records after the first 200-record chunk | 🔴 | — |
| 11 | High-risk grant: Modify All Data, View All Data, Author Apex, Customize Application, Manage Users, object View All or Modify All, a loosened org-wide default, guest access, a Remote Site with protocol security disabled | 🔴 | 🟡 for a documented integration or admin permission set group |
| 12 | Destructive change, field narrowing, or a new required or unique field without a data plan | 🔴 | 🟡 when there is no production data yet |
| 13 | Hard-coded record Ids, org URLs, or usernames | 🟡 | 🔴 if used in authorization logic |
| 14 | Swallowed exception, or ignored `Database.SaveResult` errors | 🟡 | 🔴 if it hides data loss in an integration or batch |
| 15 | Logic in the trigger body, or a second trigger on the same object | 🟡 | — |
| 16 | Changed Apex without meaningful tests (no asserts, `SeeAllData=true`, no bulk, negative, or `runAs` case) | 🟡 | 🔴 if coverage falls below the deployment gate or a trigger is uncovered |
| 17 | New field without FLS; record-triggered flow without entry conditions; flow element without a fault path | 🟡 | — |
| 18 | New `global` member in a released managed package | 🔴 | 🟡 in unlocked or unmanaged code |
| 19 | Legacy-but-valid idioms in new code (`if:true`, `@track` on primitives, `@future`, asserts without messages) | 🟢 | 💡 suggestion when the file's apiVersion is old |
| 20 | Bump across API 67.0 without reviewing the new defaults (queries, DML, inheritance chain, least-privilege tests) | 🟡 | 🔴 if `WITH SECURITY_ENFORCED` remains, or a guest, integration, or event-subscriber path loses access it needs |

### Escalate or de-escalate by exposure

Apply a row's Adjust column first. Where it does not cover the situation, move the tier once for exposure, and never above 🔴 or below 🟢. Show the numbers behind every limit finding.

- Guest or external reachability (Experience Cloud, public sites, public REST) raises a finding one tier.
- A released managed-package `global` member raises one tier: it can never be removed.
- Documented, admin-only internal tooling lowers one tier.
- A problem confined to test code (for example a query in a loop inside a test method) lowers one tier; test quality itself is row 16.

```text
🔴 [blocking] AccountTriggerHandler.cls:42 runs a SOQL query inside the loop over Trigger.new.
   200 records per chunk → 200 queries → System.LimitException at query 101
   ("Too many SOQL queries: 101") on the first bulk update. Collect the AccountIds,
   query once before the loop, and read from a Map (see apex.md, Bulkification).
```

---

## Review Checklist

### Scope & safety
- [ ] Only local, read-only commands were used: no deploy, retrieve, anonymous Apex, test runs, data queries, `sf org` commands, or instance URLs
- [ ] `sfdx-project.json` (`sourceApiVersion`, `packageDirectories`, namespace) and every changed file's `<apiVersion>`, base and head, were read
- [ ] Every entry point the change touches is listed with its caller, running user, sync or async context, and records per invocation
- [ ] Org-side evidence (test runs, coverage, query plans, data volumes) was requested from the author or CI

### Limits & transactions
- [ ] Limits were counted per transaction at bulk volume (200 per trigger chunk, up to 2,000 per event batch, the Batch scope), including downstream triggers, flows, and roll-ups
- [ ] Async hand-offs pass their input explicitly and respect the enqueue and `@future` limits of their context
- [ ] `Limits` methods only stop work early or hand it off; they never hide a loop
- [ ] No callout follows uncommitted DML, and setup-object DML is kept apart from other DML
- [ ] Heap-heavy code still fits 6 MB / 12 MB while any target org is not yet on Winter '27

### Security model
- [ ] Sharing and CRUD/FLS findings were judged against the defaults of each file's apiVersion
- [ ] Every system-mode escalation is explicit, narrow, isolated, and justified in a comment
- [ ] Classes at API 67.0+ that need system access use `WITH SYSTEM_MODE`, `as system`, or `AccessLevel.SYSTEM_MODE` instead of relying on `without sharing`
- [ ] Entry points validate input and enforce access on the server; guest-reachable code runs `with sharing` in user mode
- [ ] A bump across API 67.0 was reviewed as a behavior change, including inheritance chains and `System.runAs` tests

### Versions & portability
- [ ] No blocking finding asks for a feature newer than the file's apiVersion; upgrade ideas are 🟢
- [ ] Versioned syntax matches each file's apiVersion (for example `??` needs 60.0+)
- [ ] No hard-coded record Ids, org URLs, usernames, or endpoints; configuration lives in Custom Metadata, Custom Labels, or Named Credentials
- [ ] CI and analyzer configuration uses Code Analyzer v5 and PMD 7 rule names

### Severity
- [ ] Each finding's tier comes from the calibration table, adjusted once for exposure
- [ ] Limit findings show the math: records, operations, and the limit that fails
- [ ] Tool severities from Code Analyzer and PMD were translated into review tiers, not copied

---

## References

- [Execution Governors and Limits (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm)
- [Apex Governor Limits (Salesforce Developer Limits and Allocations Quick Reference)](https://developer.salesforce.com/docs/platform/salesforce-app-limits-cheatsheet/guide/salesforce-app-limits-platform-apexgov.html)
- [Triggers and Order of Execution (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers_order_of_execution.htm)
- [Sharing keywords (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_keywords_sharing.htm)
- [User mode for database operations (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_enforce_usermode.htm)
- [Security.stripInaccessible (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_with_security_stripInaccessible.htm)
- Summer '26 release notes: [user mode by default](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_default_user_mode.htm&language=en_US&release=262&type=5) · [`with sharing` by default](https://help.salesforce.com/s/articleView?language=en_US&id=release-notes.rn_apex_default_enforce_sharing.htm&release=262&type=5) · [`WITH SECURITY_ENFORCED` removed](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_removed_withSecurityEnforced.htm&language=en_US&release=262&type=5) · [triggers always run in system mode](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_triggers_system_mode.htm&language=en_US&release=262&type=5)
- [Apex heap limit increase (Winter '27 release notes)](https://help.salesforce.com/s/articleView?id=release-notes.rn_apex_heap_limit.htm&language=en_US&release=264&type=5)
- [Secure Apex classes (LWC Developer Guide)](https://developer.salesforce.com/docs/platform/lwc/guide/apex-security.html)
- [Configure the user and batch size for a platform event trigger (Platform Events Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.platform_events.meta/platform_events/platform_events_trigger_config.htm)
- [sObject Collections (REST API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_composite_sobjects_collections.htm)
- [Flow run context (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_distribute_context.htm&language=en_US&type=5)
- [Guest user security policies and timelines (Salesforce Help)](https://help.salesforce.com/s/articleView?language=en_US&id=platform.networks_guest_policies_timelines.htm&type=5)
- [Record-triggered automation decision guide (Salesforce Architects)](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered)
- [Code coverage requirements (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_code_coverage_intro.htm)
- [Salesforce DX project configuration (Salesforce DX Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.sfdx_dev.meta/sfdx_dev/sfdx_dev_ws_config.htm)
- [Salesforce Code Analyzer (Salesforce Developers)](https://developer.salesforce.com/docs/platform/salesforce-code-analyzer/guide/code-analyzer.html) · [CLI usage](https://developer.salesforce.com/docs/platform/salesforce-code-analyzer/guide/analyze.html) · [forcedotcom/code-analyzer (GitHub)](https://github.com/forcedotcom/code-analyzer)
- [PMD Apex rules](https://docs.pmd-code.org/latest/pmd_rules_apex.html) · [PMD Visualforce rules](https://docs.pmd-code.org/latest/pmd_rules_visualforce.html)
- [salesforce/eslint-config-lwc (GitHub)](https://github.com/salesforce/eslint-config-lwc) · [trailheadapps/lwc-recipes (GitHub)](https://github.com/trailheadapps/lwc-recipes)
- [Secure Coding Guide: Cross-Site Scripting (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.secure_coding_guide.meta/secure_coding_guide/secure_coding_cross_site_scripting.htm)
