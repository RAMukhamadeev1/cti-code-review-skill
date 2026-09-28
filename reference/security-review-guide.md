# Security Review Guide

Security-focused code review checklist based on the OWASP Top 10 and best practices, with examples for JavaScript/TypeScript (browser and Node.js), Python, and Salesforce.

## Authentication & Authorization

### Authentication
- [ ] Passwords hashed with strong algorithm (bcrypt, argon2)
- [ ] Password complexity requirements enforced
- [ ] Account lockout after failed attempts
- [ ] Secure password reset flow
- [ ] Multi-factor authentication for sensitive operations
- [ ] Session tokens are cryptographically random
- [ ] Session timeout implemented

### Authorization
- [ ] Authorization checks on every request
- [ ] Principle of least privilege applied
- [ ] Role-based access control (RBAC) properly implemented
- [ ] No privilege escalation paths
- [ ] Direct object reference checks (IDOR prevention)
- [ ] API endpoints protected appropriately

### JWT Security
```typescript
// ❌ Insecure JWT configuration
jwt.sign(payload, 'weak-secret');

// ✅ Secure JWT configuration (RS256 signs with a private key loaded from a secret manager)
jwt.sign(payload, privateKey, {
  algorithm: 'RS256',
  expiresIn: '15m',
  issuer: 'your-app',
  audience: 'your-api'
});

// ❌ Not verifying JWT properly
const decoded = jwt.decode(token);  // No signature verification!

// ✅ Verify signature and claims
const decoded = jwt.verify(token, publicKey, {
  algorithms: ['RS256'],
  issuer: 'your-app',
  audience: 'your-api'
});
```

## Input Validation

### SQL Injection Prevention

**The #1 rule**: Always use parameterized queries. Never concatenate user input into SQL strings.

Every major language and framework has a parameterized query mechanism:
- Python: `cursor.execute("SELECT ...", params)` / ORM filter methods
- Node.js: `client.query("SELECT ...", [args])` / Prisma ORM
- Salesforce Apex: static SOQL with bind variables (`WHERE Name = :name`) / `Database.queryWithBinds(query, binds, AccessLevel.USER_MODE)` for dynamic SOQL (API 57.0+). See [SQL Injection Prevention](cross-cutting/sql-injection-prevention.md#salesforce-apex-soqlsosl).

> **See [SQL Injection Prevention Guide](cross-cutting/sql-injection-prevention.md) for complete cross-language examples, ORM unsafe patterns, dynamic identifier handling, and detection tools.**

### XSS Prevention

**The #1 rule**: Rely on template and DOM auto-escaping. Audit every escape hatch.

Most templates escape by default, and text-only DOM APIs never parse HTML. Audit the escape hatches:
- Plain DOM: `textContent` is safe. Audit `innerHTML`, `outerHTML`, `insertAdjacentHTML`, and `document.write`.
- Node.js templates: audit raw output, such as EJS `<%- %>`, Handlebars `{{{ }}}`, and Pug `!{}`.
- Python (Jinja2): a bare `Environment()` doesn't escape, so enable `autoescape` (for example `select_autoescape()`). Audit `|safe` and `markupsafe.Markup()` around untrusted data.
- Salesforce: audit Visualforce `escape="false"` and merge fields inside `<script>` without `JSENCODE`, Aura `<aura:unescapedHtml>`, and LWC `lwc:dom="manual"` combined with `innerHTML`. See [XSS Prevention](cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce).

For defense-in-depth, configure Content Security Policy (CSP) with nonce-based `script-src`.

> **See [XSS Prevention Guide](cross-cutting/xss-prevention.md) for examples by technology, CSP configuration, input validation vs output encoding, and detection tools.**

### CSRF Prevention

**CSRF Token Implementation**
```typescript
// ✅ Server: generate and validate CSRF token
import crypto from 'node:crypto';

function generateCsrfToken(): string {
  return crypto.randomBytes(32).toString('hex');
}

// Constant-time comparison; timingSafeEqual throws if the lengths differ
function tokensMatch(received: unknown, expected: string | undefined): boolean {
  if (typeof received !== 'string' || typeof expected !== 'string') return false;
  const a = Buffer.from(received);
  const b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Middleware: validate token on state-changing requests
app.post('/api/data', (req, res) => {
  if (!tokensMatch(req.headers['x-csrf-token'], req.session.csrfToken)) {
    return res.status(403).json({ error: 'Invalid CSRF token' });
  }
  // ...handle request
});
```

**Python (framework-neutral)**
```python
# ✅ Synchronizer token: one random token per session, checked on every state change
import hmac
import secrets

def issue_csrf_token(session: dict) -> str:
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token  # render into a hidden form field or send as a request header

def verify_csrf_token(session: dict, submitted: str | None) -> bool:
    expected = session.get("csrf_token")
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected.encode(), submitted.encode())  # constant time

# Most web frameworks enable CSRF protection by default.
# ❌ Never exempt a state-changing endpoint from the framework's CSRF protection
#    without a documented reason (for example, a webhook verified by its signature)
```

**Salesforce (Visualforce)**
```html
<!-- ❌ action= on apex:page runs the method on page load: a GET request with no CSRF token -->
<apex:page controller="InvoiceController" action="{!markPaid}">
</apex:page>

<!-- ✅ State changes go through a form POST, which carries the Visualforce CSRF token -->
<apex:page controller="InvoiceController">
    <apex:form>
        <apex:commandButton value="Mark as paid" action="{!markPaid}"/>
    </apex:form>
</apex:page>
```

- Keep controller constructors, getters, and methods called from `<apex:page action>` free of DML: they run on GET requests, where no token is checked. Static analysis: PMD `VfCsrf` (page `action`) and `ApexCSRF` (DML in constructors and initializers).
- Apex called from LWC or Aura goes through the Lightning framework, whose requests carry the framework's own CSRF token, so `@AuraEnabled` methods need no custom token. They still need server-side access checks (see [IDOR](#idor-insecure-direct-object-reference)).

> 📖 Depth: [Visualforce CSRF](salesforce/visualforce.md#csrf--state-changes)

**SameSite Cookie**
```typescript
// ✅ Set SameSite cookie as additional defense
res.cookie('session', sessionId, {
  httpOnly: true,
  secure: true,
  sameSite: 'strict',  // or 'lax' to allow top-level navigation GET requests
  maxAge: 3600000,
});
```

### SSRF Prevention

**Python**
```python
# ❌ Vulnerable: fetches whatever URL the caller supplies
import requests

def fetch_preview(url: str) -> bytes:
    return requests.get(url, timeout=5).content

# ✅ Validate the URL against an allowlist first
from urllib.parse import urlparse

ALLOWED_HOSTS = {'api.example.com', 'cdn.example.com'}

def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS

def fetch_preview(url: str) -> bytes:
    if not is_safe_url(url):
        raise ValueError('URL not allowed')
    # Don't follow redirects: a redirect can point to an internal address
    return requests.get(url, timeout=5, allow_redirects=False).content
```

**Node.js**
```typescript
// ❌ Vulnerable: fetching arbitrary URLs
const url = req.query.url;
const response = await fetch(url);

// ✅ Validate URL before fetching
const ALLOWED_DOMAINS = ['api.internal.com'];

function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // Block internal IPs
    if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') {
      return false;
    }
    if (parsed.hostname.match(/^10\.|^172\.(1[6-9]|2\d|3[01])\.|^192\.168\./)) {
      return false; // Block private IP ranges
    }
    return ALLOWED_DOMAINS.includes(parsed.hostname);
  } catch {
    return false;
  }
}
```

**Salesforce Apex**
```apex
// ❌ Endpoint built from caller input (endpointUrl is an @AuraEnabled parameter)
HttpRequest req = new HttpRequest();
req.setEndpoint(endpointUrl);
req.setMethod('GET');

// ✅ Fixed Named Credential endpoint; the caller supplies only data, URL-encoded
HttpRequest req = new HttpRequest();
req.setEndpoint('callout:Billing_API/v1/invoices/' + EncodingUtil.urlEncode(invoiceNumber, 'UTF-8'));
req.setMethod('GET');
HttpResponse res = new Http().send(req);
```

Call out only to Named Credential endpoints (`callout:Name/path`), never to a URL the caller supplies. Remote Site Settings are an org-wide allowlist of hosts, not a validation layer: any URL on a listed host is still reachable.

> 📖 Depth: [Apex callouts](salesforce/apex.md#callouts--integrations)

### IDOR (Insecure Direct Object Reference)

**Python (SQLAlchemy)**
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

# ❌ Vulnerable: no ownership check, so any user can read any order
def get_order(session: Session, current_user: User, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise NotFoundError(order_id)
    return order

# ✅ Scope the query to the current user
def get_order(session: Session, current_user: User, order_id: int) -> Order:
    stmt = select(Order).where(Order.id == order_id, Order.user_id == current_user.id)
    order = session.scalars(stmt).one_or_none()
    if order is None:
        # Same "not found" (HTTP 404) for missing and foreign orders, so existence isn't revealed
        raise NotFoundError(order_id)
    return order
```

**Node.js (Prisma)**
```typescript
// ❌ Vulnerable: no authorization check
app.get('/api/orders/:id', async (req, res) => {
  const order = await db.order.findUnique({
    where: { id: Number(req.params.id) }
  });
  res.json(order);
});

// ✅ Include user context in query
app.get('/api/orders/:id', async (req, res) => {
  const order = await db.order.findFirst({
    where: {
      id: Number(req.params.id),
      userId: req.user.id,  // Scope to current user
    }
  });
  if (!order) return res.status(404).json({ error: 'Not found' });
  res.json(order);
});
```

**Salesforce Apex**
```apex
// ❌ Trusts the client's Id: without sharing and, at API 66.0 and earlier, a system-mode query
public without sharing class InvoiceController {
    @AuraEnabled
    public static Invoice__c getInvoice(Id invoiceId) {
        return [SELECT Id, Name, Amount__c FROM Invoice__c WHERE Id = :invoiceId];
    }
}

// ✅ Re-query in user mode: sharing, CRUD, and FLS decide what the caller can see
public with sharing class InvoiceController {
    @AuraEnabled(cacheable=true)
    public static Invoice__c getInvoice(Id invoiceId) {
        List<Invoice__c> rows = [
            SELECT Id, Name, Amount__c FROM Invoice__c
            WHERE Id = :invoiceId
            WITH USER_MODE
        ];
        return rows.isEmpty() ? null : rows[0];
    }
}
```

An `@AuraEnabled` method that takes a record Id must never trust it: re-query in user mode (in a `with sharing` class) before returning or changing the record.

> 📖 Depth: [Apex data access](salesforce/apex.md#data-access-security)

**UUID vs auto-increment IDs**
```typescript
// ❌ Auto-increment IDs can be enumerated
// GET /api/users/1, /api/users/2, /api/users/3 ...

// ✅ UUIDs are unpredictable
// GET /api/users/550e8400-e29b-41d4-a716-446655440000

// ⚠️ UUIDs only prevent enumeration; they are not access control
// You still need to verify that the current user may access the resource
```

### Command Injection Prevention

**Python**
```python
# ❌ Vulnerable: shell=True
import subprocess
subprocess.run(f"convert {filename} output.png", shell=True)

# ✅ Use list arguments without shell
subprocess.run(['convert', filename, 'output.png'], check=True)

# ✅ Validate and sanitize input
import shlex
safe_filename = shlex.quote(filename)
```

**Node.js**
```typescript
// ❌ Vulnerable: exec with string interpolation
import { exec } from 'node:child_process';
exec(`convert ${filename} output.png`);

// ✅ Use execFile with array arguments (no shell)
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execFileAsync = promisify(execFile);
await execFileAsync('convert', [filename, 'output.png']);

// ❌ Never pass user input to shell
exec(`echo ${userInput}`);  // userInput = "; rm -rf /"

// ✅ Sanitize or use non-shell alternatives
import { writeFile } from 'node:fs/promises';
await writeFile('output.txt', userInput);  // No shell involved
```

## Data Protection

### Sensitive Data Handling
- [ ] No secrets in source code
- [ ] Secrets stored in environment variables or secret manager
- [ ] Sensitive data encrypted at rest
- [ ] Sensitive data encrypted in transit (HTTPS)
- [ ] PII handled according to regulations (GDPR, etc.)
- [ ] Sensitive data not logged
- [ ] Secure data deletion when required

### Configuration Security
```yaml
# ❌ Secrets in config files
database:
  password: "super-secret-password"

# ✅ Reference environment variables
database:
  password: ${DATABASE_PASSWORD}
```

### Error Messages
```typescript
// ❌ Leaking sensitive information
catch (error) {
  return res.status(500).json({
    error: error.stack,  // Exposes internal details
    query: sqlQuery      // Exposes database structure
  });
}

// ✅ Generic error messages
catch (error) {
  logger.error('Database error', { error, userId });  // Log internally
  return res.status(500).json({
    error: 'An unexpected error occurred'
  });
}
```

## API Security

### Rate Limiting
- [ ] Rate limiting on all public endpoints
- [ ] Stricter limits on authentication endpoints
- [ ] Per-user and per-IP limits
- [ ] Graceful handling when limits exceeded

### CORS Configuration
```typescript
// ❌ Overly permissive CORS
app.use(cors({ origin: '*' }));

// ✅ Restrictive CORS
app.use(cors({
  origin: ['https://your-app.com'],
  methods: ['GET', 'POST'],
  credentials: true
}));
```

### HTTP Headers
```typescript
// Security headers to set
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
    }
  },
  hsts: { maxAge: 31536000, includeSubDomains: true },
  noSniff: true,
  xssFilter: true,
  frameguard: { action: 'deny' }
}));
```

## Cryptography

### Secure Practices
- [ ] Using well-established algorithms (AES-256, RSA-2048+)
- [ ] Not implementing custom cryptography
- [ ] Using cryptographically secure random number generation
- [ ] Proper key management and rotation
- [ ] Secure key storage (HSM, KMS)

### Common Mistakes
```typescript
// ❌ Weak random generation
const token = Math.random().toString(36);

// ✅ Cryptographically secure random
import crypto from 'node:crypto';
const token = crypto.randomBytes(32).toString('hex');

// ❌ MD5/SHA1 for passwords
const hash = crypto.createHash('md5').update(password).digest('hex');

// ✅ Use bcrypt or argon2
import bcrypt from 'bcrypt';
const hash = await bcrypt.hash(password, 12);
```

## Dependency Security

### Checklist
- [ ] Dependencies from trusted sources only
- [ ] No known vulnerabilities (npm audit, pip-audit)
- [ ] Dependencies kept up to date
- [ ] Lock files committed (package-lock.json, poetry.lock / uv.lock, hashed requirements.txt)
- [ ] Minimal dependency usage
- [ ] License compliance verified

### Audit Commands
```bash
# Node.js
npm audit
npm audit fix

# Python
pip-audit

# Salesforce: local static analysis only, never with --target-org during review.
# The Security tag includes PMD security rules and RetireJS checks for vulnerable
# JavaScript libraries, including those in static resources.
sf code-analyzer run --workspace force-app --rule-selector Security

# General
snyk test
```

## Logging & Monitoring

### Secure Logging
- [ ] No sensitive data in logs (passwords, tokens, PII)
- [ ] Logs protected from tampering
- [ ] Appropriate log retention
- [ ] Security events logged (login attempts, permission changes)
- [ ] Log injection prevented

```typescript
// ❌ Logging sensitive data
logger.info(`User login: ${email}, password: ${password}`);

// ✅ Safe logging
logger.info('User login attempt', { email, success: true });
```

## Salesforce Platform Security

> Load the [Salesforce Platform Guide](salesforce/platform.md) first — it defines the security model, API-version rules, and [severity calibration](salesforce/platform.md#severity-calibration) for Salesforce findings. Each item below links to the guide that owns the topic.

### Sharing, CRUD, and FLS
- [ ] Each class is judged against its own `<apiVersion>` (in its `-meta.xml`): from API 67.0 (Summer '26) SOQL, SOSL, and DML run in user mode by default and a class without a sharing keyword runs `with sharing`; earlier versions default to system mode ([Security Model](salesforce/platform.md#security-model))
- [ ] CRUD and FLS are enforced wherever the version default doesn't do it: `as user` DML, `AccessLevel.USER_MODE` on `Database` methods, `Security.stripInaccessible` for records sent to or received from the client ([Data Access Security](salesforce/apex.md#data-access-security))
- [ ] Queries use `WITH USER_MODE`, and no `WITH SECURITY_ENFORCED` remains (it doesn't compile at API 67.0+) ([Access Mode in Queries](salesforce/soql-sosl.md#access-mode-in-queries))
- [ ] Every system-mode escape (`without sharing`, `WITH SYSTEM_MODE`, `AccessLevel.SYSTEM_MODE`, `as system`) has a documented reason and the narrowest possible scope
- [ ] Access-sensitive logic lives in handler classes, not trigger bodies: triggers run in system mode at every API version ([Trigger Architecture](salesforce/apex-triggers.md#trigger-architecture))

### Entry points and guest access
- [ ] Every entry point is treated as a public API: `@AuraEnabled` methods (callable directly, not only from the component that uses them), `@RemoteAction`, `@RestResource` and `webservice` methods, `@InvocableMethod` actions in screen flows, and Visualforce controllers and extensions ([Security Model](salesforce/platform.md#security-model))
- [ ] Client input, including record Ids, is validated and re-checked on the server with user-mode queries, never trusted ([IDOR](#idor-insecure-direct-object-reference))
- [ ] Components with Experience Cloud targets (`lightningCommunity__Page`, `lightningCommunity__Default`) make their Apex reachable by guest users, and that Apex enforces sharing and CRUD/FLS itself ([Component Configuration](salesforce/lwc.md#component-configuration))
- [ ] Guest-user access changes (guest profile, guest sharing rules, public site pages) have a security sign-off; guests can't get View All, Modify All, or edit and delete object permissions, and guest sharing rules grant Read at most ([Permission Sets, Groups & Profiles](salesforce/metadata.md#permission-sets-groups--profiles))
- [ ] Errors sent to the client carry a user-safe message (`AuraHandledException`), never stack traces, queries, or data the user can't see ([The LWC-Apex Contract](salesforce/lwc.md#the-lwc-apex-contract))

### Secrets and integration metadata
- [ ] No secrets, tokens, or passwords in Apex, Custom Labels, Custom Metadata, custom settings, static resources, or metadata XML ([Integration Endpoints & Credentials](salesforce/metadata.md#integration-endpoints--credentials))
- [ ] Callouts go through Named Credentials backed by External Credentials, with principal access granted through permission sets; no hard-coded credentials or plain-HTTP endpoints in code (PMD `ApexSuggestUsingNamedCred`, `ApexInsecureEndpoint`)
- [ ] Remote Site Settings use HTTPS and keep `disableProtocolSecurity` false; CSP Trusted Sites and CORS allowlist entries name exact origins and allow only what they need
- [ ] OAuth integrations request the narrowest scopes, and new ones are External Client Apps (new connected apps can't be created since Spring '26)
- [ ] Encryption keys and IVs are generated (`Crypto.generateAesKey`, `Crypto.encryptWithManagedIV`) or stored as protected secrets, never hard-coded (PMD `ApexBadCrypto`)

### Local static analysis only
- [ ] The review stays static: nobody deploys, runs anonymous Apex or Apex tests, or queries an org for it; test results, coverage, and debug logs come from the author or CI ([Static Review Only](salesforce/platform.md#static-review-only))
- [ ] Salesforce Code Analyzer v5 runs on local paths only, for example `sf code-analyzer run --workspace force-app --rule-selector Security` (the v4 `sf scanner` commands were retired in August 2025)
- [ ] No `--target-org` and no `apexguru` rules (a broad selector such as `all` can include them): ApexGuru is the only engine that contacts an org, and without `--target-org` it falls back to the Salesforce CLI's default org
- [ ] Analyzer findings are triaged against the file's `<apiVersion>` and entry point before they are reported ([Tooling](salesforce/platform.md#tooling))

## Security Review Severity Levels

| Severity | Description | Action |
|----------|-------------|--------|
| **Critical** | Immediate exploitation possible, data breach risk | Block merge, fix immediately |
| **High** | Significant vulnerability, requires specific conditions | Block merge, fix before release |
| **Medium** | Moderate risk, defense in depth concern | Should fix, can merge with tracking |
| **Low** | Minor issue, best practice violation | Nice to fix, non-blocking |
| **Info** | Suggestion for improvement | Optional enhancement |
