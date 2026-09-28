# Universal Code Quality Anti-Patterns

> Language-agnostic design smells worth a review comment, each with the exceptions that make it a false positive. Flag only what the diff introduces or makes worse; anything the repo's linter, formatter, or type checker enforces is not a finding. Default tier: 🟢 or 💡, raised to 🟡 or 🔴 only where a section says so.
> Related: [Salesforce Mapping](#salesforce-mapping) shows each pattern in Apex, LWC, and Flow.

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Reuse → [Code Reuse Review](#code-reuse-review)

- [ ] A new helper, hook, query, or utility doesn't duplicate one the repo already has.
- [ ] Not a finding: a local helper when the existing one has different semantics or would add a dependency.

### Signatures → [Parameter Sprawl](#parameter-sprawl)

- [ ] The diff doesn't grow a long positional signature with one more parameter or a boolean mode flag; an options object, dataclass, or keyword-only arguments fit better (🟢 or 💡).
- [ ] Not a finding: a parameter count on its own, or a signature fixed by a framework or an interface.

### Boundaries → [Leaky Abstractions](#leaky-abstractions)

- [ ] Raw external shapes (HTTP response bodies, another service's payload, file formats) are mapped at the edge instead of travelling into domain or UI code.
- [ ] Not a finding: returning ORM entities from a repository or service, the norm in Django, SQLAlchemy, and Rails code, unless the repo already maps to DTOs at that layer.

### Types and strings → [Stringly-Typed Code](#stringly-typed-code)

- [ ] New status, role, and event-name literals use the enum, union type, or constant that already exists for them.

### Control flow → [Nested Conditionals](#nested-conditionals)

- [ ] Nesting or chained ternaries that the diff adds can be flattened with guard clauses, early returns, or a lookup keyed by an enum. Readability is the test; depth numbers and lint rules (`no-nested-ternary`, `max-depth`) are not findings.

### Duplication → [Copy-Paste Variants](#copy-paste-variants)

- [ ] The diff doesn't add a third near-copy of a non-trivial block, or a second copy of logic that must stay in sync (validation, pricing, permissions); that second case is 🟡.
- [ ] Not a finding: two short, similar functions.

### Writes and state → [No-Op Updates](#no-op-updates) · [Redundant State](#redundant-state)

- [ ] Writes that trigger side effects (Salesforce DML, webhooks, cache invalidation, state setters that re-render) skip unchanged values.
- [ ] Commits happen once per unit of work, not once per row.
- [ ] A new stored field that can be derived has a reason (query speed, history) and is updated on every write path.

### Races → [TOCTOU Race Conditions](#toctou-race-conditions)

- [ ] Check-then-act on shared state (files, rows, balances, "claim" flags) is atomic: an exclusive-create flag, a conditional `UPDATE`, a unique constraint, or a row lock. An in-process lock doesn't protect state shared by several processes. 🟡, or 🔴 when the race can lose money or data.
- [ ] Not a finding: an existence check whose race is harmless because the later operation fails cleanly and is handled.

### Data volume → [Overly Broad Operations](#overly-broad-operations)

- [ ] Filtering, lookups, and limits happen in the query or API call, not after loading everything into memory.

### Salesforce → [Salesforce Mapping](#salesforce-mapping)

- [ ] Each pattern above is also checked in its Salesforce form.

---

## Code Reuse Review

Before accepting a new helper, search for an existing one with the Grep tool: the new function's name and its core call (for example `setTimeout\(` for a hand-written debounce, `os\.path\.join\(` for a path builder) in `utils/`, `shared/`, `lib/`, `common/`, and the files next to the change. Name the existing helper's path in the finding. Prefer the repo's own helper to a new dependency, and a well-known library the repo already uses to a hand-written copy.

## Parameter Sprawl

Suggest one request or options object when the diff grows a signature: a TypeScript interface, a Python dataclass or keyword-only arguments, an Apex request class with `@AuraEnabled` or `@InvocableVariable` fields. A boolean that switches behavior (`render(data, true)`) reads better as two functions or an enum. There is no count threshold, and a long signature the diff only calls is not a finding.

## Leaky Abstractions

A leak forces callers to know an implementation detail: a component that indexes `apiResponse.data.results[0]`, a domain function that returns an HTTP client's response, a module that exposes its cache's internal map. Map external shapes once, at the edge. Where services return ORM entities everywhere, one more is consistent, not leaky.

## Stringly-Typed Code

A typo in a raw string (`emitter.on("usercreated", ...)` for `"userCreated"`) fails silently at run time. Where no enum, union type, or constant exists yet, suggest one only when the diff spreads the same literal across several files. Keys built by concatenation (`` `${a}-${b}` ``) are the same smell and lose exhaustiveness checking.

## Nested Conditionals

Flatten what the diff adds: guard clauses and early returns for preconditions, a lookup table or `match`/`switch` over an enum for value mapping. Two booleans selecting one of four values are often clearest as a short nested ternary or an `if` chain; replacing them with a map keyed by `` `${isHovered}-${isSelected}` `` trades readability for stringly-typed keys.

## Copy-Paste Variants

Two short look-alike functions that may diverge are cheaper than the wrong abstraction; parameterize at the third copy, or at the second copy of logic that must change in step (validation, pricing, permission checks, error mapping).

## No-Op Updates

A write with no net change still costs a round trip, and sometimes much more: Salesforce DML fires triggers, flows, and validation rules and uses limits ([Apex: Bulkification](salesforce/apex.md#bulkification)); Django `save()` rewrites every column; webhooks and state setters notify every subscriber. Compare with the current value and skip unchanged records.

```python
# ❌ One commit per row: N round trips, no atomicity, and with SQLAlchemy's default
#    expire_on_commit every later row is reloaded with its own SELECT
for item in items:
    item.status = compute_status(item)
    session.commit()

# ✅ One unit of work, one commit (SQLAlchemy's flush already skips unchanged values)
for item in items:
    item.status = compute_status(item)
session.commit()
```

## TOCTOU Race Conditions

Time-of-check-to-time-of-use: the state changes between the check and the action. Make the check part of the action.

```python
from sqlalchemy import update

# ❌ Check-then-act on a shared row: two requests can both pass the check and both debit
account = session.get(Account, account_id)
if account.balance >= amount:
    account.balance -= amount
    session.commit()

# ✅ One conditional UPDATE: the database checks and writes atomically
result = session.execute(
    update(Account)
    .where(Account.id == account_id, Account.balance >= amount)
    .values(balance=Account.balance - amount)
)
if result.rowcount == 0:
    raise InsufficientFundsError(account_id)  # or the account does not exist
session.commit()
```

```typescript
import { writeFile } from 'node:fs/promises';

// ❌ Another process can create the file between the check and the write
if (!existsSync(path)) {
    await writeFile(path, content);
}

// ✅ Exclusive create: the OS refuses the write when the file already exists
async function writeOnce(path: string, content: string): Promise<boolean> {
    try {
        await writeFile(path, content, { flag: 'wx' });
        return true;
    } catch (err: unknown) {
        if (err instanceof Error && 'code' in err && err.code === 'EEXIST') return false;
        throw err;
    }
}
```

An in-process lock (`threading.Lock`, a JavaScript mutex) serializes one process only; web apps with several workers or instances need the database or the filesystem to arbitrate. An existence check before `open()` is only worth a comment when the race changes behavior; otherwise open the file and handle `FileNotFoundError`.

## Overly Broad Operations

Push filters, lookups, and limits down to the storage layer: `session.get(User, user_id)` instead of loading every row and searching in Python, `WHERE status = ?` instead of `.filter()` after `SELECT`, `readline()` instead of reading a whole file for one line, and the API's `limit` and cursor instead of every page.

## Redundant State

A stored copy of derivable data (`fullName` beside `firstName` and `lastName`, `item_count` beside `items`) goes stale unless every write path updates it. Prefer a computed property; a stored copy that serves queries or history is fine when the diff updates it everywhere. Sum money as `Decimal` or integer minor units, never binary floats.

---

## Salesforce Mapping

The same anti-patterns in Salesforce code and metadata. The linked guides hold the rules and examples.

| Anti-pattern | Salesforce form | Guide |
|---|---|---|
| Code reuse | A new test-data helper, trigger dispatcher, query, logger, or LWC error parser written next to the existing `TestDataFactory`, trigger handler framework, selectors, logger, or `reduceErrors` | [Apex: Class Design](salesforce/apex.md#class-design) |
| Parameter sprawl | `@AuraEnabled` methods that take a growing list of primitives, or invocable methods that pack values into delimited strings, instead of one request class (with `@InvocableVariable` fields for Flow) | [Flows: Invocable Apex Contract](salesforce/flows.md#invocable-apex-contract) |
| Leaky abstractions | Controllers that return raw sObjects with every queried field, `Database.SaveResult`, or raw exception text to LWC instead of a response DTO and a user-safe error | [LWC: The LWC-Apex Contract](salesforce/lwc.md#the-lwc-apex-contract) |
| Stringly-typed code | `record.get('Field__c')` and field names in strings instead of `Schema.SObjectField` tokens in Apex or `@salesforce/schema` imports in LWC | [Apex: Language Pitfalls](salesforce/apex.md#language-pitfalls) · [LWC: Data Access](salesforce/lwc.md#data-access) |
| No-op updates | DML on records whose values did not change, which still fires triggers, flows, and validation rules and uses up limits | [Apex: Bulkification](salesforce/apex.md#bulkification) |
| TOCTOU race conditions | Query-then-update without `FOR UPDATE`, so two concurrent transactions (for example, two Queueable jobs) overwrite each other's changes | [Apex: Async Apex](salesforce/apex.md#async-apex) |
| Overly broad operations | `FIELDS(STANDARD)` in Apex or `FIELDS(ALL)` in API queries when the code reads a few fields; queries with no selective filter on large objects; flow Get Records elements that store all fields | [SOQL & SOSL: Selectivity & Large Data Volumes](salesforce/soql-sosl.md#selectivity--large-data-volumes) |
| Redundant state | Trigger-maintained copies of values that a formula or roll-up summary field could derive | [Metadata: Objects & Fields](salesforce/metadata.md#objects--fields) |
