# JavaScript Code Review Guide

Shared base for JavaScript-family code (plain JavaScript, TypeScript, Node.js, Lightning Web Components, Aura): it owns the language semantics those guides share. Targets ES2023+ on Node.js 22 and 24 LTS (26 becomes LTS on 2026-10-28) and evergreen browsers; check `engines.node`, `.nvmrc`, and the browserslist or bundler target before calling an API too new ([availability](#runtime-availability-of-newer-apis)).

Load with [typescript.md](typescript.md) for TypeScript and [nodejs.md](nodejs.md) for Node.js code. Related: [XSS Prevention](cross-cutting/xss-prevention.md) · [Async & Concurrency](cross-cutting/async-concurrency-patterns.md) · [Error Handling](cross-cutting/error-handling-principles.md)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Default severities: 🔴 [blocking] · 🟡 [important] · 🟢 [nit] · 💡 [suggestion]; adjust them to the impact in context. A rule a linter or tsconfig already enforces is a finding only when the diff disables it, and pre-existing code only when the change makes it worse.

### Language semantics → [Language Semantics & Pitfalls](#language-semantics--pitfalls)

- [ ] 🟡 `==`/`!=` only as the deliberate `x == null`; `NaN` tested with `Number.isNaN()`, not `=== NaN` or the coercing global `isNaN()`.
- [ ] 🟡 `??`/`??=` where `0`, `''`, or `false` are valid values (`||` only when every falsy value should fall back); parameter and destructuring defaults do not replace `null`.
- [ ] 🟡 Money in integer minor units or a decimal library, not float math or `toFixed()`; IDs above 2^53 - 1 stay strings (BigInt for arithmetic).
- [ ] 🟡 Parsed numbers are validated (`Number.isInteger`, ranges); `parseInt` has a radix and is used only for intended prefix parsing; no `.map(parseInt)`; `Number('')` is `0`.
- [ ] 🟡 No closure over a loop `var`; no `let`/`const`/`class` binding used before its declaration runs at load time (TDZ).
- [ ] 🟡 Methods passed as callbacks keep `this` (arrow class field); `removeEventListener` gets the reference that was added, not a new `bind()`.
- [ ] 🟡 Shared data (arguments, state, caches) is not mutated in place (`toSorted`/`toSpliced`/`with`, or copy first); nothing is spliced out while iterating; spread, `Object.assign`, and `Object.freeze` are shallow → [Mutation and copying](#mutation-and-copying).
- [ ] 🟡 `sort()` comparators return a signed number (`a - b`, `localeCompare`, a reused `Intl.Collator`), never a boolean; numbers never use the default string order.
- [ ] 🔴 Recursive merge, clone, or path-set of untrusted input skips `__proto__`, `constructor`, and `prototype`, or the shape is validated first → [prototype pollution](#objects-as-dictionaries-and-prototype-pollution).
- [ ] 🟡 Lookups keyed by input use `Map`, `Object.create(null)`, or `Object.hasOwn`, not `obj[key]` truthiness or `obj.hasOwnProperty(key)`.
- [ ] 🟡 Calendar dates stay `YYYY-MM-DD` strings (a date-only string parses as UTC, a date-time string as local time), instants are UTC ISO strings, display uses `Intl.DateTimeFormat` with an explicit `timeZone`, and a shared `Date` is copied before a setter runs.
- [ ] 🟡 User-visible characters are counted or cut with `Intl.Segmenter`, not `length`/`slice`; user text is `normalize()`d before comparing or keying; no `g`/`y` regex reused with `test()`/`exec()`; `replace(string)` replaces only the first match.
- [ ] 🟡 `JSON.parse` of external input is guarded and validated; `JSON.stringify` input holds no BigInt, cycles, `Map`/`Set`, or `Date` that must round-trip; no `JSON.parse(JSON.stringify(x))` deep copy.
- [ ] 🟡 Only `Error` instances are thrown or rejected; a rethrow passes `{ cause }`; generic handlers check `Error.isError(e)` (Node.js 24+) or `instanceof Error` before reading `.message` → [Throw Error objects](#throw-error-objects-and-keep-the-cause).

### Async → [Async & Promises](#async--promises)

- [ ] 🟡 `fetch` results check `response.ok`/`status`; a `catch` acts (retry, fallback, user message) or rethrows, never only logs and carries on.
- [ ] 🟡 No floating promises (🔴 in Node.js request and job paths: the process exits): await, return, or `.catch()`; deliberate fire-and-forget is `void` plus a comment that the callee handles errors (`.catch()` in LWC); async listeners, timers, and observers catch their own errors → [No floating promises](#no-floating-promises).
- [ ] 🟡 No async callbacks in `forEach`, `filter`, `some`, `every`, `find`, or `reduce`: `for…of` with `await`, or `Promise.all` over `map`.
- [ ] 🟡 The combinator fits the failure semantics (`all`, `allSettled`, `any`), and nothing assumes a combinator cancels the losers.
- [ ] 🟡 Independent awaits run concurrently and large fan-outs are bounded; a sequential `await` in a loop is fine when order, pagination, or rate limits require it.
- [ ] 🟡 Input-driven requests cancel or ignore stale responses → [Race conditions](#race-conditions-cancel-or-ignore-stale-results).
- [ ] 🟡 Outbound calls have a deadline (`AbortSignal.timeout()`), abort handling also covers `TimeoutError`, and `Promise.race` timers are cleared → [Timeouts](#timeouts-with-abortsignal).
- [ ] 🟡 `return await` inside `try` when `catch`/`finally` must see the outcome; no `new Promise` around an existing promise; no `async` executor → [Promise plumbing](#combinators-loops-and-promise-plumbing).
- [ ] 🟡 No long synchronous work (big loops, multi-megabyte `JSON.parse`, sync crypto or compression, catastrophic regexes) on the main thread or in request paths → [Don't block](#dont-block-the-event-loop-or-main-thread).

### Modules → [Modules](#modules)

- [ ] 🟡 Imports have no side effects (network, timers, global patches) except in entry points, polyfills, and registration modules; no avoidable top-level `await`.
- [ ] 🟡 No new runtime import cycle (type-only cycles are harmless).
- [ ] 🟢 Utilities use named exports, not a default-exported object (framework-required default exports, such as LWC components, are exempt).
- [ ] 🟡 Cached `import()` promises reset on failure and have a fallback; specifiers are static or allowlisted, never built from input → [Dynamic import()](#dynamic-import-and-code-splitting).

### Browser & DOM → [Browser & DOM](#browser--dom)

- [ ] 🔴 Untrusted data in HTML sinks, URL attributes, or framework escape hatches follows [XSS Prevention](cross-cutting/xss-prevention.md); DOM built from data uses `createElement` plus `textContent`, not markup strings → [Safe DOM updates](#safe-dom-updates).
- [ ] 🟡 Listeners, intervals, observers, and subscriptions on long-lived targets are removed in teardown (listeners on DOM destroyed with the component are fine) → [Clean up](#clean-up-listeners-timers-and-observers).
- [ ] 🔴 `message` handlers compare `event.origin` with an exact allowlist and validate `event.data`; `postMessage` with sensitive data names the target origin, not `'*'`.
- [ ] 🔴 No tokens, secrets, or sensitive personal data in `localStorage`, `sessionStorage`, or the client bundle (preferences are fine).

### Security-sensitive APIs → [Security-Sensitive APIs](#security-sensitive-apis)

- [ ] 🔴 No `eval`, `new Function`, or string timers fed by data that can come from input.
- [ ] 🔴 on servers, 🟡 in browsers: regexes run on untrusted input have no nested or overlapping quantifiers and see length-limited input; user text in a `RegExp` is escaped or matched with a linear-time engine.
- [ ] 🔴 Tokens, session IDs, and reset codes come from `crypto.getRandomValues()`/`crypto.randomUUID()`, never `Math.random()` (fine for jitter, sampling, UI).

### Testing → [Testing](#testing)

- [ ] 🟡 Async assertions (`resolves`/`rejects`) are awaited or returned; tests asserting inside `catch` use `expect.assertions(n)`.
- [ ] 🟡 Mocks sit at boundaries the code does not own (network via MSW, time via fake timers, randomness); the module under test is never partially mocked (partial mocks of its dependencies are fine).
- [ ] 🟡 Fake timers and spies are restored after each test (`useRealTimers()`, `restoreAllMocks()`); code mixing timers and promises uses the `*Async` advance calls; date-dependent tests pin the clock (`setSystemTime()`).
- [ ] 🟡 MSW fails on unhandled requests and resets handlers after each test; DOM tests query by role, label, or text with `userEvent.setup()`.
- [ ] 🟢 Snapshots are small and stable, generated fields use property matchers, and snapshot updates are explained in the PR.
- [ ] 🟡 When the PR changes test tooling: one runner per package, and the runner facts below hold.

### Tooling → [Linting & Tooling](#linting--tooling)

- [ ] 🟢 `eslint-disable` comments carry a reason; rules are not downgraded to turn a PR green; no `.eslintrc.*` added to an ESLint 10 project (it is ignored).
- [ ] 🟡 When the PR touches JSDoc-typed JavaScript: `// @ts-check`/`checkJs` is enforced by `tsc` in CI, and no JSDoc relies on constructs TypeScript 7 dropped.

### Runtime availability → [Runtime availability of newer APIs](#runtime-availability-of-newer-apis)

- [ ] 🟡 APIs newer than the lowest supported target are polyfilled, guarded, or avoided; APIs every target has are not findings.

---

## Language Semantics & Pitfalls

Outputs worth quoting in a finding:

```javascript
if (status == 0) {}                        // also true for '' and '0'
const discount = order.discount || 0.1;    // an explicit 0 becomes 10%
['1', '2', '3'].map(parseInt);             // [1, NaN, NaN]: map passes the index as the radix
(1.005).toFixed(2);                        // "1.00" (1.005 is stored as 1.00499...), and a string
JSON.parse('{"id": 9007199254740993}').id; // 9007199254740992
[10, 9, 1].sort();                         // [1, 10, 9]
[3, 1, 2].toSorted((a, b) => a > b);       // [3, 1, 2] in V8: a boolean comparator never returns < 0
```

### Mutation and copying

`sort()`, `reverse()`, and `splice()` change the array they are called on (`customers.sort(...)` reorders the caller's array), and a spread copy still shares nested objects (`draft.shipping.city = 'Berlin'` also changes the original). Use the ES2023 copying methods (`toSorted`, `toReversed`, `toSpliced`, `rows.with(i, value)`) or `structuredClone()`, which keeps `Date`, `Map`, and `Set`, throws on functions, and returns class instances as plain objects.

### Objects as dictionaries and prototype pollution

Plain objects inherit from `Object.prototype`, so input keys such as `constructor` or `toString` collide with built-ins, and a recursive merge of untrusted JSON can write to `Object.prototype`, changing every object in the process.

```javascript
// ❌ Inherited keys, and a merge that follows "__proto__"
counts[word] = (counts[word] || 0) + 1; // "constructor" → "function Object() { [native code] }1"
if (rolePermissions[role]) grantAccess(); // role "toString" is truthy
function unsafeMerge(target, source) {
  for (const key in source) {
    const value = source[key];
    target[key] = typeof value === 'object' && value !== null ? unsafeMerge(target[key] ?? {}, value) : value;
  }
  return target;
}
unsafeMerge(settings, JSON.parse('{"__proto__": {"isAdmin": true}}')); // ({}).isAdmin is now true

// ✅ Object.hasOwn for own keys (or a Map), and a merge that copies own keys and skips unsafe ones
if (Object.hasOwn(rolePermissions, role) && rolePermissions[role]) grantAccess();
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

`obj.hasOwnProperty(key)` also breaks on null-prototype objects such as `Object.groupBy()` results (ESLint `no-prototype-builtins`). Hardening options: the OWASP cheat sheet under [References](#references).

### Dates, text, and JSON

```javascript
new Date('2024-01-02');                             // UTC midnight
new Date('2024-01-02T00:00');                       // local midnight
new Date('2024-01-02').toLocaleDateString('en-US'); // "1/1/2024" in New York
new Date(2024, 1, 1);                               // February 1: months are 0-based
'\u{1F600}'.length;                                 // 2 for one emoji; slice() can cut it in half
'caf\u00e9' === 'cafe\u0301';                       // false until both are normalize('NFC')d
const HAS_DIGIT = /\d/g;
HAS_DIGIT.test('a1');                               // true
HAS_DIGIT.test('b2');                               // false: the search started at lastIndex 2
JSON.stringify({ note: undefined, save() {} });     // '{}'
JSON.stringify({ ratio: NaN, tags: new Set(['a']) }); // '{"ratio":null,"tags":{}}'
JSON.stringify({ total: 10n });                     // TypeError (cycles too); Dates become strings parse() does not revive

// ✅ Graphemes for user-visible length and truncation
const graphemes = Array.from(new Intl.Segmenter(locale).segment(title), (s) => s.segment);
```

MDN calls `Date` a legacy feature and recommends Temporal for new code; use Temporal only where every target has it ([availability](#runtime-availability-of-newer-apis)) or through a polyfill.

### Throw Error objects and keep the cause

```javascript
// ❌ throw 'Payment failed' has no stack; inside catch, throw new Error(`Payment failed: ${error.message}`) drops the cause
// ✅ An Error subclass with the original chained as cause (ES2022; the inherited constructor accepts { cause })
class PaymentError extends Error {
  name = 'PaymentError';
}
throw new PaymentError(`Payment failed for order ${order.id}`, { cause: error });
```

Anything can be thrown, so a generic handler checks the value before reading `.message`. `Error.isError(value)` (ES2026, Node.js 24+) also recognizes errors from other realms (iframes, `node:vm` contexts), where `instanceof Error` is false. Lint: `preserve-caught-error` (in `eslint:recommended` since ESLint 10), `prefer-promise-reject-errors`, typescript-eslint `only-throw-error`. Error hierarchies: [Error Handling Principles](cross-cutting/error-handling-principles.md).

---

## Async & Promises

`fetch()` rejects only on network failures and aborts: a 404 or 500 resolves normally. Async principles (structured concurrency, cancellation, backpressure) live in [Async & Concurrency Patterns](cross-cutting/async-concurrency-patterns.md).

### No floating promises

In Node.js an unhandled rejection exits the process by default ([process behavior](nodejs.md#async-error-handling)); in browsers it only reaches the console and the `unhandledrejection` event.

```javascript
// ❌ The rejection goes unhandled, and the dialog closes before saving finishes
saveDraft(form);
closeDialog();
saveButton.addEventListener('click', async () => { await saveDraft(form); }); // the listener's promise is ignored

// ✅ Await it, catch inside listeners, and mark deliberate fire-and-forget
await saveDraft(form);
closeDialog();
saveButton.addEventListener('click', async () => {
  try {
    await saveDraft(form);
  } catch (error) {
    showError('Could not save the draft', error);
  }
});
void sendAnalytics(event); // safe: sendAnalytics catches and logs its own errors
```

LWC's ESLint config enables `no-void`, so components end the chain with `.catch()`. Core ESLint has no floating-promise rule; typed projects use `@typescript-eslint/no-floating-promises` and `no-misused-promises` ([typescript.md](typescript.md#eslint-rules)).

### Combinators, loops, and promise plumbing

```javascript
// ❌ forEach does not wait (rejections go unhandled); filter keeps everything, since a promise is truthy
items.forEach(async (item) => { await processItem(item); });
const activeUsers = users.filter(async (user) => isActive(user));

// ✅ An async filter resolves the predicates first
const flags = await Promise.all(users.map((user) => isActive(user)));
const active = users.filter((_, index) => flags[index]);

// ✅ Promise.all rejects at the first failure while the other requests keep running: abort them
async function loadDashboard(userId) {
  const controller = new AbortController();
  try {
    return await Promise.all([
      fetchJson(`/api/users/${userId}/profile`, { signal: controller.signal }),
      fetchJson(`/api/users/${userId}/orders`, { signal: controller.signal }),
    ]);
  } catch (error) {
    controller.abort();
    throw error;
  }
}

// ✅ return await inside try: `return fetchConfig()` would skip this catch (and run a finally too early)
async function loadConfig() {
  try {
    return await fetchConfig();
  } catch (error) {
    console.warn('Config service unavailable, using defaults', error);
    return DEFAULT_CONFIG;
  }
}

// ❌ An async executor: if fetch rejects, the outer promise never settles
const getUser = (id) => new Promise(async (resolve) => resolve((await fetch(`/api/users/${id}`)).json()));
```

`new Promise` belongs only where a callback or event API is adapted, once, at the lowest level; Node.js callback APIs use the built-in promise modules ([nodejs.md](nodejs.md#async-error-handling)). `Promise.any` rejects with an `AggregateError`; `Promise.race` is rarely right (timeouts use `AbortSignal.timeout()`). Outside `try`, `return await` and `return` behave the same (typescript-eslint `return-await` enforces this; core `no-return-await` is deprecated). Bounded concurrency: the worker-pool pattern in [Async & Concurrency Patterns](cross-cutting/async-concurrency-patterns.md).

### Race conditions: cancel or ignore stale results

When input changes faster than the server answers, the last response to arrive wins instead of the last one requested.

```javascript
// ✅ Abort the previous request, and ignore the abort it causes
let controller;
async function onSearchInput(query) {
  controller?.abort();
  controller = new AbortController();
  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`Search failed: HTTP ${response.status}`);
    renderResults(await response.json());
  } catch (error) {
    if (error.name !== 'AbortError') throw error; // AbortError: superseded by a newer query
  }
}
searchInput.addEventListener('input', (event) => {
  onSearchInput(event.target.value).catch((error) => showSearchError(error));
});

// ✅ When the call cannot be aborted (for example LWC imperative Apex), drop stale results
let latestRequestId = 0;
async function onAccountChange(accountId) {
  const requestId = ++latestRequestId;
  const contacts = await getContacts({ accountId });
  if (requestId === latestRequestId) renderContacts(contacts);
}
```

### Timeouts with AbortSignal

```javascript
// ✅ A deadline plus the caller's signal; it also covers reading the body
async function fetchJson(url, { signal } = {}) {
  const timeout = AbortSignal.timeout(5000);
  const response = await fetch(url, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  return response.json();
}

// ✅ For APIs that take no signal: clear the timer however the race ends (a pending timer also keeps
//    a Node.js process alive); the slow operation itself keeps running
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

`AbortSignal.timeout()` rejects with a `DOMException` named `TimeoutError`, a manual `abort()` with `AbortError`, so code that checks only for `AbortError` misses timeouts. Node.js client defaults (undici, database pools): [nodejs.md](nodejs.md#put-timeouts-on-all-outbound-io).

### Don't block the event loop or main thread

A browser task over 50 ms delays input handling; on a server one long task stalls every request.

```javascript
// ✅ Chunk long work and yield between chunks (or move it to a Web Worker or worker thread)
async function buildReport(rows, chunkSize = 500) {
  const results = [];
  for (let start = 0; start < rows.length; start += chunkSize) {
    for (const row of rows.slice(start, start + chunkSize)) results.push(computeTotals(row));
    await new Promise((resolve) => {
      setTimeout(resolve, 0); // browsers with scheduler.yield() can use it instead
    });
  }
  return results;
}
```

Node.js specifics (the libuv threadpool, worker pools, `nextTick` starvation, event-loop metrics): [nodejs.md](nodejs.md#event-loop--cpu-bound-work). Browser performance: [Performance Review Guide](performance-review-guide.md).

---

## Modules

Top-level work runs in every page, test, and script that imports the module and cannot be retried or cancelled. Top-level `await` delays every importer, and in Node.js a graph containing it cannot be loaded with `require()` (`ERR_REQUIRE_ASYNC_MODULE`). Bundlers generally cannot drop unused members of a default-exported object, and a barrel file loads every module behind it.

A module that runs `export const session = await fetch('/api/session')` or `setInterval(refreshToken, 60_000)` at the top level does so in every page and test that imports it; export a `startTokenRefresh()` that returns a stop function instead, and let the entry point call it.

In a runtime import cycle one module runs before the other finishes: ESM throws a `ReferenceError` for bindings still in their temporal dead zone, and CommonJS hands out a partly filled `module.exports`. Which side fails depends on import order, so the bug moves when an unrelated import moves; extract the shared piece into a module both import (CI: `import/no-cycle` or madge). ESM versus CommonJS, `require(esm)`, and package `exports`: [nodejs.md](nodejs.md#modules--packaging).

### Dynamic import() and code splitting

```javascript
// ✅ Cache the load, reset it on failure (a chunk can 404 after a deploy), and show a fallback
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

// ❌ A specifier built from input can load modules that were never meant to be reachable
const widget = await import(`./widgets/${params.get('widget')}.js`);

// ✅ Map allowed names to static import() calls
const WIDGETS = { calendar: () => import('./widgets/calendar.js'), chart: () => import('./widgets/chart.js') };
const loadWidget = Object.hasOwn(WIDGETS, widgetName) ? WIDGETS[widgetName] : null;
```

Skip browser-only modules during server-side rendering (`typeof window === 'undefined'`).

---

## Browser & DOM

### Safe DOM updates

HTML sinks, sanitizing at the sink, URL protocol allowlists, framework escape hatches, and CSP are owned by [XSS Prevention](cross-cutting/xss-prevention.md). The JavaScript-specific part: build structure from data with elements, not markup strings (`outerHTML` parses markup too).

```javascript
// ❌ An item title like <img src=x onerror=alert(1)> runs script
list.insertAdjacentHTML('beforeend', `<li>${item.title}</li>`);

// ✅ Elements plus text never parse markup
const li = document.createElement('li');
li.textContent = item.title;
list.append(li);
```

### Clean up listeners, timers, and observers

Registrations on `window`, `document`, shared elements, intervals, observers, and socket or channel subscriptions outlive the code that made them: handlers pile up, run against detached DOM, and keep it alive. Undo them in the teardown hook (in LWC, `disconnectedCallback`).

```javascript
// ✅ Return a teardown function; one AbortController removes every listener
function mountClock(element) {
  const controller = new AbortController();
  window.addEventListener('resize', () => layout(element), { signal: controller.signal });
  document.addEventListener('visibilitychange', () => updateClock(element), { signal: controller.signal });
  const intervalId = setInterval(() => updateClock(element), 1000);
  const observer = new ResizeObserver(() => layout(element));
  observer.observe(element);
  return function unmount() {
    controller.abort();
    clearInterval(intervalId);
    observer.disconnect();
  };
}
```

### Messaging and storage

```javascript
// ❌ Trusts every sender, posts a token to whatever page the popup now shows, and checks a substring
window.addEventListener('message', (event) => applySettings(event.data));
popup.postMessage({ token }, '*');
if (event.origin.includes('app.example.com')) {} // https://app.example.com.attacker.net passes

// ✅ Exact origin, then the message shape; name the target origin
window.addEventListener('message', (event) => {
  if (event.origin !== TRUSTED_ORIGIN || event.data?.type !== 'settings') return;
  applySettings(event.data.settings);
});
popup.postMessage({ type: 'token', token }, TRUSTED_ORIGIN);
```

Web storage is readable by every script on the origin (an XSS payload, a compromised third-party tag), and `localStorage` survives logout: sessions belong in server-set `HttpOnly`, `Secure`, `SameSite` cookies, and a short-lived token the client must hold stays in memory.

---

## Security-Sensitive APIs

```javascript
// ❌ Strings compiled as code, a catastrophic pattern, user text as a pattern, a predictable token
const value = eval(`order.${fieldName}`);
setTimeout('refreshDashboard()', 1000);
const WORDS = /^(\w+\s?)*$/;                // a 50-character near-match blocks for seconds
const search = new RegExp(searchTerm, 'i'); // ReDoS, and "a.b" also matches "axb"
const resetToken = Math.random().toString(36).slice(2);

// ✅ Allowlisted property access, functions instead of strings, unambiguous patterns, escaping, Web Crypto
if (!SORTABLE_FIELDS.has(fieldName)) throw new Error(`Unsupported field: ${fieldName}`);
const fieldValue = order[fieldName];
setTimeout(refreshDashboard, 1000);
const SAFE_WORDS = /^\w+(?:\s\w+)*$/;       // each character can match only one way
const matchesWords = (input) => input.length <= 200 && SAFE_WORDS.test(input);
const escaped = new RegExp(RegExp.escape(searchTerm), 'i'); // Node.js 24+; older: s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const token = Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) => b.toString(16).padStart(2, '0')).join('');
```

On a server, `eval` of input is code injection; in the browser it is also an XSS sink ([XSS Prevention](cross-cutting/xss-prevention.md) covers CSP). For patterns that users supply, use a linear-time engine (RE2 bindings). `crypto.randomUUID()` needs a secure context (HTTPS) in browsers; generate secrets on the server when possible. Other crypto mistakes: [Security Review Guide](security-review-guide.md).

---

## Testing

LWC tests run on Jest through `@salesforce/sfdx-lwc-jest` ([lwc.md](salesforce/lwc.md)); type-checking tests: [typescript.md](typescript.md#testing-typescript).

| Runner | Facts that change findings |
| --- | --- |
| Vitest 5 | Needs Node.js 22.12+ and Vite 6.4+ as a peer dependency; unawaited `resolves`/`rejects` assertions fail the test; `clearMocks` defaults to `true`; fake timers also mock Temporal |
| Jest 30 | Native ESM still needs `--experimental-vm-modules`, and there `jest.mock` is not hoisted: use `jest.unstable_mockModule()`, then `await import()` the module under test; alias matchers such as `toBeCalled` and `toThrowError` were removed |
| `node:test` | Module mocks need `--experimental-test-module-mocks`; coverage is experimental; `mock.timers` is stable from Node.js 23.1, still experimental on 22 |

An unexplained snapshot update usually means `-u` was run to silence a failure. Testing Library needs no UI framework; call `userEvent.setup()` inside the test before rendering, use `findBy*` for async updates, and import the jest-dom matchers from `@testing-library/jest-dom/vitest` or `@testing-library/jest-dom` in a setup file.

```javascript
// ✅ msw-setup.js, listed in the runner's setup files: mock the network, not fetch
import { afterAll, afterEach, beforeAll } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

export const server = setupServer(
  http.get('https://api.example.com/users/:id', ({ params }) => HttpResponse.json({ id: params.id, name: 'Alice' })),
);
beforeAll(() => server.listen({ onUnhandledRequest: 'error' })); // the default only warns
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
// One test covers the error path with server.use(http.get(url, () => new HttpResponse(null, { status: 500 })))
```

---

## Linting & Tooling

ESLint 10 reads only flat config (`eslint.config.*`): `.eslintrc.*` and `.eslintignore` are ignored, `/* eslint-env */` comments are errors, `radix` always requires a radix, and `eslint:recommended` gained `no-unassigned-vars`, `no-useless-assignment`, and `preserve-caught-error`. ESLint 9 reached end of life on 2026-08-06; LWC and Aura lint setups: [lwc.md](salesforce/lwc.md). Opt-in rules that catch bugs from this guide: `eqeqeq` (`{ null: 'ignore' }`), `no-var`, `prefer-const`, `radix`, `no-eval`, `no-implied-eval`, `no-new-func`, `no-promise-executor-return`, `prefer-promise-reject-errors`, and `no-await-in-loop` (as a warning). Type-aware promise rules: [typescript.md](typescript.md#eslint-rules).

Running a linter is optional local analysis: it loads the repository's configuration, and `eslint.config.js` executes repository code, so run it only on trusted code.

JSDoc types with `// @ts-check` (per file) or `checkJs` plus `allowJs` and `noEmit` (per project) type-check plain JavaScript, but gate merges only when `tsc` runs in CI. TypeScript 7 no longer recognizes `@enum`, `@class` on constructor functions, Closure-style function types (`function(string): void`), a bare `?` type, postfix `!`, or values used as types (use `typeof`).

---

## Runtime availability of newer APIs

Checked on Node.js 22.23, 24.21, and 26.10; for browsers, check the project's browserslist target.

| API | Node.js | Notes |
| --- | --- | --- |
| `toSorted`, `toReversed`, `toSpliced`, `with`; `Object.groupBy`; `Promise.withResolvers`; `Array.fromAsync`; `Set` methods (`union`, `intersection`, …); Iterator helpers | 22+ | `Object.groupBy` returns a null-prototype object |
| `Promise.try`, `RegExp.escape`, `Float16Array`, `Error.isError`, `using`/`await using` | 24+ | Node.js 22 has `Symbol.dispose`, so TypeScript-downleveled `using` runs there |
| Temporal | 26 | Also Chrome and Edge 144+ and Firefox 139+; not Safari 27 |
| `import defer` | not shipped | TypeScript 5.9 accepts the syntax; Node.js 26 rejects it |

---

## References

- [MDN JavaScript reference](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference)
- [TC39 finished proposals](https://github.com/tc39/proposals/blob/main/finished-proposals.md)
- [OWASP Prototype Pollution Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Prototype_Pollution_Prevention_Cheat_Sheet.html)
- [ESLint: Migrate to v10.x](https://eslint.org/docs/latest/use/migrate-to-10.0.0)
- [Vitest migration guide](https://vitest.dev/guide/migration)
