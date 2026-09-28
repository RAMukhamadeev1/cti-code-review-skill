# XSS Prevention Guide

Language-agnostic Cross-Site Scripting prevention strategies with examples for plain DOM JavaScript, server-side templates (Node.js, Python), and Salesforce UI technologies (LWC, Aura, Visualforce).

> **Related**: [Security Review Guide](../security-review-guide.md) for comprehensive security checklist and decision framework.

## XSS Types

XSS belongs to A05:2025 Injection in the OWASP Top 10 (it was merged into Injection, then A03, in the 2021 edition). Three variants:

| Type | Description | Attack Vector |
|------|-------------|---------------|
| **Reflected** | Malicious script reflected off the server in the response | URL parameters, form submissions |
| **Stored (Persistent)** | Malicious script stored in the database and served to users | Comments, profiles, messages |
| **DOM-based** | Client-side JavaScript modifies the DOM unsafely | `innerHTML`, `document.write()`, `eval()` |

## Universal Prevention Strategy

1. **Output encoding** — encode data for the context it's rendered in (HTML, JS, URL, CSS)
2. **Content Security Policy (CSP)** — restrict which scripts can execute
3. **Input sanitization** — only when rich text is required (DOMPurify)
4. **Template auto-escaping** — rely on template and DOM defaults; audit every escape hatch

> **Key distinction**: Input validation prevents bad data from entering the system. Output encoding prevents bad data from being rendered as code. Both are necessary; neither alone is sufficient.

---

## Examples by Technology

### Plain DOM (JavaScript)

HTML sinks parse their argument as markup, so a value such as `<img src=x onerror=alert(1)>` runs script in the page. Text APIs never parse markup. Use an HTML sink only for markup you sanitized or generated yourself.

```javascript
import DOMPurify from 'dompurify';

// ❌ HTML sinks: innerHTML, outerHTML, insertAdjacentHTML, document.write
commentEl.innerHTML = comment.body;
listEl.insertAdjacentHTML('beforeend', `<li>${comment.author}</li>`);

// ✅ Text APIs: textContent, or nodes built with createElement
commentEl.textContent = comment.body;
const item = document.createElement('li');
item.textContent = comment.author;
listEl.append(item);

// ✅ When the feature needs HTML (rich text), sanitize it first
commentEl.innerHTML = DOMPurify.sanitize(comment.bodyHtml);

// ❌ URL attributes run javascript: URLs ("javascript:alert(1)" runs on click)
link.href = profile.website;

// ✅ Parse the URL and allow only known protocols before setting href or src
const SAFE_PROTOCOLS = new Set(['https:', 'http:', 'mailto:']);

function toSafeUrl(value) {
  try {
    const url = new URL(value, location.origin);
    return SAFE_PROTOCOLS.has(url.protocol) ? url.href : null;
  } catch {
    return null; // not a valid URL
  }
}

const href = toSafeUrl(profile.website);
if (href !== null) {
  link.href = href;
}

// ❌ A string timer is eval
setTimeout(`showGreeting('${name}')`, 1000);

// ✅ Pass a function
setTimeout(() => showGreeting(name), 1000);
```

> 📖 Depth: [Safe DOM updates](../javascript.md#safe-dom-updates) · [Security-sensitive APIs](../javascript.md#security-sensitive-apis)

### Server-Side Templates (Node.js and Python)

Template engines escape HTML by default, and each one has a raw-output syntax that turns escaping off; audit every use of it. Auto-escaping is HTML escaping only: it does not make a value safe inside `<script>`, inline event handlers (`onclick="..."`), `style`, or URL attributes (`href="javascript:..."`).

| Engine | Escaped (default) | Raw output to audit |
| --- | --- | --- |
| EJS | `<%= value %>` | `<%- value %>` |
| Handlebars | `{{value}}` | `{{{value}}}`, helpers that return `new Handlebars.SafeString(...)` |
| Pug | `#{value}`, `p= value` | `!{value}`, `p!= value` |
| Nunjucks | `{{ value }}` (`autoescape` defaults to true) | the `safe` filter, `autoescape: false` |
| Jinja2 | `{{ value }}`, only when autoescaping is on | the `safe` filter, `Markup()` around pre-built strings, `{% autoescape false %}` |

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

# ❌ A plain Jinja2 Environment does not autoescape (autoescape defaults to False)
env = Environment(loader=FileSystemLoader("templates"))

# ✅ Autoescape .html, .htm, and .xml templates and templates created from strings
env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape())

# ❌ The f-string interpolates first, then Markup() marks the unescaped result as safe
bio_html = Markup(f"<p>{user_bio}</p>")

# ✅ Markup.format() escapes its arguments
bio_html = Markup("<p>{}</p>").format(user_bio)

# ❌ The safe filter turns escaping off for that value
# <p>{{ user_bio|safe }}</p>
```

### Salesforce (LWC, Aura, Visualforce)

LWC and Aura expressions and Visualforce merge fields in HTML are encoded by the platform, so XSS comes from the escape hatches. Visualforce does not encode merge fields inside `<script>` or `<style>` blocks or in components with `escape="false"`; those need the encoding function for their context.

```html
<!-- LWC template -->
<!-- ✅ {expression} bindings render as text: markup in the value is not parsed -->
<p>{account.Description}</p>

<!-- ❌ lwc:dom="manual" filled from record data; the component JS does
     this.refs.notes.innerHTML = this.account.Notes__c; -->
<div lwc:dom="manual" lwc:ref="notes"></div>

<!-- ✅ lightning-formatted-rich-text keeps only allowed tags and attributes;
     for plain text, set textContent instead of innerHTML -->
<lightning-formatted-rich-text value={account.Notes__c}></lightning-formatted-rich-text>

<!-- Aura component -->
<!-- ❌ aura:unescapedHtml renders its value as raw HTML -->
<aura:unescapedHtml value="{!v.body}"/>

<!-- Visualforce page -->
<!-- ❌ escape="false" turns off HTML encoding -->
<apex:outputText value="{!userInput}" escape="false"/>

<!-- ✅ Keep the default encoding -->
<apex:outputText value="{!userInput}"/>

<script>
    // ❌ Merge field in a JavaScript string: a quote in the parameter ends the string
    const q = '{!$CurrentPage.parameters.q}';

    // ✅ JSENCODE for JavaScript strings (JSINHTMLENCODE in on* attributes, URLENCODE in URLs)
    const q = '{!JSENCODE($CurrentPage.parameters.q)}';
</script>
```

> 📖 Depth: [LWC security](../salesforce/lwc.md#security-in-the-browser) · [Visualforce output encoding](../salesforce/visualforce.md#output-encoding) · [Aura security](../salesforce/aura.md#security)

### Server-Side Rendering

```typescript
// ❌ SSR: injecting raw user data into HTML
const html = `<div>${userInput}</div>`;

// ✅ Always escape server-side rendered content
import escapeHtml from 'escape-html';
const html = `<div>${escapeHtml(userInput)}</div>`;

// ❌ JSON serialization without escaping
const json = JSON.stringify({ name: userInput });
// userInput could contain </script> to break out of script tags

// ✅ JSON in HTML: escape < and >
const safe = JSON.stringify({ name: userInput })
  .replace(/</g, '\\u003c')
  .replace(/>/g, '\\u003e');
```

---

## Content Security Policy (CSP)

CSP is defense-in-depth. Even if XSS escapes output encoding, CSP limits what an attacker can do.

```nginx
# ✅ Recommended CSP (strict)
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'nonce-{random}' 'strict-dynamic';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https:;
  object-src 'none';
  base-uri 'self';
  form-action 'self';
  frame-ancestors 'none';
```

```typescript
// ✅ Express middleware
import helmet from 'helmet';

app.use(helmet.contentSecurityPolicy({
  directives: {
    defaultSrc: ["'self'"],
    scriptSrc: ["'self'", "'nonce-{random}'"],
    styleSrc: ["'self'", "'unsafe-inline'"],
    objectSrc: ["'none'"],
    baseUri: ["'self'"],
    formAction: ["'self'"],
    frameAncestors: ["'none'"],
  },
}));
```

```html
<!-- ✅ CSP nonce in script tags -->
<script nonce="{random}">
  // Allowed by CSP
</script>

<!-- ❌ Inline event handlers (blocked by CSP without 'unsafe-inline') -->
<button onclick="doSomething()">Click</button>

<!-- ✅ Event listeners in JS with nonce -->
<script nonce="{random}">
  document.getElementById('btn').addEventListener('click', doSomething);
</script>
```

**CSP anti-patterns to avoid:**
- `script-src 'unsafe-inline'` without nonce/hash
- `script-src 'unsafe-eval'` (enables `eval()`)
- `default-src *` (allows loading from any origin)
- `script-src https:` (allows any HTTPS origin, including attacker-controlled)

**Salesforce**: Lightning Experience enforces its own CSP on LWC and Aura components, in addition to Lightning Web Security, and component code can't relax it. Components can't load JavaScript from a third-party origin, even a trusted one, so libraries ship as static resources. Other third-party origins (API calls, images, fonts, styles, frames, media) are allowed only through Trusted URLs (formerly CSP Trusted Sites; metadata type `CspTrustedSite`), so review every new entry (see [Integration Endpoints & Credentials](../salesforce/metadata.md#integration-endpoints--credentials)).

---

## Input Validation vs Output Encoding

| Layer | What | When | Example |
|-------|------|------|---------|
| **Input validation** | Reject/clean data on entry | At API boundary | Reject `<script>` in a name field |
| **Output encoding** | Encode data for render context | At render time | `&lt;script&gt;` in HTML |

**Rule**: Input validation is a convenience (reject obviously bad data). Output encoding is the security boundary. Never rely on input validation alone.

---

## Detection & Testing

```bash
# Automated scanning
# OWASP ZAP
zap-cli quick-scan --spider https://example.com

# Manual testing payloads
<script>alert(1)</script>
<img src=x onerror=alert(1)>
" onmouseover="alert(1)
javascript:alert(1)
'-alert(1)-'

# Static analysis (code review): HTML sinks and raw template output
grep -rnE 'innerHTML|outerHTML|insertAdjacentHTML|document\.write|<%-|\{\{\{|!\{|\| *safe|Markup\(|SafeString' src/
# Code execution sinks: eval, new Function, string timers
grep -rnE "eval\(|new Function|set(Timeout|Interval)\( *[\"'\`]" src/

# Salesforce: escape hatches in LWC, Aura, and Visualforce
grep -rnE 'escape="false"|lwc:dom="manual"|aura:unescapedHtml|innerHTML' force-app/
# PMD rules on local files (no org): VfUnescapeEl (unescaped merge fields in Visualforce),
# ApexXSSFromEscapeFalse (addError() with escaping turned off), ApexXSSFromURLParam (unescaped URL parameters)
sf code-analyzer run --workspace force-app --rule-selector pmd:VfUnescapeEl --rule-selector pmd:ApexXSSFromEscapeFalse --rule-selector pmd:ApexXSSFromURLParam
```

---

## Review Checklist

- [ ] Template and DOM auto-escaping is relied upon by default (no hand-rolled escaping)
- [ ] No raw-HTML escape hatches with untrusted data in templates or DOM APIs (`innerHTML`, `insertAdjacentHTML`, `<%- %>`, `{{{ }}}`, `!{}`, `|safe`, `Markup()`)
- [ ] All HTML rendering escape hatches are preceded by `DOMPurify.sanitize()` or equivalent
- [ ] CSP is configured with nonce-based or hash-based script-src
- [ ] No `eval()`, `new Function()`, string timers, or `javascript:` URLs with user input
- [ ] No inline event handlers (`onclick="..."`) when CSP is enabled
- [ ] Server-side rendered content is escaped before injection
- [ ] JSON in HTML is properly escaped (`</script>` → `\u003c/script\u003e`)
- [ ] Salesforce: Visualforce merge fields use the encoding function for their context (`JSENCODE`, `JSINHTMLENCODE`, `HTMLENCODE`, `URLENCODE`); no `escape="false"`, `aura:unescapedHtml`, or `lwc:dom="manual"` with untrusted data
