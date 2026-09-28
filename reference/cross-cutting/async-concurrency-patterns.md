# Async & Concurrency Patterns: Cross-Language Guide

> This guide compares concurrency models and covers common pitfalls, best practices, and structured concurrency patterns, with code examples for JavaScript/TypeScript (Node.js, browsers), Python (asyncio), and Salesforce Apex.

## Table of Contents

- [Concurrency Models Compared](#concurrency-models-compared)
- [Common Pitfalls](#common-pitfalls)
- [Best Practices](#best-practices)
- [Code Examples by Language](#code-examples-by-language)
- [Review Checklist](#review-checklist)

---

## Concurrency Models Compared

| Model | Languages | Core concepts | Pros | Cons |
|------|------|----------|------|------|
| **async/await + Event Loop** | JavaScript/TypeScript (Node.js, browsers), Python (asyncio) | Single-threaded cooperative multitasking | No locks, easy to reason about | Must never block the event loop |
| **Worker threads / processes** | Node `worker_threads`, Web Workers, Python `multiprocessing` / `ProcessPoolExecutor` | Separate threads or processes that exchange messages | True parallelism for CPU-bound work | Startup and serialization cost; no shared state by default |
| **Threads + locks** | Python `threading` (the GIL runs one thread of Python code at a time; free-threaded builds: experimental in 3.13, officially supported but optional in 3.14) | OS threads + shared memory | Blocking I/O runs in parallel; CPU parallelism only on free-threaded builds | Complex lock management, deadlock risk |
| **Asynchronous Apex** | Salesforce | Queueable / Batch / `@future` / Platform Events; each job is a new transaction with fresh limits | Platform-managed | No shared memory; enqueue limits; no ordering guarantee between jobs |

Asynchronous Apex limits (jobs per transaction, daily executions) live in [Governor Limits](../salesforce/platform.md#governor-limits).

### When to choose what

```
I/O-bound (network, database, files):
  → async/await (JavaScript/TypeScript, Python asyncio)

CPU-bound (computation, image processing):
  → worker_threads (Node.js), Web Workers (browsers)
  → multiprocessing / ProcessPoolExecutor (Python)

Mixed:
  → async + a worker-thread pool (Node.js)
  → async + run_in_executor / asyncio.to_thread (Python)

Salesforce Apex (no threads; every async job is a separate transaction):
  → Queueable: follow-up work after the current transaction, chaining, callouts
  → Batch Apex: large record sets processed in chunks
  → Platform Events: decoupled, event-driven processing
  → @future: legacy; prefer Queueable in new code
```

---

## Common Pitfalls

### Pitfall 1: Race condition

Several concurrent tasks read and write shared state, and the result depends on the order in which they run.

```
// Generic pseudocode
counter = 0

task1: counter += 1   // reads counter=0, writes counter=1
task2: counter += 1   // reads counter=0, writes counter=1
// expected counter=2, actual counter=1
```

**Solution**: mutexes, atomic operations, or encapsulating the shared state in an actor.

Single-threaded code is not immune. In JavaScript and asyncio, state read before an `await` can be stale after it (check-then-act across an `await`). In Apex, concurrent transactions race on the same records; lock them with `FOR UPDATE` (see [Salesforce Apex: Queueable, Finalizer, Locking](#salesforce-apex-queueable-finalizer-locking)).

> 📖 [TOCTOU race conditions](../code-quality-universal.md#toctou-race-conditions) · [Stale async results in UI code](../javascript.md#race-conditions-cancel-or-ignore-stale-results)

### Pitfall 2: Deadlock

Two or more tasks each wait for a lock that the other one holds.

```
task1: lock(A); lock(B);  // holds A, waits for B
task2: lock(B); lock(A);  // holds B, waits for A
// both wait forever
```

**Solution**:
- A consistent lock acquisition order
- Locks with timeouts (tryLock with timeout)
- No nested locks

### Pitfall 3: Starvation

Low-priority tasks never get a chance to run.

```
// High-priority tasks keep arriving; low-priority tasks wait in the queue forever
```

**Solution**: fair locks, task priority queues, and limits on concurrency.

In Node.js, a recursive `process.nextTick()` or an endless chain of microtasks starves I/O callbacks the same way (see [Event Loop & CPU-Bound Work](../nodejs.md#event-loop--cpu-bound-work)).

### Pitfall 4: Leaked tasks and fire-and-forget work

Concurrent work is started, but nothing makes sure it finishes, fails visibly, or stops.

```typescript
// ❌ Fire-and-forget: nobody awaits the promise, so a rejection is unhandled
//    (Node.js exits on unhandled rejections by default) and shutdown can cut the work off
async function createOrder(input: OrderInput): Promise<Order> {
    const order = await orders.insert(input);
    sendConfirmationEmail(order); // floating promise
    return order;
}

// ❌ An interval that is never cleared keeps running after its owner is gone
//    (and keeps the Node.js process alive)
function startCacheRefresh(): void {
    setInterval(refreshCache, 60_000);
}

// ✅ Await the work (or hand it to a durable job queue that owns retries and errors)
async function createOrder(input: OrderInput): Promise<Order> {
    const order = await orders.insert(input);
    await sendConfirmationEmail(order);
    return order;
}

// ✅ Keep the handle, handle each run's errors, and clear it on shutdown or teardown
function startCacheRefresh(): () => void {
    const timer = setInterval(() => {
        refreshCache().catch((err) => logger.error({ err }, 'cache refresh failed'));
    }, 60_000);
    return () => clearInterval(timer);
}
```

```python
# ❌ Python: task leak
async def process():
    task = asyncio.create_task(long_running())
    # the function returns, but the task keeps running

# ❌ No reference kept: the event loop holds tasks only weakly, so this task can be
#    garbage-collected before it finishes, and nobody handles its exception
asyncio.create_task(send_email(order))

# ✅ If work must outlive the caller, keep a strong reference until it is done
background_tasks: set[asyncio.Task[None]] = set()

task = asyncio.create_task(send_email(order))
background_tasks.add(task)
task.add_done_callback(background_tasks.discard)
```

**Solution**: `asyncio.TaskGroup` (Python 3.11+); in JavaScript, await every promise or track it and cancel it with an `AbortController`; clear timers (`clearInterval`, `clearTimeout`) on shutdown or teardown.

> 📖 [No floating promises](../javascript.md#no-floating-promises) · [Clean up listeners, timers, and observers](../javascript.md#clean-up-listeners-timers-and-observers)

### Pitfall 5: Blocking in an async context

```python
# ❌ Python: synchronous I/O in an async function blocks the event loop
async def handle():
    result = requests.get(url)  # blocks! the whole event loop stalls
    return result

# ✅ Use async I/O with one shared ClientSession (the calling coroutine opens it once and passes it in)
async def handle(session: aiohttp.ClientSession):
    async with session.get(url) as resp:  # non-blocking
        return await resp.text()

# or run the synchronous code in a thread pool
async def handle():
    result = await asyncio.to_thread(requests.get, url)
    return result
```

```typescript
import { pbkdf2, pbkdf2Sync } from 'node:crypto';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { promisify } from 'node:util';
import { Worker } from 'node:worker_threads';

const pbkdf2Async = promisify(pbkdf2);

// ❌ Node.js: synchronous calls in a request handler stall every other request
//    (readFileSync is fine at startup, not per request)
function getInvoiceTemplate(): string {
    return readFileSync('templates/invoice.html', 'utf8');
}
function hashPassword(password: string, salt: Buffer): Buffer {
    return pbkdf2Sync(password, salt, 600_000, 32, 'sha256');
}

// ✅ Async APIs run the work on the libuv thread pool; the event loop stays free
function getInvoiceTemplate(): Promise<string> {
    return readFile('templates/invoice.html', 'utf8');
}
function hashPassword(password: string, salt: Buffer): Promise<Buffer> {
    return pbkdf2Async(password, salt, 600_000, 32, 'sha256');
}

// ✅ Pure JavaScript CPU work (report rendering, large data transforms) goes to a worker thread
async function renderReport(rows: ReportRow[]): Promise<string> {
    const worker = new Worker(new URL('./render-report.js', import.meta.url), { workerData: rows });
    const [html] = await once(worker, 'message'); // rejects if the worker emits 'error'
    return html;
}
// 💡 Reuse a small pool of workers for frequent jobs; starting one per request is expensive
```

> 📖 [Don't block the event loop or main thread](../javascript.md#dont-block-the-event-loop-or-main-thread) · [Event Loop & CPU-Bound Work](../nodejs.md#event-loop--cpu-bound-work)

---

## Best Practices

### 1. Structured concurrency

Tie the lifetime of concurrent tasks to the scope that created them. When the parent is cancelled, its children are cancelled automatically.

```python
# ✅ Python 3.11+: TaskGroup
async def process_items():
    async with asyncio.TaskGroup() as tg:
        for item in items:
            tg.create_task(process_item(item))
    # the TaskGroup waits for every task when the block exits
    # if one task fails, the remaining tasks are cancelled automatically
```

```typescript
// ✅ JavaScript: Promise.all rejects on the first failure but does NOT stop the other
//    promises. Share one AbortController so the siblings are cancelled too, and wait
//    for them to settle before returning.
async function processItems(items: Item[], parentSignal: AbortSignal): Promise<Result[]> {
    const controller = new AbortController();
    const signal = AbortSignal.any([parentSignal, controller.signal]);
    const tasks = items.map((item) => processItem(item, { signal })); // processItem must honor the signal
    try {
        return await Promise.all(tasks);
    } catch (err) {
        controller.abort(err); // cancel the siblings that are still running
        await Promise.allSettled(tasks); // and wait until they have stopped
        throw err;
    }
}
```

### 2. Cancellation propagation

Make sure a cancellation signal reaches every subtask. Swallowing the cancellation (`AbortError`, `asyncio.CancelledError`) breaks it for every caller up the chain.

```typescript
// ❌ The signal stops at the first layer: saveCustomer keeps running after a timeout
async function syncCustomer(id: string, signal: AbortSignal): Promise<void> {
    const customer = await fetchCustomer(id, { signal });
    await saveCustomer(customer); // no signal, so it cannot be cancelled
}

// ✅ One signal flows down the whole call chain; the caller and the timeout can both cancel
//    (AbortSignal.any: Node.js 20.3+ and current browsers)
async function syncCustomer(id: string, userSignal: AbortSignal): Promise<void> {
    const signal = AbortSignal.any([userSignal, AbortSignal.timeout(30_000)]);
    const customer = await fetchCustomer(id, { signal });
    await saveCustomer(customer, { signal });
}

async function fetchCustomer(id: string, { signal }: { signal: AbortSignal }): Promise<Customer> {
    const response = await fetch(`${API_URL}/customers/${encodeURIComponent(id)}`, { signal });
    if (!response.ok) {
        throw new Error(`GET customer ${id} failed with HTTP ${response.status}`);
    }
    return parseCustomer(await response.json());
}
```

```python
# ✅ Python 3.11+: asyncio.timeout cancels everything inside the block and raises TimeoutError
async def sync_customer(customer_id: str) -> None:
    async with asyncio.timeout(30):
        customer = await fetch_customer(customer_id)
        await save_customer(customer)

# ✅ Clean up on cancellation, then re-raise so the cancellation keeps propagating
async def consume(queue: asyncio.Queue[Job]) -> None:
    try:
        while True:
            job = await queue.get()
            await handle(job)
            queue.task_done()
    except asyncio.CancelledError:
        await release_resources()
        raise  # swallowing CancelledError breaks TaskGroup and asyncio.timeout
```

> 📖 [Timeouts with AbortSignal](../javascript.md#timeouts-with-abortsignal)

### 3. Backpressure

When a producer is much faster than its consumer, bound the queue size so memory does not balloon.

```typescript
import { createReadStream, createWriteStream } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { createGzip } from 'node:zlib';

// ❌ write() returning false is ignored: a fast reader fills memory, and errors are not forwarded
const source = createReadStream('export.csv');
const destination = createWriteStream('backup/export.csv');
source.on('data', (chunk) => destination.write(chunk));

// ✅ pipeline() respects backpressure, forwards errors, and destroys every stream on failure
await pipeline(
    createReadStream('export.csv'),
    createGzip(),
    createWriteStream('backup/export.csv.gz'),
);
```

```python
# ✅ Python: a bounded asyncio.Queue makes the producer wait when the consumers fall behind
async def produce(queue: asyncio.Queue[Item]) -> None:
    async for item in fetch_items():
        await queue.put(item)  # suspends while the queue is full

async def consume(queue: asyncio.Queue[Item]) -> None:
    while True:
        item = await queue.get()
        try:
            await process(item)
        finally:
            queue.task_done()

async def run() -> None:
    queue: asyncio.Queue[Item] = asyncio.Queue(maxsize=100)
    async with asyncio.TaskGroup() as tg:
        consumers = [tg.create_task(consume(queue)) for _ in range(5)]
        await produce(queue)
        await queue.join()  # every queued item has been processed
        for task in consumers:
            task.cancel()
```

> 📖 [Streams & Backpressure in Node.js](../nodejs.md#streams--backpressure)

### 4. Limit concurrency

Keep a burst of work from starting so many tasks at once that resources run out.

```python
# ✅ Python: a Semaphore limits concurrency; one shared ClientSession serves every request
async def fetch_all(urls: list[str], max_concurrent: int = 10):
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_one(session: aiohttp.ClientSession, url: str):
        async with semaphore:
            async with session.get(url) as resp:
                return await resp.text()

    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(*[fetch_one(session, url) for url in urls])
```

In JavaScript/TypeScript, use a fixed-size worker pool: see [TypeScript: Worker-pool concurrency limit](#typescript-worker-pool-concurrency-limit). In Apex, the platform bounds concurrency for you; your part is to enqueue one job for a batch of records, not one per record (see [Salesforce Apex: Queueable, Finalizer, Locking](#salesforce-apex-queueable-finalizer-locking)).

---

## Code Examples by Language

### Python: asyncio + TaskGroup

```python
# ✅ Python 3.11+: structured concurrency + bounded concurrency + timeout
import asyncio

async def process_batch(items: list[Item], max_concurrent: int = 10) -> list[Result]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_one(item: Item) -> Result:
        async with semaphore:
            async with asyncio.timeout(30):  # per-item timeout
                return await process(item)

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(process_one(item)) for item in items]

    return [task.result() for task in tasks]
```

> 📖 Depth: [Python asynchronous programming](../python.md#asynchronous-programming)

### TypeScript: Worker-pool concurrency limit

```typescript
// ✅ Worker-pool pattern: a fixed number of workers compete for a shared task queue.
//    Results are assigned by their original index, so the output order matches the input.
async function processWithLimit<T, R>(
    items: T[],
    fn: (item: T) => Promise<R>,
    limit: number,
): Promise<R[]> {
    const results: R[] = [];
    let index = 0;

    const workers = Array.from({ length: limit }, async () => {
        while (index < items.length) {
            const i = index++;
            results[i] = await fn(items[i]);
        }
    });

    await Promise.all(workers);
    return results;
}
// 💡 If fn rejects, Promise.all rejects at once but the other workers keep pulling items;
//    pass an AbortSignal (see Structured concurrency) when they must stop early.
```

> 📖 Depth: [JavaScript async and Promises](../javascript.md#async--promises) · [Node.js async error handling](../nodejs.md#async-error-handling)

### Salesforce Apex: Queueable, Finalizer, Locking

Apex has no threads. Concurrency comes from asynchronous jobs, and each job runs later as a separate transaction with its own limits. The pitfalls above map directly: a job per record floods the queue, an unobserved job fails silently, an unbounded chain never stops, and two transactions that update the same rows race each other.

```apex
public with sharing class InvoiceTriggerHandler {
    // ❌ One job per record: a bulk insert hits the enqueue limit and floods the async queue
    public static void afterInsertPerRecord(List<Invoice__c> invoices) {
        for (Invoice__c inv : invoices) {
            System.enqueueJob(new AccountBalanceJob(new Set<Id>{ inv.Account__c }, 1));
        }
    }

    // ✅ One job for all affected Accounts; cap the chain depth (production chains are otherwise unbounded)
    public static void afterInsert(List<Invoice__c> invoices) {
        Set<Id> accountIds = new Set<Id>();
        for (Invoice__c inv : invoices) {
            accountIds.add(inv.Account__c);
        }
        AsyncOptions options = new AsyncOptions(); // API 59.0+ / Winter '24
        options.MaximumQueueableStackDepth = 5;
        System.enqueueJob(new AccountBalanceJob(accountIds, 1), options);
    }
}

public with sharing class AccountBalanceJob implements Queueable {
    private final Set<Id> accountIds;
    private final Integer attempt;

    public AccountBalanceJob(Set<Id> accountIds, Integer attempt) {
        this.accountIds = accountIds;
        this.attempt = attempt;
    }

    public void execute(QueueableContext context) {
        System.attachFinalizer(new AccountBalanceFinalizer(accountIds, attempt));

        // Lock the parent rows so two jobs cannot overwrite each other's totals
        Map<Id, Account> accounts = new Map<Id, Account>([
            SELECT Id, Open_Balance__c FROM Account WHERE Id IN :accountIds WITH USER_MODE FOR UPDATE
        ]);
        for (Account acc : accounts.values()) {
            acc.Open_Balance__c = 0;
        }
        // Idempotent: recompute from the source rows instead of incrementing, so a retry is safe
        for (AggregateResult row : [
            SELECT Account__c accountId, SUM(Amount__c) total
            FROM Invoice__c
            WHERE Account__c IN :accountIds AND Status__c = 'Open'
            WITH USER_MODE
            GROUP BY Account__c
        ]) {
            Account acc = accounts.get((Id) row.get('accountId'));
            if (acc != null) {
                acc.Open_Balance__c = (Decimal) row.get('total');
            }
        }
        update as user accounts.values();
    }
}

public with sharing class AccountBalanceFinalizer implements Finalizer {
    private static final Integer MAX_ATTEMPTS = 3;
    private final Set<Id> accountIds;
    private final Integer attempt;

    public AccountBalanceFinalizer(Set<Id> accountIds, Integer attempt) {
        this.accountIds = accountIds;
        this.attempt = attempt;
    }

    // Runs in its own transaction after the job ends, whether the job succeeded or failed
    public void execute(FinalizerContext context) {
        if (context.getResult() == ParentJobResult.UNHANDLED_EXCEPTION) {
            // log context.getException() with the project's logger, then retry a bounded number of times
            if (attempt < MAX_ATTEMPTS) {
                System.enqueueJob(new AccountBalanceJob(accountIds, attempt + 1));
            }
        }
    }
}
```

Static analysis: PMD `QueueableWithoutFinalizer`.

- **Lock deliberately.** `SELECT ... FOR UPDATE` holds row locks until the transaction ends; a transaction that cannot get a locked row in time fails with `UNABLE_TO_LOCK_ROW`. Lock rows in a consistent order (for example, parents before children) so concurrent jobs cannot deadlock, keep locking transactions short, and expect more contention on skewed data (many children under one parent).
- **Make jobs idempotent.** Finalizer retries, redelivered platform events, and double submissions all run the same work again: re-query by Id, skip records that are already processed, and recompute values instead of incrementing them.
- **Async is a new transaction.** The job starts later with its own limits, sees only committed data, and keeps none of the caller's static state. It may also run as a different user than the triggering code: platform event triggers, for example, run as the Automated Process user unless `PlatformEventSubscriberConfig` names another one. Declare sharing on every job class and keep data access in user mode.
- **Don't rely on ordering.** Separately enqueued jobs have no guaranteed order; chain them, or do the work in one job, when order matters.

> 📖 Depth: [Async Apex](../salesforce/apex.md#async-apex) · [Transactions & Execution Contexts](../salesforce/platform.md#transactions--execution-contexts) · [Platform Event and CDC Triggers](../salesforce/apex-triggers.md#platform-event-and-cdc-triggers)

---

## Review Checklist

### Basic checks
- [ ] Concurrent tasks have a clear exit path (nothing leaks)
- [ ] Shared state is properly protected (locks, queues, single-owner state)
- [ ] No blocking operations run in an async context
- [ ] Cancellation signals propagate to every subtask

### Architecture checks
- [ ] Structured concurrency is used (TaskGroup / Promise.all + AbortController)
- [ ] Concurrency has an upper bound (semaphore / bounded queue / worker pool)
- [ ] Long-running tasks support timeouts
- [ ] A backpressure mechanism keeps memory from ballooning

### Performance checks
- [ ] Concurrency granularity is reasonable (neither too fine nor too coarse)
- [ ] I/O-bound work uses async; CPU-bound work uses threads or processes
- [ ] Locks are held for as short a time as possible
- [ ] No unnecessary awaits (independent operations are not run one after another)

### Language-specific
- [ ] Python: the event loop is never blocked; TaskGroup manages task lifetimes; `CancelledError` is re-raised after cleanup
- [ ] TypeScript: no floating promises; `Promise.all` is combined with a concurrency limit; an `AbortSignal` is passed down for cancellation and timeouts
- [ ] Node.js: no synchronous I/O or CPU-heavy work in request handlers; streams are connected with `pipeline()`
- [ ] Apex: jobs are enqueued once per transaction, not per record; Queueables attach a Finalizer; chains and retries are bounded; jobs are idempotent
