# Async & Concurrency Patterns: Cross-Language Guide

> Concurrency defects that look alike in JavaScript/TypeScript, Python asyncio, and Apex: races across an `await` or a transaction, leaked or unobserved work, a blocked event loop, lost cancellation, and unbounded fan-out.
> Related: language details in [JavaScript](../javascript.md#async--promises), [Node.js](../nodejs.md#event-loop--cpu-bound-work), [Python](../python.md#asynchronous-programming), and [Apex](../salesforce/apex.md#async-apex)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Races → [Race conditions across await and transactions](#race-conditions-across-await-and-transactions)

- [ ] State read before an `await` is re-checked after it, or the check and the write happen in one atomic step.
- [ ] Records that several transactions read, compute from, and write back are locked (`SELECT ... FOR UPDATE`) or recomputed idempotently.
- [ ] Code that takes two locks takes them in the same order everywhere.

### Leaked work → [Leaked tasks and fire-and-forget work](#leaked-tasks-and-fire-and-forget-work)

- [ ] Every promise is awaited, returned, or handed to an owner that handles its rejection. A side effect whose failure must not fail the request is caught and logged, or queued durably. In Node.js an unhandled rejection exits the process by default, so a floating promise that can reject on a server path is 🔴.
- [ ] Python: tasks from `asyncio.create_task` are owned by a `TaskGroup` or kept in a strong reference, and their exceptions are observed.
- [ ] Intervals and timers the diff starts are cleared on shutdown or teardown.

### Blocking → [Blocking in an async context](#blocking-in-an-async-context)

- [ ] No synchronous I/O or CPU-heavy work inside async handlers (`requests`, `time.sleep`, `readFileSync`, `pbkdf2Sync`, `JSON.parse` of large bodies). Startup code and CLI scripts are exempt.
- [ ] CPU-bound work runs in worker threads or processes, not on the event loop.

### Cancellation → [1. Structured concurrency](#1-structured-concurrency) · [2. Cancellation propagation](#2-cancellation-propagation)

- [ ] Tasks started together are awaited together; when one fails, the others are cancelled if they must not keep running (`asyncio.TaskGroup`; `Promise.all` with a shared `AbortSignal`).
- [ ] A signal or timeout that a function accepts reaches every I/O call below it.
- [ ] `CancelledError` and `AbortError` are re-raised or rethrown after cleanup, never swallowed.
- [ ] Outbound I/O and long-running tasks have a timeout.

### Limits → [3. Backpressure](#3-backpressure) · [4. Limit concurrency](#4-limit-concurrency)

- [ ] Fan-out over input that grows with data (ids, URLs, files) is bounded by a semaphore or a worker pool. A fixed handful of independent calls in one `Promise.all` or `gather` needs no limit.
- [ ] Streams are connected with `pipeline()`; producer/consumer queues have a maximum size.

### Apex → [Salesforce Apex: Queueable, Finalizer, Locking](#salesforce-apex-queueable-finalizer-locking)

- [ ] A batch of records is enqueued as one job per transaction, never one job per record ([row 1 of Severity Calibration](../salesforce/platform.md#severity-calibration): 🔴).
- [ ] Chains and retries are bounded, and jobs are idempotent.
- [ ] A Queueable that must report or recover from its own failure (retry, alert, compensating update) attaches a Finalizer; a job whose failure is already visible or harmless needs none.
- [ ] Nothing depends on the order of separately enqueued jobs, or on the enqueuing user's context when the job runs as another user.
- [ ] Lock waits (`UNABLE_TO_LOCK_ROW`) and failed jobs are runtime evidence: ask the author when a finding depends on them.

---

## Common Pitfalls

### Race conditions across await and transactions

Single-threaded code still races. In JavaScript and asyncio, other work runs at every `await`, so state read before it can be stale after it (check-then-act across an `await`). Across processes and transactions the database is the shared state: make the check and the write one atomic statement, or lock the rows ([TOCTOU](../code-quality-universal.md#toctou-race-conditions)). In Apex, concurrent transactions race on the same records; lock them with `FOR UPDATE` ([Salesforce Apex](#salesforce-apex-queueable-finalizer-locking)). For UI code that renders a slow, older response over a newer one, see [stale async results](../javascript.md#race-conditions-cancel-or-ignore-stale-results).

Deadlocks come from taking two locks in opposite orders. In Node.js, a recursive `process.nextTick()` or an endless microtask chain starves I/O callbacks ([Event Loop & CPU-Bound Work](../nodejs.md#event-loop--cpu-bound-work)).

### Leaked tasks and fire-and-forget work

```typescript
// ❌ Floating promise: a rejection is unhandled (Node.js exits on unhandled rejections by
//    default), and shutdown can cut the email off
async function createOrder(input: OrderInput): Promise<Order> {
    const order = await orders.insert(input);
    sendConfirmationEmail(order);
    return order;
}

// ✅ Own the side effect. The order is already committed, so an email failure is logged instead
//    of failing the request (a client retry would create a duplicate order). A durable job
//    queue or outbox is the stronger fix when the email must arrive.
async function createOrder(input: OrderInput): Promise<Order> {
    const order = await orders.insert(input);
    try {
        await sendConfirmationEmail(order);
    } catch (err: unknown) {
        logger.error({ err, orderId: order.id }, 'confirmation email failed');
    }
    return order;
}
```

```python
# ❌ No reference kept: the event loop holds tasks only weakly, so the task can be
#    garbage-collected before it finishes, and its exception is never observed
asyncio.create_task(send_email(order))

# ✅ Work that must outlive the caller: keep a strong reference and observe the outcome
background_tasks: set[asyncio.Task[None]] = set()

def _on_done(task: asyncio.Task[None]) -> None:
    background_tasks.discard(task)
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.error("background task failed", exc_info=exc)

task = asyncio.create_task(send_email(order))
background_tasks.add(task)
task.add_done_callback(_on_done)
```

Work that the caller can wait for belongs in a `TaskGroup` ([Structured concurrency](#1-structured-concurrency)). Intervals and timers need a kept handle and a clear on teardown. More: [No floating promises](../javascript.md#no-floating-promises) · [Clean up listeners, timers, and observers](../javascript.md#clean-up-listeners-timers-and-observers).

### Blocking in an async context

```python
# ❌ Synchronous I/O in an async function stalls the whole event loop
async def fetch_profile(url: str) -> str:
    return requests.get(url, timeout=10).text

# ✅ Run the blocking call in a thread, or use an async client (aiohttp, httpx.AsyncClient)
async def fetch_profile(url: str) -> str:
    response = await asyncio.to_thread(requests.get, url, timeout=10)
    return response.text
```

In Node.js, `readFileSync` or `pbkdf2Sync` per request, synchronous `zlib` calls, and `JSON.parse` of multi-megabyte bodies stall every request; the same calls at startup are fine. Use the asynchronous APIs, which run on the libuv thread pool, or a worker thread for pure JavaScript CPU work ([Event Loop & CPU-Bound Work](../nodejs.md#event-loop--cpu-bound-work), [Don't block the event loop or main thread](../javascript.md#dont-block-the-event-loop-or-main-thread)).

---

## Best Practices

### 1. Structured concurrency

Tie the lifetime of concurrent tasks to the scope that started them, so a failure or a cancellation stops the siblings.

```python
# ✅ Python 3.11+: the block waits for every task; the first failure cancels the rest
async with asyncio.TaskGroup() as tg:
    for item in items:
        tg.create_task(process_item(item))
```

In JavaScript, `Promise.all` rejects at the first failure but does not stop the other promises. When they must stop, pass them one `AbortSignal` (combine it with the caller's signal through `AbortSignal.any`), abort it in `catch`, and await `Promise.allSettled` on the started promises before rethrowing, so nothing keeps running after the function returns ([Combinators, loops, and promise plumbing](../javascript.md#combinators-loops-and-promise-plumbing)).

### 2. Cancellation propagation

A cancellation signal must reach every subtask. Swallowing the cancellation (`AbortError`, `asyncio.CancelledError`) breaks it for every caller up the chain.

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
```

In Python 3.11+, `async with asyncio.timeout(30):` cancels everything inside the block and raises `TimeoutError`.

```python
# ✅ Clean up in finally, so cancellation still propagates (swallowing CancelledError
#    breaks TaskGroup and asyncio.timeout), and mark every item done even when handle() raises
async def consume(queue: asyncio.Queue[Job]) -> None:
    try:
        while True:
            job = await queue.get()
            try:
                await handle(job)
            finally:
                queue.task_done()
    finally:
        await release_resources()
```

> 📖 [Timeouts with AbortSignal](../javascript.md#timeouts-with-abortsignal)

### 3. Backpressure

When a producer is faster than its consumer, bound the buffer between them so memory cannot grow without limit. In Node.js, connect streams with `pipeline()` from `node:stream/promises`, which respects backpressure, forwards errors, and destroys every stream on failure; a `'data'` handler that ignores `write()` returning `false` buffers the whole input ([Streams & Backpressure](../nodejs.md#streams--backpressure)).

```python
# ✅ A bounded asyncio.Queue makes the producer wait when the consumers fall behind
async def run() -> None:
    queue: asyncio.Queue[Item] = asyncio.Queue(maxsize=100)
    async with asyncio.TaskGroup() as tg:
        consumers = [tg.create_task(consume(queue)) for _ in range(5)]
        async for item in fetch_items():
            await queue.put(item)  # suspends while the queue is full
        await queue.join()  # every queued item has been processed
        for task in consumers:
            task.cancel()
```

### 4. Limit concurrency

Bound fan-out over input that grows with data, so a burst doesn't exhaust sockets, memory, or the downstream rate limit. In Python, acquire an `asyncio.Semaphore` inside tasks owned by a `TaskGroup` ([example](#python-asyncio--taskgroup)); `asyncio.gather` with a semaphore bounds concurrency too, but it doesn't cancel the other tasks when one fails. In JavaScript/TypeScript, use a fixed-size worker pool ([example](#typescript-worker-pool-concurrency-limit)). In Apex, the platform schedules jobs; your part is one job per batch of records, not one per record ([Salesforce Apex](#salesforce-apex-queueable-finalizer-locking)).

---

## Code Examples by Language

### Python: asyncio + TaskGroup

```python
# ✅ Python 3.11+: structured concurrency + bounded concurrency + a per-item timeout
import asyncio

async def process_batch(items: list[Item], max_concurrent: int = 10) -> list[Result]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_one(item: Item) -> Result:
        async with semaphore:
            async with asyncio.timeout(30):
                return await process(item)

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(process_one(item)) for item in items]

    return [task.result() for task in tasks]
```

The first failure cancels the remaining items and raises an `ExceptionGroup`; when every item must be attempted, catch errors inside `process_one` and return them as results. More: [Python asynchronous programming](../python.md#asynchronous-programming).

### TypeScript: Worker-pool concurrency limit

```typescript
// ✅ Worker pool: `limit` workers pull [index, item] pairs from one shared iterator, and each
//    result is stored at its input index, so the output order matches the input order
async function processWithLimit<T, R>(
    items: readonly T[],
    fn: (item: T) => Promise<R>,
    limit: number,
): Promise<R[]> {
    if (!Number.isInteger(limit) || limit < 1) {
        throw new RangeError(`limit must be a positive integer, got ${limit}`);
    }
    const results = new Array<R>(items.length);
    const queue = items.entries();
    const worker = async (): Promise<void> => {
        for (const [index, item] of queue) {
            results[index] = await fn(item);
        }
    };
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
    return results;
}
// Note: if fn rejects, Promise.all rejects at once but the other workers keep pulling items;
// pass an AbortSignal (see Structured concurrency) when they must stop early.
```

> 📖 Depth: [JavaScript async and Promises](../javascript.md#async--promises) · [Node.js async error handling](../nodejs.md#async-error-handling)

### Salesforce Apex: Queueable, Finalizer, Locking

Apex has no threads: each asynchronous job runs later as a separate transaction with its own limits. The pitfalls above map directly: a job per record floods the queue, an unobserved job fails silently, an unbounded chain never stops, and two transactions that update the same rows race.

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

// System mode on purpose, and only in this job: the stored total must include every open invoice,
// whoever enqueued the job. In user mode the SUM would cover only the invoices that user can see,
// and the update would fail for users who cannot edit Open_Balance__c. The job reads two fields,
// writes one, and returns nothing to a UI.
public without sharing class AccountBalanceJob implements Queueable {
    private final Set<Id> accountIds;
    private final Integer attempt;

    public AccountBalanceJob(Set<Id> accountIds, Integer attempt) {
        this.accountIds = accountIds;
        this.attempt = attempt;
    }

    public void execute(QueueableContext context) {
        // A Finalizer because this job retries on failure
        System.attachFinalizer(new AccountBalanceFinalizer(accountIds, attempt));

        // Lock the parent rows so two jobs cannot overwrite each other's totals
        Map<Id, Account> accounts = new Map<Id, Account>([
            SELECT Id, Open_Balance__c FROM Account WHERE Id IN :accountIds WITH SYSTEM_MODE FOR UPDATE
        ]);
        for (Account acc : accounts.values()) {
            acc.Open_Balance__c = 0;
        }
        // Idempotent: recompute from the source rows instead of incrementing, so a retry is safe
        for (AggregateResult row : [
            SELECT Account__c accountId, SUM(Amount__c) total
            FROM Invoice__c
            WHERE Account__c IN :accountIds AND Status__c = 'Open'
            WITH SYSTEM_MODE
            GROUP BY Account__c
        ]) {
            Account acc = accounts.get((Id) row.get('accountId'));
            if (acc != null) {
                acc.Open_Balance__c = (Decimal) row.get('total');
            }
        }
        update as system accounts.values();
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
        // Log context.getException() with the project's logger, then retry a bounded number of times
        if (context.getResult() == ParentJobResult.UNHANDLED_EXCEPTION && attempt < MAX_ATTEMPTS) {
            System.enqueueJob(new AccountBalanceJob(accountIds, attempt + 1));
        }
    }
}
```

Static analysis: PMD `QueueableWithoutFinalizer` flags every Queueable without a Finalizer; report a hit only when the job must report or recover from its own failure.

- **Lock deliberately.** `SELECT ... FOR UPDATE` holds row locks until the transaction ends; a transaction that cannot get a locked row in time fails with `UNABLE_TO_LOCK_ROW`. Lock in a consistent order (parents before children), keep locking transactions short, and expect contention on skewed data (many children under one parent).
- **Make jobs idempotent.** Finalizer retries, redelivered platform events, and double submissions run the same work again: re-query by Id, skip records already processed, and recompute instead of incrementing.
- **Async is a new transaction.** The job starts later with its own limits, sees only committed data, and keeps none of the caller's static state. It may run as another user: platform event triggers run as the Automated Process user unless `PlatformEventSubscriberConfig` names one. Declare sharing on every job class and keep data access in user mode, except for data that must not depend on who started the job (stored totals, integration sync); keep that system-mode access narrow and commented, as above ([row 4 of Severity Calibration](../salesforce/platform.md#severity-calibration)).
- **Don't rely on ordering.** Separately enqueued jobs have no guaranteed order; chain them, or do the work in one job, when order matters.

> 📖 Depth: [Async Apex](../salesforce/apex.md#async-apex) · [Transactions & Execution Contexts](../salesforce/platform.md#transactions--execution-contexts) · [Platform Event and CDC Triggers](../salesforce/apex-triggers.md#platform-event-and-cdc-triggers)
