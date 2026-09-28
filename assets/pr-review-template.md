# Example Review

A complete review in the [Output Format](../SKILL.md#output-format). The fixed parts are:

- the verdict and scope lines;
- numbered findings, each with severity, `path:line`, the defect stated as fact, its impact and a fix;
- questions for what a static review can't settle.

Everything else varies with the change.

## The review

**Verdict:** Request changes — the invoice trigger fails at bulk volume, and the export route trusts a client-supplied account Id.
**Scope:** origin/main...feature/invoice-sync · 7 files (+214/−38) · guides: platform, apex, apex-triggers, soql-sosl, javascript, typescript, nodejs · not reviewed: package-lock.json (generated)

### Findings

1. 🔴 [blocking] `force-app/main/default/classes/InvoiceTriggerHandler.cls:41` — `[SELECT … FROM Account WHERE Id = :inv.Account__c]` runs once per invoice inside the loop.
   - Impact: a 200-record insert runs 200 queries in one trigger chunk → `System.LimitException: Too many SOQL queries: 101`, and the whole data load fails.
   - Fix: collect the `Account__c` Ids before the loop, query once into a `Map<Id, Account>`, and read from the map inside the loop.
2. 🔴 [blocking] `src/routes/export.ts:27` — `accountId` comes from `req.query` and goes straight to `exportService.run(accountId)` with no ownership check.
   - Impact: any signed-in user can export another customer's invoices by changing the query string (IDOR).
   - Fix: load the account with `where: { id: accountId, ownerId: req.user.id }` and return 404 when nothing matches.
   - Also at: `src/routes/export.ts:61` (the CSV variant)
3. 🟡 [important] `force-app/main/default/classes/InvoiceSyncJob.cls:18` — the callout response is parsed without checking `res.getStatusCode()`.
   - Impact: a 500 from the billing API deserializes to an empty list, and the job marks every invoice as synced.
   - Fix: record a failure (or throw `CalloutException`) unless the status is 200, before parsing.
4. 🟡 [important] `force-app/main/default/classes/BillingClient.cls:55` (pre-existing, now called from the new job) — the request sets no timeout.
   - Impact: the default 10-second timeout is shorter than the billing API's documented 30-second export time, so large syncs fail intermittently.
   - Fix: `req.setTimeout(30000);`
5. 🟢 [nit] `src/services/export.service.ts:12` — `let rows` is never reassigned; `const` states the intent.

### Questions

- `force-app/main/default/triggers/InvoiceTrigger.trigger-meta.xml:4` — the apiVersion moves from 62.0 to 67.0, so the query in the trigger body now runs in user mode. Can the integration user read `Account.Credit_Limit__c`? If unsure, ask for a test run as that user in the sandbox.
