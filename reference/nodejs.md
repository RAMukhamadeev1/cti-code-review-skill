# Node.js Code Review Guide

Node.js services, CLIs, and scripts, including Express 4/5; this guide owns the runtime topics other guides link to. Written for Node.js 22 and 24 LTS and 26 (LTS from 2026-10-28); Node.js 20 reached end of life on 2026-04-30.

Load with [javascript.md](javascript.md) (plus [typescript.md](typescript.md) for `.ts`); NestJS reviews open this guide only for runtime topics. Related: [Security Review Guide](security-review-guide.md) · [Async & Concurrency](cross-cutting/async-concurrency-patterns.md) · [Error Handling](cross-cutting/error-handling-principles.md)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Default severities: 🔴 [blocking] · 🟡 [important] · 🟢 [nit] · 💡 [suggestion]; adjust them to the impact in context. A rule a linter or config already enforces is a finding only when the diff disables it, and pre-existing code only when the change makes it worse.

### Runtime & built-ins → [Runtime Versions & Built-ins](#runtime-versions--built-ins)

- [ ] 🟡 When the PR touches `engines.node`, `.nvmrc`/`.node-version`, the Docker `FROM` tag, the CI matrix, or `@types/node`: they agree on a supported range (22, 24, or 26; no 20.x, odd line, or floating `latest`), and the `@types/node` major matches the lowest supported line.
- [ ] 🟡 APIs added by the diff exist on the lowest supported version ([availability](javascript.md#runtime-availability-of-newer-apis)).
- [ ] 💡 A new dependency that duplicates a built-in (listed below) needs a reason; built-ins are imported with the `node:` prefix.
- [ ] 🟡 `.ts` files that Node.js runs directly use only erasable syntax, `import type` for types, and no `tsconfig` `paths`, and CI still runs `tsc --noEmit`.

### Event loop → [Event Loop & CPU-Bound Work](#event-loop--cpu-bound-work)

- [ ] 🟡 No sync fs, crypto, zlib, child-process calls, or big `JSON.parse` in request paths (startup and CLIs are fine).
- [ ] 🟡 CPU-heavy work runs in one bounded worker pool per process (bounded queue, per-task deadline, closed on shutdown), not a `Worker` per request.
- [ ] 🟡 No recursive `process.nextTick` or loops that only await settled promises; chunked work yields with `setImmediate`.
- [ ] 💡 When the PR adds a service or its metrics: p99 event-loop delay is exported.

### Modules & packaging → [Modules & Packaging](#modules--packaging)

- [ ] 🟡 ESM code has no `require`, `module.exports`, or `__dirname`, uses full relative specifiers with extensions, and imports JSON `with { type: 'json' }`.
- [ ] 🟡 CommonJS `require()`s an ES module only when that graph has no top-level `await` (`ERR_REQUIRE_ASYNC_MODULE`).
- [ ] 🟡 A stateful package does not ship separate ESM and CommonJS builds (dual-package hazard).
- [ ] 🟡 Library `exports`: adding the field is a breaking change; `"types"` comes first and `"default"` last in every condition object; no wildcard publishes internals.

### Errors & async → [Async Error Handling](#async-error-handling)

- [ ] 🔴 No floating promise in request or job paths (an unhandled rejection exits the process), no log-only `unhandledRejection` listener, and no `--unhandled-rejections=warn|none` in scripts or `NODE_OPTIONS`.
- [ ] 🔴 Long-lived emitters (pools, sockets, streams, child processes, consumers) have synchronous `'error'` listeners; one-shot waits use `events.once()`, which rejects on `'error'`.
- [ ] 🟡 Callback APIs go through `node:*/promises`, a bound `util.promisify`, or `events.once()`; hand-written wrappers handle `err`.
- [ ] 🔴 Per-request data (user, tenant, request ID) lives in `AsyncLocalStorage` (`run()`), not in module-level variables.
- [ ] 🟡 Every outbound HTTP, database, and queue call has a deadline; retries are limited to idempotent calls, with backoff, inside that deadline → [Timeouts](#put-timeouts-on-all-outbound-io).

### Streams → [Streams & Backpressure](#streams--backpressure)

- [ ] 🟡 Streams are joined with `pipeline()`, not `.pipe()`; a client disconnect (`ERR_STREAM_PREMATURE_CLOSE`) is not logged as a server error.
- [ ] 🟡 Manual `write()` loops honor a `false` return and wait for `'drain'`.
- [ ] 🟡 Large files, downloads, exports, and uploads are streamed, not buffered whole.

### Lifecycle & containers → [Process Lifecycle & Graceful Shutdown](#process-lifecycle--graceful-shutdown)

- [ ] 🟡 When the PR touches shutdown: SIGTERM fails readiness, keeps serving briefly, closes the server and idle keep-alive sockets, drains jobs, closes pools and consumers, and has an `unref()`ed forced-exit timer below the grace period.
- [ ] 🔴 `uncaughtException` handlers log synchronously and exit; they never resume.
- [ ] 🟡 Libraries throw instead of calling `process.exit()`; CLIs set `process.exitCode`.
- [ ] 🟡 When the PR touches the Dockerfile: `node` runs directly (not `npm start`) under an init, and `--max-old-space-size` fits inside the container memory limit.
- [ ] 🟡 Liveness does not depend on downstream systems; readiness fails during startup, shutdown, and required-dependency outages; probes need no auth and reveal no internals.

### Configuration & secrets → [Configuration & Secrets](#configuration--secrets)

- [ ] 🟡 Configuration is parsed and validated once at startup (typed values, fail fast, error messages name keys but not values); other code does not read `process.env`.
- [ ] 🔴 No secrets in code, logs (whole headers or bodies), error responses (stack traces), `ARG`/`ENV` layers, or image contents.

### HTTP & Express → [HTTP Servers & Express](#http-servers--express)

- [ ] 🔴 Express 4: async handlers and middleware forward rejections (`next(err)` or a wrapper); in both majors, errors in callbacks go to `next(err)`.
- [ ] 🟡 Express 5 upgrades handle the path syntax, `req.query`, `req.body`, and removed-API changes (table below).
- [ ] 🟡 Middleware order is headers, body limits, auth, routes, 404, then a four-parameter error handler that checks `res.headersSent` and hides internals.
- [ ] 🟡 Every early response is followed by `return`; nothing calls `next()` after responding.
- [ ] 🔴 Body, query, and params are schema-validated and only the parsed output is used (operator injection, mass assignment).
- [ ] 🟡 When the PR touches server setup: `keepAliveTimeout` exceeds the load balancer's idle timeout, `headersTimeout`/`requestTimeout` stay non-zero, and `trust proxy` names the real hops (never `true`).

### Node security → [Node.js Security](#nodejs-security)

- [ ] 🔴 File paths from input stay inside a base directory (`sendFile` with `root`, or resolve plus a prefix check).
- [ ] 🔴 Tokens and signatures are compared with `crypto.timingSafeEqual` over equal-length digests; passwords go through the hashing library's verify.
- [ ] 🔴 No untrusted code runs in `vm`, `eval`, or `new Function`; the permission model is not a sandbox.
- [ ] 🟡 Body and upload limits are set per route; uploads are bounded and not held in memory.
- [ ] 🔴 Redirect targets from input resolve against the app origin and are returned as an absolute same-origin URL, or `/`.

### Dependencies → [Dependencies & Supply Chain](#dependencies--supply-chain)

- [ ] 🟡 When the PR touches `package.json` or the lockfile: the lockfile is committed, CI installs with `npm ci`, and the lockfile diff has no unexpected `resolved` hosts, git or tarball sources, or `integrity` changes without a version change.
- [ ] 🟡 New dependencies, install-script allowlist entries, `--allow-git`/`--allow-remote`, and `overrides` are justified in the PR.

### Resources → [Performance & Resource Management](#performance--resource-management)

- [ ] 🟡 Pools and clients are created once per process, bounded, released in `finally`, and closed on shutdown.
- [ ] 🟡 Module-level caches have a size cap and TTL; no listener is added per request to a long-lived emitter; disconnects are detected with `res.on('close')`.
- [ ] 🟢 Hot paths log structured, leveled objects (no pretty-printed payloads, no strings built for disabled levels), with no secrets or personal data.

### Tests → [Testing Node.js Services](#testing-nodejs-services)

- [ ] 🟡 HTTP handlers are tested in-process on port 0 with injected dependencies.
- [ ] 🟡 Unmocked outbound requests fail the test (loopback to the app under test excepted).
- [ ] 🟡 Tests close servers, pools, timers, and mock servers; no `--forceExit` or `--test-force-exit` workaround.

---

## Runtime Versions & Built-ins

| Line | LTS from | Maintenance from | End of life |
| --- | --- | --- | --- |
| 26.x | 2026-10-28 | 2027-10-20 | 2029-04-30 |
| 24.x "Krypton" | 2025-10-28 | 2026-10-20 | 2028-04-30 |
| 22.x "Jod" | 2024-10-29 | 2025-10-21 | 2027-04-30 |
| 20.x "Iron" | 2023-10-24 | 2024-10-22 | 2026-04-30 (reached) |

Production runs Active or Maintenance LTS lines; the odd lines (21, 23, 25) are end of life. From Node.js 27 every yearly release becomes LTS, and its alpha builds (from October 2026) are not for production. A major bump means reading the semver-major notes: Node.js 26 removed `--experimental-transform-types` and the `_stream_*` modules and runtime-deprecated `module.register()` (use `module.registerHooks()`). `engines.node` only warns on a mismatch unless `engine-strict` is set; Docker tags follow the same rule (`FROM node:24-bookworm-slim`, digest-pinned for reproducible builds, not `node:latest`).

Built-ins that replace common dependencies: global `fetch` (still needs a [deadline](#put-timeouts-on-all-outbound-io)) for `node-fetch` or simple `axios` calls; `crypto.randomUUID()` for `uuid` v4; `structuredClone()` for `lodash.clonedeep` ([semantics](javascript.md#mutation-and-copying)); `util.parseArgs()` for small `yargs`/`minimist` CLIs; `node --env-file=.env` and `process.loadEnvFile()` for `dotenv` (stable in 22.21 and 24.10; variables already in the environment win); `node --watch` for `nodemon`; `node:test` with `node:assert/strict` for small `mocha`/`jest` setups; `fs.glob()` (stable in 22.17 and 24.0), `fs.rm(p, { recursive: true, force: true })`, and `fs.mkdir(p, { recursive: true })` for `glob`, `rimraf`, and `mkdirp`. `node:test`, `node:sqlite`, and `node:sea` exist only under the `node:` prefix.

Type stripping runs `.ts` files without a build step: on by default since 22.18 (without a warning since 22.18 and 24.3) and stable since 24.12. It only erases types: `enum`, namespaces with runtime code, parameter properties, and import aliases fail with `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`, and decorators are a parse error. It reads no `tsconfig.json` (so no `paths`), refuses `.ts` files under `node_modules`, needs `import type` for type-only imports, and checks no types. Compiler flags that catch this: [typescript.md](typescript.md#use-erasablesyntaxonly-when-nodejs-runs-the-ts-files-ts-58).

---

## Event Loop & CPU-Bound Work

A 200 ms synchronous call delays every queued request, health checks included. Async `fs`, crypto, `zlib`, and `dns.lookup()` share the libuv threadpool (4 threads by default; `UV_THREADPOOL_SIZE` must be set before the process starts), so a burst of slow calls delays unrelated ones too. The `nextTick` and promise microtask queues drain completely before the loop moves on, so recursive `nextTick` or awaiting only settled promises starves I/O and timers. The `monitorEventLoopDelay()` histogram (`node:perf_hooks`) records nanoseconds, and a metrics interval should be `.unref()`ed. General patterns: [javascript.md](javascript.md#dont-block-the-event-loop-or-main-thread).

In a handler, `readFileSync`, `gzipSync`, or `scryptSync` blocks every request while it runs: `res.sendFile(absolutePath)` streams (and ignores client aborts), compression belongs in middleware or the proxy, and `promisify(scrypt)` runs on the threadpool.

```javascript
// ✅ One bounded pool per process for CPU-heavy work (not a Worker per request), with a deadline per task
const summaryPool = new Piscina({
  filename: new URL('./summarize.js', import.meta.url).href,
  maxThreads: availableParallelism(), // node:os
  maxQueue: 'auto', // the default queue is unbounded; a full queue rejects new tasks
});
app.get('/reports/:id/summary', async (req, res) => {
  res.json(await summaryPool.run(req.params.id, { signal: AbortSignal.timeout(10_000) }));
});
```

Data sent to a worker is copied unless it is in `transferList`; close the pool on shutdown (`await summaryPool.close()`). Chunked work yields with `await setImmediate()` from `node:timers/promises`.

---

## Modules & Packaging

The nearest `package.json` `"type"` decides how `.js` loads; `.mjs` and `.cjs` always win. ESM has no `require`, `module`, or `__dirname` (use `import.meta.dirname`, stable in 22.16 and 24.0, or `createRequire(import.meta.url)`), does not guess extensions or directory indexes (`ERR_MODULE_NOT_FOUND`), imports JSON only `with { type: 'json' }` (default export only), and `import()` of CommonJS puts `module.exports` on `default`.

CommonJS can `require()` an ES module without a flag since 22.12 (stable in 24.15): it returns the namespace object (the default export is `.default`) and throws `ERR_REQUIRE_ASYNC_MODULE` when the graph uses top-level `await`. `package.json` `"imports"` aliases (`#lib/*`) resolve at runtime; `tsconfig` `paths` do not ([typescript.md](typescript.md#path-aliases-and-module-resolution)).

A package with separate ESM and CommonJS builds can be loaded twice in one app (its code `import`s one copy while a dependency `require`s the other), so singletons, registries, and `instanceof` checks silently diverge. Fixes: one CommonJS implementation behind a thin ESM wrapper, shared state in one CommonJS file, or ESM only plus `require(esm)`.

```javascript
// ✅ index.mjs, the "import" target, re-exports the single CommonJS implementation
import cjs from './index.cjs';
export const { register, getPlugins } = cjs;
```

`"exports"` defines the only loadable entry points (anything else throws `ERR_PACKAGE_PATH_NOT_EXPORTED`), so adding it is a breaking change. Conditions match in object order and TypeScript uses the first one it recognizes:

```jsonc
// ❌ "types" last is never reached; "./*" publishes every internal file
"exports": {
  ".": { "import": "./dist/index.mjs", "require": "./dist/index.cjs", "types": "./dist/index.d.ts" },
  "./*": "./dist/*"
}
// ✅ "types" first, "default" (when present) last, only public entry points
"exports": {
  ".": { "types": "./dist/index.d.ts", "import": "./dist/index.mjs", "require": "./dist/index.cjs" },
  "./package.json": "./package.json"
}
```

Different declarations per format nest the conditions (`"import": { "types": "./dist/index.d.mts", "default": "./dist/index.mjs" }`); `npm pack --dry-run` shows what gets published.

---

## Async Error Handling

Since Node.js 15 the default `--unhandled-rejections=throw` turns an unhandled rejection into an uncaught exception, and the process exits with code 1; that default is right. Installing an `unhandledRejection` listener is what stops the exit, so a log-only listener leaves the process running in an unknown state. An `'error'` event with no listener is thrown as well, and sockets, streams, child processes, pools, and consumers emit it long after setup; a rejection inside an async `'error'` listener is itself unhandled. Promise rules: [javascript.md](javascript.md#no-floating-promises); principles: [Error Handling Principles](cross-cutting/error-handling-principles.md).

```javascript
// ❌ If notifyWarehouse() rejects, the process exits, and the log-only listener hides worse
notifyWarehouse(order); // inside an async route handler: nobody awaits or catches it
process.on('unhandledRejection', (reason) => logger.error({ reason }, 'unhandled rejection'));

// ✅ Await the work or enqueue it; listen for 'error' on long-lived emitters; once() rejects on 'error'
await jobs.enqueue('notify-warehouse', { orderId: order.id });
pool.on('error', (err) => logger.error({ err }, 'idle database client failed')); // the pool drops the client
const [code] = await once(spawn('convert', [input, output], { stdio: 'ignore' }), 'close'); // ENOENT rejects
if (code !== 0) throw new Error(`convert exited with code ${code}`);
await once(redis, 'ready', { signal: AbortSignal.timeout(5_000) }); // rejects on 'error' or timeout

// ❌ Module-level request state is overwritten by concurrent requests
let currentUser;

// ✅ One AsyncLocalStorage store per request (node:async_hooks)
export const requestContext = new AsyncLocalStorage();
app.use((req, res, next) => {
  requestContext.run({ requestId: randomUUID(), userId: req.user?.id }, next); // run(), not enterWith()
});
```

Child-process output that nobody reads fills the pipe and blocks the child, so read `stdout`/`stderr` or set `stdio`. Hand-written promise wrappers drop the error path (`(err, data) => resolve(JSON.parse(data))` throws inside the callback) and `promisify(obj.method)` loses `this`: use `node:fs/promises`, `node:timers/promises`, `node:stream/promises`, or `promisify(obj.method.bind(obj))`.

### Put timeouts on all outbound I/O

The built-in `fetch` (undici) waits up to 300 s for response headers and has no overall deadline; `http.request` only emits `'timeout'` and never aborts by itself; `pg` has no connection or statement timeout unless configured. Signal patterns: [javascript.md](javascript.md#timeouts-with-abortsignal).

```javascript
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

// ✅ Database clients too: waiting for a connection, and per statement
const pool = new Pool({ connectionString: config.DATABASE_URL, connectionTimeoutMillis: 2_000, statement_timeout: 5_000 });
```

---

## Streams & Backpressure

`.pipe()` does not forward errors: a failed stage leaves the others open. `pipeline()` (`node:stream/promises`) destroys every stage on error, returns one promise, pauses the source while the destination is full, and accepts web streams such as `fetch` bodies. `write()` returns `false` once the buffer passes `highWaterMark` (64 KiB for byte streams since Node.js 22). Buffering multiplies memory by concurrency: 50 parallel 20 MB downloads need 1 GB of heap. Principles: [Async & Concurrency Patterns](cross-cutting/async-concurrency-patterns.md).

```javascript
// ❌ Unforwarded errors leak file descriptors; ignored write() results buffer the whole export
createReadStream(src).pipe(createGzip()).pipe(createWriteStream(dest));
for await (const row of orders.cursor()) res.write(toCsvLine(row));

// ✅ pipeline() for chains and generators; a client disconnect is normal, not a server error
app.get('/orders.csv', async (req, res) => {
  try {
    await pipeline(orders.cursor(), async function* (rows) {
      for await (const row of rows) yield toCsvLine(row);
    }, res);
  } catch (err) {
    if (err.code !== 'ERR_STREAM_PREMATURE_CLOSE') throw err; // otherwise the client went away
  }
});

// ✅ By hand: wait for 'drain' whenever write() returns false
for await (const row of orders.cursor()) {
  if (!out.write(toCsvLine(row))) await once(out, 'drain');
}
out.end();
await finished(out);
```

Downloads go to disk with `pipeline(response.body, createWriteStream(path))` after an `ok` check, not through `arrayBuffer()`; `res.sendFile()` streams and supports `Range`; large JSON is better as JSON Lines or a streaming parser; uploads: [body limits](#limit-request-bodies-and-uploads).

---

## Process Lifecycle & Graceful Shutdown

Without a `SIGTERM` listener Node.js exits at once and drops in-flight work; with one, it no longer exits on that signal by itself. On Kubernetes, endpoint removal and `SIGTERM` happen concurrently, so keep serving for a few seconds (or use a `preStop` sleep) before closing the listener. NestJS: [nestjs.md](nestjs.md#lifecycle--runtime).

```javascript
// ❌ In-flight requests fail, transactions are cut, messages are redelivered
process.on('SIGTERM', () => process.exit(0));

// ✅ Fail readiness, keep serving briefly, stop accepting, drain, close resources, exit before the deadline
import { setTimeout as delay } from 'node:timers/promises';

let shuttingDown = false; // /readyz answers 503 once this is true

async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  logger.info({ signal }, 'shutdown started');
  const deadline = setTimeout(() => {
    server.closeAllConnections(); // deadline reached: cut what is left
    process.exit(1);
  }, 25_000); // below the orchestrator's grace period
  deadline.unref();
  let sweep;
  try {
    await delay(READINESS_DRAIN_MS); // load balancers stop routing here first
    // close() drops idle keep-alive sockets once; this catches the ones that go idle later
    sweep = setInterval(() => server.closeIdleConnections(), 1_000);
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

After an uncaught exception the process state is undefined: the default (print the stack, exit 1) is right, and a custom handler only logs synchronously (`fs.writeSync(process.stderr.fd, …)`; rejections arrive with origin `'unhandledRejection'`) and exits, leaving restarts to the supervisor. `process.exit()` ends the process even with stdout writes pending (pipes are asynchronous on POSIX), truncating output: libraries throw, and CLI entry points set `process.exitCode`.

Node.js was not designed to run as PID 1: there it does not respond to `SIGINT`-style signals or reap orphaned children, and `npm start` adds npm, which swallows signals. Node.js sizes the default heap from the memory it can see, cgroup limits included; an explicit `--max-old-space-size` above the container limit lets the kernel OOM-kill the process instead (`--max-old-space-size-percentage` is also accepted).

```dockerfile
# ❌ npm swallows SIGTERM; the heap limit is above the 2 GiB container limit
ENV NODE_OPTIONS="--max-old-space-size=4096"
CMD ["npm", "start"]
# ✅ node directly under an init that forwards signals and reaps children (or docker run --init), heap below the limit
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "--max-old-space-size=1536", "dist/server.js"]
```

A liveness probe that queries the database restarts every replica during a database outage, so liveness answers from the process alone, while readiness returns 503 during startup, shutdown, and required-dependency outages (with the check bounded by pool timeouts); neither needs auth or returns internals such as `process.env`.

---

## Configuration & Secrets

`process.env` values are strings or `undefined`: `'false'` is truthy and `'8080'` is not a number. Local development loads files without a dependency (`node --env-file=.env` or `--env-file-if-exists`).

A `config.js` that parses `process.env` once with a schema (for example zod: `z.coerce.number().int()` for ports, `z.enum(['true', 'false']).transform((v) => v === 'true')` for flags, never `Boolean('false')`), throws at startup with the failing key names only (values may be secrets), and exports a frozen object is the pattern to expect.

Secrets leak through source control, log lines, error responses, and image layers far more often than through exploits: redact in the logger (`pino({ redact: ['req.headers.authorization', 'req.headers.cookie', '*.password', '*.token'] })`), never log whole headers or send `err.stack` to clients, keep `.env`, `.npmrc`, and `.git` out of images with `.dockerignore`, and pass build-time secrets as BuildKit secret mounts (`RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci`), because `ARG` and `ENV` values stay in the image history.

---

## HTTP Servers & Express

### Async errors in Express 4 vs 5

Express 5 (npm `latest` since March 2025) passes a rejected promise from a handler or middleware to `next(err)`. Express 4 ignores it: the request hangs, and under the default `--unhandled-rejections=throw` the process crashes, so any client that can trigger the error can take the service down. Express 4 has been in maintenance (security and high-priority fixes only) since 2025-04-01, with end of life targeted for no sooner than 2026-10-01; check the Express support page before relying on 4.x fixes. In both majors, errors thrown inside callbacks are not caught: call `next(err)`.

On Express 4, one wrapper forwards rejections: `const asyncHandler = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)`, used as `app.get('/users/:id', asyncHandler(async (req, res) => …))`.

| Express 4 | Express 5 |
| --- | --- |
| `app.get('/*', ...)` | Wildcards must be named: `'/*splat'` (`'/{*splat}'` also matches `/`) |
| `'/:file.:ext?'`, `'/:id(\\d+)'` | Optional parts use braces (`'/:file{.:ext}'`); regex characters in string paths are gone: use a `RegExp` object, an array of paths, or validation in the handler |
| `req.query` writable, "extended" parser | Read-only getter that re-parses on every access, "simple" parser by default |
| `req.body` is `{}` without a parser | `undefined` unless a body parser ran |

Removed APIs (`app.del()`, `req.param()`, `res.sendfile()`, `res.redirect('back')`, and others) fail at runtime; the official codemod handles most of them (`npx codemod@latest @expressjs/v5-migration-recipe`, run by the author).

### Middleware order and the error handler

Express recognizes error middleware by its four parameters, so deleting an "unused" `next` turns it into ordinary middleware that never sees errors. Code that keeps running after `res.json()` throws `ERR_HTTP_HEADERS_SENT` or does work whose result is thrown away: return after every early response.

```javascript
// ✅ Headers → body limits → auth → routes → 404 → error handler with four parameters
app.use(helmet()); // security headers; also removes X-Powered-By
app.use(express.json({ limit: '100kb' }));
app.use('/api', authenticate, apiRouter);
app.use((req, res) => res.status(404).json({ error: 'Not found' }));
app.use((err, req, res, next) => {
  if (res.headersSent) return next(err); // let Express close the connection
  const status = err.expose ? err.status : 500; // http-errors (used by body-parser) sets expose on 4xx
  if (status >= 500) logger.error({ err, method: req.method, path: req.path }, 'request failed');
  res.status(status).json({ error: status >= 500 ? 'Internal Server Error' : err.message });
});
```

### Validate request input at the boundary

`req.body`, `req.query`, and `req.params` are untyped client input: a field expected to be a string can arrive as an array or object, and extra fields get mass-assigned. In Express 5, `req.query` re-parses on every access, so assigning to it throws in strict-mode code and in-place coercion is lost: keep validated values in a local variable or `res.locals`. Deep merges of request JSON: [prototype pollution](javascript.md#objects-as-dictionaries-and-prototype-pollution).

```javascript
// ❌ { "email": { "$gt": "" } } matches any user; the client can send { "ownerId": "someone-else" }
const user = await usersCollection.findOne({ email: req.body.email });
const project = await Project.create(req.body);

// ✅ Schema-validate, then build the record from known fields (z.object strips unknown keys)
const CreateProject = z.object({ name: z.string().trim().min(1).max(100), visibility: z.enum(['private', 'team']) });
app.post('/projects', async (req, res) => {
  const parsed = CreateProject.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: 'Invalid request', issues: parsed.error.issues });
  res.status(201).json(await Project.create({ ...parsed.data, ownerId: req.user.id }));
});
```

### Configure server timeouts and keep-alive

Defaults: `headersTimeout` 60 s, `requestTimeout` 300 s, `keepAliveTimeout` 5 s (Node.js main raises it to 65 s for the next major; setting it explicitly stays correct), and no socket inactivity timeout. Behind a load balancer the keep-alive timeout must exceed the balancer's idle timeout (60 s by default on an AWS ALB), or clients see sporadic 502s; without a proxy, `headersTimeout` and `requestTimeout` must stay non-zero to limit slow clients. Example: `createServer({ keepAliveTimeout: 65_000, headersTimeout: 60_000, requestTimeout: 120_000 }, app)` from `node:http`.

With the default `trust proxy` (`false`) every request seems to come from the proxy, so per-IP rate limits throttle all clients together and express-session refuses `secure` cookies; with `true`, `req.ip` is the left-most `X-Forwarded-For` entry, which any client can forge. Trust exactly the proxies you run: a hop count (`app.set('trust proxy', 1)`) or their addresses (`['loopback', '10.0.0.0/8']`).

---

## Node.js Security

Owned elsewhere: [SQL Injection Prevention](cross-cutting/sql-injection-prevention.md) (`pg`, Prisma), [XSS Prevention](cross-cutting/xss-prevention.md) (server-rendered HTML, JSON in `<script>`, CSP), the [Security Review Guide](security-review-guide.md) (JWT, CSRF, SSRF, IDOR, `exec` vs `execFile`, CORS, headers, rate limits, logging), [N+1 Queries](cross-cutting/n-plus-one-queries.md) (Prisma, DataLoader), and [Universal Quality](code-quality-universal.md) (TOCTOU with `fs`).

### Prevent path traversal

`path.join()` and `path.normalize()` do not stop `../`, `path.resolve()` drops the base when the input is absolute, and Express decodes `req.params` (`..%2F..%2Fetc%2Fpasswd` arrives as `../../etc/passwd`). If the directory can contain symlinks, compare `fs.realpath()` results.

```javascript
// ❌ "../../etc/passwd" escapes the upload directory
res.sendFile(path.join(UPLOAD_DIR, req.params.name));

// ✅ Express: pass a root, and sendFile keeps the resolved path inside it
res.sendFile(req.params.name, { root: UPLOAD_DIR, dotfiles: 'deny' });

// ✅ Plain fs: resolve, then require the result to stay under the (absolute, resolved) base
function resolveInside(base, userPath) {
  const target = path.resolve(base, userPath);
  if (target !== base && !target.startsWith(base + path.sep)) throw new Error('Path escapes the base directory');
  return target;
}
```

### Compare secrets in constant time

`===` stops at the first differing character, so response timing leaks how much of a token or signature matched; `crypto.timingSafeEqual()` throws when lengths differ, so compare fixed-length digests.

```javascript
// ✅ HMAC the raw body and compare equal-length digests (node:crypto). Register the route before any
//    global express.json(), or the body is already parsed and express.raw() skips it
app.post('/webhooks/payments', express.raw({ type: 'application/json', limit: '1mb' }), async (req, res) => {
  const expected = createHmac('sha256', config.WEBHOOK_SECRET).update(req.body).digest();
  const received = Buffer.from(req.get('x-signature') ?? '', 'hex');
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) return res.status(401).end();
  await payments.handleEvent(JSON.parse(req.body.toString('utf8')));
  res.status(204).end();
});
```

### vm is not a sandbox

The Node.js docs say `node:vm` is not a security mechanism: context code reaches the host through the objects it is given (`this.constructor.constructor('return process')()`), and `vm`-based sandboxes have a long record of escapes. The permission model (`--permission`, stable since 22.13) is a "seat belt" with no guarantees against malicious code. Run arbitrary code in a separate locked-down process or container per tenant; parse user formulas with an allowlisted expression language.

### Limit request bodies and uploads

`express.json()` and `express.urlencoded()` default to a 100 kB limit, and urlencoded also caps `parameterLimit` at 1000 and nesting `depth` at 32. Multer has no file size or count limit by default, and `memoryStorage()` keeps every file in RAM; `requestTimeout` bounds slow uploads.

```javascript
// ✅ A larger limit only on the route that needs it, registered before the small global one
app.post('/imports', authenticate, express.json({ limit: '5mb' }), importOrders);
app.use(express.json({ limit: '100kb' }));
const upload = multer({ dest: UPLOAD_TMP_DIR, limits: { fileSize: 10 * 1024 * 1024, files: 1, fields: 20 } });
```

### Avoid open redirects

`res.redirect()` puts whatever it gets into the `Location` header, so a `?next=` parameter turns a trusted login page into a phishing redirector.

```javascript
// ❌ Redirects anywhere: ?next=https://evil.example or ?next=//evil.example
res.redirect(req.query.next);

// ✅ Resolve against your own origin (config.APP_ORIGIN such as 'https://app.example.com') and return the
//    absolute URL: a bare pathname would turn "/.//evil.example" into "//evil.example", which leaves the site
function safeRedirectTarget(value) {
  if (typeof value !== 'string') return '/';
  try {
    const url = new URL(value, config.APP_ORIGIN); // also parses "//host", "/\host", and "javascript:"
    return url.origin === config.APP_ORIGIN ? url.href : '/';
  } catch {
    return '/';
  }
}
res.redirect(safeRedirectTarget(req.query.next));
```

---

## Dependencies & Supply Chain

`npm ci` installs exactly what the lockfile says, fails when it disagrees with `package.json`, and writes neither file (pass it the tree-shaping flags that built the lock, such as `--legacy-peer-deps`); `npm install` may rewrite the lockfile. In Dockerfiles, copy `package.json` and the lockfile first, run `npm ci --omit=dev`, then copy the source. In lockfile diffs, a `resolved` URL outside the registry, a git or tarball source, or an `integrity` change without a version change needs an explanation.

For a new package, check for a [built-in](#runtime-versions--built-ins), then release history and maintainers (ownership transfers), install scripts, license, tree size, and typosquatted names; the author can show them with `npm view <package> time maintainers scripts license` and `npm ls <package> --all`.

npm 12 runs dependency lifecycle scripts (`preinstall`, `install`, `postinstall`, and implicit `node-gyp` builds) only when the root `package.json` `allowScripts` policy allows them, and resolves git and remote-URL dependencies only with `--allow-git` and `--allow-remote`; `npm approve-scripts --allow-scripts-pending` lists what is blocked. An allowlist entry grants code execution at install time, so review it like a new dependency. Node.js 24 and 26 bundle npm 11, which has neither default; there, `ignore-scripts=true` in `.npmrc` is the blunt alternative.

`npm audit --audit-level=high` fails CI on known advisories; `npm audit fix --force` can install semver-major upgrades, so review its diff like any upgrade. When only a transitive dependency has a fix, root `overrides` pin it until the parent ships one (`"overrides": { "legacy-client": { "vulnerable-dep": "1.4.2" } }` scopes the pin; a top-level entry applies everywhere); link the advisory and remove the override later. Registry worms such as Shai-Hulud (September 2025) republished trojanized versions of trusted packages with stolen tokens, so a fresh patch release is not automatically safe; `min-release-age=<days>` in `.npmrc` (npm 11.10+) installs only older versions.

---

## Performance & Resource Management

A pool or client created per request pays TCP, TLS, and authentication every time, exhausts server connection slots, and leaks sockets. Create one per process, bound it, release checked-out clients in `finally` (`ROLLBACK` in `catch` for transactions), close it on shutdown, and keep `max` times the replica count below the database's connection limit. The global HTTP agent has used keep-alive since Node.js 19 and `fetch` pools connections per origin; an `http.Agent` per request defeats both.

A module-level `Map` used as a cache grows until the process runs out of memory ([Performance Review Guide](performance-review-guide.md)); cap entries and add a TTL (`new LRUCache({ max: 10_000, ttl: 5 * 60_000 })` from lru-cache). `MaxListenersExceededWarning` (more than 10 listeners for one event) usually means a listener added per request: fix the leak rather than raising the limit. Since Node.js 16 the request's `'close'` fires when the request is done, not when the socket closes, so detect disconnects with `res.on('close')`.

```javascript
// ✅ Server-sent events: remove the listener when the response closes, and skip ticks while the client is slow
app.get('/prices/stream', (req, res) => {
  res.set({ 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' }).flushHeaders();
  let behind = false;
  const onTick = (tick) => {
    if (!behind) behind = !res.write(`data: ${JSON.stringify(tick)}\n\n`);
  };
  res.on('drain', () => { behind = false; });
  priceFeed.on('tick', onTick);
  res.on('close', () => priceFeed.off('tick', onTick));
});
```

`console.log` writes synchronously to files and terminals on POSIX and asynchronously, buffering in memory, to pipes; either way, formatting large objects on hot paths costs CPU. Log objects rather than prebuilt strings with a leveled logger, and guard expensive details with `logger.isLevelEnabled('debug')`.

---

## Testing Node.js Services

Export the app from a factory that does not call `listen()`, inject its dependencies, and drive it over HTTP in the test process on port 0 so parallel files never collide (supertest: `await request(createApp(deps)).get('/users/unknown').expect(404)`).

With `node:test`, start `createApp(fakes).listen(0, '127.0.0.1')` in `before`, await `once(server, 'listening')`, read `server.address().port`, and in `after` call `server.close()` and await `once(server, 'close')`.

```javascript
// ✅ MSW (setup in javascript.md#testing): fail on unmocked hosts, but let loopback reach the app under test
before(() => api.listen({
  onUnhandledRequest(request, print) {
    if (new URL(request.url).hostname !== '127.0.0.1') print.error();
  },
}));
```

MSW's `setupServer` (`msw/node`) intercepts `http`/`https` and the global `fetch`; nock intercepts `fetch` only from v14 (`nock.disableNetConnect()` plus `nock.enableNetConnect('127.0.0.1')`). `--test-force-exit` (node:test) and `--forceExit` (Jest) hide open handles; find them with `--detectOpenHandles` (Jest) or `--reporter=hanging-process` (Vitest). In application code, give background intervals a stop function, and `.unref()` timers that must not keep a CLI alive.

---

## References

- [Node.js API documentation](https://nodejs.org/api/)
- [Node.js releases](https://nodejs.org/en/about/previous-releases)
- [Don't Block the Event Loop (Node.js)](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop)
- [Migrating to Express 5](https://expressjs.com/en/guide/migrating-5.html)
- [OWASP Node.js Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Nodejs_Security_Cheat_Sheet.html)
