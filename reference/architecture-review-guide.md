# Architecture Review Guide

> Whether a change fits the design it lands in: responsibilities, dependency direction, abstractions, public contracts, and, on Salesforce, layering and automation ownership. Review the design the diff introduces; existing structure is not a finding unless the change makes it worse.
> Related: smaller design smells in [Universal Quality](code-quality-universal.md) · Salesforce tiers in [Severity Calibration](salesforce/platform.md#severity-calibration)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Responsibilities → [Responsibilities and Boundaries](#responsibilities-and-boundaries)

- [ ] The diff doesn't give an existing unit a new, unrelated responsibility (a controller that starts pricing orders, a repository that sends email). Judge what the code does, not its name or size: `Handler`, `Manager`, and `Service` are ordinary names, and line or method counts are not findings.
- [ ] New files follow the layout the repo already uses (feature folders, layer folders, or the Salesforce DX metadata-type folders). Asking a PR to reorganize directories is out of scope.
- [ ] Business rules the diff adds live where the repo keeps business rules, not in controllers, UI components, or trigger bodies.

### Dependencies → [Dependency Direction](#dependency-direction)

- [ ] Core or domain modules don't start importing infrastructure (database drivers, HTTP clients, framework request objects) where the repo keeps them apart.
- [ ] No new import cycle: for each new import, check with the Grep tool whether the imported module already imports the importer, directly or through a shared index file.
- [ ] Values that differ per environment or change without a release (endpoints, credentials, business thresholds) aren't hard-coded; a secret in code is 🔴.

### Abstractions → [Abstractions and Extension Points](#abstractions-and-extension-points)

- [ ] A new interface, strategy, factory, or plugin point has a present use: a second implementation, a test double, or a boundary the repo already draws. An interface with one implementation is fine when it serves one of these.
- [ ] Code that calls an external service can be replaced in tests (an injected client, an interface, or a module mock); flag it only when the diff makes a unit untestable.
- [ ] No speculative generality: options, layers, or hooks "for later" that nothing uses.
- [ ] A `switch` over types or statuses is fine when it is exhaustive over a union or enum; suggest polymorphism (💡) only when the diff pastes the same switch into a third place.

### Contracts → [Public Contracts](#public-contracts)

- [ ] Changes to exported APIs, events, message schemas, database schemas, and managed-package `global` members stay backward compatible, or come with a migration path and a version note.

### Salesforce → [Salesforce Architecture](#salesforce-architecture)

- [ ] Triggers only delegate; handlers pass collections to services; services don't read `Trigger.new` or `Trigger.oldMap`.
- [ ] One automation owner per object and field: a trigger, a record-triggered flow, and a legacy workflow rule don't all write the same field.
- [ ] Record Ids, org URLs, usernames, and endpoints come from Custom Metadata, Custom Labels, or Named Credentials.
- [ ] New `global` members in a released managed package are intended.
- [ ] Platform-event and CDC subscribers are idempotent and don't rely on the publisher's user or sharing.

### Severity → [Severity Calibration](salesforce/platform.md#severity-calibration)

- [ ] Salesforce findings take the tier of the calibration row that covers them, adjusted as that table says: logic in a trigger body or a second trigger is row 15 (🟡), hard-coded Ids, URLs, and usernames row 13 (🟡; 🔴 in authorization logic), a new released `global` member row 18 (🔴), a secret row 8 (🔴).
- [ ] Elsewhere: 🔴 for a broken public contract or a secret in code; 🟡 for structure that will cost the next change (a new import cycle, core code importing infrastructure, a second owner for a field); 🟢 or 💡 for the rest.

---

## Responsibilities and Boundaries

A responsibility is a reason to change: pricing rules, persistence, presentation, and notification change for different reasons and on different schedules. A finding names the responsibility the diff adds and where that kind of code lives in this repo ("`orders.controller.ts` now computes discounts; the other discount rules live in `pricing.service.ts`").

Not findings: names that frameworks and patterns prescribe (NestJS `*Service` and `*Controller`, Salesforce `*TriggerHandler`, `I`-prefixed interfaces in fflib-style Apex such as `fflib_ISObjectUnitOfWork`), the size of a file that was already large, and a folder convention the repo follows consistently. When a large unit keeps growing, mention it once as 🟢, naming the responsibility the diff added.

## Dependency Direction

Dependencies point from policy to mechanism: business rules don't import drivers, HTTP clients, or framework request objects; adapters at the edge do, and hand the core plain data or an interface the core declares. Apply this where the repo already separates the layers: a `domain/` or `core/` package, a hexagonal layout, or layer rules in dependency-cruiser, madge, or import-linter configuration, which then define the layers. In a small service without that split, a handler that queries the database directly is normal.

A new import that closes a cycle (A → B → A, directly or through a shared index file) makes initialization order fragile and blocks splitting the modules later ([JavaScript: Modules](javascript.md#modules)); name both edges in the finding.

## Abstractions and Extension Points

- An abstraction earns its place with a second implementation, a test double, or a boundary the repo already uses; otherwise it is indirection the next reader must follow (YAGNI). A missing seam and a needless one are both 🟢 or 💡 unless the diff makes code untestable or ties the core to a vendor.
- Patterns fit problems: Strategy for behavior chosen at run time, Factory when the concrete type is decided at run time, Observer for one-to-many notification. A Strategy, a Factory, and a Registry around one `if` is over-engineering; the same `switch` pasted into a third place is a missing abstraction.
- Extension points (hooks, events, plugins) are for behavior that varies by deployment or customer; hard-coding the one behavior the product has is fine.

## Public Contracts

A public contract is anything another team, service, or subscriber compiles or calls against: exported functions and types, REST and GraphQL schemas, events and message payloads, database schemas, and managed-package `global` members. Removing or renaming a member, narrowing an accepted value, or changing a default breaks callers the diff doesn't show. Ask for a migration path (a deprecation period, a versioned endpoint, an expand-then-contract schema change) and a changelog or version note. On Salesforce, released `global` members are permanent ([Package boundaries](#package-boundaries-and-public-apis)).

---

## Salesforce Architecture

Apex shares each transaction with declarative automation (flows, validation rules, roll-up summaries), so architecture review on Salesforce is also about who owns which behavior. Load the [Salesforce Platform Guide](salesforce/platform.md) for governor limits and the security model; the rules below cover structure.

### Layering: trigger → handler → service → selector

Each layer has one reason to change. The service takes collections instead of reading `Trigger.new`, so triggers, LWC controllers, invocable actions, and Batch jobs can all reuse it.

```text
AccountTrigger                  one trigger per object, no logic: delegates to the handler
  → AccountTriggerHandler       routes by context (before/after, insert/update), passes collections
    → AccountService            business rules, bulk-safe, explicit sharing keyword
      → AccountSelector         all SOQL for the object in one place, user mode by default
```

Red flags: SOQL, DML, or branching logic in the trigger body ([Severity Calibration](salesforce/platform.md#severity-calibration) row 15: 🟡); a service that reads `Trigger.new` or `Trigger.oldMap` directly; the same query copied into several services and controllers; `@AuraEnabled` methods that implement business rules instead of calling the service. Apply the selector layer only when the repo already uses one.

Static analysis: PMD `AvoidLogicInTrigger`.

> 📖 Depth: [Trigger Architecture](salesforce/apex-triggers.md#trigger-architecture) · [Class Design](salesforce/apex.md#class-design)

### Choosing Flow vs Apex

Both can own record-triggered automation. Decide per requirement, write the decision down, and do not split one requirement across both.

| Factor | Prefer Flow | Prefer Apex |
|---|---|---|
| Declarative fit | Field updates, record creation, notifications, guided screens | Complex data structures, reusable libraries, custom handling of callout errors |
| Bulk volume | Moderate volumes, with data elements kept outside loops | High volumes, Batch or Queueable processing, fine-grained control of limits |
| Complexity | Few branches and simple formulas | Many branches, heavy transformations, savepoints and partial-success handling |
| Testability | Flow tests in Flow Builder, plus Apex tests that exercise the flow | Unit tests with bulk data, mocks, and asserts |
| Who maintains it | Admins who own the business process | Developers, through code review and CI |

Updates to the triggering record's own fields belong in a before-save flow or a before trigger; a before-save update avoids a second DML and the recursive save. Salesforce's [record-triggered automation decision guide](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered) compares the options in depth, and [Choosing the Flow Type](salesforce/flows.md#choosing-the-flow-type) covers the flow side.

### One automation owner per object and field

- Multiple Apex triggers on the same object and event run in no guaranteed order, while before-save flows, triggers, and after-save flows each run at a fixed step of the save ([Order of Execution](salesforce/apex-triggers.md#order-of-execution)). When several of them write the same field, the final value depends on that order, not on a design.
- Keep one trigger per object and name one owner for each field. Salesforce's architects advise against mixing Apex triggers and record-triggered flows as entry points on the same object.
- When several record-triggered flows on one object are unavoidable, give each an explicit Trigger Order (Spring '22+).
- Migrate Workflow Rules and Process Builder (end of support Dec 31, 2025). A workflow field update saves the record again and re-fires the update triggers, which surprises code written for a single pass.

### Configuration over code

- Keep values that differ between orgs, or that change without a release, out of Apex and flow logic: Custom Metadata Types for deployable settings and mappings (querying them does not count against the SOQL query limit), Custom Labels for user-facing text and translations, and Named Credentials with External Credentials for endpoints and authentication.
- Red flags: hard-coded record Ids, user or profile names, endpoint URLs, email addresses, and business thresholds ([Org-Agnostic Code](salesforce/platform.md#org-agnostic-code); Ids, URLs, and usernames are row 13 of [Severity Calibration](salesforce/platform.md#severity-calibration)).
- Do not overdo it: a setting that nobody will ever change is only indirection, so YAGNI applies here too.

> 📖 Depth: [Configuration Metadata](salesforce/metadata.md#configuration-metadata)

### Package boundaries and public APIs

- In a managed package, `global` is a permanent contract: once a version is released, global classes and method signatures cannot be removed or changed, only deprecated. Default to `public`, and make something `global` only when subscribers must call it (PMD `AvoidGlobalModifier`; row 18 of [Severity Calibration](salesforce/platform.md#severity-calibration)).
- `@NamespaceAccessible` shares `public` Apex with other packages in the same namespace without making it `global`.
- Unlocked and second-generation managed packages declare their dependencies in `sfdx-project.json`. Keep the graph one-directional (a base package never depends on a package built on top of it), and route cross-package calls through a small, documented service class so a package can change its internals without breaking its dependents.

> 📖 Depth: [Managed Packages](salesforce/apex.md#managed-packages)

### Event-driven integration

- Platform Events decouple publishers from subscribers (Apex triggers, flows, and external clients). Use Publish After Commit for events that describe committed data, so a rolled-back transaction does not announce work that never happened; Publish Immediately suits events that must be sent even if the transaction rolls back, such as error logging.
- Change Data Capture streams record changes to subscribers without custom triggers or polling.
- Subscribers must be idempotent: a trigger that throws `EventBus.RetryableException` receives the batch again, and replays redeliver events, so key each change on a business key or check the current state before writing.
- Platform event and Change Data Capture triggers run asynchronously, in batches, and by default as the Automated Process user (a platform event trigger can run as another user through `PlatformEventSubscriberConfig`), so never rely on the publisher's user or sharing context.

> 📖 Depth: [Platform Event and CDC Triggers](salesforce/apex-triggers.md#platform-event-and-cdc-triggers) · [Callouts & Integrations](salesforce/apex.md#callouts--integrations)

---

## References

- [Record-Triggered Automation decision guide (Salesforce Architects)](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered)
- [Triggers and Order of Execution (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers_order_of_execution.htm)
- [NamespaceAccessible Annotation (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_annotation_NamespaceAccessible.htm)
