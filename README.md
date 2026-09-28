<div align="center">

<h1>&#128269; Code Review Skill</h1>

<p>
  <strong>A modular code review skill for Claude Code, focused on JavaScript/TypeScript, Node.js, NestJS, Python, and Salesforce</strong>
</p>

<p>
  <a href="https://github.com/awesome-skills/code-review-skill/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License: MIT"/>
  </a>
  <img src="https://img.shields.io/badge/Claude_Code-Skill-7c3aed?style=flat-square&logo=anthropic&logoColor=white" alt="Claude Code Skill"/>
  <img src="https://img.shields.io/badge/Total_Lines-16%2C000%2B-3b82f6?style=flat-square" alt="16,000+ lines"/>
  <img src="https://img.shields.io/badge/Guides-25-f59e0b?style=flat-square" alt="25 guides"/>
  <img src="https://img.shields.io/badge/Stack-JS%2FTS%20%C2%B7%20Node.js%20%C2%B7%20Python%20%C2%B7%20Salesforce-0ea5e9?style=flat-square" alt="Stack: JS/TS, Node.js, Python, Salesforce"/>
</p>

</div>

> Adapted from [awesome-skills/code-review-skill](https://github.com/awesome-skills/code-review-skill) (MIT) and refocused on JavaScript/TypeScript, Node.js, NestJS, Python, and Salesforce.

---

## What is this?

**Code Review Skill** is a skill for [Claude Code](https://claude.ai/code) that turns AI-assisted code review from vague suggestions into a **structured, consistent, and expert-level** process.

It covers **JavaScript, TypeScript, Node.js, NestJS, Python, and the Salesforce platform** (Apex, triggers, SOQL/SOSL, Lightning Web Components, Aura, Visualforce, Flows, and metadata) with over **16,000 lines** of review guidance, loaded progressively to keep the context window small.

---

## &#10024; Key Features

- **Progressive Disclosure** — The core skill is ~280 lines; guides (~140–1,290 lines each) load only when the code under review needs them.
- **Four-Phase Review Process** — Structured workflow from understanding scope to delivering clear feedback.
- **Salesforce Review Path** — Detects Salesforce DX changes, routes every file type to its guide, and investigates like a Salesforce reviewer: entry points, governor limits at 200-record bulk volume, sharing and CRUD/FLS per API version (including the API 67.0 secure-by-default change), automation overlap, tests, and deployment impact.
- **Static and Safe** — Salesforce reviews never deploy, run Apex or tests, or read org data; the skill pre-approves only read-only git commands and its own analyzer.
- **Shared Foundations** — General rules live once (JavaScript base guide, Salesforce platform guide, cross-cutting guides) and the specific guides link to them instead of repeating them.
- **Severity Labeling** — Every finding is categorized: `blocking` · `important` · `nit` · `suggestion` · `learning` · `praise`, with default severities for common Salesforce findings.
- **Security-First** — Dedicated security guidance per ecosystem: injection, XSS, SSRF, IDOR, secrets, CRUD/FLS and sharing.
- **Collaborative Tone** — Questions over commands, suggestions over mandates.
- **Automation Awareness** — Clearly separates what human review should catch from what linters and static analysis handle.

---

## &#127760; Supported Languages & Frameworks

<table>
  <thead>
    <tr>
      <th>Category</th>
      <th>Technology</th>
      <th>Guide</th>
      <th>Lines</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td rowspan="4"><strong>JavaScript / TypeScript</strong></td>
      <td>JavaScript ES2023+ (shared base for TypeScript, Node.js, NestJS, LWC, Aura)</td>
      <td><code>reference/javascript.md</code></td>
      <td>~1,290</td>
    </tr>
    <tr>
      <td>TypeScript (5.x to 7.x)</td>
      <td><code>reference/typescript.md</code></td>
      <td>~900</td>
    </tr>
    <tr>
      <td>Node.js 22/24 LTS and 26, Express 4/5</td>
      <td><code>reference/nodejs.md</code></td>
      <td>~1,110</td>
    </tr>
    <tr>
      <td>NestJS</td>
      <td><code>reference/nestjs.md</code></td>
      <td>~660</td>
    </tr>
    <tr>
      <td rowspan="1"><strong>Python</strong></td>
      <td>Python 3 (typing, asyncio, pytest)</td>
      <td><code>reference/python.md</code></td>
      <td>~1,080</td>
    </tr>
    <tr>
      <td rowspan="9"><strong>Salesforce</strong></td>
      <td>Platform foundations (load first): limits, security model, API versions, severity</td>
      <td><code>reference/salesforce/platform.md</code></td>
      <td>~660</td>
    </tr>
    <tr>
      <td>Apex classes, async Apex, callouts, tests</td>
      <td><code>reference/salesforce/apex.md</code></td>
      <td>~1,270</td>
    </tr>
    <tr>
      <td>Apex triggers and handlers</td>
      <td><code>reference/salesforce/apex-triggers.md</code></td>
      <td>~560</td>
    </tr>
    <tr>
      <td>SOQL &amp; SOSL</td>
      <td><code>reference/salesforce/soql-sosl.md</code></td>
      <td>~550</td>
    </tr>
    <tr>
      <td>Lightning Web Components (LWC)</td>
      <td><code>reference/salesforce/lwc.md</code></td>
      <td>~930</td>
    </tr>
    <tr>
      <td>Aura components</td>
      <td><code>reference/salesforce/aura.md</code></td>
      <td>~460</td>
    </tr>
    <tr>
      <td>Visualforce pages and controllers</td>
      <td><code>reference/salesforce/visualforce.md</code></td>
      <td>~500</td>
    </tr>
    <tr>
      <td>Flows</td>
      <td><code>reference/salesforce/flows.md</code></td>
      <td>~740</td>
    </tr>
    <tr>
      <td>Metadata &amp; permissions</td>
      <td><code>reference/salesforce/metadata.md</code></td>
      <td>~780</td>
    </tr>
    <tr>
      <td rowspan="11"><strong>Cross-Cutting</strong></td>
      <td>Architecture Design Review</td>
      <td><code>reference/architecture-review-guide.md</code></td>
      <td>~550</td>
    </tr>
    <tr>
      <td>Performance Review</td>
      <td><code>reference/performance-review-guide.md</code></td>
      <td>~940</td>
    </tr>
    <tr>
      <td>Universal Quality Anti-Patterns</td>
      <td><code>reference/code-quality-universal.md</code></td>
      <td>~510</td>
    </tr>
    <tr>
      <td>Security Review</td>
      <td><code>reference/security-review-guide.md</code></td>
      <td>~540</td>
    </tr>
    <tr>
      <td>Common Bugs Checklist</td>
      <td><code>reference/common-bugs-checklist.md</code></td>
      <td>~190</td>
    </tr>
    <tr>
      <td>Code Review Best Practices</td>
      <td><code>reference/code-review-best-practices.md</code></td>
      <td>~140</td>
    </tr>
    <tr>
      <td>N+1 Queries</td>
      <td><code>reference/cross-cutting/n-plus-one-queries.md</code></td>
      <td>~380</td>
    </tr>
    <tr>
      <td>Error Handling Principles</td>
      <td><code>reference/cross-cutting/error-handling-principles.md</code></td>
      <td>~520</td>
    </tr>
    <tr>
      <td>Async &amp; Concurrency Patterns</td>
      <td><code>reference/cross-cutting/async-concurrency-patterns.md</code></td>
      <td>~540</td>
    </tr>
    <tr>
      <td>SQL Injection Prevention</td>
      <td><code>reference/cross-cutting/sql-injection-prevention.md</code></td>
      <td>~270</td>
    </tr>
    <tr>
      <td>XSS Prevention</td>
      <td><code>reference/cross-cutting/xss-prevention.md</code></td>
      <td>~280</td>
    </tr>
  </tbody>
</table>

---

## &#128260; The Four-Phase Review Process

```
Phase 1 - Context Gathering
  Understand PR scope, linked issues, intent, and the stack
                    |
                    v
Phase 2 - High-Level Review
  Architecture - Performance impact - Test strategy
                    |
                    v
Phase 3 - Line-by-Line Analysis
  Logic - Security - Maintainability - Edge cases
                    |
                    v
Phase 4 - Summary & Decision
  Structured feedback - Approval status - Action items
```

Salesforce changes add the **Salesforce Review Path** from `SKILL.md`: load the platform guide, route each file type to its guide, then trace entry points, count governor limits at bulk volume, check sharing and CRUD/FLS per API version, look for automation overlap, review tests, and assess metadata and deployment impact.

---

## &#127991;&#65039; Severity Labels

| Label | Meaning |
|-------|---------|
| &#128308; `blocking` | Must fix before merge |
| &#128993; `important` | Should fix; discuss if you disagree |
| &#128994; `nit` | Nice to have, not blocking |
| &#128161; `suggestion` | Alternative approach to consider |
| &#128218; `learning` | Educational note, no action needed |
| &#127881; `praise` | Good work, keep it up |

Default severities for common Salesforce findings (SOQL in loops, missing CRUD/FLS, XSS escape hatches, recursion guards, permission over-grants, and more) are in [`reference/salesforce/platform.md`](reference/salesforce/platform.md#severity-calibration).

---

## &#128193; Repository Structure

```
code-review-skill/
|
+-- SKILL.md                              # Core skill - loaded on activation (~280 lines)
+-- README.md
+-- index.html                            # Landing page
|
+-- reference/                            # On-demand guides
|   +-- javascript.md                     # Shared JS base: semantics, async, modules, DOM, testing
|   +-- typescript.md                     # TypeScript type system, strict mode, typed linting
|   +-- nodejs.md                         # Node.js runtime, streams, shutdown, Express, security
|   +-- nestjs.md                         # NestJS DI, guards, interceptors, DTOs, lifecycle
|   +-- python.md                         # Python typing, asyncio, exceptions, pytest
|   +-- architecture-review-guide.md      # SOLID, anti-patterns, coupling/cohesion
|   +-- code-quality-universal.md         # Reuse audit, parameter sprawl, TOCTOU, no-op updates
|   +-- performance-review-guide.md       # Core Web Vitals, N+1, memory leaks, governor limits
|   +-- security-review-guide.md          # Security checklist (all stacks)
|   +-- common-bugs-checklist.md          # Stack-specific bug patterns
|   +-- code-review-best-practices.md     # Communication & process guidelines
|
+-- reference/salesforce/                 # Salesforce guides (platform.md first)
|   +-- platform.md                       # Limits, transactions, security model, API versions, severity
|   +-- apex.md                           # Bulkification, sharing/user mode, async, callouts, tests
|   +-- apex-triggers.md                  # Trigger architecture, chunks, recursion, order of execution
|   +-- soql-sosl.md                      # Injection, access mode, selectivity, pagination
|   +-- lwc.md                            # Reactivity, LDS/wire, Apex contract, LWS, Jest
|   +-- aura.md                           # Server actions, events, security, migration to LWC
|   +-- visualforce.md                    # Encoding, CSRF, controller security, view state
|   +-- flows.md                          # Flow types, entry conditions, bulk safety, fault paths
|   +-- metadata.md                       # Permissions, sharing, schema, credentials, deployment
|
+-- reference/cross-cutting/              # Language-agnostic cross-cutting patterns
|   +-- sql-injection-prevention.md       # Parameterized queries: Python, Node.js, Apex
|   +-- xss-prevention.md                 # Output encoding, CSP: DOM, templates, LWC/Aura/VF
|   +-- n-plus-one-queries.md             # SQLAlchemy, Prisma, DataLoader, SOQL in loops
|   +-- error-handling-principles.md      # Python, TypeScript, Apex
|   +-- async-concurrency-patterns.md     # Event loop, cancellation, backpressure, async Apex
|
+-- assets/
|   +-- review-checklist.md               # Quick reference checklist
|   +-- pr-review-template.md             # PR review comment template
|
+-- scripts/
    +-- pr-analyzer.py                    # PR triage; Salesforce-aware; suggests guides
    +-- test_pr_analyzer.py               # Analyzer tests: parsing, scoring, report, CLI
    +-- test_skill.py                     # SKILL.md frontmatter, links, analyzer contract
```

---

## &#128640; Installation

Replace `<repository-url>` (or `<owner>/<repo>`) with the location of this repository.

**Install with `npx skills` (Cursor, Claude Code, Codex, OpenCode, and other agents):**

```bash
npx skills add <owner>/<repo>
```

The skills CLI finds `SKILL.md` at the repo root. Do not nest this skill under `skills/`.

**Or clone into the Claude Code skills directory:**

```bash
# macOS / Linux
git clone <repository-url> ~/.claude/skills/code-review-skill

# Windows (PowerShell)
git clone <repository-url> "$env:USERPROFILE\.claude\skills\code-review-skill"
```

**Or link a local checkout:**

```bash
ln -s /path/to/this/repo ~/.claude/skills/code-review-skill
```

**Or add to an existing plugin:**

```bash
cp -r code-review-skill ~/.claude/plugins/your-plugin/skills/code-review/
```

---

## &#128161; Usage

Once installed, activate the skill in your Claude Code session:

```
Use code-review-skill to review this PR
```

Or create a custom slash command in `.claude/commands/`:

```markdown
<!-- .claude/commands/review.md -->
Use code-review-skill to perform a thorough review of the changes in this PR.
Focus on: security, performance, and maintainability.
```

**Example prompts:**

| Prompt | What happens |
|--------|-------------|
| `Review this Apex trigger` | Loads `salesforce/platform.md` + `apex-triggers.md` + `apex.md` - one trigger per object, 200-record chunks, recursion, order of execution |
| `Review this Lightning Web Component` | Loads `salesforce/lwc.md` + `javascript.md` - reactivity, LDS/wire, the Apex contract, XSS, cleanup |
| `Security review of this Visualforce page` | Loads `salesforce/visualforce.md` + `platform.md` - encoding, CSRF, controller sharing, open redirects |
| `Review this flow` | Loads `salesforce/flows.md` - entry conditions, loops with data elements, fault paths, run context |
| `Review this Node.js service` | Loads `javascript.md` + `nodejs.md` - event loop, async errors, streams, graceful shutdown, Express |
| `Review this NestJS module` | Loads `nestjs.md` + `typescript.md` - DI, guards, DTO validation, lifecycle |
| `Review this Python module` | Loads `python.md` - typing, asyncio, exceptions, pytest |
| `Architecture review` | Loads `architecture-review-guide.md` - SOLID, anti-patterns, coupling, Salesforce layering |
| `Performance review` | Loads `performance-review-guide.md` - Web Vitals, N+1, complexity, governor limits |

For large diffs, the bundled analyzer triages size and risk and prints which guides to load:

```bash
git diff main...HEAD | python3 scripts/pr-analyzer.py
```

---

## &#128300; Highlights

<details>
<summary><strong>Salesforce</strong></summary>

- **Static review only**: never deploy, run Apex or tests, or query an org; ask the author or CI for org evidence
- **Platform foundations**: governor limits per transaction, records per entry point, order of execution, API-version rules
- **API 67.0 (Summer '26)**: user mode and `with sharing` by default, `WITH SECURITY_ENFORCED` removed; review each file against its own `apiVersion`
- **Apex**: bulkification, sharing and user-mode data access, partial success, async Apex with Finalizers, Named Credential callouts, meaningful tests
- **Triggers**: one trigger per object, logic in handlers, recursion control that survives 200-record chunks
- **SOQL/SOSL**: injection, `WITH USER_MODE`, selectivity and large data volumes, pagination
- **LWC & Aura**: the Apex contract (`cacheable`, `AuraHandledException`), Lightning Web Security, XSS escape hatches, lifecycle cleanup
- **Visualforce**: context-specific encoding, CSRF on page load, open redirects, view state
- **Flows & metadata**: entry conditions, fault paths, run context, permission sets and FLS, sharing, credentials, destructive changes

</details>

<details>
<summary><strong>JavaScript &amp; TypeScript</strong></summary>

- Strict equality, `??` vs `||`, number and date pitfalls, mutation vs copying, prototype pollution
- Promises: floating promises, combinators, cancellation with `AbortSignal`, stale-response races
- Modules, DOM safety, listener and timer cleanup, testing with Vitest/Jest/`node:test`
- TypeScript: `unknown` over `any`, narrowing, generics, strict mode, typed ESLint rules, modern TS features through 7.x

</details>

<details>
<summary><strong>Node.js &amp; NestJS</strong></summary>

- Event loop and worker threads, unhandled rejections, streams with `pipeline()` and backpressure
- Graceful shutdown, configuration validation, Express 4 vs 5 async errors, server timeouts
- Node security: path traversal, body limits, constant-time comparison, supply chain
- NestJS: layered architecture, DTO validation (`@ValidateNested` + `@Type`), guards vs interceptors, shutdown hooks

</details>

<details>
<summary><strong>Python</strong></summary>

- Type annotations, generics, `Protocol`, `TypedDict`
- asyncio: TaskGroup, cancellation, timeouts, semaphores
- Exceptions: specific catches, `raise ... from`, exception groups
- Pitfalls: mutable defaults, closures in loops, `is` vs `==`; pytest fixtures and mocks

</details>

---

## &#129309; Contributing

Contributions are welcome. Keep new content consistent with the existing guides:

- Follow the guide structure: `##` topic, `###` rule, a short lead-in, then a `❌` / `✅` code block; end with a Review Checklist and References.
- Put language-agnostic rules in `reference/cross-cutting/` (or the Salesforce platform guide) and link to them instead of repeating them.
- Register new guides in `SKILL.md`, this README, and `index.html`.
- English only.
- Run the tests (standard library only): `python3 -m unittest discover -s scripts`. They also check every link and anchor, and that `SKILL.md` and the analyzer agree.
- Keep `scripts/pr-analyzer.py` at 100% line and branch coverage: `python3 -m coverage run -m unittest discover -s scripts && python3 -m coverage report` (needs `pip install coverage`; settings in `.coveragerc`).

**Ideas:**
- Deeper guides for the supported stacks
- Additional checklists and templates
- Improvements to `scripts/pr-analyzer.py`

---

## &#128196; License

MIT &copy; [awesome-skills](https://github.com/awesome-skills)

---

<div align="center">
  Made with &#10084;&#65039; for developers who care about code quality
</div>
