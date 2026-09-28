# SQL Injection Prevention Guide

Bind values, allowlist identifiers, and audit every raw-SQL escape hatch in Python and Node.js drivers and ORMs. Apex SOQL and SOSL: [SOQL & SOSL Guide](../salesforce/soql-sosl.md#soql-injection).

Related: [Security Review Guide](../security-review-guide.md) · [Python Guide](../python.md) · [N+1 Queries](n-plus-one-queries.md)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Severity: 🔴 blocking · 🟡 important · 🟢 nit · 💡 suggestion.

### Values → [Parameterized Queries](#parameterized-queries)

- [ ] 🔴 No SQL text built from input with f-strings, `%`, `.format()`, `+`, or template literals (S608); values go in the driver's parameters
- [ ] 🔴 Placeholders match the driver and are never quoted (`'%s'`)
- [ ] 🟡 A t-string (`t"..."`) reaches a Template-aware API; the same text with `f"` is injection

### Escape hatches → [ORM Raw-SQL Escape Hatches](#orm-raw-sql-escape-hatches)

- [ ] 🔴 `text()`, `literal_column()`, `raw()`, `extra()`, `RawSQL`, `$queryRawUnsafe`, `Prisma.raw()`, `whereRaw()`, and `sequelize.query()` never receive interpolated input
- [ ] 🔴 Django lookups never come from `**` expansion of request data

### Identifiers → [Dynamic Identifiers](#dynamic-identifiers-tablecolumn-names)

- [ ] 🔴 Table, column, and sort names come from an allowlist that maps input to fixed names; direction maps to `ASC` or `DESC`
- [ ] 🟡 Quoting helpers (`sql.Identifier`, `{col:i}`, Knex `??`, pg-format `%I`) are paired with an allowlist when the column choice can expose data

### Apex → [Salesforce Apex (SOQL/SOSL)](#salesforce-apex-soqlsosl)

- [ ] 🔴 Dynamic SOQL and SOSL bind values; field and object names come from Schema describe or an allowlist

### Not findings → [Parameterized Queries](#parameterized-queries)

- [ ] Interpolating only generated placeholders (`", ".join(["?"] * len(ids))`), constants, or allowlisted identifiers
- [ ] Prisma's tagged `$queryRaw` template and `Prisma.sql`, which bind their interpolations
- [ ] Database-user privileges and CI scanners: deployment concerns to ask the author about, not diff findings

## Parameterized Queries

### Python

```python
# ❌ The string is built before the driver sees it (f-string, % and .format() alike)
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)

# ✅ The driver binds the value
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
session.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
User.objects.raw("SELECT * FROM auth_user WHERE username = %s", [username])

# ✅ psycopg ≥3.3 on Python 3.14: {…} becomes a parameter, {…:i} a quoted identifier
cur.execute(t"SELECT * FROM users WHERE id = {user_id} ORDER BY {sort_column:i}")
```

- Placeholders: `%s` or `%(name)s` for psycopg and PyMySQL, `?` or `:name` for sqlite3, `$1` for asyncpg, `:name` in SQLAlchemy `text()`. APIs that accept only `str` raise `TypeError` for a t-string.
- Django: "Do not use string formatting on raw queries or quote placeholders in your SQL strings!" (`raw()`, `RawSQL`, `extra()`, `cursor.execute()`).

### Node.js

```typescript
// ❌ Template literal: the value becomes SQL text
await client.query(`SELECT * FROM users WHERE id = ${userId}`);

// ✅ pg binds $1
await client.query('SELECT * FROM users WHERE id = $1', [userId]);
```

Prisma queries, TypeORM `where('u.id = :id', { id })`, Sequelize `replacements`, and Knex `?` bindings also bind values.

## ORM Raw-SQL Escape Hatches

Every ORM has a raw-SQL escape hatch; interpolation there is SQL injection.

| API | ❌ Unsafe | ✅ Safe |
| --- | --- | --- |
| SQLAlchemy `text()` | `text(f"… {v}")`, also inside `where()` | `text("… :v").bindparams(v=v)` |
| SQLAlchemy `literal_column()` | Any input: rendered verbatim | An allowlisted column |
| Django `raw()`, `RawSQL`, `extra()`, `cursor.execute()` | f-string, `%`, quoted `'%s'` | `raw(sql, [params])`, `RawSQL(sql, params)` |
| Django `filter()`, `exclude()`, `get()`, `Q()` | `**request.GET.dict()`: lookups like `password__startswith`, and `_connector` injection (CVE-2025-64459, fixed in 5.2.8, 5.1.14, 4.2.26) | Allowlisted keyword arguments |
| Prisma `$queryRawUnsafe`, `$executeRawUnsafe`, `Prisma.raw()` | Interpolated strings | Tagged `$queryRaw`, or `$queryRawUnsafe(sql, ...params)` |
| TypeORM `query()` | Template literal | `query(sql, [params])` (`$1` on PostgreSQL, `?` on MySQL) |
| Sequelize `query()` | Interpolation | `replacements` or `bind` |
| Knex `raw()`, `whereRaw()` | Interpolation | `?` bindings for values, `??` for identifiers |

## Dynamic Identifiers (Table/Column Names)

Placeholders bind values, not table names, column names, or keywords. Map input to fixed identifiers:

```python
# ✅ The allowlist maps input to columns; password_hash or SQL text never gets through
SORTABLE = {"id": User.id, "name": User.name, "email": User.email}

def list_users(session: Session, order_by: str, direction: str) -> list[User]:
    column = SORTABLE.get(order_by)
    if column is None or direction.lower() not in {"asc", "desc"}:
        raise ValueError("unsupported sort")
    ordering = column.desc() if direction.lower() == "desc" else column.asc()
    return list(session.scalars(select(User).order_by(ordering)))
```

```typescript
// ✅ Interpolating a mapped identifier is fine; values stay $n parameters
const column = new Map([['name', 'name'], ['created', 'created_at']]).get(orderBy);
if (!column) throw new Error('unsupported sort');
const dir = direction.toLowerCase() === 'desc' ? 'DESC' : 'ASC';
await pool.query(`SELECT id, name FROM users WHERE tenant_id = $1 ORDER BY ${column} ${dir}`, [tenantId]);
```

Quoting helpers (psycopg `sql.Identifier`, t-string `{col:i}`, Knex `??`, pg-format `%I`) stop injection but not exposure: sorting by `password_hash` still leaks its order, so keep the allowlist.

## Salesforce Apex (SOQL/SOSL)

Same rule: bind values (static SOQL `:var`, `Database.queryWithBinds(query, binds, AccessLevel.USER_MODE)`), take field and object names from Schema describe or an allowlist, and remember that `String.escapeSingleQuotes()` protects only quoted literals. Details, access modes, and SOSL: [SOQL & SOSL Guide](../salesforce/soql-sosl.md#soql-injection).

## Finding Call Sites

Grep-tool patterns (ripgrep syntax; `multiline` where noted); check where each hit's value comes from:

- `\b(execute|executemany|executescript|raw|text|RawSQL)\(\s*f["']` — f-strings passed to an execution API
- `(?i)\bf["'][^"']*\b(select|insert|update|delete)\b` — one-line f-strings containing SQL
- `(?is)\bf"""[^"]*?\b(select|insert|update|delete)\b` (multiline) — triple-quoted f-string SQL
- `(?i)["'][^"']*\b(select|insert|update|delete)\b[^"']*["']\s*(%\s|\.format\()` — `%` or `.format()` on SQL text
- `(?i)["'\x60][^"'\x60]*\b(select|insert|update|delete|where)\b[^"'\x60]*["'\x60]+\s*\+` — concatenation onto SQL text
- `(?i)(^|[^\w$])\x60[^\x60]*\b(select|insert|update|delete)\b[^\x60]*\$\{` — untagged template literals with SQL
- `\$(query|execute)RawUnsafe\(|\b(whereRaw|orderByRaw|havingRaw|joinRaw)\(|Prisma\.raw\(|sequelize\.query\(` — Node.js raw-SQL APIs
- `\.(raw|extra)\(|RawSQL\(|literal_column\(` — Django and SQLAlchemy verbatim SQL
- `\.(filter|exclude|get)\(\s*\*\*` — Django lookups from dict expansion

## References

- [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [Django: Performing raw SQL queries](https://docs.djangoproject.com/en/stable/topics/db/sql/)
- [psycopg: Template string queries](https://www.psycopg.org/psycopg3/docs/basic/tstrings.html)
