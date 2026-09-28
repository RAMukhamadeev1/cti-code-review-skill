# Performance Review Guide

> Performance defects a diff can show: work that grows with input size, extra round trips, unbounded memory, render-path costs, and Salesforce governor-limit use. Measurements (Core Web Vitals, latency, query plans, bundle size) need runtime evidence, so ask the author for them instead of estimating.
> Related: [N+1 Queries](cross-cutting/n-plus-one-queries.md) · JavaScript runtime details in [javascript.md](javascript.md) · limit numbers in [Governor Limits](salesforce/platform.md#governor-limits)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Frontend → [Frontend Performance (Core Web Vitals)](#frontend-performance-core-web-vitals)

- [ ] The likely LCP image (hero, above the fold) is not `loading="lazy"`.
- [ ] Images, videos, embeds, and ad slots the diff adds reserve their space (`width` and `height` attributes, or an `aspect-ratio` that matches the media); nothing is inserted above content after load.
- [ ] New web fonts limit the late layout shift (`font-display: optional`, or a metric-matched fallback); `font-display: swap` shows text sooner but does not prevent the shift.
- [ ] Event handlers the diff adds don't run long synchronous work before the next paint.

### Bundles and rendering → [JavaScript Performance](#javascript-performance)

- [ ] Heavy, rarely used modules are loaded with dynamic `import()` where the repo already code-splits; a static import is not a finding on its own.
- [ ] Large libraries are imported by path or named export where they support it; ask the author for bundle-analyzer output when a new dependency looks large.
- [ ] Lists that grow with user data paginate or virtualize; a short, bounded list is not a finding.
- [ ] Listeners, timers, observers, and subscriptions the diff creates are removed on teardown.

### Database → [Database Performance](#database-performance)

- [ ] No query per item in a loop ([N+1 Queries](cross-cutting/n-plus-one-queries.md)).
- [ ] Queries on tables that grow are bounded, and paginated queries have a deterministic `ORDER BY`.
- [ ] New predicates on large tables don't wrap the column in a function, lead with a `%` wildcard, or negate it, unless a matching index exists. Whether an index exists needs the migrations or `EXPLAIN` output: check the diff, or ask the author.

### API → [API Performance](#api-performance)

- [ ] List endpoints paginate with a capped page size.
- [ ] Caches have an expiry, an invalidation path on writes, and keys that include every input that changes the result (user, tenant, locale).
- [ ] ETags change when the representation changes; per-user responses are never `Cache-Control: public`.
- [ ] Compression and rate limiting: check where the repo configures them (middleware, proxy, gateway) before reporting that a new endpoint lacks them.

### Algorithms and efficiency → [Algorithmic Complexity](#algorithmic-complexity) · [Low-Level Efficiency Anti-Patterns](#low-level-efficiency-anti-patterns)

- [ ] Loops over two data-sized collections use a `Set` or `Map` instead of a nested scan; the finding states the input sizes.
- [ ] Loop-invariant work (file reads, parsing, regex compilation, describe calls) is hoisted out of loops.
- [ ] Independent I/O calls aren't awaited one after another.
- [ ] Import-time and per-request initialization do no heavy I/O.
- [ ] Module-level caches, maps, and queues have a size bound or a TTL.

### Salesforce → [Salesforce Platform Performance](#salesforce-platform-performance)

- [ ] No SOQL, DML, callout, or enqueue inside a loop (Apex loops or Flow Loop elements), with the limit math stated.
- [ ] Queries on large objects filter on selective, indexed fields; ask the author for Query Plan output when selectivity is unclear.
- [ ] Nested loops over two collections use a `Map` keyed by Id.
- [ ] Read-only Apex methods called from LWC are `cacheable=true`, and writes refresh the cache.
- [ ] Updates to the triggering record use a before-save flow or a before trigger.

### Severity → [Severity Calibration](salesforce/platform.md#severity-calibration)

- [ ] 🔴 only for failure at realistic volume: a governor-limit breach (row 1 of the calibration table), an unbounded query or response on a request path, an N+1 on a list that grows with data, or memory that grows without bound in a long-running process.
- [ ] 🟡 for costs that grow with data or traffic without failing; 🟢 or 💡 for micro-optimizations and style (`transition: all`, image formats, a suggested bundle analysis).
- [ ] Every finding names the input size or volume that makes it matter.

---

## Frontend Performance (Core Web Vitals)

Core Web Vitals are LCP, INP, and CLS; "good" is LCP ≤ 2.5 s, INP ≤ 200 ms, and CLS ≤ 0.1 at the 75th percentile of page loads. INP replaced FID in March 2024. FCP and TBT are diagnostics, not Core Web Vitals. None of them can be measured from a diff: when a finding depends on them, ask for Lighthouse or field data.

```html
<!-- ❌ The LCP image waits for lazy loading, and its box has no size until the file arrives -->
<img src="hero.jpg" loading="lazy" alt="Spring collection">

<!-- ✅ Load it eagerly with high priority, and reserve its box with intrinsic dimensions -->
<img src="hero.jpg" fetchpriority="high" width="1600" height="900" alt="Spring collection">
```

```css
/* ✅ Scale images to the container while keeping the ratio from the width and height attributes */
img { max-width: 100%; height: auto; }
```

- **Fonts.** `font-display: swap` shows fallback text at once, then shifts the layout when the web font arrives, unless a fallback `@font-face` matches its metrics (`size-adjust`, `ascent-override`). `font-display: optional` avoids the late swap. Swap gets text on screen sooner; it is not a CLS fix.
- **Late content.** Reserve space for content inserted after load (ads, embeds, banners), for example with `min-height`, and don't insert it above what the user is reading.
- **Responsiveness (INP).** A handler that runs long synchronous work delays the next paint; split the work and yield between chunks, or move it to a worker ([Don't block the event loop or main thread](javascript.md#dont-block-the-event-loop-or-main-thread)).
- **Animations.** Animating `width`, `height`, `top`, or `left` runs layout on every frame, where `transform` and `opacity` usually don't; `transition: all` animates properties nobody meant to. Both are 🟢 unless the animation runs on a hot interaction.

## JavaScript Performance

- **Code splitting.** Load heavy, rarely used modules (charts, PDF export, editors, admin screens) with dynamic `import()` in the handler or route that needs them, where the repo's bundler already splits chunks. Caching the load promise and handling chunk-load failures: [Dynamic import() and code splitting](javascript.md#dynamic-import-and-code-splitting).
- **Tree shaking.** Import by path or named export where the library supports it (`import debounce from 'lodash/debounce'`, not all of `lodash`). A default export of an object literal (`export default { fn1, fn2 }`) can't be tree-shaken; named exports can ([JavaScript: Modules](javascript.md#modules)).
- **Long lists.** Paginate or virtualize lists that grow with user data. When rows are built by hand, create them with `createElement` and `textContent`, collect them in a `DocumentFragment`, and insert them with one `replaceChildren` call. In LWC, `lightning-datatable` with `enable-infinite-loading` loads rows as the user scrolls.
- **Memory.** Every listener, timer, observer, socket, and subscription the diff creates needs a teardown in the component's teardown hook (for example, LWC `disconnectedCallback`); one `AbortController` signal removes many listeners at once ([Clean up listeners, timers, and observers](javascript.md#clean-up-listeners-timers-and-observers)). A closure keeps everything it captures alive for as long as the closure lives.

```css
/* ✅ Let the browser skip layout and paint for off-screen rows */
.results > li {
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
```

## Database Performance

Query-per-item loops belong to [N+1 Queries](cross-cutting/n-plus-one-queries.md#language-specific-implementations). Beyond them:

- **Bounds and order.** Queries on tables that grow need a `LIMIT` or pagination. A page needs `ORDER BY` on a unique key or tiebreaker, or rows repeat and go missing between pages. Deep `OFFSET`s read and discard every skipped row; on large tables, use keyset pagination.
- **Index use.** Whether an index exists or is used needs the schema: check migrations in the diff, or ask the author for `EXPLAIN` output. Predicates that defeat a plain B-tree index: a function on the column (`WHERE YEAR(created_at) = 2024`; rewrite it as a range or use an expression index), a leading wildcard (`LIKE '%phone%'`; needs a trigram or full-text index, and dropping the leading `%` changes which rows match), and negations. An index on a low-cardinality column such as `status` often goes unused unless the filtered value is rare; a partial or composite index that matches the query serves it better.
- **Columns.** `SELECT *` matters when it pulls large columns (blobs, JSON, long text) through a hot path, or leaks columns added later into an API response; on a primary-key lookup it is not a finding.

```sql
-- ❌ No ORDER BY: rows can repeat or go missing between pages, and OFFSET 5000 scans the skipped rows
SELECT id, created_at, message FROM logs WHERE type = 'error' LIMIT 100 OFFSET 5000;

-- ✅ Keyset pagination (PostgreSQL row comparison), served by an index on (type, created_at, id)
SELECT id, created_at, message FROM logs
WHERE type = 'error' AND (created_at, id) < (:last_created_at, :last_id)
ORDER BY created_at DESC, id DESC
LIMIT 100;
```

## API Performance

```javascript
// ✅ Cache headers for rarely changing public data; Express adds a weak ETag to res.json by default
app.get('/countries', (req, res) => {
  res.set('Cache-Control', 'public, max-age=86400');
  res.json(countries);
});
```

- **Pagination.** Parse `page` and `limit` as integers, clamp `limit` (for example, 1 to 100), and order by a unique key. A total count runs an extra `COUNT` on every request, which is costly on large tables.
- **Caches.** Every entry has an expiry; every write path that changes the source invalidates or updates the entry; the key includes every input that changes the result (user, tenant, locale, permissions). `Cache-Control: public` is never set on per-user responses.
- **ETags.** An ETag must change when the representation changes (a content hash or a version) and is a quoted string; a hard-coded ETag lets clients keep stale data.
- **Compression and rate limiting.** Both are often configured once (middleware such as `compression()` and `express-rate-limit`, or the proxy or gateway); check there before reporting a new endpoint.
- **Field selection.** Fields chosen through the query string (`?fields=`) are checked against an allowlist.

## Algorithmic Complexity

Report complexity only with the input sizes that make it matter ("`orders` is the full export, up to 100k rows"). A nested loop, or `includes`, `find`, or `indexOf` inside a loop, over two data-sized collections costs O(n × m); index one side in a `Set` or `Map`. Small, bounded inputs (a few dozen items) are not a finding.

```javascript
// ❌ O(n × m): includes() scans allowedIds for every order
const visible = orders.filter((order) => allowedIds.includes(order.accountId));

// ✅ O(n + m): build the Set once
const allowed = new Set(allowedIds);
const visibleOrders = orders.filter((order) => allowed.has(order.accountId));
```

Recursion whose depth grows with the input (walking a user-supplied tree) can overflow the stack; an explicit stack or queue avoids it.

## Low-Level Efficiency Anti-Patterns

### Unnecessary repeated work

Look for the same function or query called more than once in one request or render, and for loop-invariant work inside a loop: reading and parsing a config file, compiling a regex, or building a lookup table on every iteration. Hoist it out of the loop, or compute it once and pass it down.

### Missed concurrency opportunities

Independent I/O awaited one call after another adds the latencies together. Run it concurrently when nothing depends on an earlier result: `Promise.all` in JavaScript ([JavaScript: Async & Promises](javascript.md#async--promises)), `asyncio.TaskGroup` in Python ([asyncio + TaskGroup](cross-cutting/async-concurrency-patterns.md#python-asyncio--taskgroup)). Not findings: calls that depend on each other, ordered writes, cursor pagination, and calls kept sequential to respect a rate limit. Fan-out over data-sized input needs a concurrency limit ([Limit concurrency](cross-cutting/async-concurrency-patterns.md#4-limit-concurrency)).

### Hot-path bloat

- Module-level or import-time code that does heavy work (file I/O, network calls, building large objects) slows every cold start and every test run.
- Initialization on the per-request path that could run once at startup.
- Startup work that blocks the first request, such as a cache warm-up that could run in the background.

### Unbounded data structures

Global dicts, lists, caches, queues, and metric buffers need a maximum size or a TTL, and per-request objects must not stay reachable from long-lived references. Lifecycle defects (unclosed connections, listeners never removed) are in [Resource Management](common-bugs-checklist.md#resource-management).

```python
# ❌ Unbounded cache: grows for the life of the process
_cache: dict[str, Any] = {}

# ✅ Bounded LRU
from functools import lru_cache
from typing import Any

@lru_cache(maxsize=256)
def get_cached(key: str) -> Any:
    return expensive_computation(key)
```

---

## Salesforce Platform Performance

On Salesforce, most performance defects surface as governor-limit exceptions rather than slow pages: the transaction fails and rolls back. Review each entry point at bulk volume and state the arithmetic in the finding. The limit numbers live in [Governor Limits](salesforce/platform.md#governor-limits) and the tiers in [Severity Calibration](salesforce/platform.md#severity-calibration); this section lists what to look for.

### Governor limits are the performance budget

- Limits apply per transaction, and the transaction includes everything a save sets off: other triggers, record-triggered flows, and roll-up summary updates on parent records.
- Exceeding a limit throws `System.LimitException`, which cannot be caught, so code that works on small sandbox data fails outright once data volume grows.
- Count SOQL queries, DML statements, callouts, and enqueued jobs per invocation, not per record: trigger chunks, batch scopes, and platform-event batches all carry many records. A limit-consuming call inside a loop is row 1 of the calibration table (🔴). The fixes (collect Ids, query once into a `Map`, one DML statement per object) are in [Apex: Bulkification](salesforce/apex.md#bulkification).

Static analysis: PMD `OperationWithLimitsInLoop`.

### Query selectivity and large data volumes

- On large objects, filter on indexed fields (such as Id, Name, OwnerId, lookup and master-detail fields, CreatedDate, SystemModstamp, and External ID fields). In a trigger, a non-selective query against a large object fails with `System.QueryException: Non-selective query against large object type` instead of just running slowly.
- Leading-wildcard `LIKE` and negative operators such as `!=` and `NOT IN` usually prevent the optimizer from using an index.
- When selectivity is unclear, ask the author for the Query Plan output from their sandbox; do not query the org yourself. Details: [SOQL & SOSL: Selectivity & Large Data Volumes](salesforce/soql-sosl.md#selectivity--large-data-volumes).

Static analysis: PMD `AvoidNonRestrictiveQueries` (unfiltered SOQL and SOSL).

### Apex CPU time

- CPU time covers everything the transaction runs on the application servers (Apex and the automation it sets off), but not time spent in the database or waiting for callouts, so loops exhaust it far more often than queries do.
- Nested loops over two collections cost O(n × m) at bulk volume: index one side in a `Map` keyed by Id.
- Cache describe results instead of calling `Schema.getGlobalDescribe()` in loops, and move work the user does not need to wait for to asynchronous Apex, which has a higher CPU limit ([Async Apex](salesforce/apex.md#async-apex)).

```apex
// ❌ O(n × m) CPU time: nested loops over two collections
for (Opportunity opp : opportunities) {
    for (Account acc : accounts) {
        if (opp.AccountId == acc.Id) {
            opp.Description = acc.Name;
        }
    }
}

// ✅ O(n): index one collection by Id
Map<Id, Account> accountsById = new Map<Id, Account>(accounts);
for (Opportunity opp : opportunities) {
    Account acc = accountsById.get(opp.AccountId);
    if (acc != null) {
        opp.Description = acc.Name;
    }
}
```

Static analysis: PMD `OperationWithHighCostInLoop` (describe calls in loops).

### LWC round trips and caching

- Load a component's data with one Apex call that returns everything it renders; calling Apex once per row multiplies server requests and transactions ([N+1 Queries](cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow)).
- Mark read-only Apex methods `@AuraEnabled(cacheable=true)` so results are cached on the client. A cacheable method must not perform DML, and wired results need `refreshApex` after a write ([The LWC-Apex Contract](salesforce/lwc.md#the-lwc-apex-contract)).
- Prefer Lightning Data Service (`lightning-record-form`, or `getRecord` from `lightning/uiRecordApi`) for single-record reads and writes: it shares one cache across components and needs no Apex.
- Page large tables (for example, `lightning-datatable` with `enable-infinite-loading`) and return only the fields the component shows. More in [LWC: Performance](salesforce/lwc.md#performance).

### Flow performance

- A Get Records, Create/Update/Delete Records, or Apex action element inside a Loop runs once per iteration and consumes limits the way SOQL or DML inside an Apex loop does. Outside loops, record-triggered flows are bulkified across the records saved together ([Flows: Bulk-Safe Design](salesforce/flows.md#bulk-safe-design)).
- Use a before-save flow (Fast Field Updates) for updates to the triggering record: it sets the fields before the save, with no extra DML statement and no second pass through triggers and flows.
- Tight entry conditions, including "Only when a record is updated to meet the condition requirements", keep a flow from running on every save.
- Move callouts and long-running work to an asynchronous or scheduled path.

---

## References

- [Core Web Vitals (web.dev)](https://web.dev/articles/vitals)
- [Optimize Cumulative Layout Shift (web.dev)](https://web.dev/articles/optimize-cls)
- [SOQL query selectivity (Salesforce Help)](https://help.salesforce.com/s/articleView?id=000385218&language=en_US&type=1)
