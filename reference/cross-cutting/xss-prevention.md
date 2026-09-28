# XSS Prevention Guide

Escape hatches in DOM code, front-end frameworks, and Node.js and Python templates; CSP; pointers for Salesforce UI.

Related: [Security Review Guide](../security-review-guide.md) · [JavaScript Guide](../javascript.md)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Severity: 🔴 blocking · 🟡 important · 🟢 nit · 💡 suggestion. Encoding for the render context is the boundary; input validation is defense in depth, so don't ask for `<script>` denylists.

### DOM → [Plain DOM (JavaScript)](#plain-dom-javascript)

- [ ] 🔴 Untrusted data reaches HTML sinks (`innerHTML`, `insertAdjacentHTML`, `document.write`, `srcdoc`) only via `DOMPurify.sanitize()` at the sink; text uses `textContent`
- [ ] 🔴 URLs from data pass a protocol allowlist before `href`, `src`, or `action`
- [ ] 🔴 No `eval`, `new Function`, or string timers with data

### Frameworks → [Framework Escape Hatches](#framework-escape-hatches)

- [ ] 🔴 `dangerouslySetInnerHTML`, `v-html`, `{@html}`, `bypassSecurityTrust*`, and jQuery `.html()` get only sanitized or constant markup

### Templates → [Server-Side Templates](#server-side-templates-nodejs-and-python)

- [ ] 🔴 Raw output (`<%- %>`, `{{{ }}}`, `!{}`, `safe`, `Markup()`, `mark_safe()`, autoescape off) never wraps untrusted data
- [ ] 🔴 Template source never comes from input: template injection runs code on the server
- [ ] 🟡 Jinja2 autoescaping covers every HTML template name, including `.html.j2`
- [ ] 🔴 Data inside `<script>` goes through `tojson`, `json_script`, or JSON with `<` escaped ([SSR](#server-side-rendering))

### CSP → [Content Security Policy (CSP)](#content-security-policy-csp)

- [ ] 🔴 Nonces are generated per response; a nonce fixed in config protects nothing
- [ ] 🟡 A changed policy keeps `'unsafe-eval'`, `*`, `https:`, and `data:` out of `script-src` and sets `object-src 'none'` and `base-uri`

### Salesforce → [Salesforce (LWC, Aura, Visualforce)](#salesforce-lwc-aura-visualforce)

- [ ] 🔴 `escape="false"`, merge fields in `<script>` without `JSENCODE`, `aura:unescapedHtml`, and `lwc:dom="manual"` with `innerHTML` never carry untrusted data

### Not findings → [Framework Escape Hatches](#framework-escape-hatches)

- [ ] Escape hatches fed only constant markup (`el.innerHTML = ''`); Angular `[innerHTML]`, which Angular sanitizes
- [ ] No CSP, or `script-src 'self'` with no inline scripts: 💡 at most

## Plain DOM (JavaScript)

```javascript
// ❌ HTML sinks parse markup: <img src=x onerror=alert(1)> runs
commentEl.innerHTML = comment.body;

// ✅ Text, or sanitize right before the sink when rich text is required
commentEl.textContent = comment.body;
commentEl.innerHTML = DOMPurify.sanitize(comment.bodyHtml);

// ✅ URLs from data: known protocols only (javascript:, data:, vbscript: return null)
const SAFE_PROTOCOLS = new Set(['https:', 'http:', 'mailto:']);
function toSafeUrl(value) {
  try {
    const url = new URL(value, location.origin);
    return SAFE_PROTOCOLS.has(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
```

DOMPurify: modifying HTML after sanitizing it can "void the effects of sanitization", so sanitize at output, not on input. Don't let a client-side template engine re-process sanitized user HTML (`SAFE_FOR_TEMPLATES` is not recommended for production); review widening options (`ADD_TAGS`, `ADD_ATTR`, `ALLOW_UNKNOWN_PROTOCOLS`); Node.js needs a jsdom window.

## Framework Escape Hatches

| Framework | Escaped by default | Escape hatch to audit |
| --- | --- | --- |
| React | `{value}` | `dangerouslySetInnerHTML`; data in `href`/`src` still needs the protocol allowlist |
| Vue | `{{ value }}` | `v-html` |
| Angular | `{{ value }}`; `[innerHTML]` is sanitized | `bypassSecurityTrust*` (Html, Url, ResourceUrl, Script, Style) |
| Svelte | `{value}` | `{@html value}` |
| jQuery | `.text()` | `.html(str)`, `$(htmlString)`, `.append(str)` |

## Server-Side Templates (Node.js and Python)

Auto-escaping is HTML escaping only: it does not make a value safe inside `<script>`, inline `on*` handlers, `style`, or `href`.

| Engine | Escaped | Raw output to audit |
| --- | --- | --- |
| EJS | `<%= v %>` | `<%- v %>` |
| Handlebars | `{{v}}` | `{{{v}}}`, `new Handlebars.SafeString(...)` |
| Pug | `#{v}`, `p= v` | `!{v}`, `p!= v` |
| Nunjucks | `{{ v }}` (autoescape on by default) | `safe` filter, `autoescape: false` |
| Jinja2 | `{{ v }}` only with autoescape on | `safe` filter, `Markup()` around built strings, `{% autoescape false %}` |
| Django | `{{ v }}` | `safe` filter, `mark_safe()`, `{% autoescape off %}` |

```python
# ❌ A plain Environment doesn't escape; select_autoescape() alone skips page.html.j2
env = Environment(loader=loader)
# ✅ Name every HTML suffix the project uses
env = Environment(loader=loader, autoescape=select_autoescape(("html", "htm", "xml", "html.j2")))

# ❌ The f-string interpolates first, then Markup() trusts the result
bio_html = Markup(f"<p>{user_bio}</p>")
# ✅ Markup.format() escapes its arguments (Django: format_html())
bio_html = Markup("<p>{}</p>").format(user_bio)

# ❌ Template source from input: template injection runs code on the server
render_template_string(f"Hello {name}")
# ✅ Input goes into the context, never into the source
render_template_string("Hello {{ name }}", name=name)
```

Flask autoescapes `.html`, `.htm`, `.xml`, `.xhtml`, `.svg`, and template strings; `page.html.j2` renders unescaped.

### Server-Side Rendering

```typescript
// ❌ Raw interpolation, and JSON whose "</script>" closes the script element
const html = `<div>${userInput}</div><script>window.__DATA__ = ${JSON.stringify(data)}</script>`;

// ✅ Escape HTML text; escape < and > in JSON placed inside <script>
const safeJson = JSON.stringify(data).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
const html = `<div>${escapeHtml(userInput)}</div><script>window.__DATA__ = ${safeJson}</script>`;
```

Python: Jinja2 `{{ data|tojson }}` and Django `{{ data|json_script:"data" }}` escape `<`, `>`, and `&` for use in `<script>`.

## Content Security Policy (CSP)

```typescript
// ✅ A new nonce per response (a nonce fixed in config is the same for everyone)
app.use((req, res, next) => {
  res.locals.cspNonce = crypto.randomBytes(32).toString('hex');
  next();
});
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      scriptSrc: ["'self'", (req, res) => `'nonce-${res.locals.cspNonce}'`, "'strict-dynamic'"],
      objectSrc: ["'none'"],
      baseUri: ["'none'"],
    },
  },
}));
// Template: <script nonce="<%= cspNonce %>">…</script>
```

- Nonces don't cover inline `on*` handlers or `javascript:` URLs; use `addEventListener`.
- `'unsafe-inline'` is ignored when a nonce or hash is present; `'unsafe-eval'`, `*`, `https:`, and `data:` in `script-src` are findings.
- `script-src 'self'` without inline scripts is reasonable; 💡 a nonce with `'strict-dynamic'` is stronger.

## Salesforce (LWC, Aura, Visualforce)

- Visualforce: `JSENCODE` in script strings and `on*` handlers, `JSENCODE(HTMLENCODE())` before `innerHTML`, `URLENCODE` in URLs; no `escape="false"` with data ([Output Encoding](../salesforce/visualforce.md#output-encoding)).
- LWC: `lwc:dom="manual"` with `innerHTML` is the escape hatch; rich text goes through `lightning-formatted-rich-text` ([Security in the Browser](../salesforce/lwc.md#security-in-the-browser)).
- Aura: `aura:unescapedHtml` renders raw HTML ([Aura Security](../salesforce/aura.md#security)). Lightning's own CSP loads third-party JavaScript only from static resources.

## Finding Sinks

Grep-tool patterns (ripgrep syntax); check what feeds each hit.

- `\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML\(|document\.write(ln)?\(|\.srcdoc\s*=|createContextualFragment\(|setHTMLUnsafe\(` — DOM HTML sinks
- `dangerouslySetInnerHTML|v-html|bypassSecurityTrust|\{@html` — framework escape hatches
- `\.html\(\s*[^)\s]|\$\(\s*["'\x60]\s*<` — jQuery HTML parsing
- `<%-|\{\{\{|!\{|\|\s*safe\b|autoescape\s+(false|off)|autoescape\s*=\s*False|Markup\(\s*f["']|mark_safe\(|SafeString\(` — raw template output
- `render_template_string\(|\.from_string\(|jinja2\.Template\(` — template source from strings
- `\beval\(|new Function\(|set(Timeout|Interval)\(\s*["'\x60]` — string code execution
- `\.(href|src|action|formAction)\s*=\s*[^"'\x60\s]` — URL attributes from variables
- `escape="false"|lwc:dom="manual"|aura:unescapedHtml` — Salesforce escape hatches

## References

- [OWASP XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [OWASP DOM-based XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html)
- [DOMPurify](https://github.com/cure53/DOMPurify)
