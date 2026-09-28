# N+1 Queries: Cross-Language Guide

> One query loads N parents, then a loop, a resolver, or a child component runs one more query per parent. This guide owns N+1 for SQLAlchemy, Prisma, TypeORM, GraphQL DataLoader, and Salesforce (Apex, LWC, Flow).
> Related: [Performance Review Guide](../performance-review-guide.md#database-performance) · Salesforce limit numbers: [Governor Limits](../salesforce/platform.md#governor-limits)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

### Queries per item → [Language-Specific Implementations](#language-specific-implementations)

- [ ] No query, lazy relation access, remote call, or Apex/Flow data element runs once per element of a collection that grows with data or with the caller's input (list endpoints, resolvers, trigger chunks, batch scopes, imports).
- [ ] Related rows are loaded with their parents (eager loading) or with one batched `IN` query, then looked up in a map keyed by id.
- [ ] Not a finding: a loop over a small, fixed set (a few configuration rows, enum values), or a loop that has to be sequential (cursor pagination, ordered writes).
- [ ] Severity: 🟡 by default; 🔴 when the collection is unbounded on a request, job, or import path. Salesforce loops follow [row 1 of Severity Calibration](../salesforce/platform.md#severity-calibration) (🔴) and state the limit math.

### ORM specifics → [Python / SQLAlchemy](#python--sqlalchemy) · [TypeScript / Prisma](#typescript--prisma) · [TypeORM](#typeorm)

- [ ] SQLAlchemy: relationships read in a loop are loaded with `selectinload` (collections, or any relationship) or `joinedload` (many-to-one); `joinedload` of a collection needs `.unique()` on the result.
- [ ] SQLAlchemy with `AsyncSession`: relationships are loaded eagerly, because an implicit lazy load raises instead of querying.
- [ ] Prisma: relations come from `include` or a nested `select` on the parent query, not from a `findMany` per parent.
- [ ] TypeORM: `await entity.relation` in a loop queries only for a lazy relation (typed `Promise<T>`); an unloaded regular relation is `undefined`, a correctness bug rather than an N+1.

### GraphQL → [Node.js / GraphQL DataLoader](#nodejs--graphql-dataloader)

- [ ] Field resolvers that fetch per parent go through a DataLoader, and loaders are created per request, never at module level.
- [ ] The batch function returns one result per key, in key order.

### Salesforce → [Salesforce (Apex, LWC, Flow)](#salesforce-apex-lwc-flow)

- [ ] Apex: no SOQL inside a loop; Ids are collected first and one query fills a `Map` (PMD `OperationWithLimitsInLoop`).
- [ ] LWC: the list's data comes from one Apex call in the parent, not one call per row or per child component.
- [ ] Flow: no Get Records, Create/Update/Delete Records, or Apex action inside a Loop element.

### Tests and evidence → [Detection](#detection)

- [ ] When the diff adds a list path or changes how relations load, a test pins the query count; suggest one as 🟢 when it is missing.
- [ ] Query logs, traces, and debug logs are not in the diff: ask the author for them when the count depends on runtime data.

---

## Detection

The query usually hides in an attribute access (`order.customer`), an awaited helper (`await getUser(id)`), or a component rendered once per row, so read each loop body. Grep-tool patterns that find candidates:

- Python: `session\.(execute|scalars|get|query)\(` and Django `\.objects\.(get|filter)\(`
- JavaScript/TypeScript: `await [^;]*\.(findMany|findUnique|findFirst|findOne|findOneBy)\(`
- Apex: `\[\s*SELECT` and `Database\.query`, then check whether the hit sits inside a `for` loop
- LWC: `@salesforce/apex/` imports in components that a parent renders per row

To pin the fix, suggest a test that counts queries around the call: in SQLAlchemy, a `before_cursor_execute` listener added with `event.listens_for(engine, ...)` and removed with `event.remove` (for an `AsyncEngine`, use `engine.sync_engine`); in Prisma, `log: [{ emit: 'event', level: 'query' }]` with `prisma.$on('query', ...)`; in Apex, `Limits.getQueries()` before and after the call on 200 test records.

---

## Language-Specific Implementations

### Python / SQLAlchemy

```python
from sqlalchemy import select
from sqlalchemy.orm import joinedload, raiseload, selectinload

# ❌ N+1: every order.customer access lazy-loads one row
for order in session.scalars(select(Order)).all():
    print(order.customer.name)

# ✅ Many-to-one: one JOIN
orders = session.scalars(select(Order).options(joinedload(Order.customer))).all()

# ✅ Collections: one extra SELECT ... WHERE ... IN (...) for all parents
customers = session.scalars(select(Customer).options(selectinload(Customer.orders))).all()

# ✅ raiseload("*") turns every other lazy load into an error, so a new N+1 fails in tests
stmt = select(Order).options(joinedload(Order.customer), raiseload("*"))
```

With a raw DB-API cursor, batch the ids into one query: on PostgreSQL, `WHERE id = ANY(%s)` with a Python list works in psycopg 2 and 3, while `IN %s` with a tuple works only in psycopg 2 and fails on an empty tuple. Skip the query when the list is empty.

### TypeScript / Prisma

```typescript
// ❌ N+1: one query per user
const users = await prisma.user.findMany();
for (const user of users) {
    const posts = await prisma.post.findMany({ where: { userId: user.id } });
    render(user, posts);
}

// ✅ One call loads the users with their posts
const usersWithPosts = await prisma.user.findMany({ include: { posts: true } });
for (const user of usersWithPosts) {
    render(user, user.posts);
}
```

Prisma resolves `include` either with a database join or with one batched query per relation level, depending on the relation load strategy and the Prisma version (verify for the project). Either way, the query count no longer grows with N.

### TypeORM

A relation declared lazy (`posts: Promise<Post[]>`) runs a query on every `await user.posts`, so awaiting it inside a loop is an N+1. A regular relation is populated only when the query loads it (`find({ relations: { posts: true } })` or a query-builder join); reading it without loading it gives `undefined`. Check the entity definition before reporting either.

### Node.js / GraphQL DataLoader

A field resolver runs once per parent object, so a list of 100 users means 100 `posts` lookups. `load()` returns a Promise, and DataLoader collects every `load()` call made in the same tick into one call of the batch function (`loadMany(keys)` is shorthand for several `load()` calls).

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

In Apex, N+1 is a hard failure, not a slowdown: the query that crosses the per-transaction SOQL limit throws `System.LimitException`, which cannot be caught and rolls back the transaction. Triggers, batch jobs, and data loads pass many records at once, so a query per record fails at ordinary volumes ([Governor Limits](../salesforce/platform.md#governor-limits)).

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
}
```

Parent-to-child data can come from the same query: a subquery such as `SELECT Id, (SELECT Email FROM Contacts) FROM Account WHERE Id IN :accountIds` returns each parent with its children.

In Lightning Web Components the same shape appears as round trips: one imperative Apex call per row, or a child component per row that calls Apex (imperatively or through its own `@wire`), turns N rows into N server calls. Load the list's data with one cacheable call in the parent and pass it down ([LWC: Performance](../salesforce/lwc.md#performance)).

In Flow, the equivalent is a data element inside a Loop: every Get Records, Create/Update/Delete Records, or Apex action inside the loop runs once per iteration. Query once before the loop, collect changes with Assignment elements, and write once after it ([Bulk-safe flow design](../salesforce/flows.md#bulk-safe-design)).

> 📖 Depth: [Apex bulkification](../salesforce/apex.md#bulkification) · [SOQL query shape](../salesforce/soql-sosl.md#query-shape) · [LWC data access](../salesforce/lwc.md#data-access)
