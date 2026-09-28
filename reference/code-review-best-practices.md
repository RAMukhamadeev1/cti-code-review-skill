# Code Review Best Practices

For human reviewers and teams: review standards, mentoring, communication, and team process. An AI review does not need this guide; its process and output format are in [SKILL.md](../SKILL.md).

## Review Mindset

**Goals of code review:**

- Catch bugs and edge cases before production
- Keep the code maintainable and readable
- Share knowledge across the team, and mentor newer developers
- Apply the team's coding standards consistently
- Improve design and architecture decisions, and record them in the discussion
- Build team culture and trust

**Not the goals:**

- Showing off knowledge
- Nitpicking formatting (linters and formatters do that)
- Blocking progress without a concrete reason
- Rewriting the code to your personal preference

## Giving Feedback

Good feedback is:

- Specific and actionable: point at the line, name the input or state that breaks it, and suggest a fix
- Educational, not judgmental, and about the code, not the person
- Balanced: say what works, specifically, rather than by formula
- Prioritized with a severity label, so the author knows what blocks the merge

```markdown
❌ Bad: "This is wrong."
✅ Good: "Two concurrent requests can both pass the balance check on line 42 and both
         debit the account. A conditional UPDATE (`... WHERE balance >= :amount`)
         makes the check and the write one atomic step."

❌ Bad: "Why didn't you use X pattern?"
✅ Good: "This query is built inline in three handlers. A small repository function
         would let the tests stub it; `OrderRepository` in this codebase is an example."

❌ Bad: "Rename this variable."
✅ Good: "🟢 [nit] Consider `userCount` instead of `uc` for clarity. Not blocking
         if you prefer to keep it."
```

### Ask when you're unsure, state what you've verified

A question invites the author to explain context you may lack. It is the right tool when you are genuinely unsure:

```markdown
❌ "You need error handling here."
✅ "How should this behave if the API call fails?"

❌ "This will fail if the list is empty."   (when you haven't checked)
✅ "What happens if `items` is an empty array?"
```

When you have verified a defect, a question hides it. State it plainly, with the evidence and a fix: "`items[0]` throws when the search returns no results; return early when `items` is empty."

### Suggest, don't command

For preferences and alternative designs, use collaborative language and label the comment as a suggestion:

```markdown
❌ "You must change this to use async/await"
✅ "💡 [suggestion] async/await might make this more readable. What do you think?"

❌ "Extract this into a function"
✅ "This logic appears in 3 places. Would it make sense to extract it?"
```

Keep 🔴 `[blocking]` comments direct: say what breaks and what would fix it. Collaborative phrasing is for choices, not for defects.

## Severity Labels

Start every comment with a tier:

| Label | Meaning | Typical findings |
|---|---|---|
| 🔴 `[blocking]` | Must fix before merge | Exploitable security vulnerabilities; data loss or corruption; breaking changes without a migration; failures at realistic volume, including Salesforce governor-limit breaches; swallowed errors that hide data loss |
| 🟡 `[important]` | Should fix; discuss if you disagree | Missing error handling; no tests for new behavior; performance that degrades as data grows; duplicated logic that must stay in sync; names that mislead about behavior |
| 🟢 `[nit]` | Optional | Naming and style the linter doesn't cover; minor optimizations; extra test cases; documentation touch-ups |
| 💡 `[suggestion]` | An alternative worth considering | A simpler design; a library the codebase already uses |

Salesforce findings take their default tier from [Severity Calibration](salesforce/platform.md#severity-calibration). Mark a comment that needs no action "FYI, no action needed", so the author doesn't treat it as a request.

## Team Process

### Review timing

Suggested team norms:

| Trigger | Action |
|---|---|
| PR opened | First review within one business day, ideally the same day |
| Changes requested | Re-review promptly once the author responds |
| Blocking issue found | Tell the author right away instead of waiting to finish the review |

### Review depth

- **Skim:** the description, linked issue, CI status, and the list of changed files; decide whether a deeper review is needed.
- **Standard:** a full walkthrough of the logic, tests, and security-sensitive code.
- **Deep:** architecture, performance, a security audit, and edge-case exploration, for risky or cross-cutting changes.

Scale the depth with risk, not only with size. When a PR is too large to review well, ask the author to split it along reviewable boundaries (a refactor separate from the behavior change), or walk through it together.

### Handling disagreements

1. **Seek to understand**: ask clarifying questions
2. **Acknowledge valid points**: show you've considered their perspective
3. **Provide data**: benchmarks, documentation, or examples
4. **Escalate if needed**: involve a senior developer or an architect
5. **Know when to let go**: not every hill is worth dying on

### Anti-patterns

- **Reviewer:** rubber stamping (approving without reviewing); bike-shedding (debating trivial details at length); scope creep ("while you're at it, can you also..."); ghosting (requesting changes, then disappearing); perfectionism (blocking on style preferences).
- **Author:** mega PRs; no context (a missing description or linked issue); defensive responses to every comment; silent updates (changing code without replying to the comments).

### Metrics and improvement

Track time to first review, review cycle time, the number of review rounds, the defect escape rate, and review coverage. Hold retrospectives on the process, share lessons from escaped bugs, update checklists from recurring issues, and recognize good reviews and catches.
