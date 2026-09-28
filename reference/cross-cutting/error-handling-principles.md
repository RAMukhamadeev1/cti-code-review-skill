# Error Handling Principles

Cross-language rules for handling, wrapping, and logging errors in Python, TypeScript, and Apex. Language specifics: [Python](../python.md#exception-handling), [JavaScript](../javascript.md), [Apex](../salesforce/apex.md#transactions--error-handling).

Related: [Security: Error Messages](../security-review-guide.md#error-messages) · [Async & Concurrency](async-concurrency-patterns.md)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Severity: 🔴 blocking · 🟡 important · 🟢 nit · 💡 suggestion.

### Handling → [Core Principles](#core-principles)

- [ ] 🔴 No error is silently dropped (empty `catch`, `except: pass`, `.catch(() => {})`); narrow, commented ignores such as `contextlib.suppress(FileNotFoundError)` are fine
- [ ] 🔴 Security checks fail closed: an error in an authorization, signature, or payment check denies
- [ ] 🟡 Each error is logged once, where it is handled; lower layers re-raise or wrap with context without logging
- [ ] 🟡 Broad catches (`except Exception`, untyped `catch`) only at boundaries (request handler, job runner, CLI main) that log the stack
- [ ] 🟡 Wrapped errors keep the cause (`{ cause }`, `raise … from e`); a missing Python `from e` is 🟢 (`__context__` keeps it)
- [ ] 🟡 Messages name the operation and key IDs, never secrets or PII

### Anti-patterns → [Anti-Patterns](#anti-patterns)

- [ ] 🔴 No `return`, `break`, or `continue` in `finally`
- [ ] 🟡 Return values that signal failure are checked (`response.ok`, `re.match()` → `None`, partial-success `SaveResult`s)
- [ ] 🟡 Expected outcomes (not found, invalid input) are return values or typed errors; Python EAFP lookups are fine

### Hierarchy → [Error Hierarchy Design](#error-hierarchy-design)

- [ ] 🟡 Errors that callers handle differently get distinct types under one base class; infrastructure errors are converted at the module boundary
- [ ] 🟡 Python exceptions keep constructor arguments in `args`; TypeScript errors pass `{ cause }` and set `name`
- [ ] 💡 Small scripts and libraries don't need a three-tier hierarchy

### Logging → [Logging Best Practices](#logging-best-practices)

- [ ] 🟡 Error logs keep the stack (`logger.exception`, `{ err }`), use structured fields, and follow [Secure Logging](../security-review-guide.md#secure-logging)

### Language specifics → [Code Examples by Language](#code-examples-by-language)

- [ ] 🟡 Outbound HTTP failures, timeouts included, become module errors at the boundary
- [ ] 🟡 Apex inspects `SaveResult`s after partial-success DML and sends `AuraHandledException` with a safe message

## Core Principles

1. **Don't swallow errors.** Propagate, fall back with a log entry, or crash when the state is unrecoverable; intentional ignores are narrow and commented.
2. **Add context**: the operation and key parameters ("failed to charge order 12345: gateway timeout after 30 s") via `add_note()`, `raise … from e`, or `{ cause }`.
3. **Use specific types** so callers can branch (`OrderNotFoundError`, `PaymentTimeoutError`).
4. **Fail fast**: validate preconditions before side effects or expensive work.
5. **Handle each error once**: log where it is handled; lower layers add context and re-raise.
6. **Fail closed** (OWASP A10:2025): when a security decision or a transaction errors, deny and roll back.

```python
# ❌ Fails open: an outage in the permission service grants access
def can_edit(user, doc) -> bool:
    try:
        return permissions.check(user, doc, "edit")
    except Exception:
        return True

# ✅ Fails closed; this function handles the error, so it logs it
def can_edit(user, doc) -> bool:
    try:
        return permissions.check(user, doc, "edit")
    except PermissionServiceError:
        logger.exception("permission check failed for doc %s", doc.id)
        return False
```

## Anti-Patterns

- **Empty catch blocks**: Python `except: pass`, TypeScript `catch {}` and `promise.catch(() => {})`, Apex `catch (DmlException e) {}`, where the rest of the transaction commits and the failed records are lost.
- **Overly broad catch**: `except Exception` in the middle of a module hides which failure happened; at a boundary that logs the traceback and fails closed it is correct.
- **Losing the cause**: in TypeScript, `throw new ServiceError('IO failed')` inside `catch (err)` drops `err` unless `{ cause: err }` is passed. In Python the original stays in `__context__`; `from e` only marks it as the direct cause (B904, 🟢).
- **Exceptions for expected outcomes**: a lookup that throws on "not found" forces callers into try/catch as if/else and makes them swallow real failures too; put the miss in the return type (`User | undefined`). Python EAFP (`try: d[k]` / `except KeyError:`) is idiomatic and not this anti-pattern.
- **Jumps out of `finally`**: `return`, `break`, or `continue` in `finally` discards the in-flight exception (Python B012, a SyntaxWarning from 3.14; ESLint `no-unsafe-finally`).
- **Ignored return values**: `fetch` resolves on HTTP 4xx and 5xx ([check `response.ok`](#typescript)), `re.match()` returns `None`, partial-success DML reports failures in `SaveResult`s ([Apex](#salesforce-apex)).

```python
# ❌ re.match returns None when nothing matches
user_id = re.match(r"user-(\d+)", key).group(1)

# ✅ Check the result
match = re.match(r"user-(\d+)", key)
if match is None:
    raise ValueError(f"unexpected key format: {key!r}")
user_id = match.group(1)
```

## Error Hierarchy Design

1. Module errors inherit from one application base class, so the boundary handler catches them in one place.
2. Infrastructure errors (I/O, network, database) are converted into module errors at the module boundary, with the cause attached.
3. Each type carries the context needed to debug it (IDs, operation), not a copy of the log line.

### Example hierarchy (Python)

```python
class AppError(Exception):
    """Base class: the boundary handler catches AppError."""


class PaymentError(AppError):
    def __init__(self, order_id: str, reason: str):
        super().__init__(order_id, reason)  # args keep every constructor argument, so it pickles
        self.order_id = order_id
        self.reason = reason

    def __str__(self) -> str:
        return f"payment failed for order {self.order_id}: {self.reason}"


class PaymentGatewayTimeoutError(PaymentError):
    def __init__(self, order_id: str, gateway: str, timeout_ms: int):
        super().__init__(order_id, f"gateway {gateway} timed out after {timeout_ms} ms")
        self.args = (order_id, gateway, timeout_ms)  # match this constructor for pickling
        self.gateway = gateway
        self.timeout_ms = timeout_ms
```

An `__init__` whose arguments differ from `args` fails to unpickle (`TypeError: missing 1 required positional argument`), so errors raised in `ProcessPoolExecutor`, `multiprocessing`, or Celery workers never reach the caller intact.

### Example hierarchy (TypeScript)

```typescript
class AppError extends Error {
  readonly code: string | undefined;

  constructor(message: string, { code, cause }: ErrorOptions & { code?: string } = {}) {
    super(message, { cause }); // native ES2022 cause: loggers follow the chain
    this.name = new.target.name; // each subclass reports its own name
    this.code = code;
  }
}

class PaymentGatewayError extends AppError {
  readonly gateway: string;

  constructor(gateway: string, cause: unknown) {
    super(`payment gateway ${gateway} failed`, { code: 'PAYMENT_GATEWAY_FAILED', cause });
    this.gateway = gateway;
  }
}
```

## Logging Best Practices

- Levels: ERROR needs a human, WARN recovered on its own (retry succeeded, fallback ran), INFO records business events, DEBUG holds details.
- Structured fields (`order_id`, `gateway`, `duration_ms`) plus the stack: `logger.exception("…")` in Python, `logger.error({ err }, '…')` with pino-style loggers. What stays out: [Secure Logging](../security-review-guide.md#secure-logging).

## Code Examples by Language

### Python

```python
# ✅ Timeouts and HTTP errors become module errors at the boundary, with the cause kept
def charge(session: requests.Session, url: str, payload: dict, gateway: str) -> dict:
    try:
        response = session.post(url, json=payload, timeout=(3.05, 10))  # connect, read (seconds)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        if e.response.status_code == 429:
            raise RateLimitError(gateway) from e
        raise PaymentGatewayError(gateway, f"HTTP {e.response.status_code}") from e
    except requests.Timeout as e:  # ConnectTimeout and ReadTimeout
        raise PaymentGatewayError(gateway, "timed out") from e
    except requests.RequestException as e:  # connection errors, invalid JSON, ...
        raise PaymentGatewayError(gateway, type(e).__name__) from e
```

`requests` has no default timeout, and `ReadTimeout` is not a `ConnectionError`: catching only `ConnectionError` lets read timeouts escape unconverted.

### TypeScript

```typescript
// ✅ fetch rejects on network failures and timeouts; HTTP errors resolve, so check them too
async function processPayment(url: string, payload: string, gateway: string): Promise<Receipt> {
  let response: Response;
  try {
    response = await fetch(url, { method: 'POST', body: payload, signal: AbortSignal.timeout(10_000) });
  } catch (err) {
    throw new PaymentGatewayError(gateway, err);
  }
  if (!response.ok) throw new PaymentGatewayError(gateway, new Error(`HTTP ${response.status}`));
  return parseReceipt(await response.json());
}
```

More: [Throw Error objects and keep the cause](../javascript.md#throw-error-objects-and-keep-the-cause) · [Node.js async errors](../nodejs.md#async-error-handling) · [NestJS error handling](../nestjs.md#error-handling).

### Salesforce Apex

A caught exception rolls back only the failed DML statement while the rest of the transaction commits, so swallowing it silently loses data; an uncaught one rolls back everything.

```apex
// ✅ Partial success in user mode: every failed row is reported
List<Database.SaveResult> results = Database.insert(invoices, false, AccessLevel.USER_MODE);
for (Integer i = 0; i < results.size(); i++) {
    for (Database.Error err : results[i].getErrors()) {
        failures.add('Row ' + i + ': ' + err.getStatusCode() + ': ' + err.getMessage());
    }
}

// ✅ LWC boundary: log the details on the server, send the client a safe message
try {
    InvoiceService.submit(invoiceId);
} catch (InvoiceService.InvoiceException e) {
    // log e.getMessage() and e.getStackTraceString() with the project's logger
    throw new AuraHandledException('The invoice could not be submitted. Please try again.');
}
```

Trigger validation uses `record.Field__c.addError('…')` instead of throwing; `System.LimitException` can't be caught, so fix the design. PMD: `EmptyCatchBlock`. More: [Apex transactions](../salesforce/apex.md#transactions--error-handling) · [Flow fault handling](../salesforce/flows.md#fault-handling).

## References

- [OWASP Top 10:2025 A10 Mishandling of Exceptional Conditions](https://owasp.org/Top10/2025/A10_2025-Mishandling_of_Exceptional_Conditions/)
- [MDN: Error cause](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Error/cause)
