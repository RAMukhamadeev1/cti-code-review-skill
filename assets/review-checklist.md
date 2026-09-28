# Code Review Quick Checklist

Quick reference checklist for code reviews.

## Pre-Review (2 min)

- [ ] Read PR description and linked issue
- [ ] Check PR size (<400 lines ideal)
- [ ] Verify CI/CD status (tests passing?)
- [ ] Understand the business requirement

## Architecture & Design (5 min)

- [ ] Solution fits the problem
- [ ] Consistent with existing patterns
- [ ] No simpler approach exists
- [ ] Will it scale?
- [ ] Changes in right location

## Logic & Correctness (10 min)

- [ ] Edge cases handled
- [ ] Null/undefined checks present
- [ ] Off-by-one errors checked
- [ ] Race conditions considered
- [ ] Error handling complete
- [ ] Correct data types used

## Security (5 min)

- [ ] No hardcoded secrets
- [ ] Input validated/sanitized
- [ ] SQL injection prevented
- [ ] XSS prevented
- [ ] Authorization checks present
- [ ] Sensitive data protected

## Performance (3 min)

- [ ] No N+1 queries
- [ ] Expensive operations optimized
- [ ] Large lists paginated
- [ ] No memory leaks
- [ ] Caching considered where appropriate

## Salesforce (5 min)

For changes to Apex, LWC, Aura, Visualforce, flows, or metadata.

- [ ] Static review only: no deploys, Apex runs, or test runs against an org
- [ ] Bulk-safe at 200 records per trigger chunk
- [ ] No SOQL, DML, or callouts inside loops
- [ ] Sharing and CRUD/FLS correct for the file's `apiVersion`
- [ ] Tests cover bulk, negative, and `System.runAs` cases, with asserts
- [ ] New fields have FLS granted; permission sets follow least privilege
- [ ] No hard-coded record Ids or URLs
- [ ] Flows have entry conditions and fault paths

> See [Salesforce Platform Guide](../reference/salesforce/platform.md).

## Testing (5 min)

- [ ] Tests exist for new code
- [ ] Edge cases tested
- [ ] Error cases tested
- [ ] Tests are readable
- [ ] Tests are deterministic

## Code Quality (3 min)

- [ ] Clear variable/function names
- [ ] No code duplication
- [ ] Functions do one thing
- [ ] Complex code commented
- [ ] No magic numbers

## Documentation (2 min)

- [ ] Public APIs documented
- [ ] README updated if needed
- [ ] Breaking changes noted
- [ ] Complex logic explained

---

## Severity Labels

| Label | Meaning | Action |
|-------|---------|--------|
| 🔴 `[blocking]` | Must fix | Block merge |
| 🟡 `[important]` | Should fix | Discuss if disagree |
| 🟢 `[nit]` | Nice to have | Non-blocking |
| 💡 `[suggestion]` | Alternative | Consider |
| 📚 `[learning]` | Educational comment | No action needed |
| 🎉 `[praise]` | Good work | Celebrate! |

---

## Decision Matrix

| Situation | Decision |
|-----------|----------|
| Critical security issue | 🔴 Block, fix immediately |
| Breaking change without migration | 🔴 Block |
| Governor-limit failure at bulk volume | 🔴 Block |
| Missing error handling | 🟡 Should fix |
| No tests for new code | 🟡 Should fix |
| Style preference | 🟢 Non-blocking |
| Minor naming improvement | 🟢 Non-blocking |
| Clever but working code | 💡 Suggest simpler |

---

## Time Budget

This checklist is designed for a **lightweight quick review**. For comprehensive reviews covering architecture and performance analysis, use the full four-phase process in [SKILL.md](../SKILL.md) (19–36 minutes). Smaller PRs trend toward the lower end of each phase; larger PRs toward the upper end.

| PR Size | Quick Review | Full Review (4-phase) |
|---------|-------------|----------------------|
| < 100 lines | 10–15 min | ~19–28 min |
| 100–400 lines | 20–40 min | ~28–36 min |
| > 400 lines | Ask to split | Ask to split |

---

## Red Flags

Watch for these patterns:

- `// TODO` in production code
- `console.log` left in code
- Commented out code
- `any` type in TypeScript
- Empty catch blocks
- Un-awaited (floating) promises in JavaScript/TypeScript
- Magic numbers/strings
- Copy-pasted code blocks
- Missing null checks
- Hardcoded URLs/credentials
- SOQL/DML inside loops
- Unjustified `without sharing` / `WITH SYSTEM_MODE`
- Hard-coded record Ids
- Visualforce `escape="false"`
- `SeeAllData=true` in tests
