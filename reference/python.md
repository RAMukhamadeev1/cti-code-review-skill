# Python Code Review Guide

Python-specific rules for 3.11–3.14: version gates, asyncio, exceptions, pitfalls, tests, and performance. Cross-language principles live in the related guides.

Related: [Error Handling](cross-cutting/error-handling-principles.md) · [Async & Concurrency](cross-cutting/async-concurrency-patterns.md) · [Security](security-review-guide.md) · [SQL Injection](cross-cutting/sql-injection-prevention.md)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Severity: 🔴 blocking · 🟡 important · 🟢 nit · 💡 suggestion. Codes are Ruff rules. What the project's linter or formatter enforces (PEP 8, imports, docstrings, annotation style) is not a finding.

### Versions → [Version-Specific Rules](#version-specific-rules)

- [ ] 🔴 New syntax and APIs exist in the lowest supported Python (`requires-python`, classifiers, CI matrix; ask the author when none is declared)
- [ ] 🟡 Version-dependent behavior is right on every supported version (tarfile filter, multiprocessing start method, annotations)

### Async → [Asynchronous Programming](#asynchronous-programming)

- [ ] 🔴 No blocking calls in `async def`: `time.sleep`, `requests`, sync DB drivers, heavy CPU (ASYNC210, ASYNC251; use `asyncio.to_thread`)
- [ ] 🔴 Cancellation is never swallowed: `except CancelledError`, `except BaseException`, and bare `except:` end in `raise`; cleanup goes in `finally`
- [ ] 🟡 `TaskGroup` failures are caught with `except*`
- [ ] 🟡 `gather()` without `return_exceptions=True` only where siblings may keep running after a failure; otherwise `TaskGroup`
- [ ] 🔴 Concurrent tasks don't share one `AsyncSession` or DB connection
- [ ] 🟡 `create_task()` results are kept or owned by a `TaskGroup` (RUF006)

### Exceptions → [Exception Handling](#exception-handling)

- [ ] 🔴 No `return`, `break`, or `continue` in `finally` (B012)
- [ ] 🟡 `except Exception` only at boundaries (request handler, worker loop, CLI main) that log the traceback and fail closed; elsewhere specific types (BLE001)
- [ ] 🟡 `except …: pass` is removed, or narrowed and commented (`contextlib.suppress(FileNotFoundError)`) (S110, SIM105)
- [ ] 🟡 Custom exceptions keep every constructor argument in `args`, so they pickle across processes
- [ ] 🟢 `raise New(...) from e` inside `except` (B904)

### Pitfalls → [Common Pitfalls](#common-pitfalls)

- [ ] 🔴 No `pickle`/`yaml.load`/`eval` on untrusted data, `shell=True` with input, or SQL built from strings (S301, S506, S307, S602, S608)
- [ ] 🔴 User-supplied paths stay inside their base directory
- [ ] 🟡 Outbound `requests` calls set `timeout=` (S113) and keep `verify` on (S501)
- [ ] 🟡 None of the other patterns in the table

### Tests → [Testing](#testing)

- [ ] 🟡 `patch()` targets where the name is looked up; mocks are autospecced; async code has async tests
- [ ] 🟡 Coverage and flakiness claims come from CI (ask the author)

### Performance → [Performance](#performance)

- [ ] 🟡 No `@lru_cache`/`@cache` on methods (B019); shared caches key on every input that changes the result (user, tenant, locale)
- [ ] 🟢 Performance advice fits the workload (see the section before flagging `+=` strings, list lookups, or lists vs generators)

## Version-Specific Rules

| Version | Change | Review rule |
| --- | --- | --- |
| 3.11 | `TaskGroup`, `ExceptionGroup`, `except*` | `except` and `except*` can't share a `try`; `return`/`break`/`continue` are SyntaxErrors inside `except*` |
| 3.11 | `asyncio.timeout()` | Raises `TimeoutError` when the block exits, so `try` wraps the `async with`; `asyncio.TimeoutError` is an alias (🟢) |
| 3.11 | `add_note()`, `Self`, `LiteralString`, `NotRequired`, `datetime.UTC` | 💡 `add_note()` instead of re-wrapping only for context; `LiteralString` for APIs that take SQL or shell text |
| 3.12 | PEP 695: `def first[T](...)`, `class Box[T]:`, `type X = ...` | SyntaxError on ≤3.11; `TypeVar` style stays fine |
| 3.12 | `datetime.utcnow()` deprecated | 🟡 Naive result; use `datetime.now(UTC)` (DTZ003) |
| 3.13 | TypeVar defaults, `TypeIs`, `ReadOnly`, `Queue.shutdown()` | 💡 `Queue.shutdown()` stops consumers without sentinels |
| 3.13–3.14 | Free-threaded build (experimental in 3.13, supported but optional in 3.14) | Shared mutable state needs a lock on every build (the GIL never made `x += 1` atomic); threads can run CPU work in parallel there |
| 3.14 | Deferred annotations (PEP 649/749) | Don't flag unquoted forward references; runtime readers use `annotationlib.get_annotations()` |
| 3.14 | `except A, B:` without parentheses (PEP 758) | Valid on 3.14 only; parentheses are still required with `as` |
| 3.14 | `return`/`break`/`continue` leaving `finally` warns (PEP 765) | 🔴 The in-flight exception is discarded |
| 3.14 | t-strings (PEP 750) build a `Template`, not a `str` | Safe only with Template-aware APIs (psycopg ≥3.3 `execute(t"...")`); `f"` there is injection; str-only APIs raise `TypeError` |
| 3.14 | `multiprocessing` defaults to `forkserver` on Linux (macOS and Windows already use `spawn`) | 🟡 Code relying on fork-inherited globals or unpicklable callables breaks |
| 3.14 | `tarfile` extraction defaults to the `data` filter | 🔴 Without `filter="data"`, `extractall()` allows path traversal on ≤3.13 (S202) |
| 3.14 | `InterpreterPoolExecutor` | 💡 Option for CPU-bound work besides processes |

## Asynchronous Programming

Cross-language patterns: [Async & Concurrency](cross-cutting/async-concurrency-patterns.md). Python specifics:

- `gather()` propagates the first error but leaves the other awaitables running (asyncio docs); `TaskGroup` cancels them. After `gather()` raises, a shared `ClientSession` may close under siblings that are still running.
- SQLAlchemy says concurrent tasks "should use a separate AsyncSession per individual task"; an asyncpg connection runs one query at a time. Suggest concurrency only when each task gets its own.
- A `while True: await ...` loop is cancellable at every `await` and needs no `except CancelledError`. Suppressing a cancellation on purpose also needs `Task.uncancel()`.

```python
# ❌ Never matches: TaskGroup raises ExceptionGroup, even for one failure
try:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch(i)) for i in ids]
except GatewayError:
    ...

# ✅ except* matches inside the group
try:
    async with asyncio.TaskGroup() as tg:  # the first failure cancels the siblings
        tasks = [tg.create_task(fetch(i)) for i in ids]
except* GatewayError as group:
    log_failures(group.exceptions)
    results = []
else:
    results = [t.result() for t in tasks]
```

```python
# ❌ Swallowed cancellation: an enclosing asyncio.timeout() never fires
async def worker(queue):
    try:
        while True:
            await handle(await queue.get())
    except asyncio.CancelledError:
        pass

# ✅ Cleanup in finally; the cancellation propagates
async def worker(queue):
    try:
        while True:
            await handle(await queue.get())
    finally:
        await release_resources()
```

## Exception Handling

Principles (log once, fail closed, keep the cause, catch broadly only at boundaries): [Error Handling Principles](cross-cutting/error-handling-principles.md#core-principles). Python specifics:

- EAFP (`try: d[k]` / `except KeyError:`) is idiomatic, and `try` costs nothing when nothing is raised (3.11+).
- Bare `except:` and `except BaseException:` also catch `KeyboardInterrupt`, `SystemExit`, and `CancelledError` (E722).
- Without `from e`, `raise X` inside `except` still keeps the original as `__context__`, so B904 is a nit; `from None` hides it on purpose.
- `logger.exception("…")` keeps the traceback that `logger.error(f"…{e}")` drops (TRY400, G004); `e.add_note(...)` adds context and keeps the type.
- An `__init__` that passes other arguments to `super().__init__()` than it takes fails to unpickle, which breaks errors from `ProcessPoolExecutor`, `multiprocessing`, and Celery: [picklable pattern](cross-cutting/error-handling-principles.md#example-hierarchy-python).

## Common Pitfalls

| Pattern | Why, and when it is not a finding | Rule |
| --- | --- | --- |
| `def f(items=[])` | Shared by every call; 🟢 if never mutated | B006 |
| `def f(now=datetime.now())` | Evaluated once; framework markers such as FastAPI `Depends()` are fine | B008 |
| Mutable class attribute mutated through `self` | Shared by all instances; Django `Meta` and admin options, DRF `permission_classes`, `__slots__`, pydantic fields, and unmutated `ClassVar` constants are fine | RUF012 |
| `lambda: i` created in a loop | Every closure sees the last value; fine if called in the same iteration | B023 |
| `x is 1000`, `x is "a"` | Literal identity is an implementation detail; `is` is for `None`, sentinels, enum members | F632 |
| `.get(k) or default` | Replaces valid falsy values (`0`, `""`); use `if (v := d.get(k)) is None:` | — |
| `if x is True` | PEP 8 calls it worse than `if x:`; fine for tri-state checks | — |
| Naive `datetime.now()` | Comparing naive and aware datetimes raises `TypeError` | DTZ005 |
| `os.path.join(base, user)`, `Path(base) / user` | An absolute `user` replaces `base`; check `resolved.is_relative_to(base.resolve())` | — |
| `random` for tokens | Predictable; use `secrets` | S311 |
| `hashlib.md5`/`sha1` for security | Fine for checksums with `usedforsecurity=False` | S324 |
| `assert` for validation or authorization | Stripped by `python -O`; fine in tests | S101 |
| `hash(s)` stored or shared across processes | `str` hashes are randomized per process | — |
| Mutating a list or dict while iterating it | Skips items; dicts raise `RuntimeError` | — |
| `def f(x: int = None)` | The annotation lies | RUF013 |
| `typing.List`, `Optional`, `Union` | Style only: 🟢 at most, and only if the linter doesn't enforce it | UP006, UP007, UP035 |

## Testing

- `patch("app.orders.send_email")` names the module that looks the name up, not where it is defined; `autospec=True` makes signature drift fail the test.
- Coroutines need `AsyncMock` and an async runner (pytest-asyncio, anyio); in pytest-asyncio strict mode, async fixtures use `@pytest_asyncio.fixture`.
- `pytest.raises(SpecificError, match="…")`, not `pytest.raises(Exception)`.

## Performance

- `x in some_list` in a loop is O(n) per check; a `set` pays off for repeated lookups, not a single one.
- CPython usually optimizes `s += piece`; flag it only in hot loops, where `"".join()` is linear on every runtime (PEP 8).
- A generator saves memory only when the source streams (`fetchall()` already loaded the rows), and it runs after the caller's `with` has closed the session.
- Module-level caches are shared by every request and tenant; a TTL cache needs `time.monotonic()` and a size bound.
- CPU-bound work: processes, `InterpreterPoolExecutor`, or threads on a free-threaded build; `ProcessPoolExecutor` needs picklable functions and arguments. Queries in loops: [N+1 Queries](cross-cutting/n-plus-one-queries.md).

## References

- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [asyncio: Coroutines and Tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Ruff rules](https://docs.astral.sh/ruff/rules/)
