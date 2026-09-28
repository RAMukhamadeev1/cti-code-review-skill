# Error Handling Principles: Cross-Language Guide

> This guide covers the core principles of error handling, common anti-patterns, error hierarchy design, and logging best practices. Each principle comes with code examples for JavaScript/TypeScript, Python, and Salesforce Apex.

## Table of Contents

- [Core Principles](#core-principles)
- [Anti-Patterns](#anti-patterns)
- [Error Hierarchy Design](#error-hierarchy-design)
- [Logging Best Practices](#logging-best-practices)
- [Code Examples by Language](#code-examples-by-language)
- [Review Checklist](#review-checklist)

---

## Core Principles

### Principle 1: Don't swallow errors

Every error must be handled: propagated upward, logged, or converted into a more meaningful error. **Never** ignore it silently.

```
// Pseudocode
result = risky_operation()
if error:
    // You must do one of the following:
    //   1. return error to caller (propagate)
    //   2. log + return fallback (degrade)
    //   3. panic/crash (when unrecoverable)
```

### Principle 2: Add context

Error messages should include **the operation** and **the key parameters**, so whoever debugs the problem can locate it without reading the whole call chain.

```
// ❌ No context
"failed"

// ✅ With context
"failed to process order #12345: payment gateway timeout after 30s"
```

### Principle 3: Use specific types

Use error types to tell failure causes apart, so callers can handle each failure precisely.

```
// ❌ Generic error
throw new Error("something went wrong")

// ✅ Specific types
throw new OrderNotFoundError(orderId)
throw new PaymentTimeoutException(gatewayName, timeoutMs)
```

### Principle 4: Fail fast

Validate preconditions before the operation starts and fail as early as possible. This avoids the inconsistent state left behind when an error surfaces halfway through.

```
// ❌ Finds the invalid argument halfway through
def process(data, config):
    result = expensive_computation(data)  # already spent 5 seconds
    if not config.valid:
        raise ValueError("invalid config")  # 5 seconds wasted

// ✅ Validate first
def process(data, config):
    if not config.valid:
        raise ValueError("invalid config")
    result = expensive_computation(data)
```

### Principle 5: Handle each error once

Don't handle the same error at every layer (logging it, returning it, and wrapping it). Pick one, and let the caller decide what to do with it.

```
// ❌ Logs and returns (handled twice)
if err:
    log.error("failed: %s", err)
    return err

// ✅ Only wrap and return; the top level handles it in one place
if err:
    return wrap_error("operation failed", err)
```

---

## Anti-Patterns

### Anti-pattern 1: Empty catch blocks

```python
# ❌ Python: a bare except swallows every exception (including KeyboardInterrupt)
try:
    result = risky()
except:
    pass
```

```typescript
// ❌ TypeScript: an empty catch hides the failure
try {
    await saveOrder(order);
} catch {}

// ❌ A promise chain that throws the rejection away
saveOrder(order).catch(() => {});
```

```apex
// ❌ Apex: the records stay unsaved, nobody is told, and the rest of the transaction commits
try {
    update accounts;
} catch (DmlException e) {
}
```

### Anti-pattern 2: Overly broad catch

```python
# ❌ Catches everything, so the failure types can't be told apart
try:
    result = risky()
except Exception as e:
    logger.error(f"failed: {e}")

# ✅ Catch specific exceptions
try:
    result = risky()
except ConnectionError as e:
    logger.warning(f"network issue, retrying: {e}")
    result = retry(risky)
except ValueError as e:
    logger.error(f"bad input: {e}")
    raise
```

### Anti-pattern 3: Losing the original exception

```python
# ❌ The original exception is not recorded as the cause
try:
    result = external_api.call()
except APIError as e:
    raise RuntimeError("API failed")  # no "from e"

# ✅ Keep the exception chain
try:
    result = external_api.call()
except APIError as e:
    raise RuntimeError("API failed") from e
```

```typescript
// ❌ The original error is lost
try {
    await copyFile(source, destination);
} catch (err) {
    throw new ServiceError('IO failed');
}

// ✅ Keep the cause (ES2022 Error options)
try {
    await copyFile(source, destination);
} catch (err) {
    throw new ServiceError('IO failed', { cause: err });
}
```

### Anti-pattern 4: Exceptions for control flow

```python
# ❌ Exceptions used for normal control flow (slow and unclear)
try:
    user = users[name]
except KeyError:
    user = create_default_user(name)

# ✅ Explicit check
user = users.get(name) or create_default_user(name)
```

```typescript
// ❌ An expected "not found" is thrown, so callers write try/catch as an if/else
//    (and the bare catch also swallows real failures, such as a lost connection)
function resolveUser(id: string): User {
    try {
        return getUser(id); // throws when the id is unknown
    } catch {
        return createDefaultUser(id);
    }
}

// ✅ Put the expected miss in the return type; keep exceptions for real failures
function findUser(id: string): User | undefined {
    return usersById.get(id);
}

const user = findUser(id) ?? createDefaultUser(id);
```

### Anti-pattern 5: Ignoring return values

```python
# ❌ str methods return a new string: the stripped copy is discarded
name.strip()
save(name)  # still has the surrounding whitespace

# ✅ Use the return value
name = name.strip()
save(name)

# ❌ re.match returns None when nothing matches
user_id = re.match(r"user-(\d+)", key).group(1)  # AttributeError on None

# ✅ Check the result
match = re.match(r"user-(\d+)", key)
if match is None:
    raise ValueError(f"unexpected key format: {key!r}")
user_id = match.group(1)
```

```typescript
// ❌ fetch resolves on HTTP 4xx/5xx; ignoring response.ok treats an error page as data
const order = await (await fetch(url)).json();

// ✅ Check the status before using the body
const response = await fetch(url);
if (!response.ok) {
    throw new Error(`GET ${url} failed with HTTP ${response.status}`);
}
const order: unknown = await response.json();
```

```apex
// ❌ allOrNone = false reports failures in the results instead of throwing; here they are dropped
Database.update(records, false);

// ✅ Keep the results and record which rows failed and why (results follow the input order)
Map<Id, List<Database.Error>> errorsById = new Map<Id, List<Database.Error>>();
List<Database.SaveResult> results = Database.update(records, false, AccessLevel.USER_MODE);
for (Integer i = 0; i < results.size(); i++) {
    if (!results[i].isSuccess()) {
        errorsById.put(records[i].Id, results[i].getErrors());
    }
}
```

---

## Error Hierarchy Design

### Three-tier error architecture

```
┌────────────────────────────────────────────────────────────┐
│ Application Errors                                         │
│   - AppError / ServiceError                                │
│   - Caught by the global exception handler, which returns  │
│     a user-friendly response                               │
├────────────────────────────────────────────────────────────┤
│ Module Errors                                              │
│   - PaymentError, AuthError, ValidationError               │
│   - Each business module defines its own error types       │
├────────────────────────────────────────────────────────────┤
│ Infrastructure Errors                                      │
│   - IOError, NetworkError, DatabaseError                   │
│   - Low-level errors from the OS, network, and database    │
└────────────────────────────────────────────────────────────┘
```

### Design rules

1. **Module errors inherit from the application base class**, so they can be caught globally
2. **Infrastructure errors are converted into module errors at the module boundary**, so they never leak to upper layers
3. **Every error type carries enough context** for debugging (IDs, timestamp, operation name)

### Example hierarchy (Python)

```python
class AppError(Exception):
    """Base application exception"""
    pass

class PaymentError(AppError):
    """Payment module error"""
    def __init__(self, order_id: str, reason: str):
        self.order_id = order_id
        super().__init__(f"payment failed for order {order_id}: {reason}")

class PaymentGatewayTimeout(PaymentError):
    """Payment gateway timed out"""
    def __init__(self, order_id: str, gateway: str, timeout_ms: int):
        self.gateway = gateway
        self.timeout_ms = timeout_ms
        super().__init__(order_id, f"gateway {gateway} timed out after {timeout_ms}ms")
```

### Example hierarchy (TypeScript)

```typescript
interface AppErrorOptions extends ErrorOptions {
    code?: string;
}

class AppError extends Error {
    readonly code: string | undefined;

    constructor(message: string, { code, cause }: AppErrorOptions = {}) {
        super(message, { cause }); // native ES2022 cause: loggers and debuggers follow the chain
        this.name = new.target.name; // each subclass reports its own name
        this.code = code;
    }
}

class OrderNotFoundError extends AppError {
    readonly orderId: string;

    constructor(orderId: string) {
        super(`order ${orderId} not found`, { code: 'ORDER_NOT_FOUND' });
        this.orderId = orderId;
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

---

## Logging Best Practices

### Choosing a log level

| Level | When to use | Examples |
|------|---------|------|
| **ERROR** | Failures that need human intervention | Payment failure, data inconsistency |
| **WARN** | Problems that recover automatically | Retry succeeded, degraded fallback |
| **INFO** | Normal business events | Order created, user logged in |
| **DEBUG** | Debugging details | Function arguments, intermediate state |

### Log format

```
// ❌ No structured information
log.error("failed to process")

// ✅ Structured fields + context
log.error("payment_failed", {
    "order_id": "12345",
    "gateway": "stripe",
    "error_code": "card_declined",
    "amount": 99.99,
    "duration_ms": 2340
})
```

### Log security

- **Never log sensitive data**: passwords, tokens, PII, full credit card numbers
- **Mask values**: `email: a***@example.com`
- **Prevent log injection**: escape user input so it cannot forge log lines

---

## Code Examples by Language

### Python

```python
# ✅ Specific exceptions + context + exception chaining
try:
    response = http_client.post(url, data=payload)
    response.raise_for_status()
except requests.ConnectionError as e:
    raise PaymentGatewayError(f"cannot reach {gateway_name}") from e
except requests.HTTPError as e:
    if response.status_code == 429:
        raise RateLimitError(f"rate limited by {gateway_name}") from e
    raise PaymentGatewayError(f"HTTP {response.status_code} from {gateway_name}") from e
```

> 📖 Depth: [Python exception handling](../python.md#exception-handling)

### TypeScript

```typescript
// ✅ Custom error class + context + native cause
class PaymentError extends Error {
    constructor(
        message: string,
        public readonly orderId: string,
        public readonly gateway: string,
        cause?: unknown,
    ) {
        super(message, { cause }); // native ES2022 Error.cause instead of a field that shadows it
        this.name = 'PaymentError';
    }
}

async function processPayment(orderId: string): Promise<Receipt> {
    try {
        const response = await fetch(url, { method: 'POST', body: payload });
        if (!response.ok) {
            throw new PaymentError(
                `gateway returned ${response.status}`,
                orderId,
                gatewayName,
            );
        }
        return await response.json();
    } catch (err) {
        if (err instanceof TypeError) {
            throw new PaymentError('gateway unreachable', orderId, gatewayName, err);
        }
        throw err;
    }
}
```

> 📖 Depth: [Throw Error objects and keep the cause](../javascript.md#throw-error-objects-and-keep-the-cause) · [Node.js async error handling](../nodejs.md#async-error-handling) · [NestJS error handling](../nestjs.md#error-handling)

### Salesforce Apex

Apex rolls back only the failed DML statement when an exception is caught, and the rest of the transaction still commits, so a swallowed exception quietly loses data. Uncaught exceptions roll back the whole transaction.

```apex
public with sharing class InvoiceService {
    public class InvoiceException extends Exception {}

    // ❌ The failure disappears: the caller believes the invoices were saved
    public static void createSilently(List<Invoice__c> invoices) {
        try {
            insert invoices;
        } catch (DmlException e) {
        }
    }

    // ✅ Partial success in user mode: inspect every SaveResult and report the failures
    public static List<String> create(List<Invoice__c> invoices) {
        List<String> failures = new List<String>();
        List<Database.SaveResult> results = Database.insert(invoices, false, AccessLevel.USER_MODE);
        for (Integer i = 0; i < results.size(); i++) {
            for (Database.Error err : results[i].getErrors()) {
                failures.add('Row ' + i + ': ' + err.getStatusCode() + ': ' + err.getMessage());
            }
        }
        return failures;
    }

    // submit(Id invoiceId) throws InvoiceException when the invoice cannot be submitted
}

public with sharing class InvoiceTriggerHandler {
    // ✅ Trigger validation: addError() fails the record with a message for the user
    //    instead of throwing (pass Trigger.new from a before insert/update trigger)
    public static void validate(List<Invoice__c> newInvoices) {
        for (Invoice__c inv : newInvoices) {
            if (inv.Amount__c == null || inv.Amount__c < 0) {
                inv.Amount__c.addError('Amount must be zero or greater.');
            }
        }
    }
}

public with sharing class InvoiceController {
    // ✅ LWC boundary: keep the details in the server log, send the client a user-safe message
    @AuraEnabled
    public static void submitInvoice(Id invoiceId) {
        try {
            InvoiceService.submit(invoiceId);
        } catch (InvoiceService.InvoiceException e) {
            // log e.getMessage() and e.getStackTraceString() with the project's logger here
            throw new AuraHandledException('The invoice could not be submitted. Please try again.');
        }
    }
}

// ⚠️ System.LimitException cannot be caught: no catch block survives a governor-limit breach,
//    and the transaction rolls back. Fix the design (bulkify, move work to async Apex).
```

Static analysis: PMD `EmptyCatchBlock`.

> 📖 Depth: [Apex transactions and error handling](../salesforce/apex.md#transactions--error-handling) · [The LWC-Apex contract](../salesforce/lwc.md#the-lwc-apex-contract) · [Flow fault handling](../salesforce/flows.md#fault-handling)

---

## Review Checklist

### Core checks
- [ ] No empty catch blocks or silently ignored errors
- [ ] Error messages include the operation and the key parameters
- [ ] Specific error types are used (not a generic Error/Exception)
- [ ] The exception chain is preserved (`raise ... from`, `{ cause }`)
- [ ] Preconditions are validated before the operation starts (fail fast)

### Architecture checks
- [ ] A clear error hierarchy is defined (application / module / infrastructure)
- [ ] A global exception handler catches unhandled errors
- [ ] API boundaries convert internal errors into the appropriate HTTP status codes

### Logging checks
- [ ] Error logs include structured context
- [ ] No sensitive data is logged (passwords, tokens, PII)
- [ ] Log levels are used correctly (ERROR vs WARN vs INFO)

### Language-specific
- [ ] Python: catch specific exceptions; use `from` to keep the chain
- [ ] TypeScript: no floating promises; errors are wrapped with `{ cause }`; typed `Error` subclasses are thrown, never strings or plain objects
- [ ] Apex: no empty catch blocks; `SaveResult` is inspected after partial-success DML; `AuraHandledException` with a user-safe message at the LWC boundary
