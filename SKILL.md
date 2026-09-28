---
name: code-review-skill
description: |
  Code review for JavaScript, TypeScript, Node.js, NestJS, Python, and Salesforce: Apex, Apex triggers,
  SOQL/SOSL, Lightning Web Components (LWC), Aura, Visualforce, Flows, and metadata (profiles, permission
  sets, sharing rules, objects/fields, validation rules, Named Credentials, Remote Sites, CSP, connected apps).
  Covers architecture, performance, security (injection, XSS, CRUD/FLS, sharing, secrets), governor limits
  and bulkification, error handling, async patterns, tests, and deployment impact, with severity labels.
  Salesforce reviews are static only: never deploy, run Apex or tests, or run data commands against an org.
  Use when: reviewing a pull request, PR, diff, or code changes; code review; Salesforce, SFDX, Apex, LWC,
  or Flow review; security audit; performance review; checking code quality; finding bugs; giving feedback
  on code; setting review standards; mentoring developers.
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git show *)
  - Bash(git status *)
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/pr-analyzer.py *)
---

# Code Review Skill

Transform code reviews from gatekeeping to knowledge sharing through constructive feedback, systematic analysis, and collaborative improvement.

## When to Use This Skill

- Reviewing pull requests and code changes
- Reviewing Salesforce changes: Apex, triggers, SOQL/SOSL, LWC, Aura, Visualforce, Flows, and metadata
- Establishing code review standards for teams
- Mentoring junior developers through reviews
- Conducting architecture reviews
- Creating review checklists and guidelines
- Improving team collaboration
- Reducing code review cycle time
- Maintaining code quality standards

## Core Principles

### 1. The Review Mindset

**Goals of Code Review:**
- Catch bugs and edge cases
- Ensure code maintainability
- Share knowledge across team
- Enforce coding standards
- Improve design and architecture
- Build team culture

**Not the Goals:**
- Show off knowledge
- Nitpick formatting (use linters)
- Block progress unnecessarily
- Rewrite to your preference

### 2. Effective Feedback

**Good Feedback is:**
- Specific and actionable
- Educational, not judgmental
- Focused on the code, not the person
- Balanced (praise good work too)
- Prioritized (critical vs nice-to-have)

```markdown
❌ Bad: "This is wrong."
✅ Good: "This could cause a race condition when multiple users
         access simultaneously. Consider using a mutex here."

❌ Bad: "Why didn't you use X pattern?"
✅ Good: "Have you considered the Repository pattern? It would
         make this easier to test. Here's an example: [link]"

❌ Bad: "Rename this variable."
✅ Good: "[nit] Consider `userCount` instead of `uc` for
         clarity. Not blocking if you prefer to keep it."
```

### 3. Review Scope

**What to Review:**
- Logic correctness and edge cases
- Security vulnerabilities
- Performance implications
- Test coverage and quality
- Error handling
- Documentation and comments
- API design and naming
- Architectural fit

**What Not to Review Manually:**
- Code formatting (use Prettier, Black, etc.)
- Import organization
- Linting violations
- Simple typos

## Review Process

### Phase 1: Context Gathering (2-3 minutes)

Before diving into code, understand:
1. Read PR description and linked issue
2. Check PR size (>400 lines? Ask to split)
3. Review CI/CD status (tests passing?)
4. Understand the business requirement
5. Note any relevant architectural decisions
6. Identify the stack from the changed files and load only the matching guides (see [Language-Specific Guides](#language-specific-guides)). For Salesforce changes, also follow the [Salesforce Review Path](#salesforce-review-path).

> For large diffs, pipe the diff through [`scripts/pr-analyzer.py`](scripts/pr-analyzer.py): `git diff main...HEAD | python3 ${CLAUDE_SKILL_DIR}/scripts/pr-analyzer.py`. It triages size and risk, recognizes Salesforce DX projects (Apex, LWC, Aura, Visualforce, Flows, metadata), and prints which guides to load.

### Phase 2: High-Level Review (5-10 minutes)

1. **Architecture & Design** - Does the solution fit the problem?
   - For significant changes, consult [Architecture Review Guide](reference/architecture-review-guide.md)
   - Check: SOLID principles, coupling/cohesion, anti-patterns
2. **Performance Assessment** - Are there performance concerns?
   - For performance-critical code, consult [Performance Review Guide](reference/performance-review-guide.md)
   - Check: Algorithm complexity, N+1 queries, memory usage, governor limits on Salesforce
3. **File Organization** - Are new files in the right places?
4. **Testing Strategy** - Are there tests covering edge cases?

### Phase 3: Line-by-Line Review (10-20 minutes)

For each file, check:
- **Logic & Correctness** - Edge cases, off-by-one, null checks, race conditions
- **Security** - Input validation, injection risks, XSS, sensitive data, sharing and CRUD/FLS on Salesforce
- **Performance** - N+1 queries, unnecessary loops, memory leaks, SOQL/DML inside loops
- **Maintainability** - Clear names, single responsibility, comments
- **Reuse** - Before accepting new code, search for existing utilities/helpers that could replace it. Check adjacent files and shared modules for similar patterns. See [Universal Quality Guide](reference/code-quality-universal.md) for anti-patterns like parameter sprawl, leaky abstractions, nested conditionals, stringly-typed code, TOCTOU, and no-op updates.

### Phase 4: Summary & Decision (2-3 minutes)

1. Summarize key concerns
2. Highlight what you liked
3. Make clear decision:
   - ✅ Approve
   - 💬 Comment (minor suggestions)
   - 🔄 Request Changes (must address)
4. Offer to pair if complex
5. For Salesforce findings, calibrate severity with the [Salesforce severity table](reference/salesforce/platform.md#severity-calibration) and show the limit math (for example "200 records → 200 queries → LimitException")

## Salesforce Review Path

Use this path when the repository has an `sfdx-project.json` or the diff touches `*.cls`, `*.trigger`, `*.apex`, `*.soql`, `*.page`, `*.component`, `*-meta.xml`, `lwc/**`, `aura/**`, `manifest/*.xml`, or `destructiveChanges*.xml` (the analyzer flags these too).

**Always load the [Salesforce Platform Guide](reference/salesforce/platform.md) first.** It defines governor limits, the transaction model, the security model and API-version rules (API 67.0 makes Apex secure by default), and the severity calibration the other Salesforce guides rely on. Then load the guide for each changed file type:

| Changed files | Load | Also load when |
|---|---|---|
| `classes/*.cls`, `*.apex` | [Apex](reference/salesforce/apex.md) | [SOQL & SOSL](reference/salesforce/soql-sosl.md) if the diff has `[SELECT`, `[FIND`, `Database.query`, or `Search.query`; [LWC-Apex contract](reference/salesforce/lwc.md#the-lwc-apex-contract) for `@AuraEnabled`; [Invocable Apex](reference/salesforce/flows.md#invocable-apex-contract) for `@InvocableMethod`; [Visualforce](reference/salesforce/visualforce.md) for page controllers |
| `triggers/*.trigger` | [Apex Triggers](reference/salesforce/apex-triggers.md) + [Apex](reference/salesforce/apex.md) | SOQL & SOSL as above |
| Apex test classes | [Apex: Testing](reference/salesforce/apex.md#testing) | [Testing Triggers](reference/salesforce/apex-triggers.md#testing-triggers) |
| `*.soql` | [SOQL & SOSL](reference/salesforce/soql-sosl.md) | |
| `lwc/<bundle>/*` | [LWC](reference/salesforce/lwc.md) + [JavaScript](reference/javascript.md) | [TypeScript](reference/typescript.md) for `.ts`; Apex + SOQL & SOSL for changed `@salesforce/apex/*` methods |
| `aura/<bundle>/*` | [Aura](reference/salesforce/aura.md) + [JavaScript](reference/javascript.md) | [LWC-Apex contract](reference/salesforce/lwc.md#the-lwc-apex-contract) for server actions |
| `*.page`, `*.component` | [Visualforce](reference/salesforce/visualforce.md) | [Apex](reference/salesforce/apex.md) for controllers and extensions |
| `*.flow-meta.xml` | [Flows](reference/salesforce/flows.md) | Apex for changed invocables; Apex Triggers if the object also has triggers |
| Permission sets and groups, profiles, sharing rules, objects and fields, validation rules, named and external credentials, remote sites, CSP trusted sites, connected apps, custom metadata, labels | [Metadata & Permissions](reference/salesforce/metadata.md) | |
| `sfdx-project.json`, `.forceignore`, `manifest/*.xml`, `destructiveChanges*.xml` | [Deployment Impact](reference/salesforce/metadata.md#deployment-impact) | |
| Only `*-meta.xml` apiVersion changes | [API Versions](reference/salesforce/platform.md#api-versions) | Apex when a class crosses API 67.0 |

Investigate the change the way a Salesforce reviewer would:

1. **Context.** Read `sfdx-project.json` (`sourceApiVersion`, `packageDirectories`, namespace) and the `<apiVersion>` in each changed file's `-meta.xml` (base and head if it changed). For classes, API 67.0+ means user mode and `with sharing` by default; triggers run in system mode at every API version. A namespace means a managed package, where released `global` members are permanent.
2. **Trace entry points.** For each changed Apex method, use Grep to find how a transaction reaches it: `@salesforce/apex/Class.method` in `lwc/**`, `controller="Class"` in Aura markup, `<actionName>Class</actionName>` in flows, `controller=`/`extensions=` in Visualforce, triggers that call the handler, `System.enqueueJob(new Class`, `Database.executeBatch(new Class`, `System.schedule(`, `@RestResource(`, and platform-event triggers. Note for each entry point whether it is sync or async, who the running user is (end user, guest, Automated Process, integration user), and how many records one invocation handles.
3. **Limits at bulk volume.** Walk each entry point with 200 records per trigger chunk (more for platform-event triggers and Batch scopes). Count SOQL, DML, callouts, and enqueues per chunk and per transaction, including downstream triggers, flows, and roll-ups.
4. **Data access.** For every SOQL, SOSL, and DML statement, determine the sharing context (keyword plus the class apiVersion default), the access mode (user mode, `stripInaccessible`, or a justified system-mode exception), whether client-supplied Ids or field names are trusted, and whether dynamic queries use bind variables.
5. **UI layer.** Check XSS escape hatches, Apex error handling in the client, cache refresh after writes, and `isExposed`/`targets` (Experience Cloud targets make the component's Apex reachable by guest users).
6. **Automation overlap.** For each object written or triggered, look for other triggers, record-triggered flows (`<object>X</object>` in `flows/*.flow-meta.xml`), and validation rules (`objects/X/validationRules/`); check order of execution, recursion, and duplicated logic.
7. **Tests.** For each changed class or trigger, expect bulk tests (201+ records), negative paths, `System.runAs` with a least-privilege user, `Test.startTest`/`Test.stopTest` around async work, callout mocks, and `Assert` calls with messages; no `SeeAllData=true`.
8. **Metadata and deployment.** Check FLS for new fields, permission over-grants, OWD and sharing changes, schema changes against existing data, validation rules against integrations, destructive changes, flow `<status>`, credential and endpoint metadata, `.forceignore` and manifest changes, and apiVersion bumps across 67.0.
9. **Optional local static analysis.** Only if it is already installed, run Salesforce Code Analyzer on the changed local paths with `--rule-selector Recommended`, `Security`, or an engine- or rule-scoped selector such as `flow` or `pmd:ApexSOQLInjection` (see [Tooling](reference/salesforce/platform.md#tooling)); for LWC, ESLint. Treat the output as input, not a verdict.
10. **Report.** Calibrate each finding with the [severity table](reference/salesforce/platform.md#severity-calibration) and state the math behind limit findings.

### Salesforce Safety: Static Review Only

Review Salesforce changes by reading files and diffs only. Never deploy to, execute in, or read data from an org:

- Do not run `sf project deploy …`, `sf project retrieve …`, `sf project delete …`, `sf apex run`, `sf apex run test`, `sf apex tail log`, any `sf data …`, `sf org …` (including `sf org display`, which prints access tokens), `sf package …`, their legacy `sfdx force:*` equivalents, or any command that targets an org (`--target-org`, `-o`, or a default org).
- Do not call Salesforce instance URLs (`*.my.salesforce.com`, `*.lightning.force.com`) with WebFetch, curl, or scripts, and do not execute anonymous Apex (for example from `scripts/apex/`).
- Allowed: reading files, read-only `git` commands, `scripts/pr-analyzer.py`, and local static analysis that does not contact an org (Salesforce Code Analyzer on local paths, ESLint, Prettier `--check`). Never select Code Analyzer's `apexguru` rules, the `all` selector, or a severity-only selector such as `2` or `High`: the ApexGuru engine calls an org and falls back to the CLI's default org when no `--target-org` is given. Do not install CLI plugins or packages without asking.
- If a conclusion needs org evidence (test results, coverage, query plans, data volumes, debug logs), ask the author to run it in their sandbox or CI and share the output.

## Review Techniques

### Technique 1: The Checklist Method

Use checklists for consistent reviews. See [Security Review Guide](reference/security-review-guide.md) for comprehensive security checklist.

### Technique 2: The Question Approach

Instead of stating problems, ask questions:

```markdown
❌ "This will fail if the list is empty."
✅ "What happens if `items` is an empty array?"

❌ "You need error handling here."
✅ "How should this behave if the API call fails?"
```

### Technique 3: Suggest, Don't Command

Use collaborative language:

```markdown
❌ "You must change this to use async/await"
✅ "Suggestion: async/await might make this more readable. What do you think?"

❌ "Extract this into a function"
✅ "This logic appears in 3 places. Would it make sense to extract it?"
```

### Technique 4: Differentiate Severity

Use labels to indicate priority:

- 🔴 `[blocking]` - Must fix before merge
- 🟡 `[important]` - Should fix, discuss if disagree
- 🟢 `[nit]` - Nice to have, not blocking
- 💡 `[suggestion]` - Alternative approach to consider
- 📚 `[learning]` - Educational comment, no action needed
- 🎉 `[praise]` - Good work, keep it up!

**Severity levels:** 🔴 / 🟡 / 🟢 are the three severity tiers used for every finding in this skill: 🔴 blocks the merge, 🟡 should be addressed, 🟢 is optional. The remaining markers (💡 / 📚 / 🎉) are non-blocking annotations. Salesforce findings have default tiers in the [Salesforce severity table](reference/salesforce/platform.md#severity-calibration).

## Language-Specific Guides

Load only the guides that match the code under review. JavaScript-family code shares one base guide: pair the [JavaScript Guide](reference/javascript.md) with the most specific guide below.

| Language/Framework | Reference File | Key Topics |
|-------------------|----------------|------------|
| **JavaScript** (base for TypeScript, Node.js, NestJS, LWC, Aura) | [JavaScript Guide](reference/javascript.md) | Strict equality, `??` vs `\|\|`, numbers and dates, mutation and copying, prototype pollution, Promises and cancellation, modules, DOM safety, testing, ESLint |
| **TypeScript** | [TypeScript Guide](reference/typescript.md) | Type safety, narrowing, generics, advanced types, strict mode, immutability, typed linting, type tests, path aliases, modern TS features (through 7.x) |
| **Node.js** | [Node.js Guide](reference/nodejs.md) | Event loop, worker threads, ESM/CommonJS and package exports, async errors, streams and backpressure, graceful shutdown, configuration, Express 4/5, Node security, supply chain |
| **NestJS** | [NestJS Guide](reference/nestjs.md) | Dependency injection, layered architecture, modules, guards/interceptors/pipes, DTO validation, exception filters, circular dependencies, testing, shutdown hooks |
| **Python** | [Python Guide](reference/python.md) | Type annotations, asyncio, exception handling, mutable defaults, pytest, performance, code style |

Common combinations: TypeScript on Node.js → JavaScript + TypeScript + Node.js guides; NestJS → NestJS + TypeScript guides (plus Node.js and JavaScript for runtime issues); LWC → LWC + JavaScript guides.

### Salesforce Guides

| Area | Reference File | Key Topics |
|------|----------------|------------|
| **Platform** (load first) | [Salesforce Platform Guide](reference/salesforce/platform.md) | Static review only, governor limits, transactions, security model and API 67.0 defaults, API versions, org-agnostic code, Code Analyzer, severity calibration |
| **Apex** | [Apex Guide](reference/salesforce/apex.md) | Bulkification, language pitfalls, class design, sharing and user mode, transactions, async Apex, callouts, tests, managed packages |
| **Apex Triggers** | [Apex Triggers Guide](reference/salesforce/apex-triggers.md) | One trigger per object, handlers, context variables, 200-record chunks, recursion control, order of execution, platform events and CDC |
| **SOQL & SOSL** | [SOQL & SOSL Guide](reference/salesforce/soql-sosl.md) | Injection, `WITH USER_MODE`, selectivity and large data volumes, query shape, result handling, pagination, SOSL |
| **Lightning Web Components** | [LWC Guide](reference/salesforce/lwc.md) | Reactivity, templates, lifecycle, LDS and wire, the Apex contract, Lightning Web Security, styling, performance, Jest |
| **Aura** | [Aura Guide](reference/salesforce/aura.md) | Maintain vs migrate, server actions, `$A.getCallback`, events, rendering, security |
| **Visualforce** | [Visualforce Guide](reference/salesforce/visualforce.md) | Output encoding, CSRF, controller security, open redirects, view state, remoting |
| **Flows** | [Flow Guide](reference/salesforce/flows.md) | Flow type, entry conditions, bulk-safe design, fault paths, run context, invocable Apex, activation |
| **Metadata & Permissions** | [Metadata Guide](reference/salesforce/metadata.md) | Permission sets and profiles, sharing and OWD, objects and fields, validation rules, credentials and endpoints, deployment impact |

## Cross-Cutting Guides

Language-agnostic patterns applicable to all code reviews:

| Topic | Reference File | Key Topics |
|-------|----------------|------------|
| **Architecture Review** | [Architecture Review Guide](reference/architecture-review-guide.md) | SOLID, anti-patterns, coupling/cohesion, dependency direction, Salesforce layering |
| **Performance Review** | [Performance Review Guide](reference/performance-review-guide.md) | Web Vitals, N+1, algorithm complexity, memory leaks, caching, governor limits |
| **Security Review** | [Security Review Guide](reference/security-review-guide.md) | SQLi, XSS, CSRF, SSRF, IDOR, command injection, JavaScript/Python/Apex examples, Salesforce platform security |
| **Universal Quality** | [Universal Quality Guide](reference/code-quality-universal.md) | Reuse audit, parameter sprawl, leaky abstractions, nested conditionals, stringly-typed code, TOCTOU, no-op updates, redundant state, Salesforce mapping |
| **Common Bugs** | [Common Bugs Checklist](reference/common-bugs-checklist.md) | JavaScript, TypeScript, Node.js, NestJS, Python, and Salesforce bug patterns |
| **SQL Injection Prevention** | [SQL Injection Guide](reference/cross-cutting/sql-injection-prevention.md) | Parameterized queries, ORM safety, Python, Node.js, Apex/SOQL, dynamic identifiers, detection |
| **XSS Prevention** | [XSS Prevention Guide](reference/cross-cutting/xss-prevention.md) | Output encoding, CSP, plain DOM, server-side templates, LWC/Aura/Visualforce, detection |
| **N+1 Queries** | [N+1 Queries Guide](reference/cross-cutting/n-plus-one-queries.md) | Eager loading, batch fetching, DataLoader, SQLAlchemy, Prisma, SOQL in loops, detection |
| **Error Handling** | [Error Handling Guide](reference/cross-cutting/error-handling-principles.md) | Fail fast, error hierarchy, Python, TypeScript, Apex, anti-patterns, logging |
| **Async & Concurrency** | [Concurrency Guide](reference/cross-cutting/async-concurrency-patterns.md) | Event loop, structured concurrency, cancellation, backpressure, bounded concurrency, async Apex |
| **Review Best Practices** | [Code Review Best Practices](reference/code-review-best-practices.md) | Communication, reviewer mindset, giving feedback, severity labels |

## Additional Resources

- [PR Review Template](assets/pr-review-template.md) - PR review comment template
- [Review Checklist](assets/review-checklist.md) - Quick reference checklist
