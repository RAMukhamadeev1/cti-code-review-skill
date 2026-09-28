# Architecture Review Guide

A guide to reviewing architecture and design: whether the structure of the code is sound and the design fits the problem. The Salesforce section covers layering and automation ownership on the platform.

## SOLID Principles Checklist

### S - Single Responsibility Principle (SRP)

**What to check:**
- Does this class/module have only one reason to change?
- Do all methods in the class serve the same purpose?
- Could you describe the class to a non-technical person in one sentence?

**Warning signs in code review:**
```
⚠️ Class names containing generic words such as "And", "Manager", "Handler", "Processor"
⚠️ A class longer than 200-300 lines
⚠️ A class with more than 5-7 public methods
⚠️ Different methods operating on completely different data
```

**Questions to ask:**
- "What is this class responsible for? Can it be split?"
- "If requirement X changes, which methods have to change? What if requirement Y changes?"

### O - Open/Closed Principle (OCP)

**What to check:**
- Does adding a feature require modifying existing code?
- Can new behavior be added through extension (inheritance, composition)?
- Are there long if/else or switch statements that handle different types?

**Warning signs in code review:**
```
⚠️ switch/if-else chains that handle different types
⚠️ Adding a feature requires modifying core classes
⚠️ Type checks (instanceof, typeof) scattered through the code
```

**Questions to ask:**
- "To add a new X type, which files need to change?"
- "Will this switch statement grow with every new type?"

### L - Liskov Substitution Principle (LSP)

**What to check:**
- Can a subclass fully replace its parent class?
- Does a subclass change the expected behavior of a parent method?
- Does a subclass throw exceptions that the parent does not declare?

**Warning signs in code review:**
```
⚠️ Explicit type casts
⚠️ Subclass methods that throw new Error('Not implemented')
⚠️ Subclass methods with an empty body or a bare return
⚠️ Code that uses the base class has to check the concrete type
```

**Questions to ask:**
- "If you replace the parent class with this subclass, does the calling code need to change?"
- "Does this method's behavior in the subclass honor the parent's contract?"

### I - Interface Segregation Principle (ISP)

**What to check:**
- Is the interface small and focused?
- Are implementations forced to implement methods they do not need?
- Do clients depend on methods they do not use?

**Warning signs in code review:**
```
⚠️ Interfaces with more than 5-7 methods
⚠️ Implementations with empty methods or methods that throw new Error('Not implemented')
⚠️ Overly broad interface names (Manager, Service)
⚠️ Different clients each use only part of the interface
```

**Questions to ask:**
- "Is every method of this interface used by every implementation?"
- "Can this large interface be split into smaller, role-specific interfaces?"

### D - Dependency Inversion Principle (DIP)

**What to check:**
- Do high-level modules depend on abstractions rather than concrete implementations?
- Is dependency injection used instead of creating objects directly with new?
- Are the abstractions defined by the high-level modules rather than by the low-level ones?

**Warning signs in code review:**
```
⚠️ High-level modules create low-level concrete classes directly with new
⚠️ Importing concrete implementation classes instead of interfaces/abstract classes
⚠️ Configuration and connection strings hard-coded in business logic
⚠️ A class is hard to unit test
```

**Questions to ask:**
- "Can this class's dependencies be replaced with mocks in tests?"
- "To swap the database/API implementation, how many places would need to change?"

---

## Architecture Anti-Patterns

### Critical anti-patterns

| Anti-pattern | Warning signs | Impact |
|--------|----------|------|
| **Big Ball of Mud** | No clear module boundaries; any code may call any other code | Hard to understand, change, and test |
| **God Object** | A single class takes on too many responsibilities: it knows too much and does too much | High coupling; hard to reuse and test |
| **Spaghetti code** | Tangled control flow, goto or deep nesting, execution paths that are hard to follow | Hard to understand and maintain |
| **Lava Flow** | Old code that nobody dares to touch, with no documentation or tests | Growing technical debt |

### Design anti-patterns

| Anti-pattern | Warning signs | Recommendation |
|--------|----------|------|
| **Golden Hammer** | The same technology/pattern used for every problem | Choose the solution that fits the problem |
| **Over-engineering (Gas Factory)** | Complex solutions to simple problems; design patterns overused | YAGNI: start simple, add complexity when it is needed |
| **Boat Anchor** | Unused code written "because we might need it later" | Delete unused code; write it when it is needed |
| **Copy-paste programming** | The same logic appears in several places | Extract a shared function or module |

### Example review comments

```markdown
🔴 [blocking] "This class has 2,000 lines of code; split it into several focused classes"
🟡 [important] "This logic is duplicated in 3 places; could we extract a shared function?"
💡 [suggestion] "This switch statement could be replaced with the Strategy pattern, which is easier to extend"
```

---

## Coupling and Cohesion

### Types of coupling (best to worst)

| Type | Description | Example |
|------|------|------|
| **Message coupling** ✅ | Data passed as parameters | `calculate(price, quantity)` |
| **Data coupling** ✅ | Simple data structures shared | `processOrder(orderDTO)` |
| **Stamp coupling** ⚠️ | A complex data structure is shared, but only part of it is used | Passing the whole User object but using only name |
| **Control coupling** ⚠️ | Control flags passed in to change behavior | `process(data, isAdmin=true)` |
| **Common coupling** ❌ | Global variables shared | Several modules read and write the same global state |
| **Content coupling** ❌ | Direct access to another module's internals | Directly manipulating another class's private properties |

### Types of cohesion (best to worst)

| Type | Description | Quality |
|------|------|------|
| **Functional cohesion** | All elements perform a single task | ✅ Best |
| **Sequential cohesion** | The output of one step is the input of the next | ✅ Good |
| **Communicational cohesion** | Operations on the same data | ⚠️ Acceptable |
| **Temporal cohesion** | Tasks that run at the same time | ⚠️ Weak |
| **Logical cohesion** | Logically related but functionally different | ❌ Poor |
| **Coincidental cohesion** | No meaningful relationship | ❌ Worst |

### Metrics reference

```yaml
Coupling metrics:
  CBO (Coupling Between Objects):
    Good: < 5
    Warning: 5-10
    Danger: > 10

  Ce (efferent coupling):
    Description: how many external classes it depends on
    Good: < 7

  Ca (afferent coupling):
    Description: how many classes depend on it
    High value means: changes have a wide impact, so it must stay stable

Cohesion metrics:
  LCOM4 (Lack of Cohesion of Methods):
    1: single responsibility ✅
    2-3: may need splitting ⚠️
    >3: should be split ❌
```

### Questions to ask

- "How many other modules does this module depend on? Can we reduce that?"
- "How many other places are affected when this class changes?"
- "Do all of this class's methods operate on the same data?"

---

## Layered Architecture Review

### Clean Architecture layer check

```
┌─────────────────────────────────────┐
│         Frameworks & Drivers        │ ← Outermost layer: Web, DB, UI
├─────────────────────────────────────┤
│         Interface Adapters          │ ← Controllers, Gateways, Presenters
├─────────────────────────────────────┤
│          Application Layer          │ ← Use Cases, Application Services
├─────────────────────────────────────┤
│            Domain Layer             │ ← Entities, Domain Services
└─────────────────────────────────────┘
          ↑ Dependencies point inward only ↑
```

### Dependency rule check

**Core rule: source-code dependencies may only point inward**

```typescript
// ❌ Violates the dependency rule: the Domain layer depends on Infrastructure
// domain/User.ts
import { MySQLConnection } from '../infrastructure/database';

// ✅ Correct: the Domain layer defines the interface, Infrastructure implements it
// domain/UserRepository.ts (interface)
interface UserRepository {
  findById(id: string): Promise<User>;
}

// infrastructure/MySQLUserRepository.ts (implementation)
class MySQLUserRepository implements UserRepository {
  findById(id: string): Promise<User> { /* ... */ }
}
```

### Review checklist

**Layer boundary checks:**
- [ ] Does the Domain layer have external dependencies (database, HTTP, file system)?
- [ ] Does the Application layer access the database or call external APIs directly?
- [ ] Does the Controller contain business logic?
- [ ] Are there calls that skip layers (the UI calling a Repository directly)?

**Separation of concerns checks:**
- [ ] Is business logic separated from presentation logic?
- [ ] Is data access encapsulated in a dedicated layer?
- [ ] Is configuration and environment-specific code managed in one place?

### Example review comments

```markdown
🔴 [blocking] "The Domain entity imports the database connection directly, which violates the dependency rule"
🟡 [important] "The Controller contains business calculations; move them to the Service layer"
💡 [suggestion] "Consider dependency injection to decouple these components"
```

---

## Design Pattern Usage

### When to use design patterns

| Pattern | Good fit | Poor fit |
|------|----------|------------|
| **Factory** | Objects of different types must be created, and the type is decided at run time | Only one type, or the type never changes |
| **Strategy** | The algorithm must be switchable at run time; there are several interchangeable behaviors | Only one algorithm, or the algorithm never changes |
| **Observer** | A one-to-many dependency where state changes must notify several objects | A simple direct call is enough |
| **Singleton** | A single global instance is truly required, such as configuration management | Objects that can be passed in through dependency injection |
| **Decorator** | Responsibilities must be added dynamically, without an explosion of subclasses | Fixed responsibilities that never need dynamic composition |

### Over-engineering warning signs

```
⚠️ Warning signs of "patternitis":

1. A simple if/else replaced with a Strategy + Factory + Registry
2. Interfaces with only one implementation
3. Abstraction layers added "because we might need them later"
4. Code size grows substantially because of the patterns applied
5. Newcomers need a long time to understand the code structure
```

### Review principles

```markdown
✅ Patterns used well:
- Solve a real extensibility problem
- Make the code easier to understand and test
- Make adding features simpler

❌ Patterns overused:
- Used for the sake of using a pattern
- Add unnecessary complexity
- Violate YAGNI
```

### Questions to ask

- "What concrete problem does this pattern solve?"
- "What would go wrong without this pattern?"
- "Is the value of this abstraction layer greater than the complexity it adds?"

---

## Extensibility Assessment

### Extensibility checklist

**Feature extensibility:**
- [ ] Does adding a feature require modifying core code?
- [ ] Are extension points provided (hooks, plugins, events)?
- [ ] Is configuration externalized (configuration files, environment variables)?

**Data extensibility:**
- [ ] Does the data model support adding fields?
- [ ] Has growth in data volume been considered?
- [ ] Do queries have appropriate indexes?

**Load scalability:**
- [ ] Can it scale horizontally (add more instances)?
- [ ] Does it depend on local state (session, local cache)?
- [ ] Do database connections use a connection pool?

### Extension point design check

```typescript
// ✅ Good extension design: use events/hooks
class OrderService {
  private hooks: OrderHooks;

  async createOrder(order: Order) {
    await this.hooks.beforeCreate?.(order);
    const result = await this.save(order);
    await this.hooks.afterCreate?.(result);
    return result;
  }
}

// ❌ Poor extension design: all behavior hard-coded
class OrderService {
  async createOrder(order: Order) {
    await this.sendEmail(order);        // hard-coded
    await this.updateInventory(order);  // hard-coded
    await this.notifyWarehouse(order);  // hard-coded
    return await this.save(order);
  }
}
```

### Example review comments

```markdown
💡 [suggestion] "If we need to support a new payment method later, is this design easy to extend?"
🟡 [important] "This logic is hard-coded; could we use configuration or the Strategy pattern?"
📚 [learning] "An event-driven architecture would make this feature easier to extend"
```

---

## Code Structure Best Practices

### Directory organization

**Organize by feature/domain (recommended):**
```
src/
├── user/
│   ├── User.ts           (entity)
│   ├── UserService.ts    (service)
│   ├── UserRepository.ts (data access)
│   └── UserController.ts (API)
├── order/
│   ├── Order.ts
│   ├── OrderService.ts
│   └── ...
└── shared/
    ├── utils/
    └── types/
```

**Organize by technical layer (not recommended):**
```
src/
├── controllers/     ← different domains mixed together
│   ├── UserController.ts
│   └── OrderController.ts
├── services/
├── repositories/
└── models/
```

### Naming convention checks

| Kind | Convention | Example |
|------|------|------|
| Class name | PascalCase, noun | `UserService`, `OrderRepository` |
| Method name | camelCase, verb | `createUser`, `findOrderById` |
| Interface name | PascalCase noun, no `I` prefix | `UserRepository`, `PaymentGateway` |
| Constant | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT` |
| Private property | Underscore prefix or none | `_cache` or `#cache` |

### File size guidelines

```yaml
Recommended limits:
  Single file: < 300 lines
  Single function: < 50 lines
  Single class: < 200 lines
  Function parameters: < 4
  Nesting depth: < 4 levels

When a limit is exceeded:
  - Consider splitting into smaller units
  - Prefer composition over inheritance
  - Extract helper functions or classes
```

### Example review comments

```markdown
🟢 [nit] "This 500-line file could be split by responsibility"
🟡 [important] "Organize directories by feature domain rather than by technical layer"
💡 [suggestion] "The function name `process` is too vague; how about `calculateOrderTotal`?"
```

---

## Salesforce Architecture

Apex shares each transaction with declarative automation (flows, validation rules, roll-up summaries), so architecture review on Salesforce is also about who owns which behavior. Load the [Salesforce Platform Guide](salesforce/platform.md) for governor limits and the security model; the rules below cover structure.

### Layering: trigger → handler → service → selector

Each layer has one reason to change. The service takes collections instead of reading `Trigger.new`, so triggers, LWC controllers, invocable actions, and Batch jobs can all reuse it.

```text
AccountTrigger                  one trigger per object, no logic: delegates to the handler
  → AccountTriggerHandler       routes by context (before/after, insert/update), passes collections
    → AccountService            business rules, bulk-safe, explicit sharing keyword
      → AccountSelector         all SOQL for the object in one place, user mode by default
```

Red flags: SOQL, DML, or branching logic in the trigger body; a service that reads `Trigger.new` or `Trigger.oldMap` directly; the same query copied into several services and controllers; `@AuraEnabled` methods that implement business rules instead of calling the service.

Static analysis: PMD `AvoidLogicInTrigger`.

> 📖 Depth: [Trigger Architecture](salesforce/apex-triggers.md#trigger-architecture) · [Class Design](salesforce/apex.md#class-design)

### Choosing Flow vs Apex

Both can own record-triggered automation. Decide per requirement, write the decision down, and do not split one requirement across both.

| Factor | Prefer Flow | Prefer Apex |
|---|---|---|
| Declarative fit | Field updates, record creation, notifications, guided screens | Complex data structures, reusable libraries, custom handling of callout errors |
| Bulk volume | Moderate volumes, with data elements kept outside loops | High volumes, Batch or Queueable processing, fine-grained control of limits |
| Complexity | Few branches and simple formulas | Many branches, heavy transformations, savepoints and partial-success handling |
| Testability | Flow tests in Flow Builder, plus Apex tests that exercise the flow | Unit tests with bulk data, mocks, and asserts |
| Who maintains it | Admins who own the business process | Developers, through code review and CI |

Updates to the triggering record's own fields belong in a before-save flow or a before trigger; a before-save update avoids a second DML and the recursive save. Salesforce's [record-triggered automation decision guide](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered) compares the options in depth, and [Choosing the Flow Type](salesforce/flows.md#choosing-the-flow-type) covers the flow side.

### One automation owner per object and field

- Multiple Apex triggers on the same object and event run in no guaranteed order, while before-save flows, triggers, and after-save flows each run at a fixed step of the save ([Order of Execution](salesforce/apex-triggers.md#order-of-execution)). When several of them write the same field, the final value depends on that order, not on a design.
- Keep one trigger per object and name one owner for each field. Salesforce's architects advise against mixing Apex triggers and record-triggered flows as entry points on the same object.
- When several record-triggered flows on one object are unavoidable, give each an explicit Trigger Order (Spring '22+).
- Migrate Workflow Rules and Process Builder (end of support Dec 31, 2025). A workflow field update saves the record again and re-fires the update triggers, which surprises code written for a single pass.

### Configuration over code

- Keep values that differ between orgs, or that change without a release, out of Apex and flow logic: Custom Metadata Types for deployable settings and mappings (querying them does not count against the SOQL query limit), Custom Labels for user-facing text and translations, and Named Credentials with External Credentials for endpoints and authentication.
- Red flags: hard-coded record Ids, user or profile names, endpoint URLs, email addresses, and business thresholds ([Org-Agnostic Code](salesforce/platform.md#org-agnostic-code)).
- Do not overdo it: a setting that nobody will ever change is only indirection, so YAGNI applies here too.

> 📖 Depth: [Configuration Metadata](salesforce/metadata.md#configuration-metadata)

### Package boundaries and public APIs

- In a managed package, `global` is a permanent contract: once a version is released, global classes and method signatures cannot be removed or changed, only deprecated. Default to `public`, and make something `global` only when subscribers must call it (PMD `AvoidGlobalModifier`).
- `@NamespaceAccessible` shares `public` Apex with other packages in the same namespace without making it `global`.
- Unlocked and second-generation managed packages declare their dependencies in `sfdx-project.json`. Keep the graph one-directional (a base package never depends on a package built on top of it), and route cross-package calls through a small, documented service class so a package can change its internals without breaking its dependents.

> 📖 Depth: [Managed Packages](salesforce/apex.md#managed-packages)

### Event-driven integration

- Platform Events decouple publishers from subscribers (Apex triggers, flows, and external clients). Use Publish After Commit for events that describe committed data, so a rolled-back transaction does not announce work that never happened; Publish Immediately suits events that must be sent even if the transaction rolls back, such as error logging.
- Change Data Capture streams record changes to subscribers without custom triggers or polling.
- Subscribers must be idempotent: a trigger that throws `EventBus.RetryableException` receives the batch again, and replays redeliver events, so key each change on a business key or check the current state before writing.
- Platform event and Change Data Capture triggers run asynchronously, in batches, and by default as the Automated Process user (a platform event trigger can run as another user through `PlatformEventSubscriberConfig`), so never rely on the publisher's user or sharing context.

> 📖 Depth: [Platform Event and CDC Triggers](salesforce/apex-triggers.md#platform-event-and-cdc-triggers) · [Callouts & Integrations](salesforce/apex.md#callouts--integrations)

---

## Quick Reference Checklist

### 5-minute architecture check

```markdown
□ Is the dependency direction correct? (outer layers depend on inner layers)
□ Are there circular dependencies?
□ Is the core business logic decoupled from frameworks/UI/database?
□ Are the SOLID principles followed?
□ Are there obvious anti-patterns?
```

### Red flags (must fix)

```markdown
🔴 God Object - a single class over 1,000 lines
🔴 Circular dependency - A → B → C → A
🔴 The Domain layer contains framework dependencies
🔴 Hard-coded configuration and secrets
🔴 External service calls without an interface
🔴 Salesforce: business logic in a trigger body instead of a handler and service
🔴 Salesforce: a trigger, a flow, and a legacy workflow rule all updating the same field
```

### Yellow flags (should fix)

```markdown
🟡 Coupling between objects (CBO) > 10
🟡 More than 5 method parameters
🟡 Nesting deeper than 4 levels
🟡 Duplicated code blocks > 10 lines
🟡 Interfaces with only one implementation
```

---

## Recommended Tools

| Tool | Purpose | Languages |
|------|------|----------|
| **SonarQube** | Code quality, coupling analysis | Multi-language |
| **Madge** | Module dependency graph | JavaScript/TypeScript |
| **dependency-cruiser** | Dependency rules and cycles | JavaScript/TypeScript |
| **ESLint** | Code style, complexity checks | JavaScript/TypeScript |
| **import-linter** | Layer contracts | Python |
| **pydeps** | Module graph | Python |
| **Salesforce Code Analyzer** | Apex/LWC/Flow static analysis, run locally | Salesforce |
| **CodeScene** | Technical debt, hotspot analysis | Multi-language |

---

## References

- [Clean Architecture - Uncle Bob](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [SOLID Principles in Code Review - JetBrains](https://blog.jetbrains.com/upsource/2015/08/31/what-to-look-for-in-a-code-review-solid-principles-2/)
- [Software Architecture Anti-Patterns](https://medium.com/@christophnissle/anti-patterns-in-software-architecture-3c8970c9c4f5)
- [Coupling and Cohesion in System Design](https://www.geeksforgeeks.org/system-design/coupling-and-cohesion-in-system-design/)
- [Design Patterns - Refactoring Guru](https://refactoring.guru/design-patterns)
- [Record-Triggered Automation decision guide (Salesforce Architects)](https://architect.salesforce.com/docs/architect/decision-guides/guide/record-triggered)
- [Triggers and Order of Execution (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_triggers_order_of_execution.htm)
- [NamespaceAccessible Annotation (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_classes_annotation_NamespaceAccessible.htm)
- [Salesforce Code Analyzer (Salesforce Developers)](https://developer.salesforce.com/docs/platform/salesforce-code-analyzer/guide/code-analyzer.html)
