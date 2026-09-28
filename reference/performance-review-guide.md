# Performance Review Guide

A performance review guide covering the frontend, backend, database, algorithmic complexity, API performance, and Salesforce governor limits.

## Table of Contents

- [Frontend Performance (Core Web Vitals)](#frontend-performance-core-web-vitals)
- [JavaScript Performance](#javascript-performance)
- [Memory Management](#memory-management)
- [Database Performance](#database-performance)
- [API Performance](#api-performance)
- [Algorithmic Complexity](#algorithmic-complexity)
- [Salesforce Platform Performance](#salesforce-platform-performance)
- [Performance Review Checklist](#performance-review-checklist)
- [Performance Metric Thresholds](#performance-metric-thresholds)
- [Recommended Tools](#recommended-tools)
- [Low-Level Efficiency Anti-Patterns](#low-level-efficiency-anti-patterns)
- [References](#references)

---

## Frontend Performance (Core Web Vitals)

### Core metrics (2024)

| Metric | Full name | Target | What it measures |
|------|------|--------|------|
| **LCP** | Largest Contentful Paint | ≤ 2.5s | Time to render the largest content element |
| **INP** | Interaction to Next Paint | ≤ 200ms | Interaction responsiveness (replaced FID in 2024) |
| **CLS** | Cumulative Layout Shift | ≤ 0.1 | Unexpected layout movement |
| **FCP** | First Contentful Paint | ≤ 1.8s | Time to the first rendered content |
| **TBT** | Total Blocking Time | ≤ 200ms | Time the main thread is blocked |

### LCP checks

```javascript
// ❌ Lazy-loading the LCP image delays critical content
<img src="hero.jpg" loading="lazy" />

// ✅ Load the LCP image immediately
<img src="hero.jpg" fetchpriority="high" />

// ❌ Unoptimized image format
<img src="hero.png" />  // PNG file is too large

// ✅ Modern image formats + responsive images
<picture>
  <source srcset="hero.avif" type="image/avif" />
  <source srcset="hero.webp" type="image/webp" />
  <img src="hero.jpg" alt="Hero" />
</picture>
```

**Review points:**
- [ ] Does the LCP element set `fetchpriority="high"`?
- [ ] Are WebP/AVIF formats used?
- [ ] Is there server-side rendering or static generation?
- [ ] Is the CDN configured correctly?

### FCP checks

```html
<!-- ❌ Render-blocking CSS -->
<link rel="stylesheet" href="all-styles.css" />

<!-- ✅ Inline the critical CSS + load the rest asynchronously -->
<style>/* Critical above-the-fold styles */</style>
<link rel="preload" href="styles.css" as="style" onload="this.onload=null;this.rel='stylesheet'" />

<!-- ❌ Render-blocking font -->
@font-face {
  font-family: 'CustomFont';
  src: url('font.woff2');
}

<!-- ✅ Optimized font display -->
@font-face {
  font-family: 'CustomFont';
  src: url('font.woff2');
  font-display: swap;  /* Show a system font first, swap once the font loads */
}
```

### INP checks

```javascript
// ❌ A long task blocks the main thread
button.addEventListener('click', () => {
  // 500ms of synchronous work
  processLargeData(data);
  updateUI();
});

// ✅ Split long tasks
const yieldToMain = () => globalThis.scheduler?.yield?.() ?? new Promise((resolve) => setTimeout(resolve, 0));

button.addEventListener('click', async () => {
  // Yield to the main thread
  await yieldToMain();

  // Process in chunks
  for (const chunk of chunks) {
    processChunk(chunk);
    await yieldToMain();
  }
  updateUI();
});

// ✅ Use a Web Worker for heavy computation
const worker = new Worker('heavy-computation.js');
worker.postMessage(data);
worker.onmessage = (e) => updateUI(e.data);
```

### CLS checks

```css
/* ❌ Media without dimensions */
img { width: 100%; }

/* ✅ Reserve the space */
img {
  width: 100%;
  aspect-ratio: 16 / 9;
}

/* ❌ Dynamically inserted content shifts the layout */
.ad-container { }

/* ✅ Reserve a fixed height */
.ad-container {
  min-height: 250px;
}
```

**CLS checklist:**
- [ ] Do images/videos have width/height or aspect-ratio?
- [ ] Does font loading use `font-display: swap`?
- [ ] Is space reserved for dynamic content?
- [ ] Is inserting content above existing content avoided?

---

## JavaScript Performance

### Code splitting and lazy loading

```javascript
// ❌ Load all code up front
import { HeavyChart } from './charts';
import { PDFExporter } from './pdf';
import { AdminPanel } from './admin';

// ✅ Load on demand, inside the handler that needs it
exportButton.addEventListener('click', async () => {
  try {
    const { exportPdf } = await import('./pdf.js');
    await exportPdf(report);
  } catch (error) {
    showError(error);
  }
});

// ✅ Route-level code splitting (router-agnostic)
const routes = {
  '/dashboard': () => import('./pages/dashboard.js'),
  '/admin': () => import('./pages/admin.js'),
};
// The router awaits routes[path]() on navigation, so each page ships as its own chunk
```

> 📖 See [Dynamic import() and code splitting](javascript.md#dynamic-import-and-code-splitting) in the JavaScript Guide.

### Bundle size optimization

```javascript
// ❌ Import the entire library
import _ from 'lodash';
import moment from 'moment';

// ✅ Import only what you use
import debounce from 'lodash/debounce';
import { format } from 'date-fns';

// ❌ Defeats tree shaking
export default {
  fn1() {},
  fn2() {},  // unused, but still bundled
};

// ✅ Named exports support tree shaking
export function fn1() {}
export function fn2() {}
```

**Bundle checklist:**
- [ ] Is dynamic import() used for code splitting?
- [ ] Are large libraries imported selectively?
- [ ] Has the bundle size been analyzed? (webpack-bundle-analyzer)
- [ ] Are there unused dependencies?

### List rendering

Paginate or virtualize long lists. When rows are built by hand, create them with `createElement` and `textContent`, collect them in a `DocumentFragment`, and swap them in with one `replaceChildren` call.

```javascript
// ❌ Render the whole list at once
function renderList(list, items) {
  for (const item of items) {
    const li = document.createElement('li');
    li.textContent = item.name;
    list.append(li);
  }  // 10,000 items = 10,000 DOM nodes
}

// ✅ Paginate: render one page of rows in a single DOM update
function renderPage(list, items, page, pageSize = 50) {
  const fragment = document.createDocumentFragment();
  for (const item of items.slice(page * pageSize, (page + 1) * pageSize)) {
    const li = document.createElement('li');
    li.textContent = item.name;
    fragment.append(li);
  }
  list.replaceChildren(fragment);
}

// ✅ Thousands of rows in one scrolling view: use a virtual-scrolling library that renders only the visible rows
// (in LWC, lightning-datatable with enable-infinite-loading loads more rows as the user scrolls)
```

```css
/* ✅ Let the browser skip layout and paint for off-screen rows */
.results > li {
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
```

**Large data review points:**
- [ ] Do lists with more than 100 items use pagination or virtual scrolling?
- [ ] Do tables support pagination or virtualization?
- [ ] Is anything rendered in full when only part of it is visible?

---

## Memory Management

### Common memory leaks

Every setup needs a matching teardown. The examples pair `mount()` with `unmount()`; in a component, the teardown belongs in the framework's teardown hook (for example, LWC `disconnectedCallback`).

#### 1. Event listeners that are never removed

```javascript
// ❌ The listener outlives the component
function mount() {
  window.addEventListener('resize', handleResize);
}

// ✅ Register with an AbortSignal and abort it on teardown
let controller;

function mount() {
  controller = new AbortController();
  window.addEventListener('resize', handleResize, { signal: controller.signal });
}

function unmount() {
  controller.abort();  // removes every listener registered with this signal
}
```

#### 2. Timers that are never cleared

```javascript
// ❌ The timer is never cleared
function mount() {
  setInterval(fetchData, 5000);
}

// ✅ Keep the handle and clear it on teardown
let timer;

function mount() {
  timer = setInterval(fetchData, 5000);
}

function unmount() {
  clearInterval(timer);
}
```

#### 3. Closure references

```javascript
// ❌ The closure holds a reference to a large object
function createHandler() {
  const largeData = new Array(1000000).fill('x');

  return function handler() {
    // largeData is captured by the closure and cannot be garbage-collected
    console.log(largeData.length);
  };
}

// ✅ Keep only the data you need
function createHandler() {
  const largeData = new Array(1000000).fill('x');
  const length = largeData.length;  // keep only the value you need

  return function handler() {
    console.log(length);
  };
}
```

#### 4. Subscriptions that are never closed

```javascript
// ❌ The WebSocket/EventSource is never closed
function mount() {
  const ws = new WebSocket('wss://...');
  ws.onmessage = handleMessage;
}

// ✅ Close the connection on teardown
let ws;

function mount() {
  ws = new WebSocket('wss://...');
  ws.onmessage = handleMessage;
}

function unmount() {
  ws.close();
}
```

### Memory checklist

```markdown
- [ ] Does every setup (listener, timer, subscription, socket) have a matching teardown?
- [ ] Are event listeners removed when the component is torn down?
- [ ] Are timers cleared?
- [ ] Are WebSocket/SSE connections closed?
- [ ] Are large objects released promptly?
- [ ] Do global variables accumulate data?
```

### Detection tools

| Tool | Purpose |
|------|------|
| Chrome DevTools Memory | Heap snapshot analysis |
| MemLab (Meta) | Automated memory-leak detection |
| Performance Monitor | Real-time memory monitoring |

---

## Database Performance

### The N+1 query problem

```python
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

# ❌ N+1 problem - 1 + N queries
users = session.scalars(select(User)).all()  # 1 query
for user in users:
    print(user.profile.bio)  # N queries (one per user)

# ✅ Eager loading - one query with a JOIN
users = session.scalars(select(User).options(joinedload(User.profile))).all()
for user in users:
    print(user.profile.bio)  # no extra queries

# ✅ Many-to-many: selectinload adds one SELECT ... WHERE ... IN (...) query
posts = session.scalars(select(Post).options(selectinload(Post.tags))).all()
```

```javascript
// TypeORM example
// ❌ N+1 problem
const users = await userRepository.find();
for (const user of users) {
  const posts = await user.posts;  // runs a query on every iteration
}

// ✅ Eager Loading
const users = await userRepository.find({
  relations: ['posts'],
});
```

> 📖 Detection and fixes per ORM (and for Salesforce): [N+1 Queries](cross-cutting/n-plus-one-queries.md#language-specific-implementations).

### Index optimization

```sql
-- ❌ Full table scan
SELECT * FROM orders WHERE status = 'pending';

-- ✅ Add an index
CREATE INDEX idx_orders_status ON orders(status);

-- ❌ Index not used: a function is applied to the column
SELECT * FROM users WHERE YEAR(created_at) = 2024;

-- ✅ A range query can use the index
SELECT * FROM users
WHERE created_at >= '2024-01-01' AND created_at < '2025-01-01';

-- ❌ Index not used: leading wildcard in LIKE
SELECT * FROM products WHERE name LIKE '%phone%';

-- ✅ A prefix match can use the index
SELECT * FROM products WHERE name LIKE 'phone%';
```

### Query optimization

```sql
-- ❌ SELECT * fetches columns you do not need
SELECT * FROM users WHERE id = 1;

-- ✅ Select only the columns you need
SELECT id, name, email FROM users WHERE id = 1;

-- ❌ No LIMIT on a large table
SELECT * FROM logs WHERE type = 'error';

-- ✅ Paginated query
SELECT * FROM logs WHERE type = 'error' LIMIT 100 OFFSET 0;

-- ❌ A query inside a loop
for id in user_ids:
    cursor.execute("SELECT * FROM users WHERE id = %s", (id,))

-- ✅ One batched query
cursor.execute("SELECT * FROM users WHERE id IN %s", (tuple(user_ids),))
```

### Database checklist

```markdown
🔴 Must check:
- [ ] Are there N+1 queries?
- [ ] Are the WHERE-clause columns indexed?
- [ ] Is SELECT * avoided?
- [ ] Do queries on large tables have a LIMIT?

🟡 Should check:
- [ ] Was EXPLAIN used to analyze the query plan?
- [ ] Is the column order of composite indexes correct?
- [ ] Are there unused indexes?
- [ ] Is the slow-query log monitored?
```

---

## API Performance

### Pagination

```javascript
// ❌ Return every row
app.get('/users', async (req, res) => {
  const users = await User.findAll();  // may return 100,000 rows
  res.json(users);
});

// ✅ Paginate + cap the page size
app.get('/users', async (req, res) => {
  const page = Math.max(Number.parseInt(req.query.page, 10) || 1, 1);
  const limit = Math.min(Math.max(Number.parseInt(req.query.limit, 10) || 20, 1), 100);  // 1 to 100
  const offset = (page - 1) * limit;

  const { rows, count } = await User.findAndCountAll({
    limit,
    offset,
    order: [['id', 'ASC']],
  });

  res.json({
    data: rows,
    pagination: {
      page,
      limit,
      total: count,
      totalPages: Math.ceil(count / limit),
    },
  });
});
```

### Caching strategies

```javascript
// ✅ Redis cache example
async function getUser(id) {
  const cacheKey = `user:${id}`;

  // 1. Check the cache
  const cached = await redis.get(cacheKey);
  if (cached) {
    return JSON.parse(cached);
  }

  // 2. Query the database
  const user = await db.users.findById(id);

  // 3. Write to the cache (with an expiry)
  await redis.setex(cacheKey, 3600, JSON.stringify(user));

  return user;
}

// ✅ HTTP cache headers
app.get('/static-data', (req, res) => {
  res.set({
    'Cache-Control': 'public, max-age=86400',  // 24 hours
    'ETag': 'abc123',
  });
  res.json(data);
});
```

### Response compression

```javascript
// ✅ Enable Gzip/Brotli compression
const compression = require('compression');
app.use(compression());

// ✅ Return only the fields the client needs, checked against an allowlist
// Request: GET /users?fields=id,name,email
const ALLOWED_FIELDS = new Set(['id', 'name', 'email']);

app.get('/users', async (req, res) => {
  const requested = (req.query.fields?.split(',') ?? []).filter((f) => ALLOWED_FIELDS.has(f));
  const attributes = requested.length > 0 ? requested : ['id', 'name'];
  const users = await User.findAll({
    attributes,
  });
  res.json(users);
});
```

### Rate limiting

```javascript
// ✅ Rate limiting
const rateLimit = require('express-rate-limit');

const limiter = rateLimit({
  windowMs: 60 * 1000,  // 1 minute
  max: 100,             // at most 100 requests
  message: { error: 'Too many requests, please try again later.' },
});

app.use('/api/', limiter);
```

### API checklist

```markdown
- [ ] Do list endpoints paginate?
- [ ] Is the page size capped?
- [ ] Is hot data cached?
- [ ] Is response compression enabled?
- [ ] Is there rate limiting?
- [ ] Are only the necessary fields returned?
```

---

## Algorithmic Complexity

### Common complexities compared

| Complexity | Name | 10 items | 1,000 items | 1M items | Example |
|--------|------|-------|---------|----------|------|
| O(1) | Constant | 1 | 1 | 1 | Hash lookup |
| O(log n) | Logarithmic | 3 | 10 | 20 | Binary search |
| O(n) | Linear | 10 | 1000 | 1M | Array traversal |
| O(n log n) | Linearithmic | 33 | 10000 | 20M | Quicksort |
| O(n²) | Quadratic | 100 | 1M | 1 trillion | Nested loops |
| O(2ⁿ) | Exponential | 1024 | ∞ | ∞ | Naive recursive Fibonacci |

### Warning signs in code review

```javascript
// ❌ O(n²) - nested loops
function findDuplicates(arr) {
  const duplicates = [];
  for (let i = 0; i < arr.length; i++) {
    for (let j = i + 1; j < arr.length; j++) {
      if (arr[i] === arr[j]) {
        duplicates.push(arr[i]);
      }
    }
  }
  return duplicates;
}

// ✅ O(n) - use a Set
function findDuplicates(arr) {
  const seen = new Set();
  const duplicates = new Set();
  for (const item of arr) {
    if (seen.has(item)) {
      duplicates.add(item);
    }
    seen.add(item);
  }
  return [...duplicates];
}
```

```javascript
// ❌ O(n²) - includes() runs on every iteration
function removeDuplicates(arr) {
  const result = [];
  for (const item of arr) {
    if (!result.includes(item)) {  // includes is O(n)
      result.push(item);
    }
  }
  return result;
}

// ✅ O(n) - use a Set
function removeDuplicates(arr) {
  return [...new Set(arr)];
}
```

```javascript
// ❌ O(n) lookup - scans the array every time
const users = [{ id: 1, name: 'A' }, { id: 2, name: 'B' }, ...];

function getUser(id) {
  return users.find(u => u.id === id);  // O(n)
}

// ✅ O(1) lookup - use a Map
const userMap = new Map(users.map(u => [u.id, u]));

function getUser(id) {
  return userMap.get(id);  // O(1)
}
```

### Space complexity

```javascript
// ⚠️ O(n) space - creates a new array
const doubled = arr.map(x => x * 2);

// ✅ O(1) space - modify in place (if that is allowed)
for (let i = 0; i < arr.length; i++) {
  arr[i] *= 2;
}

// ⚠️ Deep recursion can overflow the stack
function factorial(n) {
  if (n <= 1) return 1;
  return n * factorial(n - 1);  // O(n) stack space
}

// ✅ Iterative version, O(1) space
function factorial(n) {
  let result = 1;
  for (let i = 2; i <= n; i++) {
    result *= i;
  }
  return result;
}
```

### Example review comments

```markdown
💡 "This nested loop is O(n²); it will be slow once the data grows"
🔴 "Array.includes() inside this loop makes the whole thing O(n²); use a Set"
🟡 "This recursion can get deep enough to overflow the stack; consider an iterative version"
```

---

## Salesforce Platform Performance

On Salesforce, most performance defects surface as governor-limit exceptions rather than slow pages: the transaction fails and rolls back. Review each entry point at bulk volume and state the arithmetic in the finding. The limit numbers live in the [Salesforce Platform Guide](salesforce/platform.md#governor-limits); this section lists what to look for.

### Governor limits are the performance budget

- Limits apply per transaction, and the transaction includes everything a save sets off: other triggers, record-triggered flows, and roll-up summary updates on parent records.
- Exceeding a limit throws `System.LimitException`, which cannot be caught, so code that works on small sandbox data fails outright once data volume grows.
- Count SOQL queries, DML statements, callouts, and enqueued jobs per invocation, not per record: trigger chunks, batch scopes, and platform-event batches all carry many records. The fixes (collect Ids, query once into a `Map`, one DML statement per object) are in [Apex: Bulkification](salesforce/apex.md#bulkification).

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

- Load a component's data with one Apex call that returns everything it renders; calling Apex once per row multiplies server requests and transactions.
- Mark read-only Apex methods `@AuraEnabled(cacheable=true)` so results are cached on the client. A cacheable method must not perform DML, and wired results need `refreshApex` after a write ([The LWC-Apex Contract](salesforce/lwc.md#the-lwc-apex-contract)).
- Prefer Lightning Data Service (`lightning-record-form`, or `getRecord` from `lightning/uiRecordApi`) for single-record reads and writes: it shares one cache across components and needs no Apex.
- Page large tables (for example, `lightning-datatable` with `enable-infinite-loading`) and return only the fields the component shows. More in [LWC: Performance](salesforce/lwc.md#performance).

### Flow performance

- A Get Records, Create/Update/Delete Records, or Apex action element inside a Loop runs once per iteration and consumes limits the way SOQL or DML inside an Apex loop does. Outside loops, record-triggered flows are bulkified across the records saved together ([Flows: Bulk-Safe Design](salesforce/flows.md#bulk-safe-design)).
- Use a before-save flow (Fast Field Updates) for updates to the triggering record: it sets the fields before the save, with no extra DML statement and no second pass through triggers and flows.
- Tight entry conditions, including "Only when a record is updated to meet the condition requirements", keep a flow from running on every save.
- Move callouts and long-running work to an asynchronous or scheduled path.

---

## Performance Review Checklist

### 🔴 Must check (blocking)

**Frontend:**
- [ ] Is the LCP image lazy-loaded? (It should not be)
- [ ] Is `transition: all` used?
- [ ] Are width/height/top/left animated?
- [ ] Are lists with more than 100 items paginated or virtualized?

**Backend:**
- [ ] Are there N+1 queries?
- [ ] Do list endpoints paginate?
- [ ] Is SELECT * used on large tables?

**Salesforce:**
- [ ] Is there any SOQL, DML, or callout inside a loop (Apex loops or Flow Loop elements)?
- [ ] Do queries on large objects filter on selective, indexed fields?

**General:**
- [ ] Are there nested loops that are O(n²) or worse?
- [ ] Are event listeners, timers, and subscriptions cleaned up on teardown?

### 🟡 Should check (important)

**Frontend:**
- [ ] Is code splitting used?
- [ ] Are large libraries imported selectively?
- [ ] Do images use WebP/AVIF?
- [ ] Are there unused dependencies?

**Backend:**
- [ ] Is hot data cached?
- [ ] Are the WHERE columns indexed?
- [ ] Is there slow-query monitoring?

**API:**
- [ ] Is response compression enabled?
- [ ] Is there rate limiting?
- [ ] Are only the necessary fields returned?

**Salesforce:**
- [ ] Are read-only Apex methods called from LWC marked `cacheable=true`?
- [ ] Are nested loops over collections replaced with `Map` lookups to save CPU time?
- [ ] Do updates to the triggering record use a before-save flow or a before trigger rather than an after-save update?

### 🟢 Nice to have (suggestion)

- [ ] Has the bundle size been analyzed?
- [ ] Is a CDN used?
- [ ] Is there performance monitoring?
- [ ] Have performance benchmarks been run?

---

## Performance Metric Thresholds

### Frontend metrics

| Metric | Good | Needs improvement | Poor |
|------|-----|--------|-----|
| LCP | ≤ 2.5s | 2.5-4s | > 4s |
| INP | ≤ 200ms | 200-500ms | > 500ms |
| CLS | ≤ 0.1 | 0.1-0.25 | > 0.25 |
| FCP | ≤ 1.8s | 1.8-3s | > 3s |
| Bundle Size (JS) | < 200KB | 200-500KB | > 500KB |

### Backend metrics

| Metric | Good | Needs improvement | Poor |
|------|-----|--------|-----|
| API response time | < 100ms | 100-500ms | > 500ms |
| Database query | < 50ms | 50-200ms | > 200ms |
| Page load | < 3s | 3-5s | > 5s |

---

## Recommended Tools

### Frontend performance

| Tool | Purpose |
|------|------|
| [Lighthouse](https://developer.chrome.com/docs/lighthouse/) | Core Web Vitals testing |
| [WebPageTest](https://www.webpagetest.org/) | Detailed performance analysis |
| [webpack-bundle-analyzer](https://github.com/webpack-contrib/webpack-bundle-analyzer) | Bundle analysis |
| [Chrome DevTools Performance](https://developer.chrome.com/docs/devtools/performance/) | Runtime performance profiling |

### Memory leak detection

| Tool | Purpose |
|------|------|
| [MemLab](https://github.com/facebookincubator/memlab) | Automated memory-leak detection |
| Chrome Memory Tab | Heap snapshot analysis |

### Backend performance

| Tool | Purpose |
|------|------|
| EXPLAIN | Database query plan analysis |
| [pganalyze](https://pganalyze.com/) | PostgreSQL performance monitoring |
| [New Relic](https://newrelic.com/) / [Datadog](https://www.datadoghq.com/) | APM monitoring |

### Salesforce

| Tool | Purpose |
|------|------|
| [Salesforce Code Analyzer](https://developer.salesforce.com/docs/platform/salesforce-code-analyzer/guide/code-analyzer.html) | Local static analysis; PMD `OperationWithLimitsInLoop` and `OperationWithHighCostInLoop` flag limit-consuming and expensive calls inside loops |
| Query Plan tool, debug logs | Query selectivity and limit usage per transaction; they need an org, so ask the author or CI for the output |

---

## Low-Level Efficiency Anti-Patterns

Code-level efficiency mistakes, separate from architecture-level performance problems. This section complements the resource-management and concurrency defects already covered in [common-bugs-checklist.md](common-bugs-checklist.md).

### Unnecessary repeated work

- [ ] Is the same function / query called more than once in the same request/render?
- [ ] Is a file / config read again on every loop iteration (loop-invariant work)?
- [ ] Can a computed result be cached or passed downstream?

```typescript
// ❌ Loop-invariant work repeated on every iteration
for (const path of paths) {
  const config = JSON.parse(fs.readFileSync("config.json", "utf-8"));
  processFile(path, config);
}

// ✅ Hoist it out of the loop
const config = JSON.parse(fs.readFileSync("config.json", "utf-8"));
for (const path of paths) processFile(path, config);
```

### Missed concurrency opportunities

- [ ] Are independent async operations awaited one after another?
- [ ] Could they run concurrently with `Promise.all` / `asyncio.gather` / `asyncio.TaskGroup`?

```typescript
// ❌ Sequential awaits
const a = await fetchA();
const b = await fetchB();

// ✅ Concurrent
const [a, b] = await Promise.all([fetchA(), fetchB()]);
```

> 📖 Python version with cancellation on failure: [asyncio + TaskGroup](cross-cutting/async-concurrency-patterns.md#python-asyncio--taskgroup).

### Hot-path bloat

- [ ] Does module-level / import-time code do heavy work (file I/O, network, building large objects)?
- [ ] Is there initialization on the per-request path that could be deferred?
- [ ] Does startup code block the first request?

### Unbounded data structures

> For resource-lifecycle defects (unclosed connections, listeners never removed, timers never cleared), see [common-bugs-checklist.md → Resource Management](common-bugs-checklist.md#resource-management). This section focuses on *capacity limits*.

- [ ] Do global dicts / lists / caches have a `max-size` or TTL?
- [ ] Do accumulating structures (queues, logs, metrics buffers) have an upper bound?
- [ ] Are per-request objects kept alive by long-lived references, so they cannot be garbage-collected?

```python
# ❌ Unbounded cache
_cache: dict[str, Any] = {}

# ✅ Bounded LRU
from functools import lru_cache

@lru_cache(maxsize=256)
def get_cached(key: str) -> Any:
    return expensive_computation(key)
```

---

## References

- [Core Web Vitals - web.dev](https://web.dev/articles/vitals)
- [Optimizing Core Web Vitals - Vercel](https://vercel.com/guides/optimizing-core-web-vitals-in-2024)
- [MemLab - Meta Engineering](https://engineering.fb.com/2022/09/12/open-source/memlab/)
- [Big O Cheat Sheet](https://www.bigocheatsheet.com/)
- [N+1 Query Problem - Stack Overflow](https://stackoverflow.com/questions/97197/what-is-the-n1-selects-problem-in-orm-object-relational-mapping)
- [API Performance Optimization](https://algorithmsin60days.com/blog/optimizing-api-performance/)
- [Execution Governors and Limits (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm)
- [SOQL query selectivity (Salesforce Help)](https://help.salesforce.com/s/articleView?id=000385218&language=en_US&type=1)
- [Flow bulkification in transactions (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.flow_concepts_bulkification.htm&language=en_US&type=5)
- [LWC data guidelines (Salesforce Developers)](https://developer.salesforce.com/docs/platform/lwc/guide/data-guidelines)
