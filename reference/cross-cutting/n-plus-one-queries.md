# N+1 Queries: Cross-Language Guide

> N+1 queries are the most common performance anti-pattern in ORMs and data-access layers. This guide covers the problem definition, detection methods, general solutions, and code examples for JavaScript/TypeScript (Prisma, TypeORM, GraphQL DataLoader), Python (SQLAlchemy), and Salesforce Apex (SOQL, LWC, Flow).

## Table of Contents

- [Problem Definition](#problem-definition)
- [Performance Impact](#performance-impact)
- [Detection](#detection)
- [General Solutions](#general-solutions)
- [Language-Specific Implementations](#language-specific-implementations)
- [Review Checklist](#review-checklist)

---

## Problem Definition

An N+1 query happens when **one query fetches N records and a loop then triggers N more queries** to fetch the related data.

```
Request flow:
  1 query   → fetch N parent records
  N queries → one query per parent record for its related data
  ─────────
  Total: 1 + N queries
```

### Why it hurts

| Problem | Impact |
|------|------|
| **Query count grows linearly** | 100 records = 101 SQL queries; 1,000 records = 1,001 |
| **Network latency adds up** | Every query pays a round trip (RTT); N round trips >> 1 batched query |
| **Connection pool exhaustion** | A flood of queries ties up database connections and slows down the whole application |
| **Hard to spot in development** | Development data sets are small, so N+1 goes unnoticed; performance collapses at production data volumes |

---

## Performance Impact

### Scenario: fetching 100 users and their orders

| Approach | SQL queries | Latency (assuming RTT = 1 ms) | When to use |
|------|----------|---------------------|---------|
| N+1 lazy loading | 101 | ~101 ms | Very small data sets only |
| Eager loading (JOIN) | 1 | ~1 ms | One-to-many, moderate data volume |
| Eager loading (IN) | 2 | ~2 ms | Many-to-many, large data sets |
| DataLoader / batch | 2 | ~2 ms | GraphQL / complex graph queries |

### SQL query count comparison

```sql
-- ❌ N+1: 1 + 100 = 101 queries
SELECT * FROM users;                          -- 1 query
SELECT * FROM orders WHERE user_id = 1;       -- query 2
SELECT * FROM orders WHERE user_id = 2;       -- query 3
...
SELECT * FROM orders WHERE user_id = 100;     -- query 101

-- ✅ Batch: 2 queries
SELECT * FROM users;
SELECT * FROM orders WHERE user_id IN (1,2,...,100);
```

---

## Detection

### 1. ORM SQL logs

Turn on SQL logging and watch the query count in tests or in development:

```python
# SQLAlchemy
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
# or: engine = create_engine(url, echo=True)
```

```typescript
// Prisma: print every query (adapter is the driver adapter, required from Prisma ORM 7)
const prisma = new PrismaClient({ adapter, log: ['query'] });

// TypeORM: log SQL (logging: ['query'] limits the output to queries)
const dataSource = new DataSource({
    type: 'postgres',
    url: process.env.DATABASE_URL,
    entities: [User, Post],
    logging: true,
});
```

### 2. Query-count assertions

Assert the number of SQL queries in tests:

```python
# SQLAlchemy: count statements with a cursor event, then remove the listener
from contextlib import contextmanager

from sqlalchemy import event, select
from sqlalchemy.orm import joinedload


@contextmanager
def count_queries(engine):  # for an AsyncEngine, pass engine.sync_engine
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def on_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


with count_queries(engine) as statements:
    session.scalars(select(User).options(joinedload(User.profile))).all()
assert len(statements) <= 2  # expect at most 2 queries
```

```typescript
// Prisma: emit query events and count them
const prisma = new PrismaClient({ adapter, log: [{ emit: 'event', level: 'query' }] });
let queryCount = 0;
prisma.$on('query', () => {
    queryCount += 1;
});

it('loads users with their posts in at most 2 queries', async () => {
    queryCount = 0;
    await prisma.user.findMany({ include: { posts: true } });
    expect(queryCount).toBeLessThanOrEqual(2);
});
```

```apex
// Apex test: accountIds holds 200 test Accounts, so a per-record query would show up
Integer before = Limits.getQueries();
AccountService.loadContacts(accountIds);
Assert.isTrue(Limits.getQueries() - before <= 2, 'expected at most 2 queries');
```

### 3. APM / database monitoring tools

- **ORM query logs**: per-request query counts in development and tests (SQLAlchemy `echo`, Prisma `log`, TypeORM `logging`)
- **OpenTelemetry database spans**: database instrumentation records every query as a child span of the request, so a run of identical spans stands out
- **APM (Datadog, New Relic)**: slow-query alerts and N+1 detection in production
- **Salesforce**: the review is static, so ask the author for a debug log or test output that shows the SOQL query count at bulk volume

---

## General Solutions

### Solution 1: Eager loading (JOIN)

Fetch the parent records and their related records in one JOIN query. Suits one-to-one and one-to-many relationships; for large or multiple collections the JOIN repeats every parent row, so prefer Solution 2 there.

### Solution 2: Batch fetching (IN clause)

Two queries: the parent records, then `WHERE id IN (...)` to fetch all related records at once. Suits many-to-many relationships and large data sets.

### Solution 3: DataLoader pattern

In GraphQL or other complex graph queries, collect every ID that is needed and merge them into one batch query.

```
// DataLoader pseudocode
class DataLoader<K, V> {
    load(K key) → V         // register the need; do not query yet
    loadAll([K]) → [V]      // merge into one batch query
}
```

### Solution 4: Projection

Query only the fields you need, to cut the amount of data transferred:

```sql
-- ❌ Fetches every column
SELECT * FROM users JOIN profiles ON ...

-- ✅ Projects only the fields you need
SELECT u.name, p.avatar_url FROM users u JOIN profiles p ON ...
```

---

## Language-Specific Implementations

### Python / SQLAlchemy

```python
from sqlalchemy import select
from sqlalchemy.orm import joinedload, raiseload, selectinload

# ❌ N+1: every order.customer access lazy-loads one row
for order in session.scalars(select(Order)).all():
    print(order.customer.name)

# selectinload: batch loading with an IN clause (recommended for async code)
stmt = select(Order).options(selectinload(Order.customer))

# joinedload: loading with a JOIN
stmt = select(Order).options(joinedload(Order.customer))

# 💡 raiseload turns any accidental lazy load into an error, so N+1 fails fast in tests
stmt = select(Order).options(selectinload(Order.customer), raiseload("*"))
```

### TypeScript / Prisma

```typescript
// ❌ N+1
const users = await prisma.user.findMany();
for (const user of users) {
    user.posts = await prisma.post.findMany({ where: { userId: user.id } });
}

// ✅ include (Prisma generates a JOIN or batched queries for you)
const users = await prisma.user.findMany({
    include: { posts: true },
});

// ✅ Nested include
const users = await prisma.user.findMany({
    include: {
        posts: {
            include: { comments: true },
        },
    },
});
```

### Node.js / GraphQL DataLoader

A field resolver runs once per parent object, so a list of 100 users means 100 `posts` lookups. DataLoader collects every `load()` call made in the same tick and hands them to one batch function.

```javascript
import DataLoader from 'dataloader';

// ❌ N+1: this resolver runs once per User in the list, one query each
const userResolversNaive = {
    posts: (user) => prisma.post.findMany({ where: { userId: user.id } }),
};

// ✅ One loader per request: all loads from the same tick become one IN query
export function createLoaders() {
    return {
        postsByUserId: new DataLoader(async (userIds) => {
            const posts = await prisma.post.findMany({ where: { userId: { in: [...userIds] } } });
            const byUser = Map.groupBy(posts, (post) => post.userId); // ES2024, Node.js 21+
            return userIds.map((id) => byUser.get(id) ?? []); // same length and order as the keys
        }),
    };
}

const userResolvers = {
    posts: (user, _args, context) => context.loaders.postsByUserId.load(user.id),
};
```

Create the loaders in the per-request context factory, never at module level: DataLoader caches results, so a shared instance serves stale rows and can leak one user's data to another.

### Salesforce (Apex, LWC, Flow)

In Apex, N+1 is a hard failure, not just a slowdown. Every SOQL query counts toward a per-transaction governor limit, and the query that crosses it throws `System.LimitException`, which cannot be caught and rolls back the transaction. Triggers, batch jobs, and data loads pass many records at once, so a query per record fails at ordinary volumes (numbers in [Governor Limits](../salesforce/platform.md#governor-limits)).

```apex
public with sharing class OpportunityCreditCheck {
    // ❌ One query per Opportunity: in a synchronous transaction the 101st query throws LimitException
    public static void validateSlow(List<Opportunity> opportunities) {
        for (Opportunity opp : opportunities) {
            Account acc = [SELECT Credit_Hold__c FROM Account WHERE Id = :opp.AccountId WITH USER_MODE];
            if (acc.Credit_Hold__c) {
                opp.addError('The account is on credit hold.');
            }
        }
    }

    // ✅ Collect the Ids, run one query, and look the parents up in a Map
    public static void validate(List<Opportunity> opportunities) {
        Set<Id> accountIds = new Set<Id>();
        for (Opportunity opp : opportunities) {
            accountIds.add(opp.AccountId);
        }
        Map<Id, Account> accountsById = new Map<Id, Account>(
            [SELECT Id, Credit_Hold__c FROM Account WHERE Id IN :accountIds WITH USER_MODE]
        );
        for (Opportunity opp : opportunities) {
            Account acc = accountsById.get(opp.AccountId);
            if (acc != null && acc.Credit_Hold__c) {
                opp.addError('The account is on credit hold.');
            }
        }
    }

    // ✅ Parent-to-child: a subquery returns each Account with its Contacts in one query
    public static List<String> contactEmails(Set<Id> accountIds) {
        List<String> emails = new List<String>();
        for (Account acc : [
            SELECT Id, (SELECT Email FROM Contacts WHERE Email != null)
            FROM Account
            WHERE Id IN :accountIds
            WITH USER_MODE
        ]) {
            for (Contact con : acc.Contacts) {
                emails.add(con.Email);
            }
        }
        return emails;
    }
}
```

Static analysis: PMD `OperationWithLimitsInLoop`.

The same shape appears in Lightning Web Components as round trips: one imperative Apex call per row means N server calls instead of one. A child component per row that calls Apex (imperatively or through its own `@wire`) hides the same problem; load the data once in the parent and pass it down.

```javascript
import { LightningElement, api, wire } from 'lwc';
import getOpenTotal from '@salesforce/apex/InvoiceController.getOpenTotal';
import getOpenTotals from '@salesforce/apex/InvoiceController.getOpenTotals';

export default class AccountTotals extends LightningElement {
    @api accountIds = [];

    // ❌ One Apex call per row: N sequential server round trips
    async loadTotalsOneByOne() {
        const totals = {};
        for (const accountId of this.accountIds) {
            totals[accountId] = await getOpenTotal({ accountId });
        }
        return totals;
    }

    // ✅ One cacheable call for the whole list; the Apex method returns Map<Id, Decimal>
    @wire(getOpenTotals, { accountIds: '$accountIds' })
    totals;
}
```

In Flow, the equivalent is a data element inside a Loop: every Get Records, Create/Update/Delete Records, or Apex action inside the loop runs once per iteration.

```text
❌ Loop over {!Opportunities}
     → Get Records: Account where Id = {!Loop.AccountId}   (one query per iteration)
     → Update Records: {!Loop}                             (one DML statement per iteration)

✅ Get Records: the related Accounts, once, before the loop
   Loop over {!Opportunities}
     → Assignment: set the fields, add {!Loop} to {!OpportunitiesToUpdate}
   Update Records: {!OpportunitiesToUpdate}                (one DML statement, after the loop)
```

> 📖 Depth: [Apex bulkification](../salesforce/apex.md#bulkification) · [Bulk-safe flow design](../salesforce/flows.md#bulk-safe-design) · [SOQL query shape](../salesforce/soql-sosl.md#query-shape) · [LWC data access](../salesforce/lwc.md#data-access)

---

## Review Checklist

### Detection
- [ ] SQL logging or query-count monitoring is enabled
- [ ] Tests assert the number of queries
- [ ] The APM tool is configured to alert on N+1 patterns

### Fixes
- [ ] To-one relationships use JOIN eager loading (`joinedload`, Prisma `include`)
- [ ] To-many relationships use IN batch loading (`selectinload`, DataLoader)
- [ ] No database queries are triggered inside loops
- [ ] Projections fetch only the fields that are needed
- [ ] Apex/Flow: no SOQL or data elements inside loops; related data loaded with one query into a Map
- [ ] LWC: one Apex call loads the data for the whole list, not one call per row or per child component

### Architecture
- [ ] List APIs paginate, so one request never loads too many records
- [ ] GraphQL resolvers use DataLoader, with new loader instances per request
- [ ] A caching strategy (for example, Redis) serves frequently read related data
