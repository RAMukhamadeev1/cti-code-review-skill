# Salesforce Flow Code Review Guide

Review guidance for flows in source format (`flows/*.flow-meta.xml`, `flowtests/`, `flowDefinitions/`): record-triggered, screen, autolaunched, schedule-triggered, and platform event-triggered flows, plus the invocable Apex they call. Current for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs; judge each flow against its own `<apiVersion>`.

> Load [platform.md](platform.md) first (limits, security model, API versions, severity calibration). Related: [Apex](apex.md) · [Order of Execution](apex-triggers.md#order-of-execution) · [Deployment Impact](metadata.md#deployment-impact)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Review statically: ask the author or CI for flow test, Apex test, and debug log evidence instead of running anything in an org ([Static Review Only](platform.md#static-review-only)). Severities (🔴 [blocking], 🟡 [important], 🟢 [nit], 💡 [suggestion]) default to [Severity Calibration](platform.md#severity-calibration). Unchanged flow logic is not a finding unless the change makes it worse.

### Reading the diff → [Reading a Flow Diff](#reading-a-flow-diff)

- [ ] `<apiVersion>`, `<processType>`, `<start>`, `<runInMode>`, `<status>`, and `<triggerOrder>` were read first; layout churn was skipped and connectors traced from `<start>` into loop bodies and subflows

### Flow type → [Choosing the Flow Type](#choosing-the-flow-type)

- [ ] Same-record fields use before-save; related records, actions, and email use after-save; callouts and deferrable work sit on an async (`AsyncAfterCommit`) or scheduled path
- [ ] No new Workflow Rules or Process Builder processes; migrated automation is deactivated in the same release

### Entry conditions → [Entry Conditions & Recursion](#entry-conditions--recursion)

- [ ] A new or changed record-triggered flow has entry conditions, or its `<description>` says why it must run on every save
- [ ] Update triggers act on changes: `doesRequireRecordChangedToMeetCriteria`, `$Record__Prior`, or `ISCHANGED()`
- [ ] No after-save Update Records on `$Record`, unless the value needs after-save data and the update is change-guarded
- [ ] Each field has one automation owner; record-triggered flows that share an object and timing set `<triggerOrder>`

### Bulk → [Bulk-Safe Design](#bulk-safe-design)

- [ ] No Get, Create, Update, or Delete Records, and no action or subflow that queries or writes, on a loop body; limit math counts loop iterations
- [ ] Get Records filter to the rows needed and list `<queriedFields>` when records go to a subflow or Apex action
- [ ] When the PR touches a record-triggered flow, its queries and DML were counted for a 200-record save with the object's triggers and other flows in the repo

### Faults → [Fault Handling](#fault-handling)

- [ ] DML, actions, and callouts on user-facing and integration paths have a `<faultConnector>`
- [ ] `$Flow.FaultMessage` is logged, not shown on guest or Experience Cloud screens
- [ ] Each fault path deliberately continues, rolls back (screen flows), or blocks the save (Custom Error)

### Run context → [Run Context & Security](#run-context--security)

- [ ] `SystemModeWithSharing` or `SystemModeWithoutSharing` on a screen or autolaunched flow is narrow and explained in `<description>`
- [ ] Guest and portal flows run in user context (`UserMode` at API 68.0+), re-check caller-supplied Ids, and are granted through `flowAccesses`; sensitive flows set `isAdditionalPermissionRequiredToRun`
- [ ] System-context flows don't copy restricted data into widely readable fields

### Invocables → [Invocable Apex Contract](#invocable-apex-contract)

- [ ] `@InvocableMethod` returns one result per request, in request order, with one query or DML for the batch
- [ ] Unexpected failures throw; expected per-request outcomes come back as result fields; no catch-all `return null`
- [ ] The class declares its sharing keyword; user mode where users reach it, system mode only with a stated reason
- [ ] Actions that call out run on an async or scheduled path; a screen flow that calls one after DML needs `callout=true`

### Org-agnostic values → [Org-Agnostic Values](#org-agnostic-values)

- [ ] No literal record Ids, profile names, usernames, or addresses; `DeveloperName` lookups, custom metadata, `$Permission`, `$Label`, or `$Setup` instead

### Activation and tests → [Activation, Versions & Deployment](#activation-versions--deployment)

- [ ] An `<apiVersion>` change is intentional; API names and `<isInput>`/`<isOutput>` variables are unchanged, or their callers change in the same PR
- [ ] Ask the author how the version gets activated in production and which Apex tests cover it (201+ records, a fault case); flow tests assert outcomes
- [ ] A committed `flowDefinitions/` file is a one-off deactivation that will be removed afterward

---

## Reading a Flow Diff

Flow Builder writes elements grouped by type (all `<assignments>`, then `<decisions>`, and so on), not in execution order. At API 64.0+ auto-layout flows save `<locationX>` and `<locationY>` as 0, and API 68.0 adds `<groups>`, which only organize elements: skip that churn and follow the connectors. The examples are excerpts without `<label>`, layout, and `<processMetadataValues>` elements.

### Read the landmarks before the details

| Element | Tells you | Check |
|---|---|---|
| `<apiVersion>` | The version that defines the flow's runtime behavior | A change is a behavior change ([Activation, Versions & Deployment](#activation-versions--deployment)) |
| `<processType>` | `AutoLaunchedFlow` (record-triggered, scheduled, platform event, or no trigger), `Flow` (screen flow); `Workflow`, `CustomEvent`, `InvocableProcess` are Process Builder | No new legacy types |
| `<start>`: `<object>`, `<triggerType>`, `<recordTriggerType>` | `RecordBeforeSave`, `RecordAfterSave`, `RecordBeforeDelete`, `Scheduled`, `PlatformEvent`; `Create`, `Update`, `CreateAndUpdate`, `Delete`. No `<triggerType>`: a user, Apex, or another flow launches it | The type fits the job |
| `<start>`: `<filters>`, `<filterLogic>`, `<filterFormula>`, `<doesRequireRecordChangedToMeetCriteria>` | Entry conditions | Present, and change-aware for updates |
| `<start>`: `<scheduledPaths>`, `<schedule>` | The async path (`<pathType>AsyncAfterCommit</pathType>`), scheduled paths (`<offsetNumber>`, `<offsetUnit>`, `<timeSource>`), a schedule-triggered flow's frequency | Callouts and deferrable work live here |
| `<triggerOrder>` | Run order among record-triggered flows on the object (1 to 2,000, API 54.0+) | Set when flows share object and timing |
| `<runInMode>` | Screen and autolaunched flows: `DefaultMode` (or absent), `SystemModeWithSharing`, `SystemModeWithoutSharing` (API 49.0+), `UserMode` (API 68.0+) | Justified ([Run Context & Security](#run-context--security)) |
| `<status>` | `Active`, `Draft`, `Obsolete`, `InvalidDraft`, `UnderReview` | What the deployment activates |
| `<recordLookups>`, `<recordCreates>`, `<recordUpdates>`, `<recordDeletes>` | Get, Create, Update, and Delete Records: each is a query or a DML statement | Outside loops, filtered, fault path where it matters |
| `<loops>` | `<collectionReference>`, `<nextValueConnector>` (the body), `<noMoreValuesConnector>` (after the loop) | What sits on the body path |
| `<actionCalls>`, `<subflows>` | Actions (`<actionType>` such as `apex`, `emailAlert`, or `flow`, with `<actionName>`) and subflows (`<flowName>`) | Their queries and DML count as the flow's own |
| `<variables>` with `<isInput>true</isInput>` | Values a caller sets: URL parameters, Visualforce, the `lightning-flow` component, a parent flow | Untrusted input in screen flows |

### Trace loop bodies through their connectors

An element runs once per iteration when the path from the loop's `<nextValueConnector>` reaches it and leads back to the loop; elements after `<noMoreValuesConnector>` run once. Follow the `<targetReference>` values by hand, into subflows called from the body too.

```text
❌ Each_Opportunity.nextValueConnector -> Set_Priority -> Update_Opportunity -> back to Each_Opportunity
✅ Each_Opportunity.nextValueConnector -> Set_Priority -> back to Each_Opportunity
   Each_Opportunity.noMoreValuesConnector -> Update_Opportunities (one DML statement for the collection)
```

### Search the changed flows with the Grep tool

List the changed flows with `git diff --name-only`, then run these Grep patterns on them (glob `*.flow-meta.xml` unless noted) and read each hit in context:

- `<stringValue>[A-Za-z0-9]{15}([A-Za-z0-9]{3})?</stringValue>`: literals shaped like record Ids; ordinary 15- and 18-character words match too
- `<(apiVersion|runInMode|triggerOrder|status)>`: version, run mode, order, and activation
- `SystemModeWith(out)?Sharing`: elevated run contexts
- `\$Flow\.FaultMessage`: where raw fault text goes
- `<isInput>true</isInput>`: variables a caller can set
- `RecordAfterSave`: after-save flows; read their `<recordUpdates>` for filters on `$Record.Id`
- `<actionType>apex</actionType>`: Apex actions; `@InvocableMethod` (glob `*.cls`) finds the classes

Code Analyzer's flow engine is optional local analysis: run it only if it is already installed, only on trusted code (it applies the workspace's configuration), and only as [Tooling](platform.md#tooling) allows. Its rules map to this guide: `TriggerCallout`, `TriggerWaitEvent` ([Choosing the Flow Type](#choosing-the-flow-type)); `TriggerEntryCriteria`, `SameRecordUpdate` ([Entry Conditions & Recursion](#entry-conditions--recursion)); `DbInLoop` ([Bulk-Safe Design](#bulk-safe-design)); `MissingFaultHandler` ([Fault Handling](#fault-handling)); `PreventPassingUserDataIntoElementWithoutSharing` ([Run Context & Security](#run-context--security)); `HardcodedId` ([Org-Agnostic Values](#org-agnostic-values)); `DefaultCopy`, `MissingDescription`, `CyclicSubflow`, `MissingNextValueConnector`, `UnreachableElement`, `UnusedResource` ([Activation, Versions & Deployment](#activation-versions--deployment)). `MissingFaultHandler`, `MissingDescription`, `UnreachableElement`, and `UnusedResource` are outside `Recommended`; the `flow` selector includes them.

---

## Choosing the Flow Type

### Use before-save for same-record fields, and pick every other type deliberately

A before-save flow (Fast Field Updates) changes `$Record` in memory before the record is written: no DML statement, no second pass through the save order, the fastest declarative option. It can assign, decide, get records, loop, and raise a Custom Error, but can't touch other records, call actions or subflows, or use async and scheduled paths, and `$Record.Id` isn't assigned yet on create. Everything else needs another type, and the type decides the transaction, the running user, and how many records one run sees.

| Need | Build | XML signal | Review for |
|---|---|---|---|
| Change fields on the record being saved | Record-triggered, before-save | `RecordBeforeSave` | Only `$Record` changes |
| Related records, email, Apex actions | Record-triggered, after-save | `RecordAfterSave` | Bulk safety, fault paths, no same-record update |
| Callouts or slow work after the save | After-save with an async path | `<pathType>AsyncAfterCommit</pathType>` | Separate transaction; the record may have changed again |
| Work at a time relative to a date | After-save with a scheduled path | `<scheduledPaths>` with `<offsetNumber>` | Conditions still true when it runs |
| Act on a record before it is deleted | Record-triggered, before delete | `RecordBeforeDelete` | Bulk safety, fault paths |
| Guided input from a user | Screen flow | `<processType>Flow</processType>` | Run context, input validation |
| Logic called from Apex, REST, buttons, or other flows | Autolaunched, no trigger | `AutoLaunchedFlow` with no `<triggerType>` | The caller's context, input variables |
| Periodic work over a filtered set of records | Schedule-triggered | `Scheduled` with `<schedule>` | One interview per matching record |
| Handle integration events | Platform event-triggered | `PlatformEvent` | Own transaction, idempotent handling |

When the logic needs heavy branching, high volumes, or reuse from several entry points, Apex may fit better ([Salesforce Architecture](../architecture-review-guide.md#salesforce-architecture)).

### Move callouts and deferrable work to the async path or a scheduled path (Winter '22+)

The immediate path runs inside the transaction that saves the record, so every element slows each save and callouts aren't supported there (🔴 for a synchronous callout on the save path). The async path (`AsyncAfterCommit`) runs after the commit in its own transaction; a scheduled path runs later, relative to a date field or to the triggering event, and a negative `<offsetNumber>` runs before the field's value (`<offsetNumber>-3</offsetNumber>`, `<offsetUnit>Days</offsetUnit>`, `<recordField>Due_Date__c</recordField>`, `<timeSource>RecordField</timeSource>`: three days before the due date).

```xml
<!-- ❌ The start element's own <connector> leads to Send_Invoice_To_Erp, an Apex action that calls out -->

<!-- ✅ Inside <start> of a RecordAfterSave flow: the callout runs on the async path after the commit -->
<scheduledPaths>
    <name>Sync_To_Erp</name>
    <connector><targetReference>Send_Invoice_To_Erp</targetReference></connector>
    <pathType>AsyncAfterCommit</pathType>
</scheduledPaths>
```

### Don't add Workflow Rules or Process Builder processes (end of support Dec 31, 2025)

Both still run, but get no support or bug fixes after December 31, 2025. Build new automation as record-triggered flows, migrate existing rules and processes with the Migrate to Flow tool, and deactivate the old automation in the same release so nothing fires twice.

```xml
<!-- ❌ A new <rules> entry in workflows/Invoice__c.workflow-meta.xml, or a new Process Builder process: -->
<processType>Workflow</processType>
```

---

## Entry Conditions & Recursion

### Give record-triggered flows entry conditions

Without `<filters>` or a `<filterFormula>` on `<start>`, every save of every record starts an interview and spends the transaction's CPU time on records the flow ignores (🟡). For update triggers, `<doesRequireRecordChangedToMeetCriteria>true</doesRequireRecordChangedToMeetCriteria>` ("Only when a record is updated to meet the condition requirements") runs the flow on the transition, not on every later edit. Not a finding: a flow that must run on every save by design, such as a before-save flow that normalizes or stamps every record, when its `<description>` says so.

```xml
<!-- ✅ Evaluated on create, and on update only when the record changes to match -->
<start>
    <connector><targetReference>Create_Review_Task</targetReference></connector>
    <doesRequireRecordChangedToMeetCriteria>true</doesRequireRecordChangedToMeetCriteria>
    <filterLogic>and</filterLogic>
    <filters><field>Status__c</field><operator>EqualTo</operator><value><stringValue>Approved</stringValue></value></filters>
    <object>Invoice__c</object>
    <recordTriggerType>CreateAndUpdate</recordTriggerType>
    <triggerType>RecordAfterSave</triggerType>
</start>
```

### Detect real changes with $Record__Prior or ISCHANGED() (Summer '21+)

A Decision that checks only `$Record.Status__c` is true on every later edit of an approved record, so emails, tasks, and callouts repeat. Compare with `$Record__Prior` (null on create), or use `ISCHANGED()`, `ISNEW()`, and `PRIORVALUE()` in a formula entry condition.

```xml
<!-- ✅ Decision conditions: true only on the transition to Approved -->
<conditions><leftValueReference>$Record.Status__c</leftValueReference><operator>EqualTo</operator><rightValue><stringValue>Approved</stringValue></rightValue></conditions>
<conditions><leftValueReference>$Record__Prior.Status__c</leftValueReference><operator>NotEqualTo</operator><rightValue><stringValue>Approved</stringValue></rightValue></conditions>

<!-- ✅ The same intent as a formula entry condition on <start> -->
<filterFormula>AND(OR(ISNEW(), ISCHANGED({!$Record.Status__c})), ISPICKVAL({!$Record.Status__c}, &quot;Approved&quot;))</filterFormula>
```

### Don't update the triggering record from an after-save flow

Update Records on `$Record` in an after-save flow saves the record a second time, so before-save flows, triggers, validation rules, and the object's other automation run again. Set same-record fields in a before-save flow; when the value depends on work only after-save can do (the record Id, related records), guard the update with change-aware conditions.

```xml
<!-- ❌ After-save flow on Invoice__c: <recordUpdates> filtered on Id = $Record.Id sets Review_Required__c -->

<!-- ✅ Before-save flow: assign the field in memory, no second save -->
<assignmentItems>
    <assignToReference>$Record.Review_Required__c</assignToReference>
    <operator>Assign</operator>
    <value><booleanValue>true</booleanValue></value>
</assignmentItems>
```

### Order record-triggered flows and keep one owner per field (API 54.0+ / Spring '22)

Flows on the same object and timing run by `<triggerOrder>`: 1 to 1,000 ascending, then flows without a value by created date, then 1,001 to 2,000, with ties broken by API name; before-save and after-save flows are ordered separately. Apex sits outside that order (before-save flows run before Apex before triggers, after-save flows after Apex after triggers; see [Order of Execution](apex-triggers.md#order-of-execution)), and no order makes two writers of one field safe: give each field one automation owner (🟡 when the PR adds a second writer). A missing `<triggerOrder>` matters only when another record-triggered flow shares the object and timing (🟢); a flow alone there needs none.

```xml
<!-- ✅ Explicit order, and the description names the field this flow owns -->
<description>Owns Invoice__c.Status__c after save. Runs before Invoice_Notifications (order 300).</description>
<triggerOrder>200</triggerOrder>
```

---

## Bulk-Safe Design

Interviews of the same flow in one transaction are bulkified: when they reach the same Get, Create, Update, or Delete Records element or action, the platform runs it once for all of them. Inside a Loop that happens once per iteration: 200 interviews that each loop over 5 invoice lines run a Get Records on the loop body about 5 times, one batch per iteration, not 1,000 times. The count explodes when one interview loops over a large collection: an autolaunched flow that loops over 500 records from one Get Records issues 500 queries and fails at the transaction's SOQL limit. Show that math in the finding ([Governor Limits](platform.md#governor-limits)); when the count decides the severity, ask the author for a debug log.

> 📖 For the cross-language pattern, see [N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow).

### Keep Get, Create, Update, and Delete Records out of loops

Query before the loop, change records in memory inside it with Assignment (or Collection Filter, Collection Sort, and Transform), and write the collection once after it: the loop's `<noMoreValuesConnector>` leads to one Update Records. Per [Severity Calibration](platform.md#severity-calibration), a data element in a loop on a record-triggered or list path is 🔴, and 🟡 when the loop bound is small and fixed.

```xml
<!-- ❌ Each_Opportunity.nextValueConnector points at an Update Records element that connects back to the loop -->

<!-- ✅ The loop body only collects; one Update Records runs after the loop -->
<assignmentItems>
    <assignToReference>opportunitiesToUpdate</assignToReference>
    <operator>Add</operator>
    <value><elementReference>currentOpportunity</elementReference></value>
</assignmentItems>
<recordUpdates>
    <name>Update_Opportunities</name>
    <inputReference>opportunitiesToUpdate</inputReference>
</recordUpdates>
```

### Count the flow in the transaction's limits

A record-triggered flow runs in the transaction of the DML that fired it, together with Apex triggers, validation rules, roll-ups, and the object's other flows, all on one set of limits ([Governor Limits](platform.md#governor-limits)). If one interview hits a limit, every interview in the transaction fails and the whole save rolls back. At API 57.0+ there is no per-interview limit on executed elements, but CPU time still counts.

### Query only the rows and fields the flow needs

"Automatically store all fields" (`<storeOutputAutomatically>true</storeOutputAutomatically>` with no `<queriedFields>`) queries only the fields the flow references, except when the records go to a subflow or an Apex action: then every field is queried. Filter to the rows the flow uses, list `<queriedFields>`, fetch records for many parents in one element with `In`, and cap stored rows with `<limit>` (API 63.0+) when only some are needed; selectivity on large objects is in [Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes).

```xml
<!-- ❌ The same Get Records without queriedFields, feeding a subflow: every Contact field is queried -->

<!-- ✅ One query for all accounts' Contacts, and only the fields the subflow reads -->
<filters><field>AccountId</field><operator>In</operator><value><elementReference>accountIds</elementReference></value></filters>
<queriedFields>Id</queriedFields>
<queriedFields>Email</queriedFields>
```

---

## Fault Handling

Get, Create, Update, and Delete Records, actions, and Wait elements accept a `<faultConnector>`; Subflow elements don't, so a child flow handles its own faults.

> 📖 For cross-language principles, see [Error Handling Principles](../cross-cutting/error-handling-principles.md#core-principles).

### Connect a fault path where a failure needs handling

Without a fault path a failed element fails the interview: a screen user sees an unhandled-fault message, and a record-triggered flow fails the user's save with an error that names no business rule. Expect a `<faultConnector>` (🟡) on DML, actions, and callouts in screen flows, on integration paths, and wherever the flow must log the error or continue. Not a finding by itself: a Get Records without one, or DML in a record-triggered flow whose failure should block the save anyway, because an unhandled fault already rolls the save back (a Custom Error with a clear message is a 💡). Code Analyzer keeps `MissingFaultHandler` outside `Recommended` for the same reason.

```xml
<!-- ❌ The same element without <faultConnector> in a screen flow: a failed insert ends in an unhandled-fault screen -->

<!-- ✅ The fault path logs the error and decides what happens next -->
<recordCreates>
    <name>Create_Review_Task</name>
    <faultConnector><targetReference>Log_Flow_Error</targetReference></faultConnector>
    <inputReference>reviewTask</inputReference>
</recordCreates>
```

### Log $Flow.FaultMessage and show users a friendly message

`$Flow.FaultMessage` carries the raw platform error: object and field API names, validation text, sometimes record values. Write it to a log (a platform event whose `publishBehavior` is `PublishImmediately` survives a rollback; a record on a log object rolls back with the transaction) and show the user text they can act on, from a Custom Label. Raw fault text on a screen is 🟡 for internal users, one tier higher on guest or Experience Cloud screens, and one tier lower in admin-only tools, per the exposure rules in [Severity Calibration](platform.md#severity-calibration).

```xml
<!-- ❌ <fieldText>{!$Flow.FaultMessage}</fieldText> on a screen that portal users see -->

<!-- ✅ Log the detail (Create Records on a PublishImmediately event), then show a translated message -->
<inputAssignments><field>Message__c</field><value><elementReference>$Flow.FaultMessage</elementReference></value></inputAssignments>
<fieldText>&lt;p&gt;{!$Label.Invoice_Approval_Failed}&lt;/p&gt;</fieldText>
```

### Decide whether a fault path continues, rolls back, or blocks the save

A fault path handles the error, so the rest of the transaction carries on and commits, including the flow's earlier DML. In a record-triggered flow, end the fault path with a Custom Error when the work is essential, which blocks the save with your message; log and continue only when it is optional. A screen flow commits pending changes whenever it shows a screen, so run Roll Back Records (`<recordRollbacks>`, screen flows only, API 52.0+) before the error screen; it undoes only the current transaction, not work committed before an earlier screen.

```xml
<!-- ✅ Record-triggered flow: essential work failed, so block the save with a clear message -->
<customErrors>
    <name>Block_Save_On_Sync_Failure</name>
    <customErrorMessages>
        <errorMessage>The invoice could not be prepared for billing. Try again or contact your administrator.</errorMessage>
        <isFieldError>false</isFieldError>
    </customErrorMessages>
</customErrors>

<!-- ✅ Screen flow: undo this transaction's changes, then show the error screen -->
<recordRollbacks><name>Undo_Changes</name><connector><targetReference>Show_Error</targetReference></connector></recordRollbacks>
```

---

## Run Context & Security

Record-triggered, schedule-triggered, and platform event-triggered flows always run in system context without sharing. Only screen flows and autolaunched flows without a trigger choose a context, with `<runInMode>`:

- `DefaultMode` (or absent): how the flow is launched decides; a user who launches a screen flow gets user context.
- `SystemModeWithSharing`: record sharing is enforced; object permissions and field-level security are not.
- `SystemModeWithoutSharing` (API 49.0+): all data.
- `UserMode` (API 68.0+, "User Context—Enforces User Permissions"): the running user's object permissions, field-level security, and sharing, without inheriting the calling context.

Invocable Apex keeps its own class's sharing keyword and access mode whatever the flow's context ([Invocable Apex Contract](#invocable-apex-contract)); the matrix across Apex and flows is in [Security Model](platform.md#security-model).

### Justify the runInMode of every screen and autolaunched flow

The run mode decides whether object permissions, field-level security, and record sharing apply to the flow's data elements; system context without sharing turns every input into a way to read or change any record the flow touches (🟡 when unjustified, 🔴 when guest or Experience Cloud users reach it). Under `DefaultMode` the launch decides, so a system-context caller can run the flow in system context; prefer `UserMode` at API 68.0+ for flows that users, portals, or guests reach.

```xml
<!-- ❌ Screen flow used by portal users: reads and edits whatever Invoice__c the recordId names -->
<processType>Flow</processType>
<runInMode>SystemModeWithoutSharing</runInMode>

<!-- ✅ The running user's access applies however the flow is launched, and only users granted the flow can run it
     (below API 68.0, DefaultMode gives user context when a user launches the screen flow) -->
<isAdditionalPermissionRequiredToRun>true</isAdditionalPermissionRequiredToRun>
<processType>Flow</processType>
<runInMode>UserMode</runInMode>
```

When a flow really needs system context (a guest form that creates a record, say), ask for the reason in the flow's `<description>`, keep the elevated elements few and narrow, and never let them read or update records by caller-supplied Ids. In the always-system flow types, also check what the flow copies: a record-triggered flow that sums every invoice onto `Account.Invoice_Total__c` shows those totals to everyone who can read the Account, including users who can't open the invoices.

### Treat screen-flow inputs as untrusted on sites and for guests

An input variable can be set from URL parameters, Visualforce, the `lightning-flow` component, or a parent flow, so on an Experience Cloud page or for guest users `recordId` is attacker-controlled: re-check access in the flow and run in user context. Since the Restrict User Access to Run Flows release update (enforced in Winter '26), users without Run Flows or Manage Flow, such as guest, portal, and restricted internal users, run a screen or autolaunched flow only when a profile or permission set grants it (`flowAccesses`, see [Permission Sets, Groups & Profiles](metadata.md#permission-sets-groups--profiles)); `<isAdditionalPermissionRequiredToRun>true</isAdditionalPermissionRequiredToRun>` limits a flow to those grants even for users with Run Flows. Record-triggered and schedule-triggered flows need no grant.

```xml
<!-- ❌ recordId is an input (<isInput>true</isInput>), the flow runs SystemModeWithoutSharing, and Get_Invoice
     filters on Id alone: any site user can read any invoice by editing the URL -->

<!-- ✅ User context, and the lookup also requires the invoice to belong to the user's account -->
<filters><field>Id</field><operator>EqualTo</operator><value><elementReference>recordId</elementReference></value></filters>
<filters><field>Account__c</field><operator>EqualTo</operator><value><elementReference>$User.AccountId</elementReference></value></filters>
```

---

## Invocable Apex Contract

This section stands alone for a changed class with `@InvocableMethod`. One call receives the requests of every interview in the batch, one list element per interview: a record-triggered flow on a 200-record save sends up to 200 requests at once, and it runs in system context as the user whose save fired it. Severities default to [Severity Calibration](platform.md#severity-calibration); the general Apex rules apply too: thin entry points ([Class Design](apex.md#class-design)) and untrusted parameters ([Data Access Security](apex.md#data-access-security)).

### Take a list of requests and return one result per request, in order

The method is `static`, `public` or `global`, in an outer class, with at most one list parameter, and a class has at most one `@InvocableMethod`; the compiler enforces these. The flow matches results to interviews by position, so the returned list needs the size and order of the requests; a mismatch fails with "The number of results does not match the number of interviews that were executed in a single bulk execution request". Run one query or DML for the whole batch, and ask for tests that pass 200 or more requests, one of them failing ([Testing](apex.md#testing)). Give `@InvocableVariable` fields labels and descriptions (Flow Builder shows them to the admin), and `required=true` only on inputs the action can't run without: `required` is ignored on output variables, so its absence on a result class is not a finding. In a managed package, a released invocable method can't be removed in later versions, and only `global` ones appear in the subscriber org's Flow Builder ([Managed Packages](apex.md#managed-packages)).

```apex
// ❌ [SELECT Credit_Limit__c FROM Account WHERE Id = :requests[0].accountId] in a class with no sharing keyword:
//    only the first request, system mode below API 67.0, and one result for N requests

// ✅ One query for the batch; results[i] answers requests[i]; a missing record fails only its own request
Map<Id, Account> accountsById = new Map<Id, Account>(
    [SELECT Credit_Limit__c FROM Account WHERE Id IN :accountIds WITH USER_MODE]);
for (Request request : requests) {
    Account account = accountsById.get(request.accountId);
    Result result = new Result(); // @InvocableVariable fields: creditLimit, isSuccess, errorMessage
    result.isSuccess = account != null;
    result.creditLimit = account?.Credit_Limit__c;
    result.errorMessage = account == null ? 'Account not found or not accessible' : null;
    results.add(result);
}
```

### Fail in a way the flow can handle

An uncaught exception fails the whole call, so every interview in that batch takes its fault path (up to 200 saves in a record-triggered flow); that is right for unexpected errors. For expected per-request outcomes, such as a missing or inaccessible record or a request the business rules reject, return fields such as `isSuccess` and `errorMessage` and branch on them in the flow; never catch everything and return null. A method that catches after partial writes undoes them with a savepoint ([Transactions & Error Handling](apex.md#transactions--error-handling)).

```apex
// ❌ try { return DiscountService.apply(requests); } catch (Exception e) { return null; }
//    The flow continues as if the discount was applied
// ✅ A rejected request gets isSuccess = false and an errorMessage on its own result; unexpected exceptions propagate
```

### Set the class's sharing and access mode for its callers

The class's own sharing keyword, access mode, and `<apiVersion>` decide what it can read and write, not the flow's `<runInMode>`. At API 67.0+ a class without a keyword runs `with sharing` and its queries and DML run in user mode; below 67.0 they run in system mode ([Security Model](platform.md#security-model)). Where users reach the action (screen flows, Experience Cloud, guests), it needs sharing and user mode (🔴 without them). An action that record-triggered automation calls runs as the user who saved the record, so it may need explicit system mode (`WITH SYSTEM_MODE`, `AccessLevel.SYSTEM_MODE`) with a comment giving the reason; that is a design decision, not a finding. Flows don't need `classAccesses` for the classes they call: the release update that required it was retired (verify for guest and Experience Cloud users).

### Mark callouts and keep them out of the save transaction

A callout after DML in the same transaction throws "You have uncommitted work pending", and a record-triggered flow's immediate path runs inside the save transaction, so an action that calls out belongs on an async (`AsyncAfterCommit`) or scheduled path (🔴 on the immediate path). `callout=true` matters only in screen flows: when the action's Transaction Control lets the flow decide and there is uncommitted work, the flow commits and runs the action in a new transaction (`<flowTransactionModel>Automatic</flowTransactionModel>`); a non-screen flow always runs the action in the current transaction. A screen flow that calls the action after DML without `callout=true` fails like any callout after DML; anywhere else a missing `callout=true` is a 🟢. The callout itself follows [Callouts & Integrations](apex.md#callouts--integrations).

```apex
// ❌ The same method, wired to the immediate path of an after-save flow

// ✅ Declared as a callout, one request for the batch, called from an async path or a screen flow
@InvocableMethod(label='Send Invoices to ERP' description='Call from an async path or a screen flow' callout=true)
public static void send(List<Id> invoiceIds) {
    ErpClient.sendInvoices(new Set<Id>(invoiceIds)); // Named Credential, timeout, response checks
}
```

---

## Org-Agnostic Values

Record Ids, users, hosts, and business values differ between orgs and over time; the general rules are in [Org-Agnostic Code](platform.md#org-agnostic-code), and the choice between Custom Metadata, Custom Labels, and custom settings is in [Configuration Metadata](metadata.md#configuration-metadata).

### Look records up by DeveloperName instead of hard-coding Ids

A literal Id in a `<stringValue>` points at nothing, or at the wrong record, in every other org. Look queues, groups, and record types up by `DeveloperName` in one Get Records outside any loop, and compare `$Record.RecordType.DeveloperName` instead of `RecordTypeId`.

```xml
<!-- ❌ <value><stringValue>00G000000000000AAA</stringValue></value> assigned to $Record.OwnerId: a queue Id copied from one org -->

<!-- ✅ Get Records on Group by DeveloperName and Type, then assign Get_Review_Queue.Id to $Record.OwnerId -->
<filters><field>DeveloperName</field><operator>EqualTo</operator><value><stringValue>Invoice_Review</stringValue></value></filters>
<filters><field>Type</field><operator>EqualTo</operator><value><stringValue>Queue</stringValue></value></filters>
```

### Keep thresholds, recipients, and access checks out of flow literals

A profile name, username, email address, or threshold typed into a Decision or Assignment breaks on rename and needs a new flow version for every change. Use `$Permission` for "who may", a custom metadata type for values, `$Label` for user-facing text, and `$Setup` for hierarchy custom settings.

```xml
<!-- ❌ $Profile.Name compared with "Finance Manager" decides the path, and <stringValue>finance-team@example.com</stringValue>
     receives the alert -->

<!-- ✅ A custom permission decides who may; a Get Records on Invoice_Setting__mdt supplies the address -->
<conditions><leftValueReference>$Permission.Approve_Invoices</leftValueReference><operator>EqualTo</operator><rightValue><booleanValue>true</booleanValue></rightValue></conditions>
```

---

## Activation, Versions & Deployment

Each deployment of a changed flow creates a new flow version in the target org; the file's `<status>`, the org's settings, and any FlowDefinition decide which version runs. `<apiVersion>` defines how that version runs, so a bump that rides along with an unrelated edit changes behavior nobody reviewed: ask what it is for and check it against [API Versions](platform.md#api-versions) (for flows, API 57.0 removes the executed-elements limit and API 68.0 adds `UserMode`), and never block a flow for not using a newer version's features.

### Know what a deployment activates

By default, a flow that is active in the source arrives inactive in production. With "Deploy processes and flows as active" enabled (Process Automation Settings, production only), it arrives active, and Apex tests must launch at least 75% of the org's active processes and autolaunched flows (screen flows are exempt) or the deployment rolls back. Ask the author or CI which case applies and who activates the version.

| Target | `<status>` in the file | Result |
|---|---|---|
| Sandbox or scratch org | `Active` | The new version is active |
| Production, setting off (the default) | `Active` | The new version stays inactive until someone activates it |
| Production, setting on | `Active` | Active, if the Apex tests meet the 75% flow coverage gate |
| Any org | `Draft` | A new inactive version; the active version keeps running |

`<status>Draft</status>` or `Obsolete` doesn't switch a flow off. A FlowDefinition with `<activeVersionNumber>0</activeVersionNumber>` does, but its active version number overrides the flow's `<status>` whenever both deploy together, so a file left in source keeps pinning the flow; version numbers also differ between orgs, and Salesforce recommends an empty `flowDefinitions/` directory at API 44.0+. Flag a committed FlowDefinition (🟡) unless the PR is a one-off deactivation with `0` and the file leaves source afterward. A flow version can be deleted only when it is inactive and has no paused interviews ([Deployment Impact](metadata.md#deployment-impact)).

```xml
<!-- ✅ flowDefinitions/Invoice_After_Save.flowDefinition-meta.xml: deployed once to deactivate, then removed from source -->
<FlowDefinition xmlns="http://soap.sforce.com/2006/04/metadata">
    <activeVersionNumber>0</activeVersionNumber>
</FlowDefinition>
```

### Back the flow with Apex tests and flow tests

Only Apex tests count toward the flow coverage gate: ask for tests that insert or update 201 or more records meeting the entry conditions, so a second 200-record chunk runs, and a fault case ([Testing](apex.md#testing)). Flow tests (`flowtests/*.flowtest-meta.xml`) support record-triggered, autolaunched, and Data Cloud-triggered flows, not screen flows, and should assert outcomes.

```xml
<!-- ❌ A flow test whose Finish test point has no <assertions>: it passes whatever the flow does -->

<!-- ✅ The Finish test point asserts the result -->
<testPoints>
    <assertions>
        <conditions><leftValueReference>$Record.Review_Required__c</leftValueReference><operator>EqualTo</operator><rightValue><booleanValue>true</booleanValue></rightValue></conditions>
        <errorMessage>Approved invoices that need approval must be flagged for review.</errorMessage>
    </assertions>
    <elementApiName>Finish</elementApiName>
</testPoints>
```

### Treat API names and input and output variables as a contract

Subflows, Apex (`Flow.Interview`), LWC (`lightning-flow`), Visualforce, and flow tests refer to a flow and its variables by API name, and clearing `<isInput>` or `<isOutput>` breaks the pages and flows that set or read the variable: a finding when a caller in the repo still does. Keep names stable. Renaming pasted elements that keep their default names (`Copy_1_of_...`) and describing the flow and each element help the next reviewer: 🟢, and only when the repo already follows this.

```xml
<!-- ❌ <isInput>false</isInput> on a variable the invoiceActions LWC sets -->

<!-- ✅ A stable, described contract -->
<variables>
    <name>invoiceId</name>
    <dataType>String</dataType>
    <description>Invoice__c Id passed by the invoiceActions LWC and the Invoice_Resend subflow.</description>
    <isCollection>false</isCollection>
    <isInput>true</isInput>
    <isOutput>false</isOutput>
</variables>
```

---

## References

- [Flow (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_visual_workflow.htm)
- [Record-triggered flow considerations (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_considerations_trigger_record.htm&language=en_US&type=5)
- [Flow Bulkification in Transactions (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_concepts_bulkification.htm&language=en_US&type=5)
- [InvocableMethod Annotation (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_annotation_InvocableMethod.htm)
- [Deploy Processes and Flows as Active (Salesforce Help)](https://help.salesforce.com/s/articleView?id=sf.flow_distribute_deploy_active.htm&language=en_US&type=5)
