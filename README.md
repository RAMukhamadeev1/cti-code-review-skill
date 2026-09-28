<div align="center">

<h1>&#128269; Code Review Skill</h1>

<p>
  <strong>A modular code review skill for Claude Code, focused on JavaScript/TypeScript, Node.js, NestJS, Python, and Salesforce</strong>
</p>

<p>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License: MIT"/>
  </a>
  <img src="https://img.shields.io/badge/Claude_Code-Skill-7c3aed?style=flat-square&logo=anthropic&logoColor=white" alt="Claude Code Skill"/>
  <img src="https://img.shields.io/badge/Guides-25-f59e0b?style=flat-square" alt="25 guides"/>
  <img src="https://img.shields.io/badge/Stack-JS%2FTS%20%C2%B7%20Node.js%20%C2%B7%20Python%20%C2%B7%20Salesforce-0ea5e9?style=flat-square" alt="Stack: JS/TS, Node.js, Python, Salesforce"/>
</p>

</div>

> Adapted from [awesome-skills/code-review-skill](https://github.com/awesome-skills/code-review-skill) (MIT) and refocused on JavaScript/TypeScript, Node.js, NestJS, Python, and Salesforce.

---

## What is this?

**Code Review Skill** is a skill for [Claude Code](https://claude.ai/code). It gives Claude a fixed procedure for reviewing code:

1. Resolve exactly which change to review.
2. Load only the guides that match the stack.
3. Verify every finding against the code before reporting it.
4. Report in a fixed format: a verdict, the scope, severity-ranked findings with `file:line`, impact, and fix, and open questions.

It covers **JavaScript, TypeScript, Node.js, NestJS, Python, and the Salesforce platform**: Apex, triggers, SOQL/SOSL, Lightning Web Components, Aura, Visualforce, Flows, and metadata.

---

## &#10024; Key Features

- **Checklist-first loading.** Only SKILL.md (~160 lines) loads when the skill activates. Each guide opens with a review checklist that doubles as its table of contents. Claude reads the checklists first and opens only the sections the diff touches. For example, an Apex trigger review starts from about 3.7k tokens of checklists, instead of about 49k tokens for the full guides.
- **An agent's procedure, not a human's.** A six-step workflow: resolve target → triage → load guides → review → verify → report. There are no time budgets, praise quotas, or "ask to split" steps.
- **Fixed output format.** Every review has a verdict, a scope line, numbered findings (severity, `path:line`, the defect stated as fact, impact, fix), and a Questions section for what a static review can't settle.
- **False-positive control.** Every finding is verified before it's reported. Older problems are tagged "(pre-existing)". Anything a linter or compiler already enforces is skipped, and every absolute rule in the guides lists its legitimate exceptions.
- **Salesforce Review Path.** It detects Salesforce DX changes and routes each file type to its guide. It also traces entry points, counts governor limits at 200-record bulk volume, checks sharing and CRUD/FLS per API version, and looks for automation overlap. That includes the API 67.0 defaults, under which trigger bodies run in user mode too.
- **Static and safe.** The skill pre-approves only read-only `git` and `gh pr` commands and its own analyzer, with no WebFetch. Reviewed code, comments, and PR text are treated as data, never as instructions. Salesforce reviews never deploy, run Apex or tests, or read org data.
- **Robust analyzer.** `scripts/pr-analyzer.py` still reads diffs produced under `color.ui=always`, `diff.mnemonicPrefix`, or `diff.noprefix`. It ignores lockfiles, snapshots, and minified files when it sizes a change or looks for missing tests. It also flags Salesforce risks such as renames, FlowDefinitions, and apiVersion bumps on classes and triggers.

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
      <td>JavaScript (shared base for TypeScript, Node.js, NestJS, LWC, Aura)</td>
      <td><code>reference/javascript.md</code></td>
      <td>~500</td>
    </tr>
    <tr>
      <td>TypeScript (5.x to 7.0)</td>
      <td><code>reference/typescript.md</code></td>
      <td>~270</td>
    </tr>
    <tr>
      <td>Node.js 22/24 LTS and 26, Express 4/5</td>
      <td><code>reference/nodejs.md</code></td>
      <td>~520</td>
    </tr>
    <tr>
      <td>NestJS</td>
      <td><code>reference/nestjs.md</code></td>
      <td>~260</td>
    </tr>
    <tr>
      <td rowspan="1"><strong>Python</strong></td>
      <td>Python 3.11–3.14 (typing, asyncio, pytest)</td>
      <td><code>reference/python.md</code></td>
      <td>~160</td>
    </tr>
    <tr>
      <td rowspan="9"><strong>Salesforce</strong></td>
      <td>Platform foundations (load first): limits, security model, API versions, severity</td>
      <td><code>reference/salesforce/platform.md</code></td>
      <td>~510</td>
    </tr>
    <tr>
      <td>Apex classes, async Apex, callouts, tests</td>
      <td><code>reference/salesforce/apex.md</code></td>
      <td>~550</td>
    </tr>
    <tr>
      <td>Apex triggers and handlers</td>
      <td><code>reference/salesforce/apex-triggers.md</code></td>
      <td>~470</td>
    </tr>
    <tr>
      <td>SOQL &amp; SOSL</td>
      <td><code>reference/salesforce/soql-sosl.md</code></td>
      <td>~510</td>
    </tr>
    <tr>
      <td>Lightning Web Components (LWC)</td>
      <td><code>reference/salesforce/lwc.md</code></td>
      <td>~700</td>
    </tr>
    <tr>
      <td>Aura components</td>
      <td><code>reference/salesforce/aura.md</code></td>
      <td>~380</td>
    </tr>
    <tr>
      <td>Visualforce pages and controllers</td>
      <td><code>reference/salesforce/visualforce.md</code></td>
      <td>~440</td>
    </tr>
    <tr>
      <td>Flows</td>
      <td><code>reference/salesforce/flows.md</code></td>
      <td>~510</td>
    </tr>
    <tr>
      <td>Metadata &amp; permissions</td>
      <td><code>reference/salesforce/metadata.md</code></td>
      <td>~520</td>
    </tr>
    <tr>
      <td rowspan="11"><strong>Cross-Cutting</strong></td>
      <td>Architecture Design Review</td>
      <td><code>reference/architecture-review-guide.md</code></td>
      <td>~140</td>
    </tr>
    <tr>
      <td>Performance Review</td>
      <td><code>reference/performance-review-guide.md</code></td>
      <td>~250</td>
    </tr>
    <tr>
      <td>Universal Quality Anti-Patterns</td>
      <td><code>reference/code-quality-universal.md</code></td>
      <td>~170</td>
    </tr>
    <tr>
      <td>Security Review</td>
      <td><code>reference/security-review-guide.md</code></td>
      <td>~270</td>
    </tr>
    <tr>
      <td>Common Bugs Checklist</td>
      <td><code>reference/common-bugs-checklist.md</code></td>
      <td>~180</td>
    </tr>
    <tr>
      <td>Code Review Best Practices (for human reviewers and teams)</td>
      <td><code>reference/code-review-best-practices.md</code></td>
      <td>~120</td>
    </tr>
    <tr>
      <td>N+1 Queries</td>
      <td><code>reference/cross-cutting/n-plus-one-queries.md</code></td>
      <td>~170</td>
    </tr>
    <tr>
      <td>Error Handling Principles</td>
      <td><code>reference/cross-cutting/error-handling-principles.md</code></td>
      <td>~220</td>
    </tr>
    <tr>
      <td>Async &amp; Concurrency Patterns</td>
      <td><code>reference/cross-cutting/async-concurrency-patterns.md</code></td>
      <td>~340</td>
    </tr>
    <tr>
      <td>SQL Injection Prevention</td>
      <td><code>reference/cross-cutting/sql-injection-prevention.md</code></td>
      <td>~140</td>
    </tr>
    <tr>
      <td>XSS Prevention</td>
      <td><code>reference/cross-cutting/xss-prevention.md</code></td>
      <td>~170</td>
    </tr>
  </tbody>
</table>

---

## &#128260; The Review Workflow

```
1. Resolve the target      PR (gh pr view/diff), branch, or uncommitted work
          |
          v
2. Triage                  large diffs: pr-analyzer.py -> risk factors + guides to load
          |
          v
3. Load guides             each guide's Review Checklist first, then only matching sections
          |
          v
4. Review                  correctness, security, performance and limits, errors, tests, reuse
          |
          v
5. Verify                  every candidate finding against the code; unconfirmed -> Questions
          |
          v
6. Report                  verdict · scope · findings (severity, file:line, impact, fix) · questions
```

Salesforce changes add the **Salesforce Review Path** from `SKILL.md`:

- load the platform guide first and route each file type to its guide;
- trace entry points and count governor limits at bulk volume;
- check sharing and CRUD/FLS per API version;
- look for automation overlap;
- review tests, metadata, and deployment impact.

---

## &#127991;&#65039; Severity Labels

| Label | Meaning |
|-------|---------|
| &#128308; `blocking` | Must fix before merge: wrong results, data loss, a security hole, or a limit breach at realistic volume |
| &#128993; `important` | Should fix; discuss if you disagree |
| &#128994; `nit` | Optional polish; at most five per review |
| &#128161; `suggestion` | An alternative worth considering, not a defect |

Verdict: any blocking finding → Request changes; otherwise any important finding → Comment; otherwise Approve. Default severities for common Salesforce findings (SOQL in loops, missing CRUD/FLS, XSS escape hatches, recursion guards, permission over-grants, and more) are in [`reference/salesforce/platform.md`](reference/salesforce/platform.md#severity-calibration).

---

## &#128193; Repository Structure

```
code-review-skill/
|
+-- SKILL.md                              # Core skill - loaded on activation (~160 lines)
+-- README.md
+-- LICENSE                               # MIT (upstream notice kept)
+-- index.html                            # Landing page
|
+-- reference/                            # On-demand guides, each opening with its Review Checklist
|   +-- javascript.md                     # Shared JS base: semantics, async, modules, DOM, testing
|   +-- typescript.md                     # TypeScript type system, strict mode, typed linting
|   +-- nodejs.md                         # Node.js runtime, streams, shutdown, Express, security
|   +-- nestjs.md                         # NestJS DI, guards, interceptors, DTOs, lifecycle
|   +-- python.md                         # Python 3.11-3.14: flag/don't-flag table, asyncio, pitfalls
|   +-- architecture-review-guide.md      # Design fit, coupling, dependency direction, Salesforce layering
|   +-- code-quality-universal.md         # Reuse audit, parameter sprawl, TOCTOU, no-op updates
|   +-- performance-review-guide.md       # Core Web Vitals, queries, memory, caching, governor limits
|   +-- security-review-guide.md          # Security index for all stacks
|   +-- common-bugs-checklist.md          # Stack-specific bug patterns
|   +-- code-review-best-practices.md     # For human reviewers and teams: communication, process
|
+-- reference/salesforce/                 # Salesforce guides (platform.md first)
|   +-- platform.md                       # Limits, transactions, security model, API versions, severity
|   +-- apex.md                           # Bulkification, sharing/user mode, async, callouts, tests
|   +-- apex-triggers.md                  # Trigger architecture, chunks, recursion, events and CDC
|   +-- soql-sosl.md                      # Injection, access mode, selectivity, pagination
|   +-- lwc.md                            # Reactivity, LDS/wire, Apex contract, LWS, Jest
|   +-- aura.md                           # Server actions, events, security, migration to LWC
|   +-- visualforce.md                    # Encoding, CSRF, controller security, view state
|   +-- flows.md                          # Flow types, entry conditions, bulk safety, fault paths
|   +-- metadata.md                       # Permissions, sharing, schema, credentials, deployment
|
+-- reference/cross-cutting/              # Language-agnostic cross-cutting patterns
|   +-- sql-injection-prevention.md       # Parameterized queries and identifiers: Python, Node.js
|   +-- xss-prevention.md                 # Output encoding, CSP, framework escape hatches
|   +-- n-plus-one-queries.md             # SQLAlchemy, Prisma, TypeORM, DataLoader, SOQL in loops
|   +-- error-handling-principles.md      # Python, TypeScript, Apex
|   +-- async-concurrency-patterns.md     # Event loop, cancellation, backpressure, async Apex
|
+-- assets/
|   +-- review-checklist.md               # The line-by-line pass for any stack
|   +-- pr-review-template.md             # A complete example review in the output format
|
+-- scripts/
    +-- pr-analyzer.py                    # PR triage; Salesforce-aware; suggests guides
    +-- test_pr_analyzer.py               # Analyzer tests: parsing, git configs, scoring, report, CLI
    +-- test_skill.py                     # SKILL.md contract, links, license, analyzer agreement
    +-- test_guides.py                    # Guide structure, corrected facts, runnable examples
```

---

## &#128640; Installation

**Install with `npx skills` (Cursor, Claude Code, Codex, OpenCode, and other agents):**

```bash
npx skills add RAMukhamadeev1/cti-code-review-skill
```

The skills CLI finds `SKILL.md` at the repo root. Do not nest this skill under `skills/`.

**Or clone into the Claude Code skills directory:**

```bash
# macOS / Linux
git clone https://github.com/RAMukhamadeev1/cti-code-review-skill.git ~/.claude/skills/code-review-skill

# Windows (PowerShell)
git clone https://github.com/RAMukhamadeev1/cti-code-review-skill.git "$env:USERPROFILE\.claude\skills\code-review-skill"
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

Or run it as `/code-review-skill`, optionally with a target such as a PR number or a branch.

**Example prompts:**

| Prompt | What happens |
|--------|-------------|
| `Use code-review-skill to review PR 42` | `gh pr view` / `gh pr diff`, then the matching guides and the output format |
| `Review my uncommitted changes` | `git diff HEAD` plus untracked files from `git status --porcelain` |
| `Review this Apex trigger` | platform.md + apex-triggers.md + apex.md checklists: one trigger per object, 200-record chunks, recursion, user mode at API 67.0+ |
| `Review this Lightning Web Component` | lwc.md + javascript.md: reactivity, LDS/wire, the Apex contract, XSS, cleanup |
| `Security review of this Visualforce page` | visualforce.md + platform.md: encoding, CSRF, controller sharing, open redirects |
| `Review this flow` | flows.md: entry conditions, loops with data elements, fault paths, run context |
| `Review this Node.js service` | javascript.md + nodejs.md: event loop, async errors, streams, graceful shutdown, Express |
| `Review this NestJS module` | nestjs.md + typescript.md + javascript.md: DI, guards, DTO validation, lifecycle |
| `Review this Python module` | python.md: version-aware flag/don't-flag rules, asyncio, pitfalls |

For large diffs, the bundled analyzer triages size and risk and prints which guides to load:

```bash
git diff --no-color --default-prefix main...HEAD | python3 scripts/pr-analyzer.py
```

---

## &#128300; Highlights

<details>
<summary><strong>Salesforce</strong></summary>

- **Static review only**: never deploy, run Apex or tests, or query an org; ask the author or CI for org evidence
- **Platform foundations**: governor limits per transaction, records per entry point, order of execution, API-version rules
- **API 67.0 (Summer '26)**: user mode by default, also for SOQL/DML in trigger bodies; `with sharing` by default unless a parent class declares a mode; `WITH SECURITY_ENFORCED` removed; review each file against its own `apiVersion`
- **Apex**: bulkification, sharing and user-mode data access, partial success, async Apex, Named Credential callouts, meaningful tests
- **Triggers**: one trigger per object, logic in handlers, recursion control that survives 200-record chunks, one enqueue per async transaction
- **SOQL/SOSL**: injection, access mode, selectivity and large data volumes, pagination
- **LWC & Aura**: the Apex contract (`cacheable`, `AuraHandledException`), refresh after writes, Lightning Web Security, XSS escape hatches, guest reachability
- **Visualforce**: context-specific encoding, CSRF on page load, open redirects, view state
- **Flows & metadata**: entry conditions, fault paths, run context (`UserMode` at API 68.0), FlowDefinition pitfalls, FLS, sharing, credentials, destructive changes

</details>

<details>
<summary><strong>JavaScript &amp; TypeScript</strong></summary>

- Strict equality, `??` vs `||`, number and date pitfalls, mutation vs copying, prototype pollution
- Promises: floating promises, combinators, cancellation with `AbortSignal`, stale-response races
- Modules, DOM safety, listener and timer cleanup, testing with Vitest/Jest/`node:test`
- TypeScript: `unknown` over `any`, narrowing, strict mode, typed ESLint rules, TS 6/7 upgrade notes

</details>

<details>
<summary><strong>Node.js &amp; NestJS</strong></summary>

- Event loop and worker threads, unhandled rejections, streams with `pipeline()` and backpressure
- Graceful shutdown, configuration validation, Express 4 vs 5 async errors, server timeouts
- Node security: path traversal, open redirects, body limits, constant-time comparison, supply chain
- NestJS: DTO validation (`@ValidateNested` + `@Type`), guards vs interceptors, exception filters, shutdown hooks

</details>

<details>
<summary><strong>Python</strong></summary>

- A 3.11–3.14 table of what to flag and what not to flag
- asyncio: TaskGroup and `except*`, `gather` semantics, cancellation, timeouts, one session per task
- Exceptions: specific catches, `raise ... from`, picklable exception classes
- About 30 one-line pitfalls with the Ruff rule that catches each

</details>

---

## &#129309; Contributing

Contributions are welcome. Keep new content consistent with the existing guides:

- Start every guide with its title, a short scope line, and `## Review Checklist` within the first 40 lines. Group the checklist items under `### Group → [Section](#anchor)` links so the checklist doubles as the table of contents.
- Then write `##` topics and `###` rules: a short lead-in, then a `❌` / `✅` code block. Every rule states its legitimate exceptions.
- Keep each guide under 45,000 characters and its `## References` list to at most five links.
- Use only the four severity labels. Salesforce defaults live in the platform guide's severity table.
- Give each topic one owner file and link to it from the others instead of repeating it. Express searches as Grep patterns, not shell pipelines.
- Register new guides in `SKILL.md`, this README, and `index.html`.
- Write in English.
- Run the tests (standard library only): `python3 -m unittest discover -s scripts`. They check every link and anchor, the SKILL.md contract, the guide structure, corrected facts, and the runnable examples (the Node.js example test needs `node`). They also check that `SKILL.md` and the analyzer agree.
- Keep `scripts/pr-analyzer.py` at 100% line and branch coverage: `python3 -m coverage run -m unittest discover -s scripts && python3 -m coverage report` (needs `pip install coverage`; settings in `.coveragerc`).

---

## &#128196; License

MIT. See [LICENSE](LICENSE).

- Copyright (c) 2025 [awesome-skills](https://github.com/awesome-skills), the original project
- Copyright (c) 2026 Ruslan Mukhamadeev, this adaptation

---

<div align="center">
  Made with &#10084;&#65039; for developers who care about code quality
</div>
