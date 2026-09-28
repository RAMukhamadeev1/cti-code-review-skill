# Node.js Code Review Guide

Review guidance for Node.js services, CLIs, and scripts: event loop, streams, process lifecycle, modules and packaging, HTTP servers (Express), Node-specific security, and dependencies. Written for Node.js 22 and 24 LTS and Node.js 26 (LTS from October 2026); Node.js 20 reached end-of-life on 2026-04-30. Check `engines.node`, `.nvmrc`, the Docker base image, and the CI matrix before flagging version-gated APIs.

> **Load [javascript.md](javascript.md) too** for language semantics, async and Promise pitfalls, and test-runner guidance. Add [typescript.md](typescript.md) for TypeScript code and [nestjs.md](nestjs.md) for NestJS applications.
>
> Related: [Security Review Guide](security-review-guide.md) · [Error Handling Principles](cross-cutting/error-handling-principles.md) · [Async & Concurrency Patterns](cross-cutting/async-concurrency-patterns.md)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Runtime Versions & Built-ins](#runtime-versions--built-ins)
- [Event Loop & CPU-Bound Work](#event-loop--cpu-bound-work)
- [Modules & Packaging](#modules--packaging)
- [Async Error Handling](#async-error-handling)
- [Streams & Backpressure](#streams--backpressure)
- [Process Lifecycle & Graceful Shutdown](#process-lifecycle--graceful-shutdown)
- [Configuration & Secrets](#configuration--secrets)
- [HTTP Servers & Express](#http-servers--express)
- [Node.js Security](#nodejs-security)
- [Dependencies & Supply Chain](#dependencies--supply-chain)
- [Performance & Resource Management](#performance--resource-management)
- [Testing Node.js Services](#testing-nodejs-services)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| Node service, CLI, worker, or script (JS) | This guide + [javascript.md](javascript.md) |
| Same, written in TypeScript | Also [typescript.md](typescript.md) |
| NestJS | [nestjs.md](nestjs.md) + [typescript.md](typescript.md); this guide for bootstrap, shutdown, streams, configuration, and process-level issues |
| Browser or LWC code | Not this guide: [javascript.md](javascript.md) (+ [salesforce/lwc.md](salesforce/lwc.md)) |

Examples use ES modules and Express 5, which passes rejected promises from handlers to the error handler. On Express 4 the async handlers below need the wrapper from [Async errors in Express 4 vs 5](#async-errors-in-express-4-vs-5).

---

## Runtime Versions & Built-ins

### Pin the supported Node.js version

Several files decide which Node.js actually runs, and they drift apart. A PR that uses a newer API or changes the base image must keep all of them in one supported range: `engines.node` (npm only warns on a mismatch unless `engine-strict` is set), `.nvmrc` or `.node-version`, the Dockerfile `FROM` tag, the CI matrix (at least the lowest supported version and the one production runs), and for TypeScript the `@types/node` major, which should match the lowest supported runtime.

```dockerfile
# ❌ Floating tag: "latest" jumps to every new major (and an end-of-life tag like node:20 gets no fixes)
FROM node:latest

# ✅ A supported LTS line that matches engines.node and .nvmrc (pin the digest for reproducible builds)
FROM node:24-bookworm-slim
```

| Line | LTS from | Maintenance from | End-of-life |
|---|---|---|---|
| 26.x | 2026-10-28 | 2027-10-20 | 2029-04-30 |
| 24.x "Krypton" | 2025-10-28 | 2026-10-20 | 2028-04-30 |
| 22.x "Jod" | 2024-10-29 | 2025-10-21 | 2027-04-30 |
| 20.x "Iron" | 2023-10-24 | 2024-10-22 | 2026-04-30 (reached) |

The Node.js project's guidance is that production applications should only use Active LTS or Maintenance LTS releases. Odd-numbered lines (21, 23, 25) never became LTS and are all end-of-life. From Node.js 27 there is one major release per year and every release becomes LTS; the `27.0.0-alpha` builds that start on 2026-10-28 are not for production. When a PR bumps the major version, read the semver-major list in the release notes: Node.js 26, for example, removed `--experimental-transform-types` and the legacy `_stream_*` modules and runtime-deprecated `module.register()`.

### Prefer built-in APIs and node: imports

Each dependency is code to audit, update, and trust at install time, and most classic helpers now have a built-in equivalent on every supported line. Import built-ins with the `node:` prefix (`import { readFile } from 'node:fs/promises'`): it is unambiguous for readers and tools, and `node:test`, `node:sqlite`, and `node:sea` exist only under the prefix.

| Instead of | Use | Notes |
|---|---|---|
| `node-fetch`, `axios` for simple calls | Global `fetch` | Stable since 21.0.0; still needs a timeout ([Put timeouts on all outbound I/O](#put-timeouts-on-all-outbound-io)) |
| `uuid` for v4 IDs | `crypto.randomUUID()` | |
| `lodash.clonedeep` | `structuredClone()` | Data only: functions throw, class instances become plain objects |
| `yargs`, `minimist` for small CLIs | `util.parseArgs()` | Stable since 20.0.0 |
| `dotenv` | `node --env-file=.env`, `process.loadEnvFile()` | Stable in 22.21.0 and 24.10.0; variables already in the environment win |
| `nodemon` | `node --watch` | Stable since 22.0.0 |
| `mocha`, `jest` for small packages | `node:test` + `node:assert/strict` | Stable since 20.0.0 |
| `glob`, `rimraf`, `mkdirp` | `fs.glob()`, `fs.rm(p, { recursive: true, force: true })`, `fs.mkdir(p, { recursive: true })` | `fs.glob()` stable in 22.17.0 and 24.0.0 |

Type stripping replaces `ts-node` or `tsx` for simple scripts: it runs `.ts` files without a build step. It has been on by default without a warning since 22.18.0 and stable since 24.12.0, and it only erases types: `enum`, namespaces with runtime code, parameter properties, and import aliases fail with `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`, and decorators are a parse error. Node.js does not read `tsconfig.json` (so there are no `paths`), refuses `.ts` files under `node_modules`, needs `import type` for type-only imports, and checks no types, so CI still runs `tsc --noEmit`. For compiler settings, see [typescript.md](typescript.md#modern-typescript-features).

---

## Event Loop & CPU-Bound Work

### Never block the event loop in request paths

All JavaScript in a process runs on one thread, so a 200 ms synchronous call delays every queued request, health checks included. Synchronous APIs are fine at startup and in CLIs. Async `fs`, crypto, `zlib`, and `dns.lookup()` share the libuv threadpool (4 threads by default; `UV_THREADPOOL_SIZE` must be set before the process starts), so a burst of slow calls also delays unrelated ones. General patterns are in [javascript.md](javascript.md#dont-block-the-event-loop-or-main-thread); catastrophic regular expressions are under [Security-Sensitive APIs](javascript.md#security-sensitive-apis).

```javascript
// ❌ Each call blocks the whole process while it runs
app.get('/export', (req, res) => {
  const rows = JSON.parse(readFileSync(EXPORT_PATH, 'utf8')); // sync read + parse of a large file
  res.set('Content-Encoding', 'gzip').type('json').send(gzipSync(JSON.stringify(rows)));
});
const hash = scryptSync(password, salt, 64); // synchronous key derivation on every login

// ✅ Stream the file; async fs and crypto run on the threadpool
app.get('/export', async (req, res) => {
  res.type('json');
  await pipeline(createReadStream(EXPORT_PATH), res);
});
const hash = await promisify(scrypt)(password, salt, 64);
```

### Move CPU-heavy work to worker threads

Parsing, rendering, compressing, or hashing large inputs blocks the main thread just like synchronous I/O. Worker threads run JavaScript in parallel inside the process; a bounded pool keeps startup cost and memory flat and turns overload into fast rejections instead of a growing queue.

```javascript
// ❌ A Worker per request: startup cost on every call, unlimited concurrency
const worker = new Worker(new URL('./summarize.js', import.meta.url), { workerData: req.params.id });
const [summary] = await once(worker, 'message');

// ✅ One pool per process: bounded threads and queue, a deadline per task
import { Piscina } from 'piscina';

const summaryPool = new Piscina({
  filename: new URL('./summarize.js', import.meta.url).href,
  maxThreads: availableParallelism(), // node:os
  maxQueue: 'auto', // the default is unbounded; a full queue rejects new tasks
});
app.get('/reports/:id/summary', async (req, res) => {
  res.json(await summaryPool.run(req.params.id, { signal: AbortSignal.timeout(10_000) }));
});
```

Data sent to a worker is copied unless it is listed in `transferList`. Close the pool on shutdown (`await summaryPool.close()`). See also the [worker-pool concurrency limit](cross-cutting/async-concurrency-patterns.md#typescript-worker-pool-concurrency-limit).

### Avoid process.nextTick starvation

The `process.nextTick` queue and the promise microtask queue are drained completely before the event loop moves on. Recursive `nextTick` calls, or a loop that only awaits already-settled promises (`await Promise.resolve()`), starve I/O and timers. Yield with `setImmediate` when you split work into chunks.

```javascript
// ❌ Recursive nextTick: the queue never empties, so no I/O callback or timer runs
function processAll(items, i = 0) {
  if (i >= items.length) return;
  handle(items[i]);
  process.nextTick(processAll, items, i + 1);
}

// ✅ Yield to the event loop between chunks
import { setImmediate as yieldToEventLoop } from 'node:timers/promises';

async function processAll(items, chunkSize = 500) {
  for (let i = 0; i < items.length; i += chunkSize) {
    for (const item of items.slice(i, i + chunkSize)) handle(item);
    await yieldToEventLoop();
  }
}
```

### Monitor event-loop delay

Blocking shows up as event-loop delay long before CPU graphs look alarming. Export the delay as a metric and alert on the p99; `performance.eventLoopUtilization()` adds how busy the loop is.

```javascript
// ✅ Report p99 and max event-loop delay every 10 s (the histogram records nanoseconds)
import { monitorEventLoopDelay } from 'node:perf_hooks';

const loopDelay = monitorEventLoopDelay({ resolution: 20 });
loopDelay.enable();
setInterval(() => {
  metrics.gauge('nodejs.eventloop.delay.p99_ms', loopDelay.percentile(99) / 1e6);
  metrics.gauge('nodejs.eventloop.delay.max_ms', loopDelay.max / 1e6);
  loopDelay.reset();
}, 10_000).unref(); // a metrics timer must not keep the process alive
```

---

## Modules & Packaging

### ESM vs CommonJS pitfalls

The nearest `package.json` `"type"` decides whether `.js` files load as ES modules or CommonJS; `.mjs` and `.cjs` always win. The two systems differ in globals, resolution, and loading.

```javascript
// ❌ CommonJS syntax is not available in ESM
// package.json: "type": "module"
const fs = require('fs');        // ReferenceError: require is not defined in ES module scope
module.exports = { foo: 'bar' }; // ReferenceError: module is not defined in ES module scope

// ✅ ESM syntax
import fs from 'node:fs';
export const foo = 'bar';

// ✅ __dirname in ESM: import.meta.dirname and import.meta.filename (stable since 22.16.0 and 24.0.0);
//    libraries that support older runtimes use dirname(fileURLToPath(import.meta.url)) from node:url
const templatesDir = join(import.meta.dirname, 'templates');

// ❌ Dynamic require in ESM
const moduleName = 'lodash';
const _ = require(moduleName); // ReferenceError: require is not defined

// ✅ Dynamic import(); a CommonJS module's module.exports arrives as the default export
const { default: _ } = await import(moduleName);

// ❌ ESM does not guess file extensions or directory indexes
import { formatDate } from './utils/date'; // ERR_MODULE_NOT_FOUND

// ✅ Full relative paths; JSON needs an import attribute and has only a default export
import { formatDate } from './utils/date.js';
import defaults from './defaults.json' with { type: 'json' };
```

CommonJS can `require()` an ES module without a flag since 22.12.0 and 20.19.0 (stable in 24.15.0). The call returns the module namespace object (the default export is `.default`) and throws `ERR_REQUIRE_ASYNC_MODULE` if the module graph uses top-level await, so an ESM-only library works for CommonJS consumers until it adds top-level await. `tsconfig.json` `paths` do nothing at runtime; for internal aliases use `package.json` `"imports"` (`#lib/*`), as in [typescript.md](typescript.md#path-aliases-and-module-resolution).

### Avoid the dual-package hazard

When a package ships separate ESM and CommonJS builds, one application can load both: its own code `import`s one copy while a dependency `require`s the other. Each copy has its own module state, so singletons, caches, registries, and `instanceof` checks silently diverge.

```javascript
// ❌ "plugin-host" ships index.mjs and index.cjs, so the app gets two registries
import { register } from 'plugin-host';        // app.mjs loads the ESM copy
register(auditPlugin);
const { getPlugins } = require('plugin-host'); // a CommonJS dependency loads the other copy
getPlugins();                                  // [] because this copy never saw the plugin

// ✅ One implementation: CommonJS inside, and a thin ESM wrapper (index.mjs) as the "import" target
import cjs from './index.cjs';
export const { register, getPlugins } = cjs;
```

Other fixes are to keep all state in one CommonJS file that both builds share, or to publish ESM only and rely on `require(esm)`. Question a PR that adds a second build to a stateful package.

### Package exports for libraries

`"exports"` defines the only entry points consumers can load. Any other subpath throws `ERR_PACKAGE_PATH_NOT_EXPORTED`, which makes adding `exports` to a published package a breaking change. Conditions match in object order and the first match wins: `"types"` goes first (TypeScript uses the first condition it recognizes, so a trailing `"types"` is never used), and `"default"`, when present, goes last.

```jsonc
// ❌ "types" last is never reached; "./*" publishes every internal file
"exports": {
  ".": { "import": "./dist/index.mjs", "require": "./dist/index.cjs", "types": "./dist/index.d.ts" },
  "./*": "./dist/*"
}

// ✅ "types" first in every condition object; only public entry points
"exports": {
  ".": {
    "types": "./dist/index.d.ts",
    "import": "./dist/index.mjs",
    "require": "./dist/index.cjs"
  },
  "./utils": { "types": "./dist/utils.d.ts", "import": "./dist/utils.mjs", "require": "./dist/utils.cjs" },
  "./package.json": "./package.json"
}
```

```javascript
import { foo } from 'my-library';            // ✅ resolves the "." entry
import { bar } from 'my-library/utils';      // ✅ resolves the "./utils" entry
import { secret } from 'my-library/internal'; // ❌ ERR_PACKAGE_PATH_NOT_EXPORTED
```

If the ESM and CommonJS builds ship different declarations, nest the conditions so each format gets its own: `"import": { "types": "./dist/index.d.mts", "default": "./dist/index.mjs" }` and `"require": { "types": "./dist/index.d.cts", "default": "./dist/index.cjs" }`. Check what gets published with `npm pack --dry-run`.

---

## Async Error Handling

### Unhandled rejections crash the process

Since Node.js 15 the default `--unhandled-rejections=throw` mode raises a rejection that has no handler as an uncaught exception, and the process exits with code 1. That default is right: fix the missing `await` or `.catch()`. A global `unhandledRejection` handler that only logs is worse than the crash, because installing it is what stops the exit and leaves the process running in an unknown state. `--unhandled-rejections=warn` or `none` in start scripts or `NODE_OPTIONS` is a finding too.

```javascript
// ❌ Fire-and-forget: if notifyWarehouse() rejects, the whole process exits
app.post('/orders/:id/cancel', async (req, res) => {
  const order = await orders.cancel(req.params.id, req.user.id);
  notifyWarehouse(order); // nobody awaits or catches this promise
  res.json(order);
});

// ❌ Muting the crash leaves the process running in an unknown state
process.on('unhandledRejection', (reason) => logger.error({ reason }, 'unhandled rejection'));

// ✅ Await the work, or hand it to a queue that owns retries
await jobs.enqueue('notify-warehouse', { orderId: order.id });
```

> 📖 Promise rules (floating promises, combinators, `return await`) live in [javascript.md](javascript.md#no-floating-promises); for cross-language principles, see [Error Handling Principles](cross-cutting/error-handling-principles.md#core-principles).

### Handle 'error' events on emitters and streams

An `'error'` event with no listener is thrown: Node.js prints the stack and the process exits. Sockets, streams, child processes, and client libraries built on `EventEmitter` (database pools, message consumers) all emit it, often long after setup, when nothing is awaiting them. Keep `'error'` handlers synchronous; a rejection inside an async handler is itself unhandled.

```javascript
// ❌ No 'error' listeners: a dropped database connection or a missing binary kills the service
const pool = new Pool(config.database);
const child = spawn('convert', [input, output]);

// ✅ Listen on long-lived emitters; await one-shot completion with events.once()
pool.on('error', (err) => logger.error({ err }, 'idle database client failed')); // the pool drops it
const [code] = await once(spawn('convert', [input, output]), 'close'); // rejects on 'error' (e.g. ENOENT)
if (code !== 0) {
  throw new Error(`convert exited with code ${code}`);
}
```

### Promisify callback APIs correctly

Use the promise APIs Node.js already ships (`node:fs/promises`, `node:timers/promises`, `node:stream/promises`, `node:dns/promises`) and `util.promisify` for callback-last functions. Hand-written wrappers tend to drop the error path, settle twice, or lose `this`.

```javascript
// ❌ Ignores err: JSON.parse(undefined) then throws inside the callback and crashes the process
const readConfig = (path) => new Promise((resolve) => {
  fs.readFile(path, 'utf8', (err, data) => resolve(JSON.parse(data)));
});
// ❌ promisify on an unbound method: `this` is undefined when get() runs
const get = promisify(cache.get);

// ✅ Built-in promise APIs, a bound promisify, events.once() for one-shot events
const config = JSON.parse(await readFile(path, 'utf8')); // node:fs/promises
const get = promisify(cache.get.bind(cache));
await once(redis, 'ready', { signal: AbortSignal.timeout(5_000) }); // rejects on 'error' or timeout
```

### Keep request context in AsyncLocalStorage

Module-level variables are shared by every concurrent request. `AsyncLocalStorage` carries per-request data (request ID, tenant, user) through awaits, timers, and callbacks without passing it through every function. Prefer `run()` over `enterWith()`.

```javascript
// ❌ Shared mutable state: concurrent requests overwrite each other's user
let currentUser;
app.use((req, res, next) => { currentUser = req.user; next(); });

// ✅ One store per request, readable anywhere down the async call chain
import { AsyncLocalStorage } from 'node:async_hooks';

export const requestContext = new AsyncLocalStorage();
app.use((req, res, next) => {
  requestContext.run({ requestId: randomUUID(), userId: req.user?.id }, next); // randomUUID: node:crypto
});
export function auditLog(event, fields) {
  const ctx = requestContext.getStore();
  logger.info({ ...fields, event, requestId: ctx?.requestId, userId: ctx?.userId });
}
```

### Put timeouts on all outbound I/O

The built-in `fetch` waits up to 300 s for response headers (the undici default) and has no overall deadline; `http.request` only emits `'timeout'` and never aborts on its own; `pg` has no connection or query timeout unless you configure one. One slow dependency then holds sockets, pool slots, and memory for every request waiting on it. Retry only idempotent calls, with backoff, inside the same deadline. The `AbortSignal` patterns are in [javascript.md](javascript.md#timeouts-with-abortsignal); see also [cancellation propagation](cross-cutting/async-concurrency-patterns.md#2-cancellation-propagation).

```javascript
// ❌ No deadline: a hung upstream holds this request, and its caller, indefinitely
const rates = await fetch(`${config.RATES_URL}/latest`);

// ✅ A deadline per call, combined with the client going away
app.get('/quotes', async (req, res) => {
  const clientGone = new AbortController();
  res.on('close', () => clientGone.abort()); // also fires after a normal finish; harmless then
  const rates = await fetch(`${config.RATES_URL}/latest`, {
    signal: AbortSignal.any([clientGone.signal, AbortSignal.timeout(3_000)]),
  });
  if (!rates.ok) throw new Error(`Rates service answered ${rates.status}`);
  res.json(await rates.json());
});

// ✅ Timeouts on database clients too: waiting for a connection, and per statement
const pool = new Pool({ connectionString: config.DATABASE_URL, connectionTimeoutMillis: 2_000, statement_timeout: 5_000 });
```

---

## Streams & Backpressure

### Use pipeline(), not .pipe()

`.pipe()` does not forward errors: if the source fails, the destination is not closed, and if the destination fails, the source keeps reading. `pipeline()` from `node:stream/promises` destroys every stage on error, reports the error once, and returns a promise.

```javascript
// ❌ Errors from any stage are unhandled; a failed write leaks file descriptors
createReadStream(src).pipe(createGzip()).pipe(createWriteStream(dest));

// ✅ One promise for the whole chain; every stream is destroyed on failure
await pipeline(createReadStream(src), createGzip(), createWriteStream(dest));

// ✅ Streaming a response: a client disconnect is normal, not a server error
app.get('/backups/latest', async (req, res) => {
  res.type('application/gzip');
  try {
    await pipeline(createReadStream(LATEST_BACKUP_PATH), res);
  } catch (err) {
    if (err.code !== 'ERR_STREAM_PREMATURE_CLOSE') throw err; // otherwise the client went away
  }
});
```

### Respect write() backpressure

`write()` returns `false` once the internal buffer passes `highWaterMark` (64 KiB for byte streams since Node.js 22). Code that ignores it buffers the whole output in memory whenever the consumer is slower than the producer. Let `pipeline()` pace the producer, or wait for `'drain'`. See also [backpressure](cross-cutting/async-concurrency-patterns.md#3-backpressure).

```javascript
// ❌ Ignores write(): the whole export piles up in memory for a slow client
for await (const row of orders.cursor()) res.write(toCsvLine(row));
res.end();

// ✅ pipeline() pauses the cursor while the response buffer is full
await pipeline(orders.cursor(), async function* (rows) {
  for await (const row of rows) yield toCsvLine(row);
}, res);

// ✅ By hand: wait for 'drain' whenever write() returns false
const out = createWriteStream(exportPath);
for await (const row of orders.cursor()) {
  if (!out.write(toCsvLine(row))) await once(out, 'drain'); // rejects if the stream errors
}
out.end();
await finished(out);
```

### Stream large payloads instead of buffering

Reading a whole file, download, or upload into memory multiplies memory by concurrency: 50 parallel 20 MB downloads need 1 GB of heap. Stream them, and cap whatever must be buffered. For large JSON, prefer JSON Lines or a streaming parser over one `JSON.parse`; for uploads, see [Limit request bodies and uploads](#limit-request-bodies-and-uploads).

```javascript
// ❌ Whole payloads in memory
res.send(await readFile(file.path));
const archive = Buffer.from(await (await fetch(archiveUrl)).arrayBuffer());

// ✅ Stream from disk and from the network
res.sendFile(file.path); // streams, sets headers, supports Range; errors go to next(err)

const download = await fetch(archiveUrl, { signal: AbortSignal.timeout(60_000) });
if (!download.ok || !download.body) {
  throw new Error(`Download failed with status ${download.status}`);
}
await pipeline(download.body, createWriteStream(archivePath)); // pipeline() accepts web streams
```

---

## Process Lifecycle & Graceful Shutdown

### Handle SIGTERM and drain in-flight work

Orchestrators send `SIGTERM` and kill the process after a grace period. Without a listener, Node.js exits at once and drops in-flight requests and jobs; once a listener is installed, Node.js no longer exits on that signal by itself, so the handler must finish the job. On Kubernetes, endpoint removal and `SIGTERM` happen concurrently, so keep serving for a few seconds (or use a `preStop` sleep) before closing the listener. For NestJS, see [nestjs.md](nestjs.md#lifecycle--runtime).

```javascript
// ❌ Exit at once: in-flight requests fail, transactions are cut, messages are redelivered
process.on('SIGTERM', () => process.exit(0));

// ✅ Fail readiness, stop accepting, drain, close resources, exit before the deadline
let shuttingDown = false;

async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true; // /readyz now answers 503
  logger.info({ signal }, 'shutdown started');
  const deadline = setTimeout(() => {
    server.closeAllConnections(); // deadline reached: cut what is left
    process.exit(1);
  }, 25_000); // below the orchestrator's grace period
  deadline.unref(); // never keeps the process alive by itself
  // close() drops idle keep-alive sockets once; sockets busy at that moment
  // would otherwise stay open for keepAliveTimeout after their last response
  const sweep = setInterval(() => server.closeIdleConnections(), 1_000);
  try {
    await new Promise((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())));
    await jobConsumer.close(); // stop taking jobs, wait for running ones
    await pool.end();
  } catch (err) {
    logger.error({ err }, 'shutdown failed');
    process.exitCode = 1;
  } finally {
    clearInterval(sweep);
  }
}

process.once('SIGTERM', () => void shutdown('SIGTERM')); // shutdown() handles its own errors
process.once('SIGINT', () => void shutdown('SIGINT'));
```

### Exit after uncaughtException

After an uncaught exception the process is in an undefined state; the Node.js docs say it is not safe to resume normal operation. The default (print the stack, exit with code 1) is already correct. A custom handler may only log synchronously and exit, and the supervisor (container runtime, systemd, PM2) restarts the process.

```javascript
// ❌ Log and carry on: half-finished work, held locks, corrupted in-memory state
process.on('uncaughtException', (err) => logger.error({ err }, 'uncaught exception'));

// ✅ Write synchronously, then exit; unhandled rejections arrive here too (origin 'unhandledRejection')
process.on('uncaughtException', (err, origin) => {
  writeSync(process.stderr.fd, `${origin}: ${err?.stack ?? err}\n`); // node:fs
  process.exit(1);
});
```

### No process.exit() in library code

`process.exit()` ends the process immediately, even with writes to stdout still pending (writes to pipes are asynchronous on POSIX), so output is truncated and callers cannot clean up or recover. Libraries throw; CLIs set `process.exitCode` and let the process end.

```javascript
// ❌ A library decides the fate of the whole process
if (!existsSync(path)) {
  console.error(`Config not found: ${path}`);
  process.exit(1);
}

// ✅ Libraries throw; the CLI entry point sets exitCode
try {
  await run(process.argv.slice(2));
} catch (err) {
  console.error(err.message);
  process.exitCode = 1;
}
```

### Containers: signals, PID 1, and memory limits

Node.js was not designed to run as PID 1: it does not respond to `SIGINT` and similar signals there, and it does not reap orphaned child processes. `npm start` puts npm between the runtime and Node.js, and npm swallows signals. Node.js sizes its default heap from the memory it can see, including the cgroup limit, but an explicit `--max-old-space-size` above the container limit lets the kernel OOM-kill the process instead of V8 failing with a heap error. Newer releases also accept `--max-old-space-size-percentage`.

```dockerfile
# ❌ npm as the entry point swallows SIGTERM; the heap limit is above the 2 GiB container limit
ENV NODE_OPTIONS="--max-old-space-size=4096"
CMD ["npm", "start"]

# ✅ node directly, under an init that forwards signals and reaps children (or `docker run --init`),
#    and a heap below the limit to leave room for buffers, stacks, and native memory
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "--max-old-space-size=1536", "dist/server.js"]
```

### Health and readiness checks

Liveness answers "is the process responsive?" and must not depend on downstream systems, or a database outage restarts every replica. Readiness answers "should traffic come here?": it fails during startup, during shutdown, and while a required dependency is down. Both answer fast, need no authentication, and reveal no internals.

```javascript
// ❌ Liveness that checks the database (one outage restarts every replica) and leaks configuration
app.get('/healthz', async (req, res) => {
  await pool.query('SELECT 1');
  res.json({ status: 'ok', env: process.env });
});

// ✅ Cheap liveness; readiness reflects startup, shutdown, and required dependencies
app.get('/livez', (req, res) => res.send('ok'));
app.get('/readyz', async (req, res) => {
  if (!startupComplete || shuttingDown) return res.status(503).send('not ready');
  try {
    await pool.query('SELECT 1'); // bounded by the pool's timeouts
    res.send('ok');
  } catch {
    res.status(503).send('database unavailable');
  }
});
```

---

## Configuration & Secrets

### Validate configuration once at startup

`process.env` values are strings or `undefined`: `'false'` is truthy and `'8080'` is not a number. Parse and validate all configuration in one module at startup, fail fast with a clear message, and pass the typed result around; other code should not read `process.env`. For local development, `node --env-file=.env` (or `--env-file-if-exists`) loads a file without a dependency.

```javascript
// ❌ Read ad hoc, deep in the code; mistakes surface one request at a time
if (process.env.ENABLE_CACHE) enableCache(); // 'false' is truthy
const port = process.env.PORT || 3000;        // the string '8080', or 3000 when unset

// ✅ config.js: parse once, fail fast, freeze (zod shown; any schema validator works)
const Env = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']),
  PORT: z.coerce.number().int().min(1).max(65_535).default(3000),
  DATABASE_URL: z.string().min(1),
  PAYMENTS_KEY: z.string().min(1),
  ENABLE_CACHE: z.enum(['true', 'false']).default('false').transform((v) => v === 'true'),
});
const parsed = Env.safeParse(process.env);
if (!parsed.success) {
  const fields = parsed.error.issues.map((issue) => issue.path.join('.')).join(', ');
  throw new Error(`Invalid configuration: ${fields}`); // names only: values may be secrets
}
export const config = Object.freeze(parsed.data);
```

### Keep secrets out of code, logs, and images

Secrets leak through source control, log lines, error responses, and container layers far more often than through exploits. Keep `.env`, `.npmrc`, and `.git` out of images with `.dockerignore`. Values passed with `ARG` or `ENV` stay in the image history, so pass build-time secrets as BuildKit secret mounts (`RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci`). For error responses, see [Error messages](security-review-guide.md#error-messages).

```javascript
// ❌ A hard-coded key, whole headers in logs, stack traces sent to clients
const payments = new PaymentsClient({ apiKey: 'live-3f9a1c0e7d' });
logger.info({ headers: req.headers }, 'incoming request'); // Authorization, Cookie
res.status(500).json({ error: err.message, stack: err.stack });

// ✅ Secrets from validated configuration; redaction in the logger
const payments = new PaymentsClient({ apiKey: config.PAYMENTS_KEY });
export const logger = pino({ redact: ['req.headers.authorization', 'req.headers.cookie', '*.password', '*.token'] });
```

---

## HTTP Servers & Express

### Async errors in Express 4 vs 5

Express 5 (the npm `latest` since March 2025) passes a rejected promise from a handler or middleware to `next(err)`. Express 4 ignores it: the request hangs, and under the default `--unhandled-rejections=throw` the process crashes, so any client that can trigger the error can take the service down. Express 4 has been in maintenance (security and high-priority fixes only) since 2025-04-01, with end-of-life announced for no sooner than 2026-10-01. In both versions, errors from callback APIs are not caught: call `next(err)` in the callback instead of throwing.

```javascript
// ❌ Express 4: the rejection never reaches the error handler and crashes the process
app.get('/users/:id', async (req, res) => {
  res.json(await users.findById(req.params.id)); // throws on a database error
});

// ✅ Express 4: forward rejections explicitly, for example with one wrapper
const asyncHandler = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
app.get('/users/:id', asyncHandler(async (req, res) => {
  res.json(await users.findById(req.params.id));
}));

// ✅ Express 5: the unwrapped async handler is fine; rejections go to next(err)
```

| Express 4 | Express 5 |
|---|---|
| `app.get('/*', ...)` | Wildcards must be named: `'/*splat'` (`'/{*splat}'` also matches `/`) |
| `'/:file.:ext?'`, `'/:id(\\d+)'` | Optional parts use braces (`'/:file{.:ext}'`); regex in paths is gone, so validate in the handler |
| `req.query` writable, "extended" parser | Read-only getter, "simple" parser by default |
| `req.body` is `{}` without a parser | `undefined` unless a body parser ran |

Removed APIs (`app.del()`, `req.param()`, `res.sendfile()`, `res.redirect('back')`, and others) fail at runtime; the official codemod handles most of them: `npx codemod@latest @expressjs/v5-migration-recipe`.

### Middleware order and the error handler

Express runs middleware in registration order: security headers and body limits first, then authentication, routes, a 404 handler, and the error handler last. Express recognizes error middleware by its four parameters, so deleting an "unused" `next` turns it into ordinary middleware that never sees errors.

```javascript
// ❌ Error handler before the routes, with three parameters, leaking internals
app.use((err, req, res) => res.status(500).json({ message: err.message, stack: err.stack }));
app.use('/api', apiRouter);

// ✅ Headers → body limits → auth → routes → 404 → error handler with four parameters
app.use(helmet()); // security headers; also removes X-Powered-By
app.use(express.json({ limit: '100kb' }));
app.use('/api', authenticate, apiRouter);
app.use((req, res) => res.status(404).json({ error: 'Not found' }));
app.use((err, req, res, next) => {
  if (res.headersSent) return next(err); // let Express close the connection
  const status = err.expose ? err.status : 500; // http-errors (used by body-parser) sets expose
  if (status >= 500) logger.error({ err, method: req.method, path: req.path }, 'request failed');
  res.status(status).json({ error: status >= 500 ? 'Internal Server Error' : err.message });
});
```

### Send exactly one response

Code that keeps running after `res.json()` either throws `ERR_HTTP_HEADERS_SENT` ("Cannot set headers after they are sent to the client") or does work whose result is thrown away. Return after every early response, and never call `next()` after responding.

```javascript
// ❌ Falls through after the 404; the second res.json() throws ERR_HTTP_HEADERS_SENT
if (!invoice) {
  res.status(404).json({ error: 'Invoice not found' });
}
res.json(invoice);

// ❌ Responds, then calls next(): the next handler responds again
if (!req.user) res.status(401).end();
next();

// ✅ Return after every early response
if (!invoice) {
  res.status(404).json({ error: 'Invoice not found' });
  return;
}
res.json(invoice);
```

### Validate request input at the boundary

`req.body`, `req.query`, and `req.params` are untyped client input: a field you expect to be a string can arrive as an array or an object, and extra fields get mass-assigned. Validate shape and types with a schema, then use only the parsed output. In Express 5, `req.query` is a getter that re-parses on every access, so assigning to it throws in strict-mode code and in-place coercion is lost; keep validated values in a local variable or `res.locals`. Deep merges of request JSON are a [prototype-pollution](javascript.md#objects-as-dictionaries-and-prototype-pollution) risk.

```javascript
// ❌ Trusts the shape: { "email": { "$gt": "" } } makes the filter match any user
const user = await usersCollection.findOne({ email: req.body.email });
// ❌ Mass assignment: the client can send { "ownerId": "someone-else" }
const project = await Project.create(req.body);

// ✅ Schema-validate, then build the record from known fields (unknown keys are stripped)
const CreateProject = z.object({
  name: z.string().trim().min(1).max(100),
  visibility: z.enum(['private', 'team']),
});

app.post('/projects', async (req, res) => {
  const parsed = CreateProject.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: 'Invalid request', issues: parsed.error.issues });
  }
  res.status(201).json(await Project.create({ ...parsed.data, ownerId: req.user.id }));
});
```

### Configure server timeouts and keep-alive

The defaults are `headersTimeout` 60 s, `requestTimeout` 300 s, `keepAliveTimeout` 5 s, and no socket inactivity timeout. Behind a load balancer, the server's keep-alive timeout must be longer than the balancer's idle timeout (60 s by default on an AWS ALB); otherwise Node.js closes connections the balancer still reuses, and clients see sporadic 502s. Without a proxy in front, `headersTimeout` and `requestTimeout` must stay non-zero to limit slow-client attacks. A future major is expected to raise the `keepAliveTimeout` default; setting it explicitly stays correct either way.

```javascript
// ❌ The 5 s default keep-alive behind a 60 s load-balancer idle timeout: intermittent 502s
app.listen(config.PORT);
// ❌ Disabled timeouts: slow or stalled clients hold sockets forever
server.requestTimeout = 0;
server.headersTimeout = 0;

// ✅ Keep-alive above the balancer's idle timeout; bounded header and request time
import { createServer } from 'node:http';

const server = createServer({
  keepAliveTimeout: 65_000, // longer than the ALB idle timeout (60 s)
  headersTimeout: 60_000,
  requestTimeout: 120_000,  // the longest legitimate request or upload
}, app);
server.listen(config.PORT);
```

### Set trust proxy correctly

Behind a proxy, `req.ip`, `req.protocol`, and `req.hostname` come from the `X-Forwarded-*` headers only as far as `trust proxy` allows. With the default (`false`), every request seems to come from the proxy: per-IP rate limits ([Rate limiting](security-review-guide.md#rate-limiting)) throttle all clients together, and express-session refuses to set `secure` cookies. With `true`, `req.ip` is the left-most `X-Forwarded-For` entry, which any client can forge to dodge rate limits and poison audit logs.

```javascript
// ❌ Trusts any X-Forwarded-For value, so clients choose their own req.ip
app.set('trust proxy', true);

// ✅ Trust exactly the proxies you run: a hop count (one load balancer here) or their addresses
app.set('trust proxy', 1);
// app.set('trust proxy', ['loopback', '10.0.0.0/8']);
```

---

## Node.js Security

Topics shared with other stacks live in their own guides; this section keeps only the Node-specific rules.

| Topic | See |
|---|---|
| SQL injection with `pg`/Prisma | [SQL Injection Prevention](cross-cutting/sql-injection-prevention.md#nodejs) |
| Escaping server-rendered HTML; JSON inside `<script>` | [XSS Prevention](cross-cutting/xss-prevention.md#server-side-rendering) |
| CSP with helmet | [XSS Prevention](cross-cutting/xss-prevention.md#content-security-policy-csp) |
| JWT, CSRF/SameSite, SSRF, IDOR, `exec` vs `execFile` | [Security Review Guide](security-review-guide.md#jwt-security), [CSRF](security-review-guide.md#csrf-prevention), [SSRF](security-review-guide.md#ssrf-prevention), [IDOR](security-review-guide.md#idor-insecure-direct-object-reference), [Command injection](security-review-guide.md#command-injection-prevention) |
| CORS, security headers, crypto mistakes, leaky error responses, rate limits, `npm audit`, logging | [CORS](security-review-guide.md#cors-configuration), [Headers](security-review-guide.md#http-headers), [Common mistakes](security-review-guide.md#common-mistakes), [Error messages](security-review-guide.md#error-messages), [Rate limiting](security-review-guide.md#rate-limiting), [Dependencies](security-review-guide.md#audit-commands), [Logging](security-review-guide.md#secure-logging) |
| Pagination, caching, compression, rate limiting in Express | [Performance: API](performance-review-guide.md#api-performance) |
| Prisma N+1; DataLoader | [N+1 Queries](cross-cutting/n-plus-one-queries.md#typescript--prisma), [DataLoader](cross-cutting/n-plus-one-queries.md#nodejs--graphql-dataloader) |
| Worker-pool concurrency; backpressure | [Async patterns](cross-cutting/async-concurrency-patterns.md#typescript-worker-pool-concurrency-limit), [Backpressure](cross-cutting/async-concurrency-patterns.md#3-backpressure) |
| Error classes and cause chains | [Error Handling](cross-cutting/error-handling-principles.md#example-hierarchy-typescript) |
| TOCTOU with `fs` (`flag: 'wx'`) | [Universal Quality](code-quality-universal.md#toctou-race-conditions) |

### Prevent path traversal

`path.join()` and `path.normalize()` do not stop `../` sequences, and `path.resolve()` drops the base entirely when the input is absolute. Resolve against a fixed base, then check that the result stays inside it; if the directory can contain symlinks, compare `fs.realpath()` results. Express decodes `req.params`, so `..%2F..%2Fetc%2Fpasswd` arrives as `../../etc/passwd`.

```javascript
// ❌ "../../etc/passwd" escapes the upload directory
res.sendFile(path.join(UPLOAD_DIR, req.params.name));

// ✅ Express: pass a root, and sendFile keeps the resolved path inside it
res.sendFile(req.params.name, { root: UPLOAD_DIR, dotfiles: 'deny' });

// ✅ Plain fs: resolve, then require the result to stay under the (absolute, resolved) base
function resolveInside(base, userPath) {
  const target = path.resolve(base, userPath);
  if (target !== base && !target.startsWith(base + path.sep)) {
    throw new Error('Path escapes the base directory');
  }
  return target;
}
```

### Compare secrets in constant time

`===` on strings stops at the first differing character, so response timing leaks how much of a token or signature matched. Use `crypto.timingSafeEqual()`; it throws when the lengths differ, so compare fixed-length digests. Passwords are never compared directly: use the verify function of a password-hashing library.

```javascript
// ❌ Early-exit comparison: the signature can be guessed byte by byte
const valid = req.get('x-signature') === expectedSignature;

// ✅ HMAC the raw body and compare digests of equal length (node:crypto). Register the route
//    before any global express.json(), or the body is already parsed and express.raw() skips it
app.post('/webhooks/payments', express.raw({ type: 'application/json', limit: '1mb' }), async (req, res) => {
  const expected = createHmac('sha256', config.WEBHOOK_SECRET).update(req.body).digest();
  const received = Buffer.from(req.get('x-signature') ?? '', 'hex');
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) {
    return res.status(401).end();
  }
  await payments.handleEvent(JSON.parse(req.body.toString('utf8')));
  res.status(204).end();
});
```

### vm is not a sandbox

The Node.js docs are explicit: `node:vm` is not a security mechanism, so do not use it to run untrusted code. Code in a context reaches the host through the objects it is given, and in-process sandbox libraries built on `vm` have a long record of escapes. The permission model (`--permission`, stable since 22.13.0) restricts file system, child-process, worker, addon, and WASI access, but the docs call it a "seat belt": it gives no guarantees against malicious code. If running arbitrary code is the product, use a separate locked-down process or container per tenant.

```javascript
// ❌ "Sandboxed" user formulas; this input reaches the host process:
//    this.constructor.constructor('return process')().exit()
const total = vm.runInNewContext(req.body.formula, { price, quantity });

// ✅ Don't execute user code: parse a small expression language with an allowlist of operations
const total = evaluateFormula(parseFormula(req.body.formula), { price, quantity });
```

### Limit request bodies and uploads

Every buffered byte is memory. `express.json()` and `express.urlencoded()` default to a 100 kB limit, and urlencoded also caps `parameterLimit` at 1000 and nesting `depth` at 32; raise a limit on the route that needs it, not globally. Multer has no file size or count limit by default, and `memoryStorage()` keeps every file in RAM. `requestTimeout` bounds slow uploads as well.

```javascript
// ❌ A global 50 MB JSON limit, and unbounded uploads held in memory
app.use(express.json({ limit: '50mb' }));
const upload = multer({ storage: multer.memoryStorage() });

// ✅ A small global limit; a larger one only on the route that needs it, registered first
app.post('/imports', authenticate, express.json({ limit: '5mb' }), importOrders);
app.use(express.json({ limit: '100kb' }));
// ✅ Uploads bounded and written to disk
const upload = multer({ dest: UPLOAD_TMP_DIR, limits: { fileSize: 10 * 1024 * 1024, files: 1, fields: 20 } });
```

### Avoid open redirects

`res.redirect()` puts whatever it gets into the `Location` header without validation, so a `?next=` parameter turns a trusted login page into a phishing redirector. Allow only same-origin paths, or hosts on an allowlist.

```javascript
// ❌ Redirects anywhere: ?next=https://evil.example or ?next=//evil.example
res.redirect(req.query.next);

// ✅ Resolve against your own origin and keep only same-origin targets
function safeRedirectTarget(value) {
  if (typeof value !== 'string') return '/';
  try {
    const url = new URL(value, config.APP_ORIGIN); // also catches "//host" and "/\host" tricks
    return url.origin === config.APP_ORIGIN ? `${url.pathname}${url.search}${url.hash}` : '/';
  } catch {
    return '/';
  }
}
res.redirect(safeRedirectTarget(req.query.next));
```

---

## Dependencies & Supply Chain

### Commit the lockfile and install with npm ci

`npm install` may rewrite the lockfile and resolve newer versions. `npm ci` installs exactly what the lockfile says, fails if the lockfile disagrees with `package.json`, and never writes either file; pass it the same tree-shaping flags that built the lock (`--legacy-peer-deps`, `--install-links`). In review, read lockfile diffs: a `resolved` URL outside the registry, a git or tarball source, or an `integrity` change without a version change needs an explanation.

```dockerfile
# ❌ The lockfile is ignored or rewritten, so each build can resolve a different tree
COPY . .
RUN npm install

# ✅ Lockfile first (layer caching), exact install, no dev dependencies at runtime
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY . .
```

### Review new dependencies

Each new package brings its transitive tree and its maintainers, and it may run install scripts on developer machines and in CI. Check for a [built-in](#prefer-built-in-apis-and-node-imports) first, then maintenance and release history, the size of the tree, the license, and the name itself (typosquats, recent ownership transfers).

```bash
# ✅ Look before approving
npm view <package> time maintainers scripts license   # release history, owners, install scripts
npm ls <package> --all                                # what it pulls into the tree
npm approve-scripts --allow-scripts-pending           # npm 12: install scripts that would be blocked
```

npm 12 blocks dependency lifecycle scripts (`preinstall`, `install`, `postinstall`, and implicit `node-gyp` builds) unless the root `package.json` allowlist permits them, and stops resolving git and remote-URL dependencies unless `--allow-git` and `--allow-remote` permit them. A PR that adds a package to the script allowlist gives it code execution at install time, so review it like a new dependency. Which npm major CI uses decides the default: Node.js 24 bundles npm 11, where `ignore-scripts=true` in `.npmrc` is the blunt alternative.

### Audit and patch transitive vulnerabilities

`npm audit --audit-level=high` fails CI on known advisories, and `npm audit signatures` verifies registry signatures and provenance attestations. `npm audit fix --force` can install semver-major upgrades, so review its diff like any other upgrade. When only a transitive dependency has a fix, `overrides` in the root `package.json` pins it until the parent package ships one; a top-level `"vulnerable-dep": "1.4.2"` applies everywhere.

```json
{
  "overrides": {
    "legacy-client": { "vulnerable-dep": "1.4.2" }
  }
}
```

Link the advisory in the PR and remove the override once the parent package ships the fix. Registry worms such as Shai-Hulud (September 2025) republished hundreds of trojanized packages with stolen tokens, so a fresh patch release of a trusted package is not automatically safe; `min-release-age=<days>` in `.npmrc` (npm 11.10.0+) installs only versions older than that.

---

## Performance & Resource Management

### Reuse clients and connection pools

A database pool, Redis client, or SDK client created per request opens new connections every time (TCP, TLS, authentication), exhausts server connection slots under load, and leaks sockets nobody closes. Create one per process at startup, bound it, close it on shutdown, and keep `max` times the replica count below the database's connection limit. For outbound HTTP, the global agent has used keep-alive since Node.js 19 and `fetch` pools connections per origin; an `http.Agent` per request defeats both.

```javascript
// ❌ A pool per request, and a checked-out client that leaks when the query throws
const pool = new Pool({ connectionString: config.DATABASE_URL }); // inside the handler
const client = await pool.connect();
const { rows } = await client.query('SELECT id, name FROM accounts WHERE id = $1', [req.params.id]);
client.release();

// ✅ One bounded pool per process (db.js); release checked-out clients in finally
export const pool = new Pool({ connectionString: config.DATABASE_URL, max: 10, connectionTimeoutMillis: 2_000 });

export async function transfer(fromId, toId, amountCents) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await applyTransfer(client, fromId, toId, amountCents);
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
```

### Bound caches and watch for listener leaks

A module-level `Map` used as a cache grows until the process runs out of memory ([unbounded data structures](performance-review-guide.md#unbounded-data-structures)); cap entries and add a TTL, for example `new LRUCache({ max: 10_000, ttl: 5 * 60_000 })` from lru-cache. `MaxListenersExceededWarning` (more than 10 listeners for one event) usually means a listener is added per request to a long-lived emitter; fix the leak instead of raising the limit. Detect disconnects with `res.on('close')`: since Node.js 16 the request's `'close'` fires when the request is done, not when the socket closes.

```javascript
// ❌ A listener per request on a process-wide emitter, never removed
app.get('/prices/stream', (req, res) => {
  priceFeed.on('tick', (tick) => res.write(`data: ${JSON.stringify(tick)}\n\n`));
});

// ✅ Remove the listener when the response closes (it also closes when the client disconnects)
app.get('/prices/stream', (req, res) => {
  res.set({ 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' }).flushHeaders();
  let behind = false; // a live feed cannot pause: skip ticks while the client is slow
  const onTick = (tick) => {
    if (!behind) behind = !res.write(`data: ${JSON.stringify(tick)}\n\n`);
  };
  res.on('drain', () => { behind = false; });
  priceFeed.on('tick', onTick);
  res.on('close', () => priceFeed.off('tick', onTick));
});
```

### Log efficiently

`console.log` writes to stdout synchronously when stdout is a file or a terminal on POSIX, and asynchronously, buffering in memory, when it is a pipe. Either way, formatting large objects on hot paths ([hot-path bloat](performance-review-guide.md#hot-path-bloat)) costs CPU. Use a leveled, structured logger, log objects rather than prebuilt strings, and never log secrets or personal data ([secure logging](security-review-guide.md#secure-logging)).

```javascript
// ❌ Pretty-printed payloads on every request; strings built even when debug is off
console.log('order payload: ' + JSON.stringify(order, null, 2));
logger.debug(`cart: ${JSON.stringify(cart)}`);

// ✅ Structured and leveled; expensive details only when the level is enabled
logger.info({ orderId: order.id, itemCount: order.items.length }, 'order created');
if (logger.isLevelEnabled('debug')) {
  logger.debug({ cart: summarizeCart(cart) }, 'cart state');
}
```

---

## Testing Node.js Services

### Test HTTP handlers in-process

Export the app from a factory that does not call `listen()`, inject its dependencies, and drive it over HTTP inside the test process. Listen on port 0 so parallel test files never collide. supertest does the same with `await request(createApp(deps)).get('/users/unknown').expect(404)`.

```javascript
// ❌ The test imports the real server: fixed port, real database, process-wide side effects
import '../src/server.js'; // calls app.listen(3000) and connects to the database

// ✅ node:test + fetch against an ephemeral port, with fakes injected
let server;
let baseUrl;

before(async () => {
  server = createApp({ users: new InMemoryUserRepository() }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});
after(async () => {
  server.close();
  await once(server, 'close');
});

test('GET /users/:id returns 404 for an unknown user', async () => {
  const res = await fetch(`${baseUrl}/users/unknown`, { signal: AbortSignal.timeout(2_000) });
  assert.equal(res.status, 404);
});
```

### Block real network calls in tests

A test that quietly reaches a real API is slow and flaky, and it can have side effects such as emails or charges. Intercept outbound HTTP and fail on anything unhandled. MSW's `setupServer` (from `msw/node`) intercepts `http`/`https` requests and the global `fetch`; nock intercepts `fetch` only from v14 (`nock.disableNetConnect()` plus `nock.enableNetConnect('127.0.0.1')`). Both also see requests to your own in-process server, so let loopback traffic through. For MSW basics, see [javascript.md](javascript.md#testing).

```javascript
// ❌ Unit tests call the payment provider's real API
await checkout(order); // POST https://payments.example.com/v1/charges

// ✅ MSW: mock what the test needs; anything else fails, except the app under test
const api = setupServer(
  http.post('https://payments.example.com/v1/charges', () => HttpResponse.json({ id: 'ch_1', status: 'succeeded' })),
);
before(() => api.listen({
  onUnhandledRequest(request, print) {
    if (new URL(request.url).hostname !== '127.0.0.1') print.error(); // loopback = in-process server
  },
}));
afterEach(() => api.resetHandlers());
after(() => api.close());
```

### Close handles after tests

Servers, pools, intervals, and mock servers left open keep the test process alive or leak state into the next test file. Close everything a test opened in `after`/`afterAll`. `--test-force-exit` (node:test) and `--forceExit` (Jest) hide the leak rather than fix it: find the handle with `--detectOpenHandles` (Jest) or `--reporter=hanging-process` (Vitest), then close it. In application code, give background intervals a stop function, and `.unref()` timers that must not keep a CLI alive.

```javascript
// ❌ Pool and interval never closed; CI works around the hang with "jest --forceExit"
const pool = new Pool(testConfig.database);
startCacheRefresh(); // setInterval inside, never cleared

// ✅ Tear down what the tests opened
after(async () => {
  stopCacheRefresh(); // clearInterval() in the module that started it
  await pool.end();
});
```

---

## Review Checklist

### Runtime & event loop
- [ ] `engines.node`, `.nvmrc`, the Docker base image, and the CI matrix agree on a supported LTS range (no 20.x or older, no odd-numbered line)
- [ ] Version-gated APIs exist on the lowest supported version; built-ins replace new dependencies where they fit and are imported with `node:`
- [ ] No synchronous fs, crypto, zlib, or child-process calls in request paths
- [ ] CPU-heavy work runs in a bounded worker pool, not on the main thread or in a worker per request
- [ ] No recursive `process.nextTick`; chunked work yields with `setImmediate`; event-loop delay is exported as a metric
- [ ] ESM code uses full relative paths and no `require`/`__dirname`; `require(esm)` targets have no top-level await
- [ ] Library `exports` put `"types"` first and `"default"` last, expose no internals through wildcards, and are released as a breaking change when added

### Errors & lifecycle
- [ ] Every promise is awaited or handled; no log-only `unhandledRejection` handler; no `--unhandled-rejections=warn` or `none`
- [ ] Long-lived emitters (pools, sockets, child processes, consumers) have `'error'` listeners
- [ ] Callback APIs go through `node:*/promises`, `util.promisify`, or `events.once`
- [ ] Per-request context lives in `AsyncLocalStorage`, not in module-level variables
- [ ] Every outbound HTTP, database, and queue call has a timeout
- [ ] The SIGTERM handler fails readiness, closes the server (including busy keep-alive sockets), drains work, closes pools and consumers, and has an `unref()`ed forced-exit timer
- [ ] `uncaughtException` handlers log synchronously and exit; libraries never call `process.exit()`
- [ ] Containers run `node` directly under an init; the heap limit fits inside the container memory limit
- [ ] Liveness does not depend on downstream services; readiness fails during startup and shutdown
- [ ] Configuration is validated once at startup; secrets stay out of code, logs, error responses, and image layers

### Streams & I/O
- [ ] Streams are connected with `pipeline()`; client disconnects are not logged as server errors
- [ ] Manual `write()` loops honor the return value and wait for `'drain'`
- [ ] Large files, downloads, exports, and uploads are streamed, not buffered

### HTTP & Express
- [ ] The Express major is known; on Express 4, async handlers forward errors to `next()`
- [ ] Middleware order is headers, body limits, auth, routes, 404, then a four-parameter error handler that checks `res.headersSent` and hides internals
- [ ] Every early response is followed by `return`; nothing calls `next()` after responding
- [ ] Body, query, and params are schema-validated, and only parsed fields are used
- [ ] `keepAliveTimeout` exceeds the load balancer's idle timeout; header and request timeouts are non-zero
- [ ] `trust proxy` matches the real proxy hops

### Security & dependencies
- [ ] File paths from input are contained (`sendFile` with `root`, or resolve plus a prefix check)
- [ ] Tokens and signatures are compared with `crypto.timingSafeEqual`
- [ ] No untrusted code runs in `vm`, `eval`, or `new Function`
- [ ] Body and upload limits are set per route; uploads are not held in memory
- [ ] Redirect targets are validated against the app's origin or an allowlist
- [ ] The lockfile is committed and CI installs with `npm ci`; lockfile diffs contain no unexpected sources
- [ ] New dependencies, install-script allowlist entries, and `overrides` are justified in the PR; `npm audit` runs in CI

### Tests
- [ ] HTTP handlers are tested in-process on an ephemeral port with injected dependencies
- [ ] Unmocked outbound requests fail the test
- [ ] Tests close servers, pools, timers, and mock servers; no `--forceExit` or `--test-force-exit` workaround

---

## References

- [Don't Block the Event Loop (Node.js)](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop)
- [Backpressuring in Streams (Node.js)](https://nodejs.org/en/learn/modules/backpressuring-in-streams)
- [Security Best Practices (Node.js)](https://nodejs.org/en/learn/getting-started/security-best-practices)
- [ECMAScript Modules (Node.js API)](https://nodejs.org/api/esm.html)
- [Packages and exports (Node.js API)](https://nodejs.org/api/packages.html#exports)
- [Process events (Node.js API)](https://nodejs.org/api/process.html#process-events)
- [HTTP (Node.js API)](https://nodejs.org/api/http.html)
- [Worker threads (Node.js API)](https://nodejs.org/api/worker_threads.html)
- [AsyncLocalStorage (Node.js API)](https://nodejs.org/api/async_context.html)
- [Test runner (Node.js API)](https://nodejs.org/api/test.html)
- [TypeScript support (Node.js API)](https://nodejs.org/api/typescript.html)
- [Permissions (Node.js API)](https://nodejs.org/api/permissions.html)
- [Node.js Releases](https://nodejs.org/en/about/previous-releases)
- [Evolving the Node.js Release Schedule](https://nodejs.org/en/blog/announcements/evolving-the-nodejs-release-schedule)
- [Migrating to Express 5](https://expressjs.com/en/guide/migrating-5.html)
- [Express Error Handling](https://expressjs.com/en/guide/error-handling.html)
- [Express Security Best Practices](https://expressjs.com/en/advanced/best-practice-security.html)
- [Express Behind Proxies](https://expressjs.com/en/guide/behind-proxies.html)
- [Express Version Support](https://expressjs.com/en/support/)
- [OWASP Node.js Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Nodejs_Security_Cheat_Sheet.html)
- [npm ci](https://docs.npmjs.com/cli/v12/commands/npm-ci)
- [npm audit](https://docs.npmjs.com/cli/v12/commands/npm-audit)
- [package.json overrides (npm)](https://docs.npmjs.com/cli/v12/configuring-npm/package-json#overrides)
- [MSW Node.js integration](https://mswjs.io/docs/integrations/node)
