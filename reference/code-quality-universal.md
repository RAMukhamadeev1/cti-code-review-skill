# Universal Code Quality Anti-Patterns

> A language-agnostic guide to code-quality anti-patterns, covering core topics such as code reuse, leaky abstractions, parameter sprawl, nested conditionals, stringly-typed code, TOCTOU, and no-op updates. It applies to PR reviews in every language; [Salesforce Mapping](#salesforce-mapping) shows the Salesforce form of each anti-pattern.

## Table of Contents

- [Code Reuse Review](#code-reuse-review)
- [Parameter Sprawl](#parameter-sprawl)
- [Leaky Abstractions](#leaky-abstractions)
- [Stringly-Typed Code](#stringly-typed-code)
- [Nested Conditionals](#nested-conditionals)
- [Copy-Paste Variants](#copy-paste-variants)
- [No-Op Updates](#no-op-updates)
- [TOCTOU Race Conditions](#toctou-race-conditions)
- [Overly Broad Operations](#overly-broad-operations)
- [Redundant State](#redundant-state)
- [Salesforce Mapping](#salesforce-mapping)
- [Universal Quality Checklist](#universal-quality-checklist)

---

## Code Reuse Review

Before accepting new code, search the existing codebase for reusable utilities.

### Search for existing utilities

```python
# ❌ Newly written path-joining logic - the project already has PathBuilder
def get_config_path(name):
    base = os.environ.get("APP_ROOT", ".")
    return os.path.join(base, "config", name + ".json")

# ✅ Use the existing PathBuilder
def get_config_path(name):
    return PathBuilder.config(f"{name}.json")
```

```javascript
// ❌ Hand-written debounce - the project already has lodash or utils/debounce.ts
function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ✅ Use the existing utility
import { debounce } from "@/utils/debounce";
```

**Review points:**
- Does a new function duplicate the name or the functionality of an existing utility?
- Can inline logic be replaced with a call to an existing module?
- Check adjacent files and the shared/utils directories

---

## Parameter Sprawl

### Function parameters keep growing

```python
# ❌ One more parameter for every new requirement
def create_user(name, email, role, team, active, avatar_url, timezone):
    ...

# ✅ Use a parameter object / dataclass
@dataclass
class CreateUserParams:
    name: str
    email: str
    role: Role = Role.MEMBER
    team: str | None = None
    active: bool = True
    avatar_url: str | None = None
    timezone: str = "UTC"

def create_user(params: CreateUserParams) -> User:
    ...
```

```typescript
// ❌ 6+ positional parameters
function renderWidget(
  title: string, width: number, height: number,
  theme: string, collapsible: boolean, icon: string
) { ... }

// ✅ Options object pattern
interface WidgetOptions {
  title: string;
  width?: number;
  height?: number;
  theme?: "light" | "dark";
  collapsible?: boolean;
  icon?: string;
}
function renderWidget(options: WidgetOptions) { ... }
```

**Review points:**
- Does the function take ≥ 4 parameters? Consider an options object / dataclass
- Is the new parameter just a boolean flag? Consider an enum or the strategy pattern
- Are there mutually exclusive parameters such as `enable_x` and `disable_y`?

---

## Leaky Abstractions

### Exposing internal implementation details

```python
# ❌ Returns internal ORM objects - callers are forced to know SQLAlchemy
def get_users():
    return session.query(User).filter(User.active == True).all()

# ✅ Return domain objects and hide the persistence layer
def get_active_users() -> list[UserDTO]:
    rows = user_repo.find_active()
    return [UserDTO.from_row(r) for r in rows]
```

```typescript
// ❌ The render function receives the raw API response structure
renderUserCard(apiResponse.data.results[0]);

// ✅ The render function receives a domain type; an adapter handles the mapping
interface UserSummary {
  displayName: string;
  avatarUrl: string;
}
function renderUserCard(user: UserSummary): void { /* ... */ }
renderUserCard(adaptUser(apiResponse));
```

**Review points:**
- Does the function's return type leak the underlying implementation (ORM, HTTP client, file format)?
- Does a component/function depend on an external system's data structures?
- Does the change break an existing abstraction boundary?

---

## Stringly-Typed Code

### Raw strings instead of constants/enums

```python
# ❌ Magic strings scattered everywhere
if status == "active":
    ...
if role == "admin":
    ...

# ✅ Use an enum
class Status(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"

if user.status == Status.ACTIVE:
    ...
```

```typescript
// ❌ Raw string event names - a typo raises no error
emitter.emit("userCreated", data);
emitter.on("usercreated", handler); // bug: typo

// ✅ Constants or a branded type
const Events = {
  USER_CREATED: "userCreated",
  USER_SUSPENDED: "userSuspended",
} as const;
emitter.emit(Events.USER_CREATED, data);
```

**Review points:**
- Is a raw string used where an enum/union type already exists?
- Are event names, action types, and status values scattered across several files?
- Are string comparisons case-sensitive without the input being validated?

---

## Nested Conditionals

### Ternary chains and nested if/else

```python
# ❌ Ternary chains are hard to read
label = (
    "Admin" if role == "admin" else
    "Manager" if role == "manager" else
    "Viewer" if role == "viewer" else
    "Unknown"
)

# ✅ Lookup table or match
ROLE_LABELS = {
    "admin": "Admin",
    "manager": "Manager",
    "viewer": "Viewer",
}
label = ROLE_LABELS.get(role, "Unknown")
```

```typescript
// ❌ Nested ternary
const bg = isHovered
  ? isSelected ? "blue" : "gray"
  : isSelected ? "navy" : "white";

// ✅ Lookup table (lookup map)
const bgMap: Record<string, string> = {
  "true-true": "blue",
  "true-false": "gray",
  "false-true": "navy",
  "false-false": "white",
};
const bg = bgMap[`${isHovered}-${isSelected}`];
```

```python
# ❌ if statements nested 3+ levels deep
def process(order):
    if order is not None:
        if order.items:
            for item in order.items:
                if item.price > 0:
                    ...

# ✅ Early return + guard clauses
def process(order):
    if not order or not order.items:
        return
    for item in order.items:
        if item.price <= 0:
            continue
        ...
```

**Review points:**
- Are ternaries nested 2 or more levels deep?
- Is if/else nested 3 or more levels deep?
- Can a lookup table, an early return, or match replace it?

---

## Copy-Paste Variants

### Near-duplicate code blocks

```python
# ❌ Two functions that are almost identical, except for the field names
def format_user(user):
    return f"{user.first_name} {user.last_name} ({user.email})"

def format_employee(emp):
    return f"{emp.first_name} {emp.last_name} ({emp.work_email})"

# ✅ One shared abstraction
def format_person(first: str, last: str, email: str) -> str:
    return f"{first} {last} ({email})"
```

```typescript
// ❌ Copy-pasted handler with only the URL changed
async function deletePost(id: string) {
  await fetch(`/api/posts/${id}`, { method: "DELETE" });
  router.push("/posts");
}
async function deleteComment(id: string) {
  await fetch(`/api/comments/${id}`, { method: "DELETE" });
  router.push("/comments");
}

// ✅ Parameterize
async function deleteResource(resource: string, id: string) {
  await fetch(`/api/${resource}/${id}`, { method: "DELETE" });
  router.push(`/${resource}`);
}
```

**Review points:**
- Are there ≥ 2 blocks of code that differ only in variable names/URLs/strings?
- Can a parameterized shared function be extracted?
- Can a template method or strategy remove the variants?

---

## No-Op Updates

### State updates triggered unconditionally

```typescript
// ❌ Every poll notifies the subscriber - even when the data has not changed
function startStatusPolling(onChange: (status: Status) => void): () => void {
  const interval = setInterval(() => {
    fetch("/api/status").then(r => r.json()).then(onChange);
  }, 5000);
  return () => clearInterval(interval);
}

// ✅ Notify only when the value changes
function startStatusPolling(onChange: (status: Status) => void): () => void {
  let last: Status | undefined;
  const interval = setInterval(() => {
    fetch("/api/status")
      .then(r => r.json())
      .then((next: Status) => {
        if (!isEqual(last, next)) {
          last = next;
          onChange(next);
        }
      })
      .catch(handleError);
  }, 5000);
  return () => clearInterval(interval);
}
```

```python
# ❌ Writes to the DB on every loop iteration - even when the value has not changed
for item in items:
    item.status = compute_status(item)
    session.commit()

# ✅ Write only when the value changes
for item in items:
    new_status = compute_status(item)
    if item.status != new_status:
        item.status = new_status
        session.commit()
```

**Review points:**
- Do polling / interval / event handlers update unconditionally?
- Do wrapper functions preserve same-reference returns (hand back the previous value when nothing changed)?
- Do DB writes check that something actually changed?

---

## TOCTOU Race Conditions

### Time-of-Check-to-Time-of-Use

```python
# ❌ Check first, then act - the file may be deleted or created in between
if os.path.exists(path):
    with open(path) as f:
        data = f.read()

# ✅ Act directly + handle the exception
try:
    with open(path) as f:
        data = f.read()
except FileNotFoundError:
    data = None
```

```python
# ❌ Check the balance, then debit: two steps that are not atomic
if account.balance >= amount:
    account.balance -= amount

# ✅ An atomic operation or a lock
with account.lock:
    if account.balance < amount:
        raise InsufficientFundsError()
    account.balance -= amount
```

```typescript
// ❌ Check-then-act is unsafe in async code
if (!fileExists(path)) {
  await writeFile(path, content);
}

// ✅ Act directly + catch
try {
  await writeFile(path, content, { flag: "wx" });
} catch (e) {
  if (e.code === "EEXIST") { /* handle */ }
  else throw e;
}
```

**Review points:**
- Can an `if exists → operate` pattern be replaced with `try operate → catch`?
- Are multi-step state changes inside a transaction/lock?
- In async code, is there an await between the check and the act?

---

## Overly Broad Operations

### Reading too much data

```python
# ❌ Read the entire file to get the first line
content = Path("log.txt").read_text()
first_line = content.split("\n")[0]

# ✅ Read only the first line, without loading the whole file
with open("log.txt") as f:
    first_line = f.readline()
```

```typescript
// ❌ Load every item, then filter
const allItems = await db.query("SELECT * FROM orders");
const pending = allItems.filter(o => o.status === "pending");

// ✅ Filter in the database
const pending = await db.query(
  "SELECT * FROM orders WHERE status = ?", ["pending"]
);
```

```python
# ❌ Load the whole table to find one record
user = next(u for u in session.scalars(select(User)).all() if u.id == user_id)

# ✅ Precise lookup by primary key
user = session.get(User, user_id)
```

**Review points:**
- Does the code read an entire collection/file and then use only a small part of it?
- Can filtering be pushed down to the database/storage layer?
- Do API calls support pagination/limit parameters?

---

## Redundant State

### State that can be derived

```typescript
// ❌ Stores fullName alongside firstName + lastName
interface User {
  firstName: string;
  lastName: string;
  fullName: string;  // redundant
}

// ✅ fullName is a derived value
interface User {
  firstName: string;
  lastName: string;
}
const fullName = `${user.firstName} ${user.lastName}`;
```

```python
# ❌ Cached values can go stale when the source data changes
class Order:
    total: float
    item_count: int       # redundant if len(items) gives the same
    items: list[Item]

# ✅ Derive it, or use a property
class Order:
    items: list[Item]

    @property
    def total(self) -> float:
        return sum(item.price for item in self.items)

    @property
    def item_count(self) -> int:
        return len(self.items)
```

**Review points:**
- Can any field be derived from other fields?
- Do cached values have an invalidation mechanism?
- Can an observer/effect be replaced with a direct call?

---

## Salesforce Mapping

The same anti-patterns in Salesforce code and metadata. The linked guides hold the rules and examples.

| Anti-pattern | Salesforce form | Guide |
|---|---|---|
| Code reuse | A new test-data helper, trigger dispatcher, query, logger, or LWC error parser written next to the existing `TestDataFactory`, trigger handler framework, selectors, logger, or `reduceErrors` | [Apex: Class Design](salesforce/apex.md#class-design) |
| Parameter sprawl | `@AuraEnabled` methods that take a growing list of primitives, or invocable methods that pack values into delimited strings, instead of one request class (with `@InvocableVariable` fields for Flow) | [Flows: Invocable Apex Contract](salesforce/flows.md#invocable-apex-contract) |
| Leaky abstractions | Controllers that return raw sObjects with every queried field, `Database.SaveResult`, or raw exception text to LWC instead of a response DTO and a user-safe error | [LWC: The LWC-Apex Contract](salesforce/lwc.md#the-lwc-apex-contract) |
| Stringly-typed code | `record.get('Field__c')` and field names in strings instead of `Schema.SObjectField` tokens in Apex or `@salesforce/schema` imports in LWC | [Apex: Language Pitfalls](salesforce/apex.md#language-pitfalls) · [LWC: Data Access](salesforce/lwc.md#data-access) |
| No-op updates | DML on records whose values did not change, which still fires triggers, flows, and validation rules and uses up limits | [Apex: Bulkification](salesforce/apex.md#bulkification) |
| TOCTOU race conditions | Query-then-update without `FOR UPDATE`, so two concurrent transactions (for example, two Queueable jobs) overwrite each other's changes | [Apex: Async Apex](salesforce/apex.md#async-apex) |
| Overly broad operations | `FIELDS(STANDARD)` in Apex or `FIELDS(ALL)` in API queries when the code reads a few fields; queries with no selective filter on large objects; flow Get Records elements that store all fields | [SOQL & SOSL: Selectivity & Large Data Volumes](salesforce/soql-sosl.md#selectivity--large-data-volumes) |
| Redundant state | Trigger-maintained copies of values that a formula or roll-up summary field could derive | [Metadata: Objects & Fields](salesforce/metadata.md#objects--fields) |

---

## Universal Quality Checklist

- [ ] **Reuse review**: existing utilities/helpers were searched for; nothing is reinvented?
- [ ] **Parameter count**: functions take ≤ 3 parameters? If more, is an options object / dataclass used?
- [ ] **Abstraction boundaries**: return types do not expose internal implementation details (ORM, HTTP client, file format)?
- [ ] **Type safety**: no magic strings in place of an existing enum/constant/union type?
- [ ] **Condition depth**: ternaries nested ≤ 1 level? if/else nested ≤ 2 levels?
- [ ] **DRY**: no copy-paste-with-variation (≥ 2 near-identical blocks)?
- [ ] **No-op guards**: polling / interval / event handlers have a change-detection guard?
- [ ] **TOCTOU**: `if exists → operate` replaced with `try operate → catch`?
- [ ] **Data precision**: no reading an entire collection/file just to use a subset?
- [ ] **Redundant state**: no stored fields that can be derived from other fields?
- [ ] **Salesforce**: each anti-pattern above also checked in its Salesforce form ([Salesforce Mapping](#salesforce-mapping))?
