# SQL Injection Prevention Guide

Language-agnostic SQL injection prevention strategies with code examples for Python, Node.js, and Salesforce Apex (SOQL/SOSL).

> **Related**: [Security Review Guide](../security-review-guide.md) for comprehensive security checklist and decision framework.

## Attack Types

SQL injection (SQLi) belongs to A05:2025 Injection in the OWASP Top 10 (the Injection category was A03 in the 2021 edition). Three common variants:

| Type | Description | Risk |
|------|-------------|------|
| **Classic (In-band)** | Attacker receives results directly in the HTTP response | Data exfiltration, authentication bypass |
| **Blind (Boolean/Time-based)** | Attacker infers data from response differences or timing | Slower but still viable for data extraction |
| **Out-of-band** | Attacker uses DNS/HTTP callbacks to exfiltrate data | Less common but harder to detect |

## Universal Prevention Strategy

1. **Parameterized queries** — always (the #1 defense)
2. **ORM safe usage** — understand what your ORM escapes
3. **Input validation** — allowlist over denylist
4. **Least privilege** — database user with minimal permissions
5. **WAF** — web application firewall as defense-in-depth

---

## Cross-Language Examples

### Python

```python
# ❌ Vulnerable: string formatting
query = f"SELECT * FROM users WHERE id = {user_id}"
cursor.execute(query)

# ❌ Vulnerable: % formatting (it looks like a placeholder, but the string is built before execute() runs)
cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)

# ✅ Parameterized (DB-API); the placeholder style depends on the driver:
#    %s for psycopg and PyMySQL, ? for sqlite3
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# ✅ SQLAlchemy ORM (2.0 style)
users = session.scalars(select(User).where(User.id == user_id)).all()

# ❌ SQLAlchemy raw SQL with string interpolation
session.execute(text(f"SELECT * FROM users WHERE id = {user_id}"))

# ✅ SQLAlchemy raw SQL with bound parameters
session.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
```

### Node.js

```typescript
// ❌ Vulnerable: template literal
const query = `SELECT * FROM users WHERE id = ${userId}`;
const result = await client.query(query);

// ✅ pg parameterized ($1, $2, ...)
const result = await client.query(
    "SELECT * FROM users WHERE id = $1",
    [userId]
);

// ✅ Prisma ORM (parameterized by default)
const user = await prisma.user.findUnique({
    where: { id: userId },
});

// ❌ Prisma $queryRawUnsafe with string interpolation
await prisma.$queryRawUnsafe(
    `SELECT * FROM users WHERE id = ${userId}`
);

// ✅ Prisma $queryRaw with tagged template (safe)
await prisma.$queryRaw`
    SELECT * FROM users WHERE id = ${userId}
`;

// ✅ TypeORM query builder with a named parameter
const user = await dataSource
    .getRepository(User)
    .createQueryBuilder("u")
    .where("u.id = :id", { id: userId })
    .getOne();

// ✅ Sequelize raw query with replacements
const users = await sequelize.query("SELECT * FROM users WHERE id = :id", {
    replacements: { id: userId },
    type: QueryTypes.SELECT,
});

// ✅ Knex raw query with a positional binding
const rows = await knex.raw("SELECT * FROM users WHERE id = ?", [userId]);
```

### Salesforce Apex (SOQL/SOSL)

Dynamic SOQL and SOSL can be injected the same way as SQL: a quote in concatenated input rewrites the query. Static queries with `:bind` variables can't. The fixes below also state the access mode, because below API 67.0 a query without one runs in system mode (see [Security Model](../salesforce/platform.md#security-model)).

```apex
public with sharing class AccountSearchService {
    // ❌ Concatenation: name = "x' OR Name LIKE '%" makes the filter match every account
    public static List<Account> findByNameUnsafe(String name) {
        return Database.query('SELECT Id, Name FROM Account WHERE Name = \'' + name + '\'');
    }

    // ✅ Static SOQL: the bind variable is treated as a value, never parsed as SOQL
    public static List<Account> findByName(String name) {
        return [SELECT Id, Name FROM Account WHERE Name = :name WITH USER_MODE];
    }

    // ✅ Dynamic SOQL (API 57.0+ / Spring '23): values in a bind map, access level stated
    public static List<Account> findByNameDynamic(String name) {
        return Database.queryWithBinds(
            'SELECT Id, Name FROM Account WHERE Name = :name',
            new Map<String, Object>{ 'name' => name },
            AccessLevel.USER_MODE
        );
    }

    // ⚠️ String.escapeSingleQuotes() only protects a value inside a quoted string literal.
    //    It does nothing for numbers, field or object names, ORDER BY, or LIMIT: allowlist those
    //    (see Dynamic Identifiers below).

    // ✅ SOSL: bind the search term in static SOSL; never concatenate it into a Search.query() string
    public static List<List<SObject>> searchAccountsAndContacts(String term) {
        return [
            FIND :term IN NAME FIELDS
            RETURNING Account(Id, Name), Contact(Id, Name)
            WITH USER_MODE
            LIMIT 50
        ];
    }
}
```

> 📖 Depth: [SOQL & SOSL Guide](../salesforce/soql-sosl.md#soql-injection).

---

## ORM Unsafe Usage Patterns

ORMs do NOT automatically prevent SQL injection in all cases:

```python
# ❌ SQLAlchemy: text() with an f-string, run directly or as a fragment inside a query
session.execute(text(f"SELECT * FROM users WHERE id = {user_id}"))
select(User).where(text(f"name = '{name}'"))

# ✅ SQLAlchemy: bound parameters in text(), including fragments
select(User).where(text("name = :name").bindparams(name=name))
```

```typescript
// ❌ Prisma: $queryRawUnsafe / $executeRawUnsafe with interpolation
await prisma.$queryRawUnsafe(`SELECT * FROM users WHERE email = '${email}'`);
// ✅ The tagged $queryRaw, or $queryRawUnsafe with positional parameters
await prisma.$queryRaw`SELECT * FROM users WHERE email = ${email}`;
await prisma.$queryRawUnsafe("SELECT * FROM users WHERE email = $1", email);
// ⚠️ Prisma.raw() inside a tagged template is inserted verbatim: never pass it user input

// ❌ TypeORM: .query() with a template literal
await dataSource.query(`SELECT * FROM users WHERE email = '${email}'`);
// ✅ Parameters array (placeholder syntax follows the driver: $1 for PostgreSQL, ? for MySQL)
await dataSource.query("SELECT * FROM users WHERE email = $1", [email]);

// ❌ Sequelize: query() with interpolation and no replacements
await sequelize.query(`SELECT * FROM users WHERE email = '${email}'`);
// ✅ Replacements (or bind parameters)
await sequelize.query("SELECT * FROM users WHERE email = :email", {
    replacements: { email },
    type: QueryTypes.SELECT,
});

// ❌ Knex: whereRaw() or raw() with interpolation
await knex("users").whereRaw(`email = '${email}'`);
// ✅ Bindings
await knex("users").whereRaw("email = ?", [email]);
```

**Rule**: Every ORM has a "raw SQL" escape hatch. String interpolation in that escape hatch = SQL injection. Always use the ORM's parameter binding mechanism.

In Apex, `Database.query`, `Database.countQuery`, `Database.getQueryLocator`, and `Search.query` are the raw-query escape hatches (see [Salesforce Apex (SOQL/SOSL)](#salesforce-apex-soqlsosl)).

---

## Dynamic Identifiers (Table/Column Names)

Placeholders can only bind **values**, not table names, column names, or SQL keywords. For dynamic identifiers:

```python
# ✅ Allowlist validation, then look the column up on the model
ALLOWED_COLUMNS = {"id", "name", "email", "created_at"}
ALLOWED_DIRECTIONS = {"asc", "desc"}

def get_users(session: Session, order_by: str, direction: str) -> list[User]:
    if order_by not in ALLOWED_COLUMNS:
        raise ValueError(f"Invalid column: {order_by}")
    if direction.lower() not in ALLOWED_DIRECTIONS:
        raise ValueError(f"Invalid direction: {direction}")

    # ⚠️ Without the allowlist, getattr() accepts any attribute, e.g. password_hash:
    #    sorting by a secret column leaks information about it through the row order
    column = getattr(User, order_by)
    ordering = column.desc() if direction.lower() == "desc" else column.asc()
    return list(session.scalars(select(User).order_by(ordering)))
```

```typescript
import type { Pool } from "pg";

// ✅ Allowlist validation with pg: the identifier comes from a fixed set, values stay $n parameters
const SORTABLE_COLUMNS = new Set(["id", "name", "email", "created_at"]);

export async function listUsers(pool: Pool, tenantId: string, orderBy: string, direction: string) {
    if (!SORTABLE_COLUMNS.has(orderBy)) {
        throw new Error(`Invalid sort column: ${orderBy}`);
    }
    const dir = direction.toLowerCase() === "desc" ? "DESC" : "ASC";
    const { rows } = await pool.query(
        `SELECT id, name, email FROM users WHERE tenant_id = $1 ORDER BY ${orderBy} ${dir}`,
        [tenantId]
    );
    return rows;
}
```

- Map the sort direction to a fixed keyword (`ASC` or `DESC`); never pass the input through.
- **Apex**: validate field names against `Schema.SObjectType.Account.fields.getMap()` (and check `isSortable()` for ORDER BY), then build the clause from the field's describe (`getDescribe().getName()`), not from the raw input.

---

## Detection & Testing

```bash
# Automated scanning
sqlmap -u "https://example.com/api/users?id=1" --batch

# Static analysis (Python)
bandit -r src/ -f custom

# Static analysis (Semgrep registry ruleset)
semgrep scan --config p/sql-injection src/

# Code review keywords to search for
# Python: f-strings, % and .format() applied to SQL text
grep -rnEi "f[\"'][^\"']*(SELECT|INSERT|UPDATE|DELETE) |[\"'][^\"']*(SELECT|INSERT|UPDATE|DELETE) [^\"']*[\"'] *(%|\.format\()" src/
# JavaScript/TypeScript: SQL in template literals, and raw-query APIs
grep -rnEi '`[^`]*(select|insert|update|delete) [^`]*\$\{' src/
grep -rnE '\$(query|execute)RawUnsafe|(where|orderBy|having)Raw\(|\.raw\(|sequelize\.query\(' src/
# Any language: string concatenation onto SQL text
grep -rnEi "(select|insert|update|delete) [^\"']*[\"']+ *\+" src/

# Salesforce: every dynamic SOQL/SOSL call site, then PMD ApexSOQLInjection on local files (no org)
grep -rn "Database\.query\|Database\.countQuery\|Database\.getQueryLocator\|Search\.query" force-app/
sf code-analyzer run --workspace force-app --rule-selector pmd:ApexSOQLInjection
```

---

## Review Checklist

- [ ] All SQL queries use parameterized queries (no string interpolation)
- [ ] ORM raw SQL methods use bound parameters, not string formatting
- [ ] Dynamic identifiers (table/column names) validated against an allowlist
- [ ] Database user has least privilege (no DROP/ALTER for app user)
- [ ] No SQL queries constructed from user input without parameterization
- [ ] Static analysis tools (Bandit, Semgrep, SonarQube) run in CI
- [ ] Apex dynamic SOQL/SOSL uses binds or `Database.queryWithBinds`; identifiers allowlisted via Schema describe
