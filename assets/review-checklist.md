# Review Checklist

This is the line-by-line pass for any stack: step 4 of the [workflow](../SKILL.md#workflow). The stack guides add their own checklists; this one covers what every change needs.

## Correctness

- [ ] Edge cases: empty, null or undefined, zero, negative, duplicate, and very large inputs; time zones and DST.
- [ ] Off-by-one and boundary conditions in loops, slices, pagination, and date ranges.
- [ ] Shared state: races and check-then-act on shared data; idempotency for anything that can run twice (retries, re-delivered events, double submits).
- [ ] Changed contracts: every caller of a changed signature, return shape, or error type still works.

## Security → [Security Review](../reference/security-review-guide.md)

- [ ] Untrusted input reaches no query, command, template, path, or URL without parameters, encoding, or an allowlist.
- [ ] The server checks authorization for the specific record, not only the route (no IDOR).
- [ ] No secrets, tokens, or personal data appear in code, logs, error messages, or client responses.

## Performance → [Performance Review](../reference/performance-review-guide.md)

- [ ] No queries, callouts, or DML run inside loops (N+1).
- [ ] List endpoints and queries are bounded or paginated.
- [ ] Caches, listeners, timers, and subscriptions are bounded and cleaned up.

## Error handling → [Error Handling](../reference/cross-cutting/error-handling-principles.md)

- [ ] Each failure is handled once, where something can be done about it, with context. Nothing is swallowed.
- [ ] Network and I/O calls have timeouts and check the response status before using the body.

## Tests

- [ ] Changed behavior has tests that assert outcomes, including the failure path.
- [ ] Tests are deterministic: no real network, wall clock, or order dependence.

## Maintainability → [Universal Quality](../reference/code-quality-universal.md)

- [ ] New code reuses existing helpers instead of duplicating them. Grep for similar code before accepting a new utility.
- [ ] Names and comments describe what the code does now.
- [ ] Public API changes and breaking changes are documented.
