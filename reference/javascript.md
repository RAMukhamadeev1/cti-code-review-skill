# JavaScript Code Review Guide

Shared base guide for all JavaScript-family code: plain JavaScript, TypeScript, Node.js, NestJS, and Lightning Web Components (LWC). Targets ECMAScript 2023+ (Node.js 22 and 24 LTS, and evergreen browsers; Node.js 26 enters LTS on 2026-10-28). Rules that need a newer runtime say which one.

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Language Semantics & Pitfalls](#language-semantics--pitfalls)
- [Async & Promises](#async--promises)
- [Modules](#modules)
- [Browser & DOM](#browser--dom)
- [Security-Sensitive APIs](#security-sensitive-apis)
- [Testing](#testing)
- [Linting & Tooling](#linting--tooling)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| Plain JS (browser scripts, libraries, build scripts) | This guide |
| TypeScript | This guide + [typescript.md](typescript.md) |
| Node.js service, CLI, or script | This guide + [nodejs.md](nodejs.md) |
| NestJS | [nestjs.md](nestjs.md) + [typescript.md](typescript.md); this guide for async/runtime pitfalls |
| Lightning Web Components | [salesforce/lwc.md](salesforce/lwc.md) + this guide |
| Aura controllers and helpers | [salesforce/aura.md](salesforce/aura.md) + this guide |

Check the project's targets (`engines.node`, `.nvmrc`, the browserslist or bundler target) before flagging an API as too new, or before asking for a newer one.

---

## Language Semantics & Pitfalls

### Use strict equality

`==` converts operand types before comparing, so unrelated values compare equal and data-dependent branches misfire. `Object.is` treats `NaN` as equal to itself and tells `0` from `-0`; `===` does neither.

```javascript
// ❌ Loose equality coerces: '' == 0, '0' == false, and [] == false are all true
if (status == 0) { /* also runs for '' and '0' */ }
if (price === NaN) { /* never runs: NaN equals nothing, not even itself */ }

// ✅ Strict equality; == null is the one deliberate idiom (it matches only null and undefined)
if (status === 0) { /* only the number 0 */ }
if (value == null) return fallback;
if (Number.isNaN(price)) { /* unlike the global isNaN(), it does not coerce: isNaN('abc') is true */ }
```

Static analysis: ESLint `eqeqeq` with `{ "null": "ignore" }` (opt-in) and `use-isnan` (recommended).

### Defaults: nullish coalescing vs logical OR

`||` falls back on every falsy value, so a legitimate `0`, `''`, or `false` gets replaced; `??` falls back only on `null` and `undefined`. Parameter and destructuring defaults apply only to `undefined`, so an explicit `null` passes through them.

```javascript
// ❌ Valid falsy values are treated as missing
const discount = order.discount || 0.1; // an explicit 0 becomes 10%
const notify = settings.notify || true; // false becomes true: the setting can never be turned off

// ✅ Nullish coalescing keeps 0, '', and false
const discount = order.discount ?? 0.1;
options.retries ??= 3;
```

### Numbers: floating point, integers, and parsing

Numbers are IEEE 754 doubles: most decimal fractions are approximations, and integers are exact only up to `Number.MAX_SAFE_INTEGER` (2^53 - 1).

```javascript
// ❌ Floating-point money, and 64-bit IDs parsed as numbers
0.1 + 0.2;                                 // 0.30000000000000004
(1.005).toFixed(2);                        // "1.00" (1.005 is stored as 1.00499...), and a string
JSON.parse('{"id": 9007199254740993}').id; // 9007199254740992

// ✅ Integer minor units (cents) or a decimal library; large IDs stay strings (BigInt for arithmetic)
const totalCents = unitPriceCents * quantity;
const label = new Intl.NumberFormat(locale, { style: 'currency', currency }).format(totalCents / 100);

// ❌ Lenient or surprising parsing
parseInt('12px');              // 12: stops at the first non-digit
['1', '2', '3'].map(parseInt); // [1, NaN, NaN]: map passes the index as the radix
Number('');                    // 0: an empty field becomes zero

// ✅ Parse strictly and validate; pass a radix when prefix parsing is intended
const page = Number(query.page);
if (!Number.isInteger(page) || page < 1) throw new RangeError(`Invalid page: ${query.page}`);
const widthPx = Number.parseInt(style.width, 10); // "12px" -> 12, on purpose
```

Static analysis: ESLint `radix` (opt-in; since v10 it always requires the radix) and `no-loss-of-precision` (recommended; it checks literals, not parsed data).

### Scope, hoisting, and closures

`var` is function-scoped, so closures created in a loop share one binding. `let`, `const`, and `class` throw if used before their declaration runs (the temporal dead zone), and `const` blocks reassignment, not mutation.

```javascript
// ❌ One var binding for the whole loop: every handler sees the final value of i
for (var i = 0; i < tabs.length; i++) {
  tabs[i].addEventListener('click', () => selectTab(i));
}

// ✅ let creates a fresh binding per iteration
for (let i = 0; i < tabs.length; i++) {
  tabs[i].addEventListener('click', () => selectTab(i));
}

// ❌ init() runs at load time, before DEFAULTS is initialized: ReferenceError
init();
const DEFAULTS = { theme: 'light' };
function init() { applyTheme(DEFAULTS.theme); }
```

Static analysis: ESLint `no-var` and `prefer-const` (opt-in).

### Preserve this in callbacks

A method passed as a callback is called without its object, so `this` becomes the element, `undefined`, or the global object, depending on the caller.

```javascript
// ❌ Passed without its object: when the click fires, this is the button, not the view
button.addEventListener('click', this.handleClick);

// ❌ bind() returns a new function each time, so this removes nothing
button.removeEventListener('click', this.handleClick.bind(this));

// ✅ Arrow class field: bound to the instance, and one stable reference to add and remove
class CartView {
  handleClick = () => {
    this.cart.checkout();
  };

  mount(button) {
    button.addEventListener('click', this.handleClick);
  }

  unmount(button) {
    button.removeEventListener('click', this.handleClick);
  }
}
```

### Mutation and copying

`sort()`, `reverse()`, and `splice()` change the array they are called on, and spread, `Object.assign()`, and `Object.freeze()` act one level deep. Mutating shared data (arguments, state, cached objects) causes changes at a distance and defeats change detection that compares references.

```javascript
// ❌ Sorts the caller's array as a side effect
const top = customers.sort((a, b) => b.revenue - a.revenue).slice(0, 10);

// ✅ Copying array methods (ES2023): toSorted, toReversed, toSpliced, with
const top = customers.toSorted((a, b) => b.revenue - a.revenue).slice(0, 10);
const updated = rows.with(index, { ...rows[index], name: newName });

// ❌ Removing items while iterating skips the element after each removal
for (let i = 0; i < items.length; i++) {
  if (items[i].expired) items.splice(i, 1);
}

// ✅ Build a new array instead
const active = items.filter((item) => !item.expired);

// ❌ Spread copies one level: the nested object is still shared
const draft = { ...order };
draft.shipping.city = 'Berlin'; // also changes order.shipping.city

// ✅ structuredClone copies deeply: keeps Date, Map, and Set, throws on functions,
//    and returns class instances as plain objects
const draft = structuredClone(order);

// ⚠️ Object.freeze is shallow too: nested objects stay writable
```

### Sorting pitfalls

Without a comparator, `sort()` compares elements as strings, and a comparator must return a number whose sign gives the order.

```javascript
// ❌ String comparison, and a boolean comparator (it never returns a negative number)
[10, 9, 1].sort();                   // [1, 10, 9]
[3, 1, 2].toSorted((a, b) => a > b); // [3, 1, 2] in V8: not sorted

// ✅ Numbers subtract; strings use one reused Intl.Collator (or localeCompare)
const ascending = amounts.toSorted((a, b) => a - b);
const collator = new Intl.Collator(locale, { numeric: true }); // "file2" before "file10"
const byFileName = fileNames.toSorted(collator.compare);

// ✅ Several keys: a tie (0) falls through to the next comparison
const byPerson = people.toSorted((a, b) => a.lastName.localeCompare(b.lastName) || a.age - b.age);
```

### Objects as dictionaries and prototype pollution

Plain objects inherit from `Object.prototype`, so keys that come from input (`constructor`, `toString`, `__proto__`) collide with built-ins. A recursive merge of untrusted JSON can even write to `Object.prototype`, which changes every object in the process (prototype pollution).

```javascript
// ❌ Keys from input collide with inherited properties
const counts = {};
for (const word of words) {
  counts[word] = (counts[word] || 0) + 1; // "constructor" -> "function Object() { [native code] }1"
}
if (rolePermissions[role]) grantAccess(); // role "toString" is truthy

// ✅ Map for data keyed by input (or Object.create(null)); Object.hasOwn for own-key checks
const counts = new Map();
for (const word of words) counts.set(word, (counts.get(word) ?? 0) + 1);
if (Object.hasOwn(rolePermissions, role) && rolePermissions[role]) grantAccess();

// ❌ Recursive merge of parsed JSON: {"__proto__": {"isAdmin": true}} writes to Object.prototype
function merge(target, source) {
  for (const key in source) {
    const value = source[key];
    target[key] = typeof value === 'object' && value !== null ? merge(target[key] ?? {}, value) : value;
  }
  return target;
}
merge(userSettings, JSON.parse(requestBody));
({}).isAdmin; // true: every object now inherits it

// ✅ Validate the shape first; a generic merge copies own keys only and skips the unsafe ones
const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
const isPlainObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);

function merge(target, source) {
  for (const [key, value] of Object.entries(source)) {
    if (UNSAFE_KEYS.has(key)) continue;
    const current = Object.hasOwn(target, key) && isPlainObject(target[key]) ? target[key] : {};
    target[key] = isPlainObject(value) ? merge(current, value) : value;
  }
  return target;
}
```

Static analysis: ESLint `no-prototype-builtins` (recommended) flags `obj.hasOwnProperty(key)`, which also breaks on null-prototype objects such as the result of `Object.groupBy`.

> 📖 Hardening options (frozen or sealed prototypes, Node.js `--disable-proto=delete`): [OWASP Prototype Pollution Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Prototype_Pollution_Prevention_Cheat_Sheet.html).

### Dates and time zones

`Date` parsing depends on the string format and the runtime's time zone, months are 0-based, and `Date` objects are mutable. MDN now calls `Date` a legacy feature.

```javascript
// ❌ Similar strings, different zones: date-only is UTC midnight, date-time is local midnight
new Date('2024-01-02');                             // 2024-01-02T00:00:00.000Z
new Date('2024-01-02T00:00');                       // midnight in the runtime's time zone
new Date('2024-01-02').toLocaleDateString('en-US'); // "1/1/2024" in New York

// ❌ 0-based months, and setters that mutate a Date other code still holds
const due = new Date(2024, 1, 1); // February 1
date.setDate(date.getDate() + 7); // changes the caller's object

// ✅ Calendar dates stay 'YYYY-MM-DD' strings, instants are UTC ISO strings; copy before changing
const birthday = '1990-04-15';
const createdAt = new Date().toISOString();
const nextWeek = new Date(date);
nextWeek.setDate(nextWeek.getDate() + 7);

// ✅ Format for display with Intl.DateTimeFormat and an explicit time zone
const shown = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: userTimeZone })
  .format(new Date(createdAt));
```

MDN recommends Temporal for new code. It reached Stage 4 in March 2026 (expected in ES2027) and is on by default in Node.js 26, Chrome and Edge 144+, and Firefox 139+, but not in Node.js 22/24 or stable Safari. Use it only where every target runtime has it, or through a polyfill.

### Strings, Unicode, and regular expressions

String length and indexes count UTF-16 code units, equal-looking text can differ in code points, and the `g` and `y` flags give a regex state that survives between calls.

```javascript
// ❌ .length and slice() count UTF-16 code units
'\u{1F600}'.length;                 // 2 for a single emoji
const preview = title.slice(0, 20); // can cut an emoji or an accented letter in half

// ✅ Code points via the string iterator; user-perceived characters via Intl.Segmenter
[...'\u{1F600}'].length; // 1
const graphemes = Array.from(new Intl.Segmenter(locale).segment(title), (s) => s.segment);
const preview = graphemes.slice(0, 20).join('');

// ❌ Visually identical strings with different code points
'caf\u00e9' === 'cafe\u0301'; // false

// ✅ Normalize before comparing, deduplicating, or using text as a key
'caf\u00e9'.normalize('NFC') === 'cafe\u0301'.normalize('NFC'); // true

// ❌ The g flag makes test() stateful through lastIndex; replace() with a string replaces only the first match
const HAS_DIGIT = /\d/g;
HAS_DIGIT.test('a1');           // true
HAS_DIGIT.test('b2');           // false: the search started at lastIndex 2
'2024-01-02'.replace('-', '/'); // "2024/01-02"

// ✅ No g flag for test(); replaceAll() or matchAll() when you need every match
const HAS_DIGIT = /\d/;
'2024-01-02'.replaceAll('-', '/'); // "2024/01/02"
```

### JSON round-trips

`JSON.parse` throws on malformed input, and `JSON.stringify` silently changes or drops values it cannot represent, so data that crosses a boundary needs explicit conversion.

```javascript
// ❌ One malformed message throws inside the handler
socket.addEventListener('message', (event) => applyUpdate(JSON.parse(event.data)));

// ✅ Parse at the boundary, handle the failure, then validate the shape
socket.addEventListener('message', (event) => {
  let update;
  try {
    update = JSON.parse(event.data);
  } catch (error) {
    console.warn('Ignoring malformed update', error);
    return;
  }
  if (isValidUpdate(update)) applyUpdate(update);
});

// ❌ Values that JSON.stringify changes or rejects
JSON.stringify({ id: 1, note: undefined, save() {} }); // '{"id":1}': undefined and functions vanish
JSON.stringify({ ratio: NaN, tags: new Set(['a']) });  // '{"ratio":null,"tags":{}}'
JSON.stringify({ placedAt: new Date(0) });             // an ISO string; parse() does not revive a Date
JSON.stringify({ total: 10n });                        // throws a TypeError (so do circular structures)

// ✅ Convert explicitly on the way out and on the way in
const body = JSON.stringify({ total: order.total.toString(), tags: [...order.tags] });
const placedAt = new Date(JSON.parse(text).placedAt);
```

`JSON.parse(JSON.stringify(value))` as a deep copy loses the same types; use `structuredClone` (see [Mutation and copying](#mutation-and-copying)).

### Throw Error objects and keep the cause

Only `Error` instances carry a stack trace and work with `instanceof Error`, loggers, and error trackers. A new error thrown from a `catch` block should wrap the original with `cause` (ES2022). Anything can be thrown, so generic handlers check `error instanceof Error` before reading `.message`.

```javascript
// ❌ A string has no stack trace, and a new error without the original loses the root cause
throw 'Payment failed';

try {
  await gateway.charge(order);
} catch (error) {
  throw new Error(`Payment failed: ${error.message}`);
}

// ✅ Throw Error instances (or subclasses) and chain the original as cause
class PaymentError extends Error {
  name = 'PaymentError'; // the inherited constructor already accepts { cause }
}

try {
  await gateway.charge(order);
} catch (error) {
  throw new PaymentError(`Payment failed for order ${order.id}`, { cause: error });
}
```

Static analysis: ESLint `preserve-caught-error` (recommended since v10) and `prefer-promise-reject-errors` (opt-in); typescript-eslint `only-throw-error`.

> 📖 For error hierarchies and cross-language principles, see [Error Handling Principles](cross-cutting/error-handling-principles.md#example-hierarchy-typescript).

---

## Async & Promises

### Handle rejections and HTTP errors

`fetch()` rejects only on network failures and aborts: a 404 or 500 response resolves normally, so every call needs a `response.ok` (or status) check. Catch where the code can act (retry, fallback, a message for the user) and let the error propagate otherwise; a `catch` that only logs and carries on hides the failure.

```javascript
// ❌ HTTP errors go unnoticed: json() parses the error body (or throws on an HTML error page)
async function fetchUser(id) {
  const response = await fetch(`/api/users/${id}`);
  return response.json();
}

// ✅ Check response.ok, and add context without losing the original error
async function fetchUser(id) {
  try {
    const response = await fetch(`/api/users/${encodeURIComponent(id)}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    throw new Error(`Failed to fetch user ${id}`, { cause: error });
  }
}
```

### No floating promises

A promise that is not awaited, returned, or given a `.catch()` "floats": nothing waits for it and nothing sees its rejection. In Node.js an unhandled rejection terminates the process by default; in browsers it only reaches the console and the `unhandledrejection` event, so the user sees nothing.

```javascript
// ❌ Floating: a failed save goes unhandled, and the dialog closes before saving finishes
saveDraft(form);
closeDialog();

// ✅ Await it, so failures reach the caller and the dialog closes only after saving
await saveDraft(form);
closeDialog();

// ✅ Or handle the rejection where the promise is created, or mark deliberate fire-and-forget
saveDraft(form).catch((error) => showError('Could not save the draft', error));
void sendAnalytics(event); // safe: sendAnalytics catches and logs its own errors
// ⚠️ LWC's ESLint config enables no-void: in Lightning Web Components end the chain with .catch() instead

// ❌ addEventListener ignores the listener's promise, so a rejection is unhandled
saveButton.addEventListener('click', async () => {
  await saveDraft(form);
});

// ✅ Catch inside the listener (the same goes for timer and observer callbacks)
saveButton.addEventListener('click', async () => {
  try {
    await saveDraft(form);
  } catch (error) {
    showError('Could not save the draft', error);
  }
});
```

Core ESLint has no rule for this. In TypeScript projects, `@typescript-eslint/no-floating-promises` and `no-misused-promises` catch it (see [typescript.md](typescript.md#eslint-rules)).

> 📖 Process-level behavior (the `unhandledRejection` event, crashes, exit codes): [Node.js Async Error Handling](nodejs.md#async-error-handling).

### Async callbacks in array methods

Array methods ignore the promises an async callback returns: `forEach` does not wait for them, and `filter`, `some`, `every`, and `find` treat every promise as truthy.

```javascript
// ❌ forEach does not wait: "done" logs first, and rejections are unhandled
items.forEach(async (item) => {
  await processItem(item);
});
console.log('done');

// ❌ filter() keeps every user: a promise is always truthy
const activeUsers = users.filter(async (user) => isActive(user));

// ✅ Sequential: for...of with await. Concurrent: Promise.all over map()
for (const item of items) {
  await processItem(item);
}
await Promise.all(items.map((item) => processItem(item)));

// ✅ Async filter: resolve the predicates first
const flags = await Promise.all(users.map((user) => isActive(user)));
const activeUsers = users.filter((_, index) => flags[index]);
```

### Promise combinators: all, allSettled, any, race

Pick the combinator by the failure semantics you need. None of them cancels the operations that are still running when it settles.

```javascript
// ❌ When partial results are acceptable, Promise.all discards them: one failure rejects the whole call
async function fetchAllUsers(ids) {
  const users = await Promise.all(ids.map((id) => fetchUser(id)));
  return users;
}

// ✅ Promise.allSettled collects every outcome
async function fetchAllUsers(ids) {
  const results = await Promise.allSettled(ids.map((id) => fetchUser(id)));

  const users = [];
  const errors = [];
  for (const result of results) {
    if (result.status === 'fulfilled') {
      users.push(result.value);
    } else {
      errors.push(result.reason);
    }
  }
  return { users, errors };
}

// ⚠️ Promise.all rejects early but does not stop the other requests: abort them yourself
async function loadDashboard(userId) {
  const controller = new AbortController();
  const { signal } = controller;
  try {
    return await Promise.all([
      fetchJson(`/api/users/${userId}/profile`, { signal }),
      fetchJson(`/api/users/${userId}/orders`, { signal }),
    ]);
  } catch (error) {
    controller.abort(); // stop the requests that are still running
    throw error;
  }
}
```

| Combinator | Fulfills | Rejects | Typical use |
|---|---|---|---|
| `Promise.all` | when every input fulfills | at the first rejection | all-or-nothing work |
| `Promise.allSettled` | when every input settles | never | batches that tolerate partial failure |
| `Promise.any` | at the first fulfillment | when all inputs reject, with an `AggregateError` (`.errors`) | fallbacks, redundant sources |
| `Promise.race` | if the first input to settle fulfills | if the first input to settle rejects | rarely needed; use `AbortSignal.timeout()` for timeouts |

### Run independent work concurrently, with a limit

Awaiting independent calls one after another adds their latencies together. Firing thousands at once has the opposite problem: it exhausts sockets and memory, and trips the server's rate limits.

```javascript
// ❌ Independent requests in sequence: the total time is the sum of all three
const profile = await fetchProfile(userId);
const orders = await fetchOrders(userId);
const invoices = await fetchInvoices(userId);

// ✅ Start them together when none depends on another
const [profile, orders, invoices] = await Promise.all([
  fetchProfile(userId),
  fetchOrders(userId),
  fetchInvoices(userId),
]);

// ❌ Unbounded fan-out: 10,000 simultaneous requests
await Promise.all(orderIds.map((id) => syncOrder(id)));

// ✅ Bound the concurrency with a small worker pool (see the example linked below)
await processWithLimit(orderIds, (id) => syncOrder(id), 5);
```

ESLint `no-await-in-loop` (opt-in) flags sequential awaits, but some loops are sequential on purpose (cursor pagination, ordered writes, rate limits), so judge each hit.

> 📖 See [Missed concurrency opportunities](performance-review-guide.md#missed-concurrency-opportunities) and the [worker-pool example](cross-cutting/async-concurrency-patterns.md#typescript-worker-pool-concurrency-limit).

### Race conditions: cancel or ignore stale results

When input changes faster than the server answers, responses can arrive out of order, and the last response to arrive wins instead of the last one requested. Abort the superseded request, or tag each request and drop results that are no longer current.

```javascript
// ❌ A slow reply for "ca" can arrive after the reply for "cat" and overwrite it
async function onSearchInput(query) {
  const response = await fetch(`/api/search?q=${query}`);
  renderResults(await response.json());
}

// ✅ Abort the previous request when a new one starts
let controller;

async function onSearchInput(query) {
  controller?.abort();
  controller = new AbortController();
  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, {
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Search failed: HTTP ${response.status}`);
    renderResults(await response.json());
  } catch (err) {
    if (err.name === 'AbortError') return; // superseded by a newer query
    throw err;
  }
}

searchInput.addEventListener('input', (event) => {
  onSearchInput(event.target.value).catch((err) => showSearchError(err));
});

// ✅ When the call cannot be aborted (for example LWC imperative Apex), ignore stale results
let latestRequestId = 0;

async function onAccountChange(accountId) {
  const requestId = ++latestRequestId;
  const contacts = await getContacts({ accountId });
  if (requestId !== latestRequestId) return; // a newer call has started
  renderContacts(contacts);
}
```

### Timeouts with AbortSignal

A request without a timeout can hang for minutes while it holds the UI or server resources. `AbortSignal.timeout(ms)` aborts with a `TimeoutError` DOMException (so a check for `AbortError` alone misses it), and `AbortSignal.any()` (added in Node.js 20.3.0 and 18.17.0) combines it with a caller's signal.

```javascript
// ❌ No timeout: a stalled server keeps the request (and the spinner) alive
const response = await fetch(url);

// ✅ Timeout plus optional caller cancellation; the signal also covers reading the body
async function fetchJson(url, { signal } = {}) {
  const timeout = AbortSignal.timeout(5000);
  const response = await fetch(url, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  return response.json();
}

// ❌ Promise.race with a timer that is never cleared: the timer keeps running (and keeps
//    a Node.js process alive), and the slow operation is not cancelled
function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('Timed out')), ms)),
  ]);
}

// ✅ For APIs that take no signal: clear the timer however the race ends
async function withTimeout(promise, ms) {
  let timerId;
  const timeout = new Promise((_, reject) => {
    timerId = setTimeout(() => reject(new Error(`Timed out after ${ms} ms`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timerId);
  }
}
```

### return await inside try/catch

Returning a promise from inside `try` hands it to the caller before it settles, so this function's `catch` never sees the rejection, and its `finally` (releasing a lock or a connection, hiding a spinner) runs too early.

```javascript
async function loadConfig() {
  try {
    // ❌ return fetchConfig(); would skip this catch when the promise rejects
    // ✅ Await inside try so catch and finally see the outcome
    return await fetchConfig();
  } catch (error) {
    console.warn('Config service unavailable, using defaults', error);
    return DEFAULT_CONFIG;
  }
}
```

Outside `try`, `return await` and `return` behave the same. ESLint's `no-return-await` is deprecated; the type-aware typescript-eslint rule `return-await` enforces awaiting inside `try`.

### Avoid the explicit Promise constructor anti-pattern

Wrapping existing promises in `new Promise` adds code and loses errors. An `async` executor is worse: if it throws, the error becomes an unhandled rejection and the returned promise never settles. An `async` function already returns a promise (see `fetchUser` above).

```javascript
// ❌ If fetch rejects, the outer promise stays pending forever
function getUser(id) {
  return new Promise(async (resolve) => {
    const response = await fetch(`/api/users/${id}`);
    resolve(response.json());
  });
}

// ✅ Use new Promise only to adapt a callback or event API, once, at the lowest level
function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Failed to load image: ${src}`));
    image.src = src;
  });
}
```

`Promise.withResolvers()` (ES2024; Node.js 22+) helps when `resolve` and `reject` must be called from outside the executor. For Node.js callback APIs, use `util.promisify` or promise-based modules such as `node:fs/promises` (see [nodejs.md](nodejs.md#async-error-handling)). Static analysis: ESLint `no-async-promise-executor` (recommended) and `no-promise-executor-return` (opt-in).

### Don't block the event loop or main thread

Your JavaScript runs on one thread. A long synchronous task (a big loop, `JSON.parse` of a multi-megabyte payload, synchronous crypto or compression, a [catastrophic regex](#regular-expression-denial-of-service-redos)) freezes input handling in the browser, where tasks over 50 ms hurt responsiveness, and stalls every request on a Node.js server.

```javascript
// ❌ One long task: nothing else runs until every row is processed
const report = rows.map((row) => computeTotals(row));

// ✅ Process in chunks and yield between them, or move the work to a Web Worker / worker thread
async function buildReport(rows, chunkSize = 500) {
  const results = [];
  for (let start = 0; start < rows.length; start += chunkSize) {
    for (const row of rows.slice(start, start + chunkSize)) {
      results.push(computeTotals(row));
    }
    // eslint-disable-next-line no-await-in-loop -- yielding between chunks is the point
    await new Promise((resolve) => {
      setTimeout(resolve, 0); // browsers that support it can use scheduler.yield()
    });
  }
  return results;
}
```

> 📖 Browser responsiveness: [JavaScript Performance](performance-review-guide.md#javascript-performance). Node.js worker threads and event-loop monitoring: [nodejs.md](nodejs.md#event-loop--cpu-bound-work).

---

## Modules

### Prefer named exports and side-effect-free imports

Importing a module should only define things. Top-level work (network calls, timers, global patches) runs in every page, test, and script that imports the module, and cannot be retried or cancelled. Named exports keep names consistent across files and let bundlers drop unused code; barrel files that re-export a whole directory load every module behind them.

```javascript
// ❌ Importing session.js fires a request and starts a timer, in every page and test that imports it
export const session = await fetch('/api/session').then((response) => response.json());
setInterval(refreshToken, 60_000);

// ❌ Default-exported object: bundlers generally cannot drop the members nobody uses
export default { formatDate, formatPrice, parseCsv };

// ✅ Export functions; the application entry point decides when to call them
export async function loadSession() {
  const response = await fetch('/api/session');
  if (!response.ok) throw new Error(`Session request failed: HTTP ${response.status}`);
  return response.json();
}

export function startTokenRefresh(intervalMs = 60_000) {
  const timerId = setInterval(() => {
    refreshToken().catch((error) => reportRefreshFailure(error));
  }, intervalMs);
  return () => clearInterval(timerId);
}
```

Top-level `await` also delays every module that imports this one, and in Node.js a module graph that contains top-level `await` cannot be loaded with `require()` (`ERR_REQUIRE_ASYNC_MODULE`).

### Circular imports

In an import cycle, one module runs before the other has finished evaluating. ESM then throws a `ReferenceError` for any `const`, `let`, or `class` binding still in its temporal dead zone; CommonJS hands out a partly filled `module.exports`, so values are `undefined`. Which module fails depends on import order, so the bug can appear or vanish when an unrelated import moves.

```javascript
// ❌ order.js and customer.js import each other
// order.js
import { formatCustomer } from './customer.js';
export const ORDER_STATUSES = ['open', 'paid'];
export const describeOrder = (order) => `${order.id} for ${formatCustomer(order.customer)}`;

// customer.js
import { ORDER_STATUSES } from './order.js';
export const DEFAULT_STATUS = ORDER_STATUSES[0]; // ReferenceError when order.js is imported first
export function formatCustomer(customer) {
  return customer.name;
}

// ✅ Move the shared piece into a module that both import, so dependencies point one way
// order-statuses.js
export const ORDER_STATUSES = ['open', 'paid'];
```

A cycle checker (`madge --circular src`, or the `import/no-cycle` lint rule) catches new cycles in CI.

### Dynamic import() and code splitting

`import()` loads code on demand and lets bundlers split it into separate chunks. Cache the loading promise so every caller shares one load, reset it on failure so later calls do not keep getting the cached rejection, and show a fallback when loading fails (a chunk download can fail on a flaky network or after a deploy removes old chunks).

```javascript
// ✅ Load a module only when it is needed, and skip it where it cannot run
async function loadChartLibrary() {
  if (typeof window === 'undefined') return null; // skip during server-side rendering
  const { Chart } = await import('chart.js');
  return Chart;
}

// ✅ Cache the promise, reset it on failure, and show a fallback
let chartModule;

function loadChartModule() {
  chartModule ??= import('./chart.js').catch((error) => {
    chartModule = undefined; // don't cache the failure: the next click tries again
    throw error;
  });
  return chartModule;
}

chartButton.addEventListener('click', async () => {
  try {
    const { renderChart } = await loadChartModule();
    renderChart(chartContainer, salesData);
  } catch (error) {
    showFallback(chartContainer, 'The chart could not be loaded. Try again.', error);
  }
});

// ❌ Never build module specifiers from user input: it can load modules never meant to be reachable
const widget = await import(`./widgets/${params.get('widget')}.js`);

// ✅ Map allowed names to static import() calls
const WIDGETS = {
  calendar: () => import('./widgets/calendar.js'),
  chart: () => import('./widgets/chart.js'),
};
const loadWidget = Object.hasOwn(WIDGETS, widgetName) ? WIDGETS[widgetName] : null;
```

ESM versus CommonJS, `require(esm)`, and package `exports` are runtime topics: see [nodejs.md](nodejs.md#modules--packaging).

---

## Browser & DOM

### Safe DOM updates

HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`) parse strings as markup, so interpolated data can inject elements and event-handler attributes that run script. Text APIs never parse markup.

```javascript
// ❌ A name like <img src=x onerror=alert(1)> runs script
greeting.innerHTML = `Hello, ${user.name}!`;
list.insertAdjacentHTML('beforeend', `<li>${item.title}</li>`);

// ✅ Set text, and build elements with createElement
greeting.textContent = `Hello, ${user.name}!`;
const li = document.createElement('li');
li.textContent = item.title;
list.append(li);

// ✅ When HTML is a requirement (rich text from a CMS), sanitize it first
import DOMPurify from 'dompurify';
article.innerHTML = DOMPurify.sanitize(untrustedHtml);

// ⚠️ URL attributes need a protocol allowlist too: a javascript: href runs script when clicked
```

> 📖 More sinks, URL validation, and CSP: [XSS Prevention](cross-cutting/xss-prevention.md#plain-dom-javascript).

### Clean up listeners, timers, and observers

Anything registered on a long-lived target (`window`, `document`, a shared element, an interval, an observer, a socket or channel subscription) outlives the code that registered it: handlers pile up, run against detached DOM, and keep it from being garbage-collected. Undo every registration in the teardown hook (for example LWC `disconnectedCallback`, see [lwc.md](salesforce/lwc.md#lifecycle)).

```javascript
// ❌ Nothing is undone on teardown
function mountClock(element) {
  window.addEventListener('resize', () => layout(element));
  setInterval(() => updateClock(element), 1000);
  new ResizeObserver(() => layout(element)).observe(element);
}

// ✅ Return a teardown function; one AbortController removes every listener
function mountClock(element) {
  const controller = new AbortController();
  const { signal } = controller;
  window.addEventListener('resize', () => layout(element), { signal });
  document.addEventListener('visibilitychange', () => updateClock(element), { signal });
  const intervalId = setInterval(() => updateClock(element), 1000);
  const observer = new ResizeObserver(() => layout(element));
  observer.observe(element);

  return function unmount() {
    controller.abort(); // removes both listeners
    clearInterval(intervalId);
    observer.disconnect();
  };
}
```

### Validate postMessage origins

Any window can post a message to yours, so a `message` handler must compare `event.origin` with an exact allowlist and validate the data. When sending, name the target origin instead of `'*'`, so the data cannot reach a page that has navigated elsewhere.

```javascript
// ❌ Trusts every sender, and posts a token to whatever page the popup now shows
window.addEventListener('message', (event) => applySettings(event.data));
popup.postMessage({ token }, '*');

// ❌ Substring checks: https://app.example.com.attacker.net passes
if (event.origin.includes('app.example.com')) { /* ... */ }

// ✅ Exact origin match, then validate the message shape
const TRUSTED_ORIGIN = 'https://app.example.com';

window.addEventListener('message', (event) => {
  if (event.origin !== TRUSTED_ORIGIN || event.data?.type !== 'settings') return;
  applySettings(event.data.settings);
});
popup.postMessage({ type: 'token', token }, TRUSTED_ORIGIN);
```

### Don't store secrets in web storage

`localStorage` and `sessionStorage` are readable by every script on the origin, including an XSS payload or a compromised third-party tag, and `localStorage` survives logout. Anything shipped in client code is public.

```javascript
// ❌ Any script on the page can read the token, and a bundled secret is public
localStorage.setItem('accessToken', accessToken);
const PAYMENT_API_SECRET = 'secret-value';

// ✅ The server sets an HttpOnly, Secure, SameSite session cookie; script never sees the token
const response = await fetch('/api/login', { method: 'POST', body: new FormData(loginForm) });
if (!response.ok) throw new Error(`Login failed: HTTP ${response.status}`);

// ✅ A short-lived token the client must hold stays in memory only, never in storage
```

---

## Security-Sensitive APIs

### No eval, new Function, or string timers

`eval`, `new Function`, and string arguments to `setTimeout`/`setInterval` compile strings as code, so any data that reaches them becomes code injection. A Content Security Policy without `'unsafe-eval'` blocks all of them.

```javascript
// ❌ Strings compiled as code
const value = eval(`order.${fieldName}`);
const compute = new Function('a', 'b', formulaFromConfig);
setTimeout('refreshDashboard()', 1000);

// ✅ Property access through an allowlist, and functions instead of strings (JSON.parse for data)
const SORTABLE_FIELDS = new Set(['name', 'createdAt', 'amount']);
if (!SORTABLE_FIELDS.has(fieldName)) throw new Error(`Unsupported field: ${fieldName}`);
const value = order[fieldName];
setTimeout(refreshDashboard, 1000);
```

Static analysis: ESLint `no-eval`, `no-implied-eval`, and `no-new-func` (all opt-in).

### Regular expression denial of service (ReDoS)

JavaScript regex engines backtrack. Nested or overlapping quantifiers can take exponential time on input that almost matches, which freezes a browser tab or blocks every request on a Node.js server.

```javascript
// ❌ Nested quantifiers: 10 words plus a trailing "!" (50 characters) block for seconds,
//    and each extra word roughly triples the time
const WORDS = /^(\w+\s?)*$/;

// ❌ User text compiled as a pattern: ReDoS, and "a.b" also matches "axb"
const search = new RegExp(searchTerm, 'i');

// ✅ Bound the input, and write the pattern so each character can match only one way
if (userInput.length > 200) return false;
const WORDS = /^\w+(?:\s\w+)*$/;

// ✅ Escape user text: RegExp.escape (ES2025; Node.js 24+), or a helper on older runtimes
const search = new RegExp(RegExp.escape(searchTerm), 'i');
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
```

For patterns that users supply, use a linear-time engine (RE2 bindings) instead of `RegExp`.

### Use cryptographic randomness for tokens

Tokens, session and reset IDs, and anything else that grants access must be unguessable. `Math.random()` is not cryptographically secure; `crypto.getRandomValues()` and `crypto.randomUUID()` are. Generate secrets on the server whenever possible.

```javascript
// ❌ Math.random() output can be predicted
const resetToken = Math.random().toString(36).slice(2);

// ✅ Web Crypto, available in browsers and Node.js
const sessionId = crypto.randomUUID(); // browsers: secure contexts (HTTPS) only
const bytes = crypto.getRandomValues(new Uint8Array(32));
const resetToken = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
```

> 📖 Other crypto mistakes: [Security Review Guide](security-review-guide.md#common-mistakes).

---

## Testing

### Choose a test runner (Vitest, Jest, node:test)

Use one runner per package. LWC projects use Jest through `@salesforce/sfdx-lwc-jest` (see [lwc.md](salesforce/lwc.md#testing-with-jest)); TypeScript-specific setup such as `ts-jest` is in [typescript.md](typescript.md).

| Runner | Good fit | Watch for |
|---|---|---|
| Vitest 5 | New projects, Vite apps, ESM-first code | Needs Node.js 22.12+ and `vite` 6.4+ as a peer dependency; unawaited async assertions fail the test |
| Jest 30 | Existing Jest suites, LWC | Native ESM is experimental (`--experimental-vm-modules`); alias matchers such as `toBeCalled` and `toThrowError` were removed |
| `node:test` | Node.js libraries, CLIs, and services (no dependencies; run with `node --test`) | Module mocking needs `--experimental-test-module-mocks`; coverage is still experimental |

```javascript
// ✅ New projects: Vitest (integrates with the Vite ecosystem, native ESM support)
// vitest.config.js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['src/**/*.test.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
});

// ✅ Existing Jest projects can stay on Jest; mind the configuration differences
// jest.config.js
/** @type {import('jest').Config} */
const config = {
  testEnvironment: 'node',
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
};
export default config;
```

### Await async assertions

An async assertion that is neither awaited nor returned settles after its test has finished, so its failure escapes the test: Vitest 5 fails the test (earlier versions awaited it at the end with a warning), and in Jest it surfaces as an unhandled rejection that can crash the whole run. Tests that assert inside a `catch` block also need `expect.assertions(n)`, or they pass when nothing throws.

```javascript
// ❌ The test ends before the assertion settles
it('rejects unknown users', () => {
  expect(fetchUser('missing')).rejects.toThrow('Not found');
});

// ✅ Await (or return) async assertions
it('rejects unknown users', async () => {
  await expect(fetchUser('missing')).rejects.toThrow('Not found');
});
```

### Snapshot testing

Snapshots catch unintended changes in stable output, but a large or noisy snapshot gets approved without anyone reading it. Review snapshot file changes like code: an update with no explanation in the PR often means someone ran `-u` to make a failure go away.

```javascript
// ✅ Snapshots suit stable output: serialized configuration objects, error messages
it('matches the serialized config', () => {
  const config = createAppConfig();
  expect(config).toMatchSnapshot();
});

// ❌ Avoid large objects, dynamic data, and random values
it('matches the user list', () => {
  const hugePayload = { users: generateRandomUsers(1000) };
  expect(hugePayload).toMatchSnapshot(); // too long to review, and a change never shows its intent
});

// ✅ Inline snapshots for small fragments
it('formats the error message', () => {
  expect(formatError('INVALID_INPUT')).toMatchInlineSnapshot(
    `"Error: Invalid input provided"`
  );
});

// ✅ Property matchers for dynamic values
it('creates a user with a generated id', () => {
  expect(createUser('Alice')).toMatchSnapshot({
    id: expect.any(String),
    createdAt: expect.any(Date),
  });
});
```

### Mocking strategy

Mock the boundaries you don't own (network, time, randomness) and assert on what the code under test does, not on the mock. With native ESM, Jest does not hoist `jest.mock`: register mocks with `jest.unstable_mockModule()` and then load the module under test with `await import()`.

```javascript
// ✅ Vitest: vi.mock calls are hoisted above the imports
import { vi, it, expect } from 'vitest';
import { fetchUser } from './api.js';
import { getDisplayName } from './user-service.js';

vi.mock('./api.js', () => ({
  fetchUser: vi.fn(),
}));

it('uses the user name as the display name', async () => {
  fetchUser.mockResolvedValue({ id: 1, name: 'Alice' });
  await expect(getDisplayName(1)).resolves.toBe('Alice');
  expect(fetchUser).toHaveBeenCalledWith(1);
});

// ✅ Jest: jest.mock is hoisted as well (CommonJS or Babel-transformed code)
jest.mock('./database', () => ({
  query: jest.fn().mockResolvedValue([{ id: 1 }]),
}));

// ❌ Avoid partial mocks: the test exercises the mock, not the real behavior
jest.mock('./utils', () => ({
  ...jest.requireActual('./utils'),
  calculateTotal: jest.fn(), // the other functions are real; this one is fake
}));
```

Vitest 5 clears mock call history before every test (`clearMocks` now defaults to `true`). Restore spies with `vi.restoreAllMocks()` or `jest.restoreAllMocks()`.

### Fake timers

Tests that wait on real timers are slow and flaky. Fake timers move the clock explicitly; restore real timers after each test so later tests are unaffected.

```javascript
// ❌ Real waiting: slow, and flaky on a busy CI machine
await new Promise((resolve) => {
  setTimeout(resolve, 350);
});

// ✅ Fake timers: advance the clock, then restore real timers
beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

it('debounces search input', () => {
  const onSearch = vi.fn();
  const debounced = debounce(onSearch, 300);
  debounced('a');
  debounced('ab');

  vi.advanceTimersByTime(299);
  expect(onSearch).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(onSearch).toHaveBeenCalledTimes(1);
  expect(onSearch).toHaveBeenCalledWith('ab');
});

// ✅ When timers and promises interleave, use the async variant; pin "now" for date logic
await vi.advanceTimersByTimeAsync(1000);
vi.setSystemTime(new Date('2026-01-15T12:00:00Z'));
```

Jest has the same calls on `jest` (`useFakeTimers`, `advanceTimersByTime`, `advanceTimersByTimeAsync`, `setSystemTime`); `node:test` has `mock.timers` (stable since Node.js 23.1.0). Vitest 5 fake timers also control Temporal.

### DOM and network test helpers

Test the DOM the way users see it (roles, labels, text) with Testing Library, which needs no UI framework, and mock HTTP at the network level with MSW instead of stubbing `fetch`. The jest-dom matchers come from `@testing-library/jest-dom/vitest` (Vitest) or `@testing-library/jest-dom` (Jest), imported in a setup file.

```javascript
// @vitest-environment jsdom
// ✅ DOM tests with Testing Library: query by role, label, or text; interact through user-event
import { afterEach, expect, it } from 'vitest';
import { screen } from '@testing-library/dom';
import userEvent from '@testing-library/user-event';
import { renderLoginForm } from './login-form.js';

afterEach(() => {
  document.body.replaceChildren();
});

it('submits the form', async () => {
  const user = userEvent.setup(); // inside the test, before rendering
  renderLoginForm(document.body);

  await user.type(screen.getByLabelText('Email'), 'alice@example.com');
  await user.click(screen.getByRole('button', { name: 'Submit' }));

  // findBy* waits for async updates; toBeInTheDocument comes from jest-dom
  expect(await screen.findByText('Welcome, Alice!')).toBeInTheDocument();
});

// ✅ Mock the network with MSW (msw-setup.js, listed in the runner's setup files)
import { afterAll, afterEach, beforeAll } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

export const server = setupServer(
  // absolute URLs work in every test environment
  http.get('https://api.example.com/users/:id', ({ params }) => {
    return HttpResponse.json({ id: params.id, name: 'Alice' });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' })); // the default only warns
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ✅ Override a handler inside one test to cover the error path
server.use(
  http.get('https://api.example.com/users/:id', () => new HttpResponse(null, { status: 500 })),
);
```

---

## Linting & Tooling

### ESLint baseline (flat config)

ESLint v10 is current (v9 reached end of life on 2026-08-06; Salesforce's LWC and Aura configs still require v9, see [lwc.md](salesforce/lwc.md#testing-with-jest)) and reads only flat config: `.eslintrc.*` and `.eslintignore` files are ignored and `/* eslint-env */` comments are errors. `js/recommended` leaves out several rules that catch the bugs in this guide, so turn them on explicitly.

```javascript
// eslint.config.js
import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import globals from 'globals';

export default defineConfig([
  {
    files: ['**/*.js'],
    plugins: { js },
    extends: ['js/recommended'],
    languageOptions: {
      globals: { ...globals.browser }, // globals.node for Node.js code
    },
    rules: {
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-var': 'error',
      'prefer-const': 'error',
      radix: 'error',
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-promise-executor-return': 'error',
      'prefer-promise-reject-errors': 'error',
      'no-await-in-loop': 'warn', // sometimes sequential on purpose: judge each hit
    },
  },
]);
```

In review, flag `.eslintrc.*` files left in an ESLint v10 project (they are silently ignored), `eslint-disable` comments without a reason, and rules downgraded to get a PR green. Type-aware rules (`no-floating-promises`, `no-misused-promises`) are in [typescript.md](typescript.md#eslint-rules); the LWC ESLint configuration is in [lwc.md](salesforce/lwc.md#testing-with-jest).

### Type-check JavaScript with // @ts-check

JSDoc types plus `// @ts-check` (per file) or `checkJs` (per project, alongside `allowJs` and `noEmit`) give plain JavaScript compile-time checks without a build step. Run `tsc` in CI so the checks gate merges.

```javascript
// @ts-check

/**
 * @param {Array<{ sku: string, quantity: number, unitPriceCents: number }>} items
 * @returns {number} Order total in cents.
 */
export function orderTotalCents(items) {
  return items.reduce((sum, item) => sum + item.quantity * item.unitPriceCents, 0);
}

// ❌ Reported by tsc: Type 'string' is not assignable to type 'number'.
orderTotalCents([{ sku: 'A-1', quantity: '2', unitPriceCents: 500 }]);
```

TypeScript 7.0 reworked JavaScript checking: `@enum`, `@class` on constructor functions, Closure-style types such as `function(string): void`, and a bare `?` type are no longer recognized, so flag new JSDoc that relies on them.

---

## Review Checklist

### Language semantics
- [ ] Comparisons use `===`/`!==`; `== null` appears only as a deliberate null-or-undefined check; NaN is tested with `Number.isNaN`
- [ ] Defaults use `??` wherever `0`, `''`, or `false` are valid values
- [ ] Money uses integer minor units or a decimal library; large IDs stay strings; parsed numbers are validated and `parseInt` has a radix
- [ ] No `var`; methods passed as callbacks keep their `this`
- [ ] Shared arrays and objects are not mutated in place (`toSorted`/`toSpliced`/`with`, `structuredClone`); nothing is removed from an array while iterating over it
- [ ] Sorts pass a numeric comparator, `localeCompare`, or an `Intl.Collator`
- [ ] Lookups keyed by input use `Map`, `Object.create(null)`, or `Object.hasOwn`; merges of untrusted JSON skip `__proto__`, `constructor`, and `prototype`
- [ ] Calendar dates stay `YYYY-MM-DD` strings, instants are stored in UTC, and display uses `Intl.DateTimeFormat` with an explicit time zone
- [ ] `JSON.parse` at trust boundaries is guarded and followed by validation; values passed to `JSON.stringify` hold no BigInt, cycles, `Map`, or `Set`
- [ ] Only `Error` instances are thrown or rejected, and wrapping errors pass `{ cause }`

### Async & Promises
- [ ] async functions have error handling: they catch where they can act, otherwise the error propagates
- [ ] Promise rejections are handled correctly, and `fetch` calls check `response.ok`
- [ ] No floating promises: each one is awaited, returned, given a `.catch()`, or marked `void` with a reason; async listeners catch their own errors
- [ ] No async callbacks in `forEach`, `filter`, `some`, `every`, or `find`
- [ ] Concurrent requests use Promise.all or Promise.allSettled, whichever matches the failure semantics; large fan-outs have a concurrency limit
- [ ] Race conditions are handled with AbortController, or with a request id when the call cannot be aborted
- [ ] Outbound calls have timeouts (`AbortSignal.timeout()`); `Promise.race` timers are cleared
- [ ] `return await` is used inside `try`; no `new Promise` around existing promises and no async executors
- [ ] No long synchronous work on the main thread or the event loop

### Modules
- [ ] Modules have no import-time side effects (network calls, timers, global patches) and no avoidable top-level `await`
- [ ] Utilities use named exports, not a default-exported object; no new circular imports
- [ ] Dynamic `import()` promises are cached, reset on failure, and backed by a fallback; specifiers are static or allowlisted

### Browser & DOM
- [ ] Untrusted text goes through `textContent`/`createElement`; HTML sinks receive only sanitized HTML (DOMPurify)
- [ ] Every listener, timer, and observer registered during setup is removed in teardown
- [ ] `message` handlers check `event.origin` by exact match and validate `event.data`; `postMessage` names a target origin
- [ ] No tokens, secrets, or sensitive personal data in `localStorage`, `sessionStorage`, or the client bundle

### Security
- [ ] No `eval`, `new Function`, or string arguments to `setTimeout`/`setInterval`
- [ ] Regexes that run on user input avoid nested quantifiers, run on length-limited input, and escape user text
- [ ] Tokens and IDs that grant access come from `crypto.getRandomValues()`/`crypto.randomUUID()`, never `Math.random()`

### Testing & tooling
- [ ] Async assertions are awaited or returned; tests that assert inside `catch` use `expect.assertions`
- [ ] Snapshots are small and stable, dynamic fields use property matchers, and snapshot updates are explained in the PR
- [ ] Mocks sit at the boundaries (network through MSW, time through fake timers); no partial mocks of the module under test
- [ ] Fake timers are restored after each test; DOM tests query by role, label, or text and use `userEvent.setup()`
- [ ] MSW fails on unhandled requests and resets handlers after each test
- [ ] ESLint uses flat config with the opt-in rules above; every `eslint-disable` carries a reason; JSDoc-typed files are checked with `// @ts-check` or `checkJs`

---

## References

- [Equality comparisons and sameness (MDN)](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Equality_comparisons_and_sameness)
- [Promise (MDN)](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise)
- [AbortSignal (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal) and [AbortSignal.timeout() (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static)
- [Array.prototype.toSorted() (MDN)](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/toSorted)
- [structuredClone() (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Window/structuredClone)
- [Date (MDN)](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date) and [Intl.DateTimeFormat (MDN)](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat)
- [Crypto.randomUUID() (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/randomUUID)
- [OWASP Prototype Pollution Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Prototype_Pollution_Prevention_Cheat_Sheet.html)
- [ESLint: Configuration files (flat config)](https://eslint.org/docs/latest/use/configure/configuration-files), [Migrate to v10.x](https://eslint.org/docs/latest/use/migrate-to-10.0.0), and [Rules](https://eslint.org/docs/latest/rules/)
- [TypeScript: JSDoc Reference](https://www.typescriptlang.org/docs/handbook/jsdoc-supported-types.html) and [checkJs](https://www.typescriptlang.org/tsconfig/#checkJs)
- [Vitest guide](https://vitest.dev/guide/) and [migration guide](https://vitest.dev/guide/migration)
- [Jest: Getting Started](https://jestjs.io/docs/getting-started) and [ECMAScript Modules](https://jestjs.io/docs/ecmascript-modules)
- [Node.js test runner (node:test)](https://nodejs.org/api/test.html)
- [DOM Testing Library](https://testing-library.com/docs/dom-testing-library/intro), [user-event](https://testing-library.com/docs/user-event/intro), and [user-event setup](https://testing-library.com/docs/user-event/setup)
- [MSW documentation](https://mswjs.io/docs/) and [Node.js integration](https://mswjs.io/docs/integrations/node)
