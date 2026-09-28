# Common Bugs Checklist

Quick-reference bug patterns organized by category. For detailed code examples, explanations, and comprehensive review checklists, see the dedicated language guides linked below.

## Universal Issues

### Logic Errors
- [ ] Off-by-one errors in loops and array access
- [ ] Incorrect boolean logic (De Morgan's law violations)
- [ ] Missing null/undefined checks
- [ ] Race conditions in concurrent code
- [ ] Incorrect comparison operators (`==` vs `===`, `=` vs `==`)
- [ ] Integer overflow/underflow
- [ ] Floating point comparison issues

### Resource Management
- [ ] Memory leaks (unclosed connections, listeners)
- [ ] File handles not closed
- [ ] Database connections not released
- [ ] Event listeners not removed
- [ ] Timers/intervals not cleared

### Error Handling
- [ ] Swallowed exceptions (empty catch blocks)
- [ ] Generic exception handling hiding specific errors
- [ ] Missing error propagation
- [ ] Incorrect error types thrown
- [ ] Missing finally/cleanup blocks

## JavaScript

- [ ] `==` instead of `===` (`'' == 0` and `'0' == false` are both `true`)
- [ ] `||` defaults where `0`, `''`, or `false` are valid values (`count || 10` turns `0` into `10`; use `??`)
- [ ] Missing `await` or floating promises (errors surface later as unhandled rejections, or never)
- [ ] `async` callbacks in `forEach` (not awaited) or `filter` (a Promise is always truthy); use `for...of` or `Promise.all(items.map(...))`
- [ ] `fetch` assumed to reject on HTTP errors (it resolves on 4xx/5xx; check `response.ok`)
- [ ] Methods passed as callbacks lose `this` (`setTimeout(this.save, 0)`; bind them or use an arrow function)
- [ ] `var` in a loop captured by closures (every callback sees the last value; use `let`)
- [ ] `parseInt` without a radix (`parseInt('0x1f')` is `31`; pass `10` or use `Number()`)
- [ ] `sort()` on numbers without a comparator (`[10, 9, 1].sort()` gives `[1, 10, 9]`), or in-place `sort()`/`reverse()` on a shared array (use `toSorted()`/`toReversed()`)
- [ ] Removing array elements while iterating (`splice` inside `forEach` or an index loop skips elements)
- [ ] Binary floats for money (`0.1 + 0.2 !== 0.3`; use integer minor units or a decimal library)
- [ ] `new Date('2024-01-02')` parses as UTC midnight while `new Date('2024-01-02T00:00')` is local time (off-by-one-day dates)
- [ ] `JSON.parse` on external input without `try`/`catch` and shape validation
- [ ] Deep merge or `obj[key] = value` with untrusted keys (`__proto__`, `constructor`, `prototype`) polluting `Object.prototype`

**Full guide:** [JavaScript Guide](javascript.md)

## TypeScript

- [ ] `any` in signatures, casts, or `JSON.parse` results turns off checking (use `unknown` and narrow)
- [ ] `as` assertions and non-null `!` hiding `undefined` or wrong shapes (validate or narrow instead)
- [ ] `@ts-ignore` suppressing errors (use `@ts-expect-error` with a reason; it fails once the error is gone)
- [ ] `strict` disabled, or `noUncheckedIndexedAccess` off so `arr[i]` and `record[key]` are typed as always present (it isn't part of `strict`)
- [ ] `switch` over a union with no exhaustiveness check (`const unreachable: never = value` in `default`)
- [ ] `paths` aliases the runtime or bundler doesn't resolve (`tsc` compiles, then the app fails with a module-not-found error)

**Full guide:** [TypeScript Guide](typescript.md)

## Node.js

- [ ] Synchronous I/O or CPU-heavy work in request handlers (`readFileSync`, `pbkdf2Sync`, large `JSON.parse`) blocking the event loop
- [ ] Unhandled promise rejections (they crash the process by default since Node 15), or emitters and streams without an `'error'` listener (the error is thrown and the process exits)
- [ ] `.pipe()` chains without error handling (errors aren't forwarded and streams aren't cleaned up; use `pipeline()` from `node:stream/promises`)
- [ ] No `SIGTERM` handling (in-flight requests are dropped on deploy), or `process.exit()` in library code (set `process.exitCode`)
- [ ] Two responses for one request (`ERR_HTTP_HEADERS_SENT`: a missing `return` after `res.send()` or `next()`)
- [ ] Express 4 async handlers that don't pass errors to `next(err)` (Express 4 doesn't forward rejected promises; Express 5 does)
- [ ] Path traversal: `path.join(baseDir, userInput)` without checking that the resolved path stays inside `baseDir`
- [ ] Request bodies read without a size limit (hand-rolled parsers, or a `limit` raised far above the `express.json()` default)
- [ ] Environment configuration used without validation at startup (`process.env` values are strings or `undefined`; fail fast)
- [ ] Outbound HTTP calls without a timeout (pass `signal: AbortSignal.timeout(ms)` to `fetch`)

**Full guide:** [Node.js Guide](nodejs.md)

## NestJS

- [ ] `@ValidateNested()` without `@Type(() => NestedDto)` (the nested object is never validated)
- [ ] `ValidationPipe` without `whitelist: true` (unknown properties reach the service; add `forbidNonWhitelisted` to reject them)
- [ ] `@Body() body: any` or an interface instead of a DTO class (nothing is validated; interfaces don't exist at runtime)
- [ ] ORM client or repository injected straight into controllers (data access in the HTTP layer)
- [ ] Business logic in guards or interceptors
- [ ] `forwardRef()` hiding a circular dependency that a shared module or an extracted service should break
- [ ] A request-scoped provider making every consumer request-scoped (scope bubbles up the injection chain: one instance per request)
- [ ] `catch { return null }` hiding failures (callers can't tell "not found" from "failed"; throw an `HttpException` or let an exception filter map it)
- [ ] E2E tests without the production global pipes, filters, and interceptors (`app.useGlobalPipes()` in `main.ts` isn't part of the testing module)

**Full guide:** [NestJS Guide](nestjs.md)

## Python

- [ ] Mutable default arguments (`def f(x=[])`)
- [ ] Bare `except:` catching `KeyboardInterrupt` and `SystemExit`
- [ ] Shared mutable class attributes (`class C: items = []`)
- [ ] Using `is` instead of `==` for value comparison
- [ ] Forgetting `self` parameter in methods
- [ ] Modifying list while iterating
- [ ] String concatenation in loops (use `"".join()`)
- [ ] Not closing files (use `with` statement)
- [ ] Missing type annotations on public functions

**Full guide:** [Python Guide](python.md)

## Salesforce

**Apex:**
- [ ] SOQL, DML, callouts, or `System.enqueueJob` inside loops (the transaction hits a governor limit at bulk volume)
- [ ] Callout after uncommitted DML (`You have uncommitted work pending`), or setup and non-setup objects written in one transaction (`MIXED_DML_OPERATION`)
- [ ] Empty `catch` blocks, or `Database.SaveResult` errors ignored after partial-success DML (`allOrNone` set to `false`)
- [ ] String `==` assumed to be case-sensitive (it isn't; use `equals()`), while `Map` keys and `Set` elements of type String are case-sensitive
- [ ] Hard-coded record Ids, org URLs, or usernames that break in every other org (PMD `AvoidHardcodingId`)

**Triggers:**
- [ ] Only `Trigger.new[0]` processed, so every other record in the chunk is silently skipped
- [ ] Static Boolean recursion guard that skips the records in later 200-record chunks of the same transaction
- [ ] Logic that runs on every update instead of only when the relevant field changed (no `Trigger.oldMap` comparison)
- [ ] Field assignments on `Trigger.new` in an after trigger (the records are read-only; set fields in a before trigger)
- [ ] Logic in the trigger body, or a second trigger on the same object (the order between triggers isn't guaranteed)

**SOQL/SOSL:**
- [ ] Single-row assignment (`Account acc = [SELECT ...];`) that throws `QueryException` when no row or more than one row matches; query into a `List` and check it
- [ ] Reading a field the query didn't select (`SObjectException: SObject row was retrieved via SOQL without querying the requested field`)
- [ ] `WITH SECURITY_ENFORCED` in a class at API 67.0+ (it no longer compiles; use `WITH USER_MODE`)
- [ ] Dynamic SOQL or SOSL that concatenates input instead of using binds or `Database.queryWithBinds` (injection)
- [ ] Non-selective or unbounded queries on large objects (leading `%` wildcards, negative operators, no `WHERE` or `LIMIT`; PMD `AvoidNonRestrictiveQueries`)

**LWC/Aura:**
- [ ] `@AuraEnabled(cacheable=true)` method that performs DML (it fails at runtime; cacheable methods must be read-only)
- [ ] `refreshApex` called with the unwrapped `data` instead of the whole value the `@wire` provisioned, or used for LDS record data (use `notifyRecordUpdateAvailable`)
- [ ] Listeners, timers, or message-channel subscriptions set up in `connectedCallback` with no cleanup in `disconnectedCallback`
- [ ] Mutating `@api` properties or wired data in place (they're read-only; copy before changing)
- [ ] Aura server-action callbacks that ignore the `ERROR` and `INCOMPLETE` states, or async code that touches the component outside `$A.getCallback()`

**Visualforce:**
- [ ] `escape="false"` on `apex:outputText` (or any component) with user-controlled data
- [ ] Merge fields inside `<script>` or URLs without `JSENCODE`, `JSINHTMLENCODE`, or `URLENCODE` (for example `'{!$CurrentPage.parameters.q}'`)
- [ ] DML in a controller constructor, a getter, or a `<apex:page action>` method (it runs on a GET page load with no CSRF token; PMD `ApexCSRF`, `VfCsrf`)
- [ ] Large collections or query results kept in non-`transient` controller fields, bloating view state

**Flows:**
- [ ] Get Records, Create/Update/Delete Records, or Apex actions inside a Loop (they run once per iteration; collect, then act once after the loop)
- [ ] Data and action elements without a fault path (the user sees a generic unhandled-fault error and the whole transaction fails)
- [ ] Record-triggered flow without entry conditions, or one that runs on every update when it should run only when the record changes to meet the criteria
- [ ] After-save flow updating its own triggering record (a second save that re-runs automation; use a before-save flow for same-record field updates)
- [ ] Hard-coded record Ids, usernames, or queue names in flow elements (use Custom Metadata, Custom Labels, or lookups by DeveloperName)

**Metadata:**
- [ ] New custom field without FLS in any permission set (users can't see it, and user-mode queries that reference it fail)
- [ ] High-risk permissions (`ModifyAllData`, `ViewAllData`, `AuthorApex`, `CustomizeApplication`, `ManageUsers`) or object View All/Modify All granted without a justification
- [ ] Profiles retrieved in full, so the diff carries unrelated permission changes and reordered elements that silently change access on deploy
- [ ] Destructive changes, narrowed field types or lengths, or new required or unique fields on objects that already hold data
- [ ] `<apiVersion>` bumped across 67.0 as if it were a no-op (user mode and implicit `with sharing` change query results and DML permissions)

**Full guides:** [Platform](salesforce/platform.md) · [Apex](salesforce/apex.md) · [Triggers](salesforce/apex-triggers.md) · [SOQL/SOSL](salesforce/soql-sosl.md) · [LWC](salesforce/lwc.md) · [Aura](salesforce/aura.md) · [Visualforce](salesforce/visualforce.md) · [Flows](salesforce/flows.md) · [Metadata](salesforce/metadata.md)

## SQL

- [ ] String concatenation for queries (SQL injection risk) — use parameterized queries
- [ ] Missing indexes on filtered/joined columns
- [ ] `SELECT *` instead of specific columns
- [ ] N+1 query patterns
- [ ] Missing `LIMIT` on large tables
- [ ] Not handling `NULL` comparisons correctly (`IS NULL` vs `= NULL`)
- [ ] Missing transactions for related operations
- [ ] Incorrect JOIN types
- [ ] Collation / case sensitivity surprises across databases (MySQL vs Postgres defaults)
- [ ] Date and timezone handling errors (naive timestamps, server-local `NOW()`, DST)

**See also:** [Security Review Guide](security-review-guide.md) for SQL injection prevention, and the [SQL Injection Prevention Guide](cross-cutting/sql-injection-prevention.md) for cross-language examples

## API Design

- [ ] Inconsistent resource naming
- [ ] Wrong HTTP methods (POST for idempotent operations)
- [ ] Missing pagination for list endpoints
- [ ] Incorrect status codes
- [ ] Missing rate limiting
- [ ] Missing input validation and sanitization
- [ ] Trusting client-side validation only

## Testing

- [ ] Testing implementation details instead of behavior
- [ ] Missing edge case tests
- [ ] Flaky tests (non-deterministic)
- [ ] Tests with external dependencies (no mocks)
- [ ] Missing negative tests (error cases)
- [ ] Overly complex test setup
