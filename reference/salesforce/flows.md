# Salesforce Flow Code Review Guide

Review guidance for flows in source format (`flows/*.flow-meta.xml`): record-triggered (before-save, after-save, before-delete), screen, autolaunched, schedule-triggered, and platform event-triggered flows, plus the invocable Apex they call. Current for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs; judge each flow against its own `<apiVersion>`.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
> Related: [Apex](apex.md) · [Order of execution](apex-triggers.md#order-of-execution) · [Deployment impact](metadata.md#deployment-impact)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Reading a Flow Diff](#reading-a-flow-diff)
- [Choosing the Flow Type](#choosing-the-flow-type)
- [Entry Conditions & Recursion](#entry-conditions--recursion)
- [Bulk-Safe Design](#bulk-safe-design)
- [Fault Handling](#fault-handling)
- [Run Context & Security](#run-context--security)
- [Invocable Apex Contract](#invocable-apex-contract)
- [Org-Agnostic Values](#org-agnostic-values)
- [Activation, Versions & Deployment](#activation-versions--deployment)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| `flows/*.flow-meta.xml` (any flow type) | This guide |
| Apex class with `@InvocableMethod` | [Invocable Apex Contract](#invocable-apex-contract) + [Apex](apex.md) |
| A flow and an Apex trigger on the same object | This guide + [Order of Execution](apex-triggers.md#order-of-execution) |
| `flowtests/*.flowtest-meta.xml`, `flowDefinitions/*.flowDefinition-meta.xml` | [Activation, Versions & Deployment](#activation-versions--deployment) |
| `workflows/*.workflow-meta.xml`, or a `<processType>` of `Workflow`, `CustomEvent`, or `InvocableProcess` (Process Builder) | [Choosing the Flow Type](#choosing-the-flow-type) |
| `flowAccesses` in permission sets, or `classAccesses` for invocable classes | [Permission Sets, Groups & Profiles](metadata.md#permission-sets-groups--profiles) |
| A screen flow on an Experience Cloud page or reachable by guest users | [Run Context & Security](#run-context--security) + [Security Model](platform.md#security-model) |

Review flow XML as statically as Apex: ask the author or CI for flow test and Apex test results instead of activating or debugging anything in an org ([Static Review Only](platform.md#static-review-only)), and rate findings with [Severity Calibration](platform.md#severity-calibration).

---

## Reading a Flow Diff

Flow Builder writes elements grouped by type (all `<assignments>`, then `<decisions>`, and so on), not in execution order, and at API 64.0+ auto-layout flows save `<locationX>` and `<locationY>` as 0. Skip layout churn and follow the connectors. The examples are excerpts without `<label>`, layout, and `<processMetadataValues>` elements.

### Read the landmarks before the details

These elements say what starts the flow, how it runs, and what it touches.

| Element | Tells you | Check |
|---|---|---|
| `<apiVersion>` | The version that defines the flow's runtime behavior | A change is a behavior change ([Activation, Versions & Deployment](#activation-versions--deployment)) |
| `<processType>` | `AutoLaunchedFlow` (record-triggered, scheduled, platform event, or no trigger), `Flow` (screen flow); `Workflow`, `CustomEvent`, `InvocableProcess` are Process Builder | No new legacy types |
| `<start>`: `<object>`, `<triggerType>`, `<recordTriggerType>` | `RecordBeforeSave`, `RecordAfterSave`, `RecordBeforeDelete`, `Scheduled`, `PlatformEvent`; `Create`, `Update`, `CreateAndUpdate`, `Delete`. No `<triggerType>`: a user, Apex, or another flow launches it | The type fits the job |
| `<start>`: `<filters>`, `<filterLogic>`, `<filterFormula>`, `<doesRequireRecordChangedToMeetCriteria>` | Entry conditions | Present, and change-aware for updates |
| `<start>`: `<scheduledPaths>`, `<schedule>` | The async path (`<pathType>AsyncAfterCommit</pathType>`), scheduled paths (`<offsetNumber>`, `<offsetUnit>`, `<timeSource>`), a schedule-triggered flow's frequency | Callouts and deferrable work live here |
| `<triggerOrder>` | Run order among record-triggered flows on the object (1 to 2,000, API 54.0+) | Set, and consistent with the object's other flows |
| `<runInMode>` | Run context of screen and autolaunched flows | Justified ([Run Context & Security](#run-context--security)) |
| `<status>` | `Active`, `Draft`, `Obsolete`, `InvalidDraft`, `UnderReview` | What the deployment activates |
| `<recordLookups>`, `<recordCreates>`, `<recordUpdates>`, `<recordDeletes>` | Get, Create, Update, and Delete Records: each is a query or a DML statement | Outside loops, filtered, with a `<faultConnector>` |
| `<loops>` | `<collectionReference>`, `<nextValueConnector>` (the body), `<noMoreValuesConnector>` (after the loop) | What sits on the body path |
| `<actionCalls>`, `<subflows>` | Actions (`<actionType>` such as `apex`, `emailAlert`, or `flow`, with `<actionName>`) and subflows (`<flowName>`) | Their queries and DML count as the flow's own |
| `<variables>` with `<isInput>true</isInput>` | Values a caller sets: URL parameters, Visualforce, the `lightning-flow` component, a parent flow | Untrusted input in screen flows |

### Trace loop bodies through their connectors

An element runs once per item when the path from the loop's `<nextValueConnector>` reaches it and leads back to the loop; elements after `<noMoreValuesConnector>` run once. Follow the `<targetReference>` values by hand, into subflows called from the body too.

```text
❌ Each_Opportunity.nextValueConnector -> Set_Priority -> Update_Opportunity -> back to Each_Opportunity
   Update_Opportunity sits on the loop body: one DML statement per Opportunity

✅ Each_Opportunity.nextValueConnector -> Set_Priority -> back to Each_Opportunity
   Each_Opportunity.noMoreValuesConnector -> Update_Opportunities (one DML statement for the collection)
```

### Scan the changed flows locally

Grep the changed files before reading them element by element, and run Code Analyzer's flow engine (Flow Scanner) only as [Tooling](platform.md#tooling) allows: already installed, local paths, no org. Its rules are named in the sections below; `MissingFaultHandler`, `MissingDescription`, `UnreachableElement`, and `UnusedResource` are outside `Recommended`, so add the engine-scoped `flow` selector to include them (it runs locally, like every engine except ApexGuru).

```bash
# Read-only: the flows changed on this branch
git diff --name-only --diff-filter=d origin/main...HEAD -- '*.flow-meta.xml'

# Literals that look like 15- or 18-character record Ids, then version, run mode, order, and status
git diff --name-only --diff-filter=d origin/main...HEAD -- '*.flow-meta.xml' \
  | xargs grep -nE '<stringValue>[A-Za-z0-9]{15}([A-Za-z0-9]{3})?</stringValue>|<(apiVersion|runInMode|triggerOrder|status)>'

# Local only: the flow engine needs Python 3.10+ and never contacts an org
sf code-analyzer run --workspace force-app --rule-selector Recommended --rule-selector flow --view table \
  --target force-app/main/default/flows/Invoice_After_Save.flow-meta.xml
```

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

The immediate path runs inside the transaction that saves the record, so every element slows each save and callouts aren't supported there. The async path (`AsyncAfterCommit`) runs after the commit in its own transaction; a scheduled path runs later, relative to a date field or to the triggering event.

```xml
<!-- ❌ The start element's own <connector> leads to Send_Invoice_To_Erp, an Apex action that calls out -->

<!-- ✅ No immediate path; the callout runs on the async path after the commit -->
<start>
    <doesRequireRecordChangedToMeetCriteria>true</doesRequireRecordChangedToMeetCriteria>
    <filters><field>Status__c</field><operator>EqualTo</operator><value><stringValue>Approved</stringValue></value></filters>
    <object>Invoice__c</object>
    <recordTriggerType>Update</recordTriggerType>
    <scheduledPaths>
        <name>Sync_To_Erp</name>
        <connector><targetReference>Send_Invoice_To_Erp</targetReference></connector>
        <label>Sync to ERP</label>
        <pathType>AsyncAfterCommit</pathType>
    </scheduledPaths>
    <triggerType>RecordAfterSave</triggerType>
</start>

<!-- ✅ A scheduled path three days before the due date (a negative offset runs before the field's value) -->
<scheduledPaths>
    <name>Three_Days_Before_Due</name>
    <connector><targetReference>Create_Reminder_Task</targetReference></connector>
    <label>Three Days Before Due</label>
    <offsetNumber>-3</offsetNumber>
    <offsetUnit>Days</offsetUnit>
    <recordField>Due_Date__c</recordField>
    <timeSource>RecordField</timeSource>
</scheduledPaths>
```

Static analysis: Code Analyzer flow engine `TriggerCallout`, `TriggerWaitEvent`.

### Don't add Workflow Rules or Process Builder processes (end of support Dec 31, 2025)

Both still run, but get no support or bug fixes after December 31, 2025. Build new automation as record-triggered flows, migrate existing rules and processes with the Migrate to Flow tool, and deactivate the old automation in the same release so nothing fires twice.

```xml
<!-- ❌ A new workflow rule (workflows/Invoice__c.workflow-meta.xml) -->
<rules>
    <fullName>Flag_Approved_Invoices</fullName>
    <active>true</active>
    <criteriaItems><field>Invoice__c.Status__c</field><operation>equals</operation><value>Approved</value></criteriaItems>
    <triggerType>onCreateOrTriggeringUpdate</triggerType>
</rules>

<!-- ❌ ...or a Process Builder process -->
<processType>Workflow</processType>
```

---

## Entry Conditions & Recursion

### Give every record-triggered flow entry conditions

Without `<filters>` or a `<filterFormula>` on `<start>`, every save of every record starts an interview and spends the transaction's limits on records the flow ignores. For update triggers, `<doesRequireRecordChangedToMeetCriteria>true</doesRequireRecordChangedToMeetCriteria>` ("Only when a record is updated to meet the condition requirements") runs the flow on the transition, not on every later edit.

```xml
<!-- ❌ The same start element without <filters>: every insert and edit of every Invoice__c starts an interview -->

<!-- ✅ Conditions on the start element, evaluated only when an update makes the record match -->
<start>
    <connector><targetReference>Create_Review_Task</targetReference></connector>
    <doesRequireRecordChangedToMeetCriteria>true</doesRequireRecordChangedToMeetCriteria>
    <filterLogic>and</filterLogic>
    <filters><field>Status__c</field><operator>EqualTo</operator><value><stringValue>Approved</stringValue></value></filters>
    <filters><field>Review_Required__c</field><operator>EqualTo</operator><value><booleanValue>true</booleanValue></value></filters>
    <object>Invoice__c</object>
    <recordTriggerType>CreateAndUpdate</recordTriggerType>
    <triggerType>RecordAfterSave</triggerType>
</start>
```

Static analysis: Code Analyzer flow engine `TriggerEntryCriteria`.

### Detect real changes with $Record__Prior or ISCHANGED() (Summer '21+)

A Decision that checks only `$Record.Status__c` is true on every later edit of an approved record, so emails, tasks, and callouts repeat. Compare with `$Record__Prior` (null on create), or use `ISCHANGED()`, `ISNEW()`, and `PRIORVALUE()` in a formula entry condition.

```xml
<!-- ❌ A Decision outcome with only the first condition: true on every edit of an approved invoice -->

<!-- ✅ True only on the transition to Approved -->
<rules>
    <name>Became_Approved</name>
    <conditionLogic>and</conditionLogic>
    <conditions><leftValueReference>$Record.Status__c</leftValueReference><operator>EqualTo</operator><rightValue><stringValue>Approved</stringValue></rightValue></conditions>
    <conditions><leftValueReference>$Record__Prior.Status__c</leftValueReference><operator>NotEqualTo</operator><rightValue><stringValue>Approved</stringValue></rightValue></conditions>
    <connector><targetReference>Create_Review_Task</targetReference></connector>
</rules>

<!-- ✅ The same intent as a formula entry condition on <start> -->
<filterFormula>AND(OR(ISNEW(), ISCHANGED({!$Record.Status__c})), ISPICKVAL({!$Record.Status__c}, &quot;Approved&quot;))</filterFormula>
```

### Don't update the triggering record from an after-save flow

Update Records on `$Record` in an after-save flow saves the record a second time, so before-save flows, triggers, validation rules, and the object's other automation run again. Set same-record fields in a before-save flow; if the value depends on work only after-save can do, guard the update with change-aware conditions.

```xml
<!-- ❌ After-save flow on Invoice__c updates the invoice that fired it -->
<recordUpdates>
    <name>Set_Review_Flag</name>
    <filters><field>Id</field><operator>EqualTo</operator><value><elementReference>$Record.Id</elementReference></value></filters>
    <inputAssignments><field>Review_Required__c</field><value><booleanValue>true</booleanValue></value></inputAssignments>
    <object>Invoice__c</object>
</recordUpdates>

<!-- ✅ Before-save flow: assign the field in memory, no second save -->
<assignments>
    <name>Set_Review_Flag</name>
    <assignmentItems>
        <assignToReference>$Record.Review_Required__c</assignToReference>
        <operator>Assign</operator>
        <value><booleanValue>true</booleanValue></value>
    </assignmentItems>
</assignments>
```

Static analysis: Code Analyzer flow engine `SameRecordUpdate`.

### Order record-triggered flows and keep one owner per field (API 54.0+ / Spring '22)

Flows on the same object and timing run by `<triggerOrder>`: 1 to 1,000 ascending, then flows without a value by created date, then 1,001 to 2,000, with ties broken by API name; before-save and after-save flows are ordered separately. Apex sits outside that order (before-save flows run before Apex before triggers, after-save flows after Apex after triggers; see [Order of Execution](apex-triggers.md#order-of-execution)), and no order makes two writers of one field safe: give each field one automation owner.

```xml
<!-- ❌ A second after-save flow writing Status__c with no triggerOrder: it runs between 1,000 and 1,001
     by created date, and whichever flow runs last wins -->

<!-- ✅ Explicit order, and the description names the field this flow owns -->
<description>Owns Invoice__c.Status__c after save. Runs before Invoice_Notifications (order 300).</description>
<status>Active</status>
<triggerOrder>200</triggerOrder>
```

---

## Bulk-Safe Design

Interviews of the same flow in one transaction are bulkified: when they reach the same Get, Create, Update, or Delete Records element or action, the platform runs it once for all of them. An element inside a Loop runs once per iteration instead.

> 📖 For the cross-language pattern, see [N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow).

### Keep Get, Create, Update, and Delete Records out of loops

Query before the loop, change records in memory inside it with Assignment (or Collection Filter, Collection Sort, and Transform), and write the collection once after it.

```xml
<!-- ❌ Each_Opportunity.nextValueConnector points at an Update Records element that connects back to the loop:
     one DML statement per Opportunity -->

<!-- ✅ In memory inside the loop, one Update Records after it
     (currentOpportunity and opportunitiesToUpdate: an Opportunity record variable and record collection) -->
<loops>
    <name>Each_Opportunity</name>
    <assignNextValueToReference>currentOpportunity</assignNextValueToReference>
    <collectionReference>Get_Open_Opportunities</collectionReference>
    <iterationOrder>Asc</iterationOrder>
    <nextValueConnector><targetReference>Collect_Opportunity</targetReference></nextValueConnector>
    <noMoreValuesConnector><targetReference>Update_Opportunities</targetReference></noMoreValuesConnector>
</loops>
<assignments>
    <name>Collect_Opportunity</name>
    <assignmentItems>
        <assignToReference>currentOpportunity.Priority__c</assignToReference>
        <operator>Assign</operator>
        <value><stringValue>High</stringValue></value>
    </assignmentItems>
    <assignmentItems>
        <assignToReference>opportunitiesToUpdate</assignToReference>
        <operator>Add</operator>
        <value><elementReference>currentOpportunity</elementReference></value>
    </assignmentItems>
    <connector><targetReference>Each_Opportunity</targetReference></connector>
</assignments>
<recordUpdates>
    <name>Update_Opportunities</name>
    <faultConnector><targetReference>Log_Flow_Error</targetReference></faultConnector>
    <inputReference>opportunitiesToUpdate</inputReference>
</recordUpdates>
```

Static analysis: Code Analyzer flow engine `DbInLoop`.

### Count the flow in the transaction's limits

A record-triggered flow runs in the transaction of the DML that fired it, together with Apex triggers, validation rules, roll-ups, and the object's other flows, and all of them draw on one set of per-transaction limits ([Governor Limits](platform.md#governor-limits)). If one interview hits a limit, every interview in the transaction fails and the whole save rolls back.

```text
❌ A Get Records inside a loop over each invoice's lines, in a flow on Invoice__c: one query per line
   per interview, so a 200-invoice update from an integration asks for hundreds of queries,
   the 101st throws, and all 200 saves roll back

✅ One Get Records before the loop (with In on a collection of Ids when several parents are involved):
   the 200 interviews share one query at that element. At API 57.0+ there is no per-interview limit
   on executed elements, but CPU time still counts
```

### Query only the rows and fields the flow needs

"Automatically store all fields" (`<storeOutputAutomatically>true</storeOutputAutomatically>` with no `<queriedFields>`) queries only the fields the flow references, except when the records go to a subflow or an Apex action: then every field is queried. Filter to the rows the flow uses, list `<queriedFields>`, and fetch records for many parents in one element with `In`; selectivity on large objects is in [Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes).

```xml
<!-- ❌ The same element without the second filter and without queriedFields: the subflow gets every field -->

<!-- ✅ One query for all accounts' reachable Contacts, and only the fields the subflow reads -->
<recordLookups>
    <name>Get_Contacts</name>
    <filterLogic>and</filterLogic>
    <filters><field>AccountId</field><operator>In</operator><value><elementReference>accountIds</elementReference></value></filters>
    <filters><field>HasOptedOutOfEmail</field><operator>EqualTo</operator><value><booleanValue>false</booleanValue></value></filters>
    <getFirstRecordOnly>false</getFirstRecordOnly>
    <object>Contact</object>
    <queriedFields>Id</queriedFields>
    <queriedFields>Email</queriedFields>
    <storeOutputAutomatically>true</storeOutputAutomatically>
</recordLookups>
```

---

## Fault Handling

Get, Create, Update, and Delete Records, actions, and Wait elements accept a `<faultConnector>`; Subflow elements don't, so a child flow handles its own faults.

> 📖 For cross-language principles, see [Error Handling Principles](../cross-cutting/error-handling-principles.md#core-principles).

### Connect a fault path to every data element and action

Without a fault path a failed element fails the interview: a screen user sees an unhandled-fault message, and a record-triggered flow fails the user's save with an error that names no business rule. A fault path lets the flow log the error and choose what happens next.

```xml
<!-- ❌ The same element without <faultConnector>: a failed insert fails the interview and, in a
     record-triggered flow, the save -->

<!-- ✅ The fault path logs the error and decides what happens next -->
<recordCreates>
    <name>Create_Review_Task</name>
    <faultConnector><targetReference>Log_Flow_Error</targetReference></faultConnector>
    <inputReference>reviewTask</inputReference>
</recordCreates>
```

Static analysis: Code Analyzer flow engine `MissingFaultHandler` (not in `Recommended`).

### Log $Flow.FaultMessage and show users a friendly message

`$Flow.FaultMessage` carries the raw platform error: object and field API names, validation text, sometimes record values. Write it to a log (a platform event whose `publishBehavior` is `PublishImmediately` survives a rollback; a record on a log object rolls back with the transaction) and show the user text they can act on, from a Custom Label.

```xml
<!-- ❌ <fieldText>{!$Flow.FaultMessage}</fieldText> on a screen: the raw error goes to the user -->

<!-- ✅ Publish the detail to a log event, then show a translated, friendly message -->
<recordCreates>
    <name>Log_Flow_Error</name>
    <connector><targetReference>Show_Error</targetReference></connector>
    <inputAssignments><field>Flow_Name__c</field><value><stringValue>Invoice_Approval</stringValue></value></inputAssignments>
    <inputAssignments><field>Message__c</field><value><elementReference>$Flow.FaultMessage</elementReference></value></inputAssignments>
    <object>Flow_Error__e</object>
</recordCreates>
<fields>
    <name>Error_Text</name>
    <fieldText>&lt;p&gt;{!$Label.Invoice_Approval_Failed}&lt;/p&gt;</fieldText>
    <fieldType>DisplayText</fieldType>
</fields>
```

### Decide whether a fault path continues, rolls back, or blocks the save

A fault path handles the error, so the rest of the transaction carries on and commits, including the flow's earlier DML. In a record-triggered flow, end the fault path with a Custom Error when the work is essential, which blocks the save with your message; log and continue only when it is optional. A screen flow commits pending changes whenever it shows a screen, so run Roll Back Records (`<recordRollbacks>`, API 52.0+) before the error screen; it undoes only the current transaction, not work committed before an earlier screen.

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
<recordRollbacks>
    <name>Undo_Changes</name>
    <connector><targetReference>Show_Error</targetReference></connector>
</recordRollbacks>
```

---

## Run Context & Security

Record-triggered, schedule-triggered, and platform event-triggered flows always run in system context without sharing; only screen flows and autolaunched flows without a trigger choose a context, with `<runInMode>`. Invocable Apex keeps its own class's sharing keyword and access mode whatever the flow's context ([Invocable Apex Contract](#invocable-apex-contract)). The matrix across Apex and flows is in [Security Model](platform.md#security-model).

### Justify the runInMode of every screen and autolaunched flow

The run mode decides whether object permissions, field-level security, and record sharing apply to the flow's data elements; system context without sharing turns every input into a way to read or change any record the flow touches.

| `<runInMode>` | Flow Builder label | Object and field permissions | Record sharing |
|---|---|---|---|
| `DefaultMode` or absent | User or System Context—Depends on How Flow is Launched | Depend on the launch: a user running a screen flow gets user context | Same |
| `SystemModeWithSharing` | System Context with Sharing—Enforces Record-Level Access | Not enforced | Enforced |
| `SystemModeWithoutSharing` (API 49.0+) | System Context without Sharing—Access All Data | Not enforced | Not enforced |
| Added in Winter '27 (API 68.0+) | User Context–Enforces User Permissions | Enforced, even when the caller runs in system context | Enforced |

```xml
<!-- ❌ Screen flow used by portal users: reads and edits whatever Invoice__c the recordId names -->
<processType>Flow</processType>
<runInMode>SystemModeWithoutSharing</runInMode>

<!-- ✅ The launching user's access applies, and only users granted the flow can run it -->
<isAdditionalPermissionRequiredToRun>true</isAdditionalPermissionRequiredToRun>
<processType>Flow</processType>
<runInMode>DefaultMode</runInMode>
```

When a flow really needs system context (a guest form that creates a record, say), ask for the reason in the flow's `<description>`, keep the elevated elements few and narrow, and never let them read or update records by caller-supplied Ids. In the always-system flow types, also check what the flow copies: a record-triggered flow that sums every invoice onto `Account.Invoice_Total__c` shows those totals to everyone who can read the Account, including users who can't open the invoices.

### Treat screen-flow inputs as untrusted on sites and for guests

An input variable can be set from URL parameters, Visualforce, the `lightning-flow` component, or a parent flow, so on an Experience Cloud page or for guest users `recordId` is attacker-controlled. Re-check access in the flow, run in user context, and grant the flow through `flowAccesses` with `<isAdditionalPermissionRequiredToRun>true</isAdditionalPermissionRequiredToRun>`.

```xml
<!-- ❌ recordId is an input (<isInput>true</isInput>), the flow runs SystemModeWithoutSharing, and Get_Invoice
     filters on Id alone: any site user can read any invoice by editing the URL -->

<!-- ✅ User context, and the lookup also requires the invoice to belong to the user's account -->
<recordLookups>
    <name>Get_Invoice</name>
    <filterLogic>and</filterLogic>
    <filters><field>Id</field><operator>EqualTo</operator><value><elementReference>recordId</elementReference></value></filters>
    <filters><field>Account__c</field><operator>EqualTo</operator><value><elementReference>$User.AccountId</elementReference></value></filters>
    <getFirstRecordOnly>true</getFirstRecordOnly>
    <object>Invoice__c</object>
    <queriedFields>Id</queriedFields>
    <queriedFields>Status__c</queriedFields>
    <storeOutputAutomatically>true</storeOutputAutomatically>
</recordLookups>
<runInMode>DefaultMode</runInMode>
```

Static analysis: Code Analyzer flow engine `PreventPassingUserDataIntoElementWithoutSharing`.

---

## Invocable Apex Contract

One `@InvocableMethod` call receives the requests of every interview in the batch, one list element per interview ([Governor Limits](platform.md#governor-limits)). The class's own sharing keyword, access mode, and `<apiVersion>` decide what it can read and write, not the flow's `<runInMode>` ([Security Model](platform.md#security-model)), and the general Apex rules apply: thin entry points ([Class Design](apex.md#class-design)) and untrusted parameters ([Data Access Security](apex.md#data-access-security)).

### Take a list of requests and return one result per request, in order

The flow matches results to interviews by position, so the returned list needs the size and order of the requests; a mismatch fails with "The number of results does not match the number of interviews that were executed in a single bulk execution request". Use request and result classes whose `@InvocableVariable` fields carry labels, descriptions, and `required=true` (Flow Builder shows them to the admin), and run one query or DML for the whole batch.

```apex
// ❌ [SELECT Credit_Limit__c FROM Account WHERE Id = :accountIds[0]] in a class with no sharing keyword:
//    only the first request, system mode below API 67.0, and one result for N requests

// ✅ Bulk, user mode, typed and described, one result per request in request order
public with sharing class AccountCreditCheckAction {
    public class Request {
        @InvocableVariable(label='Account ID' description='Account to check' required=true)
        public Id accountId;
    }

    public class Result {
        @InvocableVariable(label='Credit Limit' description='Credit_Limit__c of the account')
        public Decimal creditLimit;
    }

    public class CreditCheckException extends Exception {}

    @InvocableMethod(label='Check Account Credit' description='Credit data per request, in request order')
    public static List<Result> check(List<Request> requests) {
        Set<Id> accountIds = new Set<Id>();
        for (Request request : requests) {
            accountIds.add(request.accountId);
        }
        Map<Id, Account> accountsById = new Map<Id, Account>(
            [SELECT Id, Credit_Limit__c FROM Account WHERE Id IN :accountIds WITH USER_MODE]
        );

        List<Result> results = new List<Result>();
        for (Request request : requests) {
            Account account = accountsById.get(request.accountId);
            if (account == null) {
                // ✅ Fails the call so the flow's fault path runs, instead of a silent null
                throw new CreditCheckException('Account not found or not accessible: ' + request.accountId);
            }
            Result result = new Result();
            result.creditLimit = account.Credit_Limit__c;
            results.add(result);
        }
        return results;
    }
}
```

### Fail in a way the flow can handle

An uncaught exception fails the whole call, so every interview in that batch takes its fault path; that is right for unexpected errors. For expected per-request outcomes (a request the business rules reject), return explicit fields such as `isSuccess` and `errorMessage` and branch on them in the flow; never catch everything and return null. A method that catches after partial writes undoes them with a savepoint ([Transactions & Error Handling](apex.md#transactions--error-handling)).

```apex
// ❌ try { return DiscountService.apply(requests); } catch (Exception e) { return null; }
//    The flow continues as if the discount was applied

// ✅ Rule failures come back per request (isSuccess, errorMessage); unexpected exceptions reach the fault path
public with sharing class ApplyDiscountAction {
    @InvocableMethod(label='Apply Discount' description='One result per request; unexpected errors fail the call')
    public static List<DiscountService.Result> apply(List<DiscountService.Request> requests) {
        return DiscountService.apply(requests); // validates each request and writes in user mode
    }
}
```

### Mark callouts and keep them out of the save transaction

A callout after DML in the same transaction throws "You have uncommitted work pending", and a record-triggered flow's immediate path doesn't support callouts. Set `callout=true` on methods that call out, so Flow knows when it decides whether to run the action in a new transaction (`<flowTransactionModel>`), and call them from an async or scheduled path; the callout itself follows [Callouts & Integrations](apex.md#callouts--integrations).

```apex
// ❌ The same method without callout=true, wired to the immediate path of an after-save flow

// ✅ Declared as a callout, one request for the batch, called from the flow's AsyncAfterCommit path
public with sharing class ErpSyncAction {
    @InvocableMethod(label='Send Invoices to ERP' description='Call from an async path only' callout=true)
    public static void send(List<Id> invoiceIds) {
        ErpClient.sendInvoices(new Set<Id>(invoiceIds)); // Named Credential, timeout, response checks
    }
}
```

---

## Org-Agnostic Values

Record Ids, users, hosts, and business values differ between orgs and over time; the general rules are in [Org-Agnostic Code](platform.md#org-agnostic-code), and the choice between Custom Metadata, Custom Labels, and custom settings is in [Configuration Metadata](metadata.md#configuration-metadata).

### Look records up by DeveloperName instead of hard-coding Ids

A literal Id in a `<stringValue>` points at nothing, or at the wrong record, in every other org. Look queues, groups, and record types up by `DeveloperName` in one Get Records outside any loop, and compare `$Record.RecordType.DeveloperName` instead of `RecordTypeId`.

```xml
<!-- ❌ <value><stringValue>00G000000000000AAA</stringValue></value> assigned to $Record.OwnerId: a queue Id copied from one org -->

<!-- ✅ Resolve the queue by DeveloperName, then assign its Id -->
<recordLookups>
    <name>Get_Review_Queue</name>
    <filterLogic>and</filterLogic>
    <filters><field>DeveloperName</field><operator>EqualTo</operator><value><stringValue>Invoice_Review</stringValue></value></filters>
    <filters><field>Type</field><operator>EqualTo</operator><value><stringValue>Queue</stringValue></value></filters>
    <getFirstRecordOnly>true</getFirstRecordOnly>
    <object>Group</object>
    <queriedFields>Id</queriedFields>
    <storeOutputAutomatically>true</storeOutputAutomatically>
</recordLookups>
<assignmentItems>
    <assignToReference>$Record.OwnerId</assignToReference>
    <operator>Assign</operator>
    <value><elementReference>Get_Review_Queue.Id</elementReference></value>
</assignmentItems>
```

Static analysis: Code Analyzer flow engine `HardcodedId`.

### Keep thresholds, recipients, and access checks out of flow literals

A profile name, username, email address, or threshold typed into a Decision or Assignment breaks on rename and needs a new flow version for every change. Use `$Permission` for "who may", a custom metadata type for values, `$Label` for user-facing text, and `$Setup` for hierarchy custom settings.

```xml
<!-- ❌ A profile name decides the path, and a literal address receives the alert -->
<conditions><leftValueReference>$Profile.Name</leftValueReference><operator>EqualTo</operator><rightValue><stringValue>Finance Manager</stringValue></rightValue></conditions>
<inputAssignments><field>Notify_Email__c</field><value><stringValue>finance-team@example.com</stringValue></value></inputAssignments>

<!-- ✅ A custom permission decides who may; a custom metadata record holds the value -->
<conditions><leftValueReference>$Permission.Approve_Invoices</leftValueReference><operator>EqualTo</operator><rightValue><booleanValue>true</booleanValue></rightValue></conditions>
<recordLookups>
    <name>Get_Invoice_Settings</name>
    <filters><field>DeveloperName</field><operator>EqualTo</operator><value><stringValue>Default</stringValue></value></filters>
    <getFirstRecordOnly>true</getFirstRecordOnly>
    <object>Invoice_Setting__mdt</object>
    <queriedFields>Notify_Email__c</queriedFields>
    <storeOutputAutomatically>true</storeOutputAutomatically>
</recordLookups>
```

---

## Activation, Versions & Deployment

Each deployment of a changed flow creates a new flow version in the target org; the file's `<status>` and the org's settings decide which version runs. `<apiVersion>` defines how that version runs, so a bump that rides along with an unrelated edit changes behavior nobody reviewed: ask what it is for and check it against [API Versions](platform.md#api-versions) (for flows, API 57.0 removes the executed-elements limit and API 68.0 adds the user-context run mode), and never block a flow for not using a newer version's features.

### Know what a deployment activates

By default, a flow that is active in the source arrives inactive in production. With "Deploy processes and flows as active" enabled (Process Automation Settings, production only), it arrives active, and Apex tests must cover at least 75% of the org's active autolaunched flows and processes (screen flows are exempt) or the deployment rolls back. Ask the author or CI which case applies and who activates the version.

| Target | `<status>` in the file | Result |
|---|---|---|
| Sandbox or scratch org | `Active` | The new version is active |
| Production, setting off (the default) | `Active` | The new version stays inactive until someone activates it |
| Production, setting on | `Active` | Active, if Apex tests cover at least 75% of active autolaunched flows and processes |
| Any org | `Draft` | A new inactive version; the active version keeps running |

```xml
<!-- ❌ <status>Draft</status> to switch the flow off: it only adds an inactive version -->

<!-- ✅ flowDefinitions/Invoice_After_Save.flowDefinition-meta.xml deactivates the flow on deploy
     (confirm that the pipeline deploys FlowDefinition before relying on it) -->
<FlowDefinition xmlns="http://soap.sforce.com/2006/04/metadata">
    <activeVersionNumber>0</activeVersionNumber>
</FlowDefinition>
```

### Back the flow with Apex tests and flow tests

Only Apex tests count toward the flow coverage gate: ask for tests that insert or update records meeting the entry conditions, including a 200-record case and a fault case ([Testing](apex.md#testing)). Flow tests (`flowtests/*.flowtest-meta.xml`) support record-triggered, autolaunched, and Data Cloud-triggered flows, not screen flows, and should assert outcomes.

```xml
<!-- ✅ flowtests/Invoice_Review_Flag.flowtest-meta.xml asserts the result, not just that the flow ran -->
<FlowTest xmlns="http://soap.sforce.com/2006/04/metadata">
    <flowApiName>Invoice_Before_Save</flowApiName>
    <label>Approved invoice is flagged for review</label>
    <testPoints>
        <elementApiName>Start</elementApiName>
        <parameters>
            <leftValueReference>$Record</leftValueReference>
            <type>InputTriggeringRecordInitial</type>
            <value><sobjectValue>{&quot;Status__c&quot;:&quot;Approved&quot;,&quot;Needs_Approval__c&quot;:true}</sobjectValue></value>
        </parameters>
    </testPoints>
    <testPoints>
        <assertions>
            <conditions><leftValueReference>$Record.Review_Required__c</leftValueReference><operator>EqualTo</operator><rightValue><booleanValue>true</booleanValue></rightValue></conditions>
            <errorMessage>Approved invoices that need approval must be flagged for review.</errorMessage>
        </assertions>
        <elementApiName>Finish</elementApiName>
    </testPoints>
</FlowTest>
```

### Treat API names and input and output variables as a contract

Subflows, Apex (`Flow.Interview`), LWC (`lightning-flow`), Visualforce, and flow tests refer to a flow and its variables by API name, and clearing `<isInput>` or `<isOutput>` breaks the pages and flows that set or read the variable. Keep names stable, rename pasted elements that keep their default names (`Copy_1_of_...`), and describe the flow and each element for the next reviewer.

```xml
<!-- ❌ <isInput>false</isInput> on a variable the invoiceActions LWC sets, and an element named
     Copy_1_of_Update_Records with no description -->

<!-- ✅ A stable, described contract (elements get a meaningful <name> and a <description> too) -->
<variables>
    <name>invoiceId</name>
    <dataType>String</dataType>
    <description>Invoice__c Id passed by the invoiceActions LWC and the Invoice_Resend subflow.</description>
    <isCollection>false</isCollection>
    <isInput>true</isInput>
    <isOutput>false</isOutput>
</variables>
```

Static analysis: Code Analyzer flow engine `DefaultCopy`, `MissingDescription` (not in `Recommended`), `CyclicSubflow`, `MissingNextValueConnector`.

---

## Review Checklist

### Type & triggering
- [ ] The flow type fits the job: before-save for same-record fields, after-save for related records and actions, async or scheduled paths for callouts and deferrable work
- [ ] Record-triggered flows have entry conditions; update triggers use `doesRequireRecordChangedToMeetCriteria` or explicit change checks (`$Record__Prior`, `ISCHANGED()`)
- [ ] No after-save update of the triggering record; `<triggerOrder>` is set and each field has one automation owner
- [ ] No new Workflow Rules or Process Builder processes; migrated automation is deactivated in the same release

### Bulk
- [ ] No Get, Create, Update, or Delete Records, and no actions or subflows that query or write, on a loop body
- [ ] Get Records filter to the rows needed and list `queriedFields` when records go to subflows or Apex
- [ ] The flow's queries and DML were counted for a 200-record save together with the object's triggers and other flows

### Faults
- [ ] Every Get, Create, Update, and Delete Records element and every action has a `<faultConnector>`
- [ ] `$Flow.FaultMessage` is logged, never shown to end users
- [ ] Each fault path deliberately continues, rolls back (screen flows), or blocks the save (Custom Error)

### Security context
- [ ] `<runInMode>` on screen and autolaunched flows is justified; `SystemModeWithoutSharing` is narrow and explained in the description
- [ ] Screen-flow inputs are treated as untrusted; site and guest flows run in user context or re-check access, and sensitive flows set `isAdditionalPermissionRequiredToRun`
- [ ] System-context flows don't copy restricted data into widely readable fields

### Invocables
- [ ] `@InvocableMethod` takes a list of requests and returns one result per request, in order, with one query or DML for the batch
- [ ] Request and result classes use `@InvocableVariable` with labels, descriptions, and `required`
- [ ] Unexpected failures throw so the fault path runs; expected outcomes come back as explicit fields; no silent nulls
- [ ] The class declares its sharing keyword, uses user-mode data access, and sets `callout=true` when it calls out

### Deployment
- [ ] The PR says how the version gets activated in production and which Apex tests cover the flow
- [ ] Flow tests (where the flow type supports them) assert outcomes; Apex tests include a 200-record case
- [ ] An `apiVersion` change is intentional; API names and input and output variables are unchanged or their callers are updated
- [ ] No hard-coded Ids, profile names, usernames, or addresses; the flow and its elements have descriptions

---

## References

- [Flow (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_visual_workflow.htm)
- [FlowTest (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_flowtest.htm)
- [FlowDefinition (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_flowdefinition.htm)
- [Record-triggered flow considerations (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_considerations_trigger_record.htm&language=en_US&type=5)
- [Run order of record-triggered flows (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_task_trigger_run_order.htm&language=en_US&type=5)
- [Scheduled Paths (Salesforce Help)](https://help.salesforce.com/s/articleView?language=en_US&id=platform.flow_concepts_trigger_scheduled_path.htm&type=5)
- [Flow Bulkification in Transactions (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_concepts_bulkification.htm&language=en_US&type=5)
- [How Flows Run in Transactions (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_concepts_transaction.htm&language=en_US&type=5)
- [Per-transaction flow limits (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_considerations_limit_transaction.htm&language=en_US&type=5)
- [Flow run context (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_distribute_context.htm&language=en_US&type=5)
- [Set a flow's run context (Salesforce Help)](https://help.salesforce.com/s/articleView?language=en_US&id=platform.flow_distribute_system_mode.htm&type=5)
- [Global Variables Resource (Salesforce Help)](https://help.salesforce.com/s/articleView?language=en_US&id=platform.flow_ref_resources_global_variables.htm&type=5)
- [Flow best practices (Salesforce Help)](https://help.salesforce.com/s/articleView?id=sf.flow_prep_bestpractices.htm&language=en_US&type=5)
- [Deploy Processes and Flows as Active (Salesforce Help)](https://help.salesforce.com/s/articleView?id=sf.flow_distribute_deploy_active.htm&language=en_US&type=5)
- [Workflow Rules and Process Builder end of support (Salesforce Help)](https://help.salesforce.com/s/articleView?id=001096524&language=en_US&type=1)
- [Migrate to Flow tool (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_migrate_to_flow.htm&language=en_US&type=5)
- [Record-Triggered Automation decision guide (Salesforce Architects)](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered)
- [InvocableMethod Annotation (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_annotation_InvocableMethod.htm)
- [InvocableVariable Annotation (Apex Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_annotation_InvocableVariable.htm)
- [Flow rules (Salesforce Code Analyzer)](https://developer.salesforce.com/docs/platform/salesforce-code-analyzer/guide/rules-flow.html)
- [Flow engine rule catalog (GitHub, forcedotcom/code-analyzer-core)](https://github.com/forcedotcom/code-analyzer-core/blob/dev/packages/code-analyzer-flow-engine/src/hardcoded-catalog.ts)
