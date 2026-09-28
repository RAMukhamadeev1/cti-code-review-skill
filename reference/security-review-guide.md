# Security Review Guide

Index of security review rules for JavaScript/TypeScript, Python, and Salesforce: each attack type gets a short rule, its legitimate exceptions, and a link to the guide that owns the detail.

Related: [SQL Injection](cross-cutting/sql-injection-prevention.md) · [XSS](cross-cutting/xss-prevention.md) · [Error Handling](cross-cutting/error-handling-principles.md) · [Salesforce Security Model](salesforce/platform.md#security-model)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Severity: 🔴 blocking · 🟡 important · 🟢 nit · 💡 suggestion ([how to pick](#severity)). Pre-existing code is not a finding unless the change makes it worse.

### Identity → [Authentication & Authorization](#authentication--authorization)

- [ ] 🔴 New endpoints check authorization on the server and scope queries to the caller ([IDOR](#idor-insecure-direct-object-reference))
- [ ] 🔴 Passwords use Argon2id, scrypt, bcrypt, or PBKDF2 at current work factors, never a plain or fast hash
- [ ] 🟡 Password rules follow NIST SP 800-63B-4: length and a breached-password check, no composition rules or forced rotation
- [ ] 🔴 JWTs are verified with pinned algorithms ([JWT](#jwt-security)); tokens come from a CSPRNG

### Injection → [Input Validation](#input-validation)

- [ ] 🔴 SQL and SOQL bind every value; identifiers come from allowlists ([SQL Injection](cross-cutting/sql-injection-prevention.md))
- [ ] 🔴 HTML output is auto-escaped or sanitized; template source never comes from input ([XSS](cross-cutting/xss-prevention.md))
- [ ] 🔴 No shell parses user input ([Command Injection](#command-injection-prevention))
- [ ] 🔴 Fetches of caller-supplied URLs pass an exact allowlist and refuse redirects ([SSRF](#ssrf-prevention))
- [ ] 🔴 No deserialization of untrusted data; user paths stay inside their base directory ([Deserialization & Paths](#deserialization--file-paths))

### Browser boundaries → [CSRF Prevention](#csrf-prevention)

- [ ] 🔴 Cookie-authenticated state changes check a CSRF token, a custom header, or `Sec-Fetch-Site`; bearer-token APIs need none
- [ ] 🟡 Credentialed CORS names exact origins; `*` on public, unauthenticated data is fine ([CORS](#cors-configuration))
- [ ] 🟡 A new or changed CSP follows [XSS: CSP](cross-cutting/xss-prevention.md#content-security-policy-csp)

### Data → [Data Protection](#data-protection)

- [ ] 🔴 No secrets in code, config, fixtures, images, or logs
- [ ] 🟡 Clients get safe error messages ([Error Messages](#error-messages)); logs carry IDs, not credentials or PII ([Secure Logging](#secure-logging))
- [ ] 🟡 Encryption is AEAD with unique nonces; no custom crypto ([Cryptography](#cryptography))
- [ ] 🟡 When the PR touches manifests or lockfiles: lockfile updated, new packages justified ([Dependencies](#dependency-security))

### Salesforce → [Salesforce Platform Security](#salesforce-platform-security)

- [ ] 🔴 Entry points enforce sharing, CRUD, and FLS for their API version and re-query client-supplied Ids in user mode

## Authentication & Authorization

- Passwords (NIST SP 800-63B-4): ≥15 characters single-factor (8 with MFA), allow ≥64, blocklist check, no composition rules or periodic changes, rate-limited failures instead of hard lockout.
- Hashing (OWASP): Argon2id (m=19 MiB, t=2, p=1) > scrypt (N=2^17, r=8, p=1) > bcrypt (cost ≥10, 72-byte limit) > PBKDF2-HMAC-SHA256 at 600,000 iterations for FIPS. Stronger defaults (argon2-cffi `PasswordHasher()`, Django's PBKDF2 hasher) are not findings.
- Sessions: CSPRNG IDs, a new ID at login, idle and absolute timeouts. Authorization runs on the server per object and tenant; hiding a button is UX.

### JWT Security

```typescript
// ❌ Decoding is not verifying
const claims = jwt.decode(token);

// ✅ Verify the signature with a pinned algorithm and check the claims
const claims = jwt.verify(token, publicKey, { algorithms: ['RS256'], issuer: 'your-app', audience: 'your-api' });
```

PyJWT: `jwt.decode(token, key, algorithms=["RS256"], audience=..., issuer=...)`; `options={"verify_signature": False}` outside tests is 🔴. HS256 with a strong managed secret is fine; flag hard-coded or short secrets and missing `exp`.

## Input Validation

### SQL Injection Prevention

Bind every value and take identifiers from an allowlist. Raw-SQL escape hatches, placeholders, t-strings, Django, and Apex: [SQL Injection Prevention](cross-cutting/sql-injection-prevention.md).

### XSS Prevention

Rely on auto-escaping and audit every escape hatch (`innerHTML`, `dangerouslySetInnerHTML`, `v-html`, `|safe`, `mark_safe`, `escape="false"`). Template source built from input is template injection, which executes code. Details: [XSS Prevention](cross-cutting/xss-prevention.md).

### CSRF Prevention

- Only credentials the browser attaches itself (cookies, HTTP auth, client certificates) need CSRF defenses; `Authorization: Bearer` APIs don't.
- Django enables `CsrfViewMiddleware` (flag new `@csrf_exempt`); Flask needs Flask-WTF `CSRFProtect`; FastAPI, Starlette, and Express have nothing built in.
- Defenses (OWASP): a token compared in constant time (`hmac.compare_digest`, [`crypto.timingSafeEqual`](nodejs.md#compare-secrets-in-constant-time)), a custom request header, or `Sec-Fetch-Site` with an `Origin` fallback. `SameSite` is defense in depth: `Lax` still sends cookies on top-level GETs, so GET never changes state. Webhooks exempt from CSRF verify a signature.
- Salesforce: Visualforce changes state only through a form POST ([Visualforce CSRF](salesforce/visualforce.md#csrf--state-changes)); `@AuraEnabled` calls carry the Lightning framework's token.

### SSRF Prevention

```python
# ❌ Fetches any URL the caller supplies: internal services, cloud metadata
requests.get(url, timeout=5)

# ✅ Exact HTTPS host allowlist; reject anything another URL parser could read differently
from urllib.parse import urlsplit

import requests

ALLOWED_HOSTS = {"api.example.com", "cdn.example.com"}


def is_safe_url(url: str) -> bool:
    # Backslashes, userinfo, non-ASCII, spaces, and control characters are where urlsplit()
    # and urllib3 disagree: "https://evil.com\@api.example.com/" connects to evil.com
    if not url.isascii() or "\\" in url or any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.username is None
        and parts.password is None
        and parts.hostname in ALLOWED_HOSTS
        and port in (None, 443)
    )


def fetch_preview(url: str) -> bytes:
    if not is_safe_url(url):
        raise ValueError("URL not allowed")
    # A redirect can point anywhere, including internal addresses: don't follow it
    return requests.get(url, timeout=5, allow_redirects=False).content
```

```typescript
// ✅ Node.js: fetch uses this same WHATWG parser; redirects are refused
const ALLOWED_HOSTS = new Set(['api.example.com', 'cdn.example.com']);

function allowedUrl(input: string): URL | null {
  const url = URL.canParse(input) ? new URL(input) : null;
  const ok = url?.protocol === 'https:' && ALLOWED_HOSTS.has(url.hostname)
    && !url.username && !url.password && !url.port;
  return ok ? url : null;
}

const target = allowedUrl(String(req.query.url));
if (!target) return res.status(400).end();
const response = await fetch(target, { redirect: 'error', signal: AbortSignal.timeout(5000) });
```

- Better still: take an allowlist key from the caller and map it to a fixed URL.
- Open-ended destinations (webhooks, link previews): resolve every A and AAAA record, reject private, loopback, link-local (`169.254.169.254`), and reserved addresses, and connect to the vetted IP so DNS can't change in between; or route through an egress proxy that enforces this.
- Refuse redirects or re-validate every hop. Host and IP string denylists are bypassable (`127.0.0.2`, `[::1]`, `0.0.0.0`, `localhost.`, decimal forms).
- Salesforce: call out only to Named Credential endpoints with URL-encoded caller data ([Callouts](salesforce/apex.md#callouts--integrations)).

### IDOR (Insecure Direct Object Reference)

```python
# ❌ Any user can read any order
order = session.get(Order, order_id)

# ✅ Scope the query to the caller; the same 404 for missing and foreign orders
order = session.scalars(
    select(Order).where(Order.id == order_id, Order.user_id == current_user.id)
).one_or_none()
if order is None:
    raise NotFoundError(order_id)
```

Prisma: `findFirst({ where: { id, userId: req.user.id } })`. Random IDs (UUIDv4) slow enumeration but are not access control. Salesforce: an `@AuraEnabled` method re-queries a client-supplied Id in user mode ([Apex data access](salesforce/apex.md#data-access-security)).

### Command Injection Prevention

```python
# ❌ The shell parses the input
subprocess.run(f"convert {filename} out.png", shell=True)

# ✅ No shell; a resolved absolute path can't be read as an option
path = (UPLOAD_DIR / filename).resolve()  # UPLOAD_DIR: an absolute, resolved Path
if not path.is_relative_to(UPLOAD_DIR):
    raise ValueError("path escapes the upload directory")
subprocess.run(["convert", str(path), "out.png"], check=True, timeout=30)
```

- Argument lists stop shell injection, not option injection: a value starting with `-` becomes a flag, so use `--` where supported or absolute paths. Node.js: `execFile`/`spawn` with an array and no `shell: true`.
- `shlex.quote()` only builds POSIX shell strings when a shell is unavoidable; it is not validation, and in an argument list its quotes become part of the value.
- Tools that interpret file names (ImageMagick coders such as `msl:`) are restricted in the tool's own policy.

### Deserialization & File Paths

- Untrusted `pickle`, `shelve`, `marshal`, `jsonpickle`, and `yaml.load` without `SafeLoader` execute code (S301, S506); use JSON or `yaml.safe_load`.
- Resolve user paths and check containment (`resolved.is_relative_to(base)`; [Node.js](nodejs.md#nodejs-security)). `tarfile` extraction passes `filter="data"` (the default only from Python 3.14); hand-written zip loops check every entry name.

## Data Protection

Secrets come from the environment or a secret manager, never code, committed `.env` files, fixtures, images, or CI logs; a leaked secret is rotated, not just deleted (ask the author).

### Error Messages

Clients get a generic message and a correlation ID; stack traces, SQL, and internal hostnames stay in server logs. Salesforce: `AuraHandledException` with a user-safe message. Principles: [Error Handling](cross-cutting/error-handling-principles.md#core-principles).

## API Security

### Rate Limiting

Login, password reset, OTP, signup, and expensive endpoints need per-account and per-IP limits (429 with `Retry-After`). When a new one has no limiter in code, ask whether the gateway enforces one before reporting it.

### CORS Configuration

```typescript
// ❌ Reflects any Origin with credentials: every site can read the user's data
app.use(cors({ origin: true, credentials: true }));

// ✅ Exact origins when credentials are allowed
app.use(cors({ origin: ['https://app.example.com'], credentials: true }));
```

`*` (the `cors()` default) is fine for public, unauthenticated data; browsers refuse it on credentialed requests. Flag reflected or `null` origins with credentials, unanchored regexes and suffix checks, and `*` on intranet-only services.

### HTTP Headers

`app.use(helmet())` sets a CSP, HSTS, `X-Content-Type-Options`, `frame-ancestors 'self'`, and `X-XSS-Protection: 0`, which disables the legacy browser filter on purpose (`xssFilter: true` sets the same). HSTS `includeSubDomains` or `preload` only when every subdomain serves HTTPS.

## Cryptography

AEAD (AES-GCM, ChaCha20-Poly1305) with a unique nonce per message; no ECB, no CBC without a MAC; AES-128 and AES-256 are both fine, RSA keys ≥2048 bits. No custom cryptography; keys come from a KMS or secret manager; secrets and signatures are compared in constant time.

### Common Mistakes

```typescript
// ❌ Predictable token, and a fast hash for passwords
const token = Math.random().toString(36);
const hash = crypto.createHash('sha256').update(password).digest('hex');

// ✅ CSPRNG token and a password hash
const token = crypto.randomBytes(32).toString('hex');
const hash = await bcrypt.hash(password, 12);
```

Python: `secrets.token_urlsafe(32)` and `argon2.PasswordHasher().hash(password)` (S311, S324).

## Dependency Security

When the PR touches manifests or lockfiles: the lockfile changes with the manifest, new packages are maintained and justified, and ranges don't widen without reason.

### Audit Commands

Read `npm audit`, `pip-audit`, or Snyk results from CI, or ask the author; the review doesn't run them. Salesforce: Code Analyzer on local paths ([Tooling](salesforce/platform.md#tooling)).

## Logging & Monitoring

### Secure Logging

```typescript
// ❌ Credentials and PII in the log
logger.info(`login ${email} password=${password}`);

// ✅ Structured fields with IDs; the outcome comes from the code path
logger.info({ userId: user.id, success }, 'login attempt');
```

No passwords, tokens, session IDs, API keys, or card numbers; PII becomes IDs. Structured logs prevent forged lines (plain text: strip CR/LF from input). New auth and permission flows log security events.

## Salesforce Platform Security

Load the [Salesforce Platform Guide](salesforce/platform.md) first: its [Security Model](salesforce/platform.md#security-model) sets the API-version defaults and its [severity calibration](salesforce/platform.md#severity-calibration) applies to Salesforce findings.

- Sharing, CRUD, and FLS follow each class's `<apiVersion>`; system-mode escapes have a documented reason ([Apex data access](salesforce/apex.md#data-access-security)). `@AuraEnabled`, `@RemoteAction`, `@RestResource`, `webservice`, `@InvocableMethod`, and Visualforce controllers are public entry points ([guest access](salesforce/platform.md#guest-and-experience-cloud-users)).
- Owners: [SOQL injection](salesforce/soql-sosl.md#soql-injection), [UI escape hatches](cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce), [credentials and endpoints](salesforce/metadata.md#integration-endpoints--credentials), [static review only](salesforce/platform.md#static-review-only).

## Severity

- 🔴 blocking: exploitable as written, or exposes data or secrets.
- 🟡 important: exploitable under specific conditions, or removes a defense-in-depth layer.
- 🟢 nit: hardening with little risk. 💡 suggestion: optional.

## References

- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/)
- [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
- [NIST SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)
