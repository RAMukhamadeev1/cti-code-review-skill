# Visualforce Code Review Guide

Review guidance for Visualforce pages and components (`.page`, `.component`), their custom controllers and extensions, and JavaScript remoting: output encoding, CSRF, controller security, view state, remoting, static resources, Lightning Experience, and controller tests.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
> Related: [Apex](apex.md) · [SOQL injection](soql-sosl.md#soql-injection) · [XSS Prevention](../cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Visualforce Today](#visualforce-today)
- [Output Encoding](#output-encoding)
- [CSRF & State Changes](#csrf--state-changes)
- [Controller Security](#controller-security)
- [View State & Performance](#view-state--performance)
- [JavaScript Remoting & Remote Objects](#javascript-remoting--remote-objects)
- [Static Resources & Lightning Experience](#static-resources--lightning-experience)
- [Testing Controllers](#testing-controllers)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| `pages/*.page`, `components/*.component`, Visualforce email templates (`<messaging:emailTemplate>`) | This guide |
| Custom controllers and extensions (`ApexPages.StandardController` constructors, `PageReference`, `@RemoteAction`) | This guide + [apex.md](apex.md) |
| Queries built from page parameters | [SOQL Injection](soql-sosl.md#soql-injection) |
| A page being replaced by a Lightning web component | [lwc.md](lwc.md) |

Read two versions before judging behavior: the page's `.page-meta.xml` `<apiVersion>` sets Visualforce behavior, and the controller's `.cls-meta.xml` sets its Apex defaults, including user mode and implicit `with sharing` at API 67.0+ ([Security Model](platform.md#security-model)). A diff that bumps only one of them changes only that side.

---

## Visualforce Today

### Build new UI in LWC; keep Visualforce where it still fits

Salesforce recommends Lightning Web Components over Visualforce for custom functionality. Visualforce still fits print-ready PDFs (`renderAs="pdf"`), Visualforce email templates, and existing pages and overrides under maintenance; a new Visualforce page for general UI is a 🟡 finding unless the PR says why LWC doesn't fit. PDF rendering runs no JavaScript, supports no web fonts, and needs a response under 15 MB.

```html
<!-- ❌ New interactive UI as a Visualforce page with hand-rolled rendering over remoting -->
<apex:page controller="InvoiceBoardController" lightningStylesheets="true"><div id="board"></div><script>/* ... */</script></apex:page>

<!-- ✅ Visualforce where it fits: a print-ready PDF from the standard controller -->
<apex:page standardController="Invoice__c" renderAs="pdf">
    <h1>Invoice {!Invoice__c.Name}</h1><apex:outputField value="{!Invoice__c.Total__c}"/>
</apex:page>
```

---

## Output Encoding

Every merge field is HTML-encoded automatically unless it sits inside `<script>` or `<style>` or in a component with `escape="false"`. That encoding runs last, covers `<`, `>`, and quotes, and makes HTML text and quoted attributes safe, nothing else: wherever a value passes through JavaScript, a URL, or CSS, the page encodes for that context itself.

> 📖 Cross-language background: [XSS Prevention](../cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce).

### Encode for the context the value lands in

Each parser a value passes through needs its own layer of encoding, applied innermost first.

| Where the merge field lands | Encode with |
|---|---|
| HTML text or a quoted attribute | Nothing extra: automatic HTML encoding |
| A quoted string inside `<script>` | `JSENCODE`; parse numbers and booleans explicitly (`parseInt('{!JSENCODE(qty)}')`) |
| An inline event handler such as `onclick` | `JSENCODE`; automatic HTML encoding adds the outer layer |
| Script that writes the value into `innerHTML` | `JSENCODE(HTMLENCODE(...))`, or set `textContent` instead |
| Markup inside `escape="false"` | `HTMLENCODE` on each value |
| A URL parameter | `URLENCODE`, with the scheme, host, and path fixed by the page |
| `<style>` or a `style` attribute | Nothing is enough: allowlist the value in the controller |

`JSINHTMLENCODE` predates automatic encoding: in an event handler it double-encodes (safe, but users see entities), and in a script it is shorthand for `JSENCODE(HTMLENCODE())`. Encoding can't make a CSS value safe, so keep merge fields out of `<style>` and `style` attributes.

```html
<!-- ❌ Quote breaks out of the string; handler decodes then runs; innerHTML parses markup; caller picks the URL and the CSS -->
<script>var q = '{!$CurrentPage.parameters.q}';</script>
<button onclick="selectAccount('{!acc.Name}')">Select</button>
<script>document.getElementById('greeting').innerHTML = 'Hi {!JSENCODE(acc.Name)}';</script>
<a href="{!$CurrentPage.parameters.next}">Continue</a>
<style>.banner { color: #{!$CurrentPage.parameters.color}; }</style>

<!-- ✅ One layer per parser, the page owns the URL, and CSS comes from an allowlist in the controller -->
<script>var q = '{!JSENCODE($CurrentPage.parameters.q)}';</script>
<button onclick="selectAccount('{!JSENCODE(acc.Name)}')">Select</button>
<script>document.getElementById('greeting').innerHTML = 'Hi {!JSENCODE(HTMLENCODE(acc.Name))}';</script>
<a href="/apex/InvoiceSearch?q={!URLENCODE(searchTerm)}">Search again</a>
<div class="{!bannerClass}">...</div> <!-- bannerClass returns 'banner_info' or 'banner_warning', never raw input -->
```

Static analysis: PMD `VfUnescapeEl`, `VfHtmlStyleTagXss` (it accepts `HTMLENCODE` or `URLENCODE` in `<style>`, which satisfies the rule but not the attack).

### Never combine escape="false" with data the page doesn't control

`escape="false"` on `apex:outputText`, `apex:outputLabel`, `apex:pageMessage`, `apex:pageMessages`, or `apex:sectionHeader`, and `itemEscaped="false"` on `apex:selectOption`, switch encoding off for everything inside. When markup must wrap data, encode each value with `HTMLENCODE`; `apex:outputField` renders rich text fields. The Apex twin is `record.addError(message, false)`, which unescapes an error shown on the page.

```html
<!-- ❌ User data rendered as markup -->
<apex:outputText value="{!comment.Body__c}" escape="false"/>
<apex:pageMessages escape="false"/> <!-- messages built from user input -->

<!-- ✅ Markup from the page, data encoded; rich text through outputField -->
<apex:outputText escape="false" value="<b>{!HTMLENCODE(Account.Name)}</b> updated this record"/>
<apex:outputField value="{!Account.Rich_Notes__c}"/>
```

Static analysis: PMD `VfUnescapeEl`, `ApexXSSFromEscapeFalse` (the `addError` form).

### Treat page parameters as untrusted in Apex too

Values from `ApexPages.currentPage().getParameters()` are attacker-controlled wherever they go: into markup, into dynamic SOQL ([SOQL Injection](soql-sosl.md#soql-injection)), or into a redirect ([Controller Security](#controller-security)). Keep them as data: trim, bound, and parse them, and let the page encode them.

```apex
// ❌ The raw parameter becomes markup that the page renders with escape="false"
banner = 'Results for <b>' + ApexPages.currentPage().getParameters().get('q') + '</b>';

// ✅ Data stays data; the page renders it as encoded text: <b><apex:outputText value="{!searchTerm}"/></b>
public with sharing class InvoiceSearchController {
    public String searchTerm { get; private set; }
    public InvoiceSearchController() { searchTerm = ApexPages.currentPage().getParameters().get('q')?.trim().left(80); }
}
```

Static analysis: PMD `ApexXSSFromURLParam`.

---

## CSRF & State Changes

Visualforce puts an anti-CSRF token in every `<apex:form>` and checks it on the POST; nothing checks GET requests. A state change that runs on page load or from URL parameters can be triggered by a link or an image tag on another site.

> 📖 Cross-language background: [CSRF Prevention](../security-review-guide.md#csrf-prevention).

### Keep DML out of page load

`<apex:page action="...">` runs on the GET that loads the page, and Visualforce doesn't allow DML in getters or controller constructors, so writes on load usually hide in an `init()` wired to `action=`. Load, validate, and display on GET; change data only in an action method that a form calls (`apex:commandButton`, `apex:commandLink`, `apex:actionFunction`).

```apex
// ❌ <apex:page standardController="Invoice__c" extensions="InvoiceVoidExtension" action="{!init}"/>
//    runs init() on GET: a link or image tag on another site voids the invoice
public void init() {
    update as user new Invoice__c(Id = invoiceId, Status__c = 'Void');
}

// ✅ The constructor reads; the change runs only from the form POST, which carries the token:
//    <apex:form><apex:commandButton action="{!voidInvoice}" value="Void {!Invoice__c.Name}"/></apex:form>
public with sharing class InvoiceVoidExtension {
    private final Id invoiceId;
    public InvoiceVoidExtension(ApexPages.StandardController std) { invoiceId = std.getId(); }

    public PageReference voidInvoice() {
        Invoice__c inv = new Invoice__c(Id = invoiceId, Status__c = 'Void');
        update as user inv;
        return new ApexPages.StandardController(inv).view();
    }
}
```

Static analysis: PMD `VfCsrf` (page `action`), `ApexCSRF` (DML in constructors, initializer blocks, and methods named `init`).

### Never change state from GET parameters or on load

A URL such as `/apex/ApproveInvoice?id=...&approve=1` must not approve anything, and scripts must not submit a form or call an `apex:actionFunction` on load: the POST then carries a valid token, but the user never chose it. When a page opened from a custom button must act at once, show an intermediate confirmation page. A page that overrides the standard Delete button can require a token on GET: Require CSRF protection on GET requests, `<confirmationTokenRequired>true</confirmationTokenRequired>` in `.page-meta.xml`.

```html
<!-- ❌ Auto-submits on load: every visit, including one forced by another site, approves -->
<apex:form><apex:actionFunction name="approve" action="{!approve}"/></apex:form>
<script>window.onload = function () { approve(); };</script>

<!-- ✅ The user starts the change -->
<apex:form><apex:commandButton action="{!approve}" value="Approve invoice {!invoice.Name}"/></apex:form>
```

---

## Controller Security

Standard controllers enforce the user's object permissions, FLS, and sharing. Custom controllers, extensions, and `@RemoteAction` methods are ordinary Apex that follows its class's `<apiVersion>`: below API 67.0 they run in system mode with sharing set by the keyword, at 67.0+ in user mode and `with sharing` when undeclared ([Security Model](platform.md#security-model)). Every URL parameter is attacker-controlled.

### Declare with sharing and query in user mode in every controller and extension

A Visualforce controller is an entry point, so below API 67.0 a class without a keyword runs without sharing. Declare `with sharing` (`inherited sharing` for shared helpers), and query and write in user mode ([Data Access Security](apex.md#data-access-security)).

```apex
// ❌ API 66.0: no keyword and no access mode: every invoice and every field, whatever the user may see
public class InvoiceListController {
    public List<Invoice__c> getInvoices() { return [SELECT Id, Name, Internal_Margin__c FROM Invoice__c LIMIT 100]; }
}

// ✅ Sharing, CRUD, and FLS enforced; one query per request (transient: rebuilt, never serialized)
public with sharing class InvoiceListController {
    private transient List<Invoice__c> invoices;
    public List<Invoice__c> getInvoices() {
        if (invoices == null) { invoices = [SELECT Id, Name, Total__c FROM Invoice__c WHERE OwnerId = :UserInfo.getUserId() WITH USER_MODE LIMIT 100]; }
        return invoices;
    }
}
```

Static analysis: PMD `ApexSharingViolations`, `ApexCRUDViolation`.

### Don't let extensions and controller properties bypass the standard controller's checks

A standard controller checks access to the record it loads, and `apex:inputField`, `apex:outputField`, and merge fields bound to sObject fields honor FLS. An extension's own queries and DML don't inherit that, and a value copied into a controller property (a String, wrapper, or map) loses FLS because the page can't tell where it came from.

```apex
// ❌ System-mode query in the extension; the margin reaches the page through a String property
marginText = String.valueOf([SELECT Internal_Margin__c FROM Invoice__c WHERE Id = :std.getId()].Internal_Margin__c);

// ✅ User-mode query, and fields stay on the sObject so <apex:outputField value="{!invoice.Total__c}"/> applies FLS
public with sharing class InvoiceExtension {
    public Invoice__c invoice { get; private set; }
    public InvoiceExtension(ApexPages.StandardController std) {
        Id invoiceId = std.getId(); invoice = [SELECT Id, Name, Total__c FROM Invoice__c WHERE Id = :invoiceId WITH USER_MODE];
    }
}
```

### Validate record Ids from the URL and bind every parameter

An `id` parameter can name a record of another type, a record the user can't see, or garbage. Parse it (`Id.valueOf` throws `StringException` on bad input), check its sObject type, bind it, and look it up in user mode; never concatenate a parameter into a query ([SOQL Injection](soql-sosl.md#soql-injection); client-supplied Ids: [Data Access Security](apex.md#data-access-security)).

```apex
// ❌ Any object type, an unhandled exception on garbage, and a system-mode lookup
Id invoiceId = ApexPages.currentPage().getParameters().get('id');
Invoice__c inv = [SELECT Id, Name FROM Invoice__c WHERE Id = :invoiceId];

// ✅ Typed and type-checked; then query WHERE Id = :invoiceId WITH USER_MODE into a list
public inherited sharing class PageParams {
    public static Id recordId(String name, Schema.SObjectType expectedType) {
        String raw = ApexPages.currentPage().getParameters().get(name);
        try {
            Id value = String.isBlank(raw) ? null : Id.valueOf(raw);
            return value?.getSObjectType() == expectedType ? value : null;
        } catch (StringException e) { return null; } // not an Id: handled like a missing parameter
    }
}
```

### Allowlist redirect targets

`new PageReference(retURL)` with a caller-supplied `retURL` sends users wherever an attacker chooses, typically a copy of the login page. Accept only local paths (one leading `/`, no backslash or line break), or choose the destination in code.

```apex
// ❌ Open redirect
return new PageReference(ApexPages.currentPage().getParameters().get('retURL'));

// ✅ Local paths only; anything else falls back to a page the code chose, such as stdController.view()
public inherited sharing class SafeRedirect {
    public static PageReference toLocal(String target, PageReference fallback) {
        Boolean isLocal = String.isNotBlank(target) && target.startsWith('/') && !target.startsWith('//') && !target.containsAny('\\\r\n');
        return isLocal ? new PageReference(target) : fallback;
    }
}
```

Static analysis: PMD `ApexOpenRedirect`.

---

## View State & Performance

Every postback carries the page's view state: the non-transient fields of the controller and extensions plus component state, serialized, encrypted, and limited to 170 KB. Pages also count against Apex limits ([Governor Limits](platform.md#governor-limits)).

### Keep view state small

Mark fields the next request can rebuild as `transient`, keep Ids instead of record lists, and use one `<apex:form>` per page, with `<apex:actionRegion>` to limit what a partial request processes. Static variables, `PageReference` objects, and most system objects are never saved.

```apex
// ❌ Thousands of rows and a derived report serialized into every postback
public List<Invoice__c> allInvoices { get; set; }
public Map<Id, Decimal> totalsByAccount { get; set; }

// ✅ Small state survives; derived data is transient and rebuilt per request
public Id selectedAccountId { get; set; }
public transient Map<Id, Decimal> totalsByAccount { get; private set; }
```

### Page lists with StandardSetController and keep getters idempotent

`ApexPages.StandardSetController` pages a query in the database and holds one page of rows; `next()`, `previous()`, and `getHasNext()` drive navigation. It handles up to 10,000 records (`getCompleteResult()` returns false when the query matched more), and iteration components render at most 1,000 items outside read-only mode. Visualforce calls getters in no defined order and any number of times per request, so a getter must not query on every call or have side effects.

```apex
// ❌ Every matching record, queried again on each evaluation, rendered in one table
public List<Contact> getContacts() { return [SELECT Id, Name FROM Contact WHERE AccountId = :accountId WITH USER_MODE]; }

// ✅ The database pages; the getter builds the controller once and returns 25 rows
public with sharing class AccountContactsController {
    public Id accountId { get; set; }
    public ApexPages.StandardSetController setCon {
        get {
            if (setCon == null) {
                setCon = new ApexPages.StandardSetController(Database.getQueryLocator([SELECT Id, Name FROM Contact WHERE AccountId = :accountId WITH USER_MODE ORDER BY Name]));
                setCon.setPageSize(25);
            }
            return setCon;
        }
        private set;
    }
    public List<Contact> getContacts() { return (List<Contact>) setCon.getRecords(); }
}
```

### Use read-only mode for large read-only pages

`<apex:page readOnly="true">` raises the query-row limit for the request to 1,000,000 and the iteration-component limit from 1,000 to 10,000 items, and forbids DML. For a single remote call, `@ReadOnly` on an `@RemoteAction` method raises the row limit but not the iteration limit.

```html
<!-- ❌ A large report page that fails once the org grows -->
<apex:page controller="RegionReportController"><apex:dataTable value="{!rows}" var="r"><apex:column value="{!r.Name}"/></apex:dataTable></apex:page>

<!-- ✅ Read-only mode for a page that never writes -->
<apex:page controller="RegionReportController" readOnly="true"><apex:dataTable value="{!rows}" var="r"><apex:column value="{!r.Name}"/></apex:dataTable></apex:page>
```

### Poll slowly, and stop when the work is done

Each `apex:actionPoller` tick is a request that runs its action and rerenders; the interval must be at least 5 seconds (default 60), and a polling page keeps the session alive indefinitely. Keep the action light (no DML or callouts), don't combine the poller with other AJAX components, and switch it off with `enabled` when nothing is left to wait for.

```html
<!-- ❌ Fast, endless polling with a heavy action -->
<apex:actionPoller action="{!refreshAllInvoices}" interval="5" reRender="board"/>

<!-- ✅ Slow, light, and switched off once the job finishes -->
<apex:actionPoller action="{!checkJobStatus}" interval="30" reRender="status" enabled="{!jobRunning}"/>
```

---

## JavaScript Remoting & Remote Objects

Remoting calls `@RemoteAction` methods without view state or a form post; Remote Objects give JavaScript direct create, read, update, and delete access to declared objects and fields. The server-side rules of [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract) apply here too.

### Treat every @RemoteAction method as a public endpoint

Adding a class as a controller or extension exposes all of its `@RemoteAction` methods, including ones the page never calls: anyone who can view the page can call them with any arguments. Declare the class's sharing, query and write in user mode, validate every argument, and return only the fields the page shows.

```apex
// ❌ Caller-supplied filter text, system mode, and every selected field back to the browser
@RemoteAction
public static List<Account> search(String whereClause) { return Database.query('SELECT Id, Name, AnnualRevenue FROM Account WHERE ' + whereClause); }

// ✅ Typed and bounded input, user mode, a narrow result
public with sharing class AccountRemoter {
    @RemoteAction
    public static List<Account> findByName(String name) {
        if (String.isBlank(name) || name.length() > 80) { throw new IllegalArgumentException('Enter 1 to 80 characters.'); }
        String prefix = name.trim() + '%';
        return [SELECT Id, Name FROM Account WHERE Name LIKE :prefix WITH USER_MODE ORDER BY Name LIMIT 20];
    }
}
```

### Keep remoting responses escaped

With the default `{ escape: true }`, remoting HTML-encodes the response, which suits callbacks that build markup. `escape: false` hands raw values to the callback and is safe only when every value is written as text (`textContent`); rich text then needs a sanitizer. The same configuration sets `timeout`: 30 seconds by default, 120 at most.

```javascript
// ❌ Raw values written as markup
Visualforce.remoting.Manager.invokeAction('{!$RemoteAction.AccountRemoter.findByName}', term,
    (result, event) => { if (event.status) { listEl.innerHTML = result.map((a) => `<li>${a.Name}</li>`).join(''); } }, { escape: false });

// ✅ Default escaping: values arrive HTML-encoded, and failures show a fixed message
Visualforce.remoting.Manager.invokeAction('{!$RemoteAction.AccountRemoter.findByName}', term,
    (result, event) => {
        if (!event.status) { statusEl.textContent = 'Search failed. Try again.'; return; }
        listEl.innerHTML = result.map((a) => `<li>${a.Name}</li>`).join('');
    },
    { escape: true, timeout: 30000 });
```

### Scope Remote Objects to the fields the page needs

The Remote Objects controller applies sharing and FLS and always HTML-encodes responses, but every field in `fields` can be read and written from the browser within the user's rights. Override methods (`create="{!$RemoteAction...}"`) are ordinary controller code and must enforce access themselves.

```html
<!-- ❌ More fields than the page uses, and a create override that skips the built-in checks -->
<apex:remoteObjects><apex:remoteObjectModel name="Contact" fields="Id,Name,Email,Phone,Birthdate,Salary__c" create="{!$RemoteAction.ContactRemoter.createContact}"/></apex:remoteObjects>

<!-- ✅ Only the fields the page shows; overrides only where they enforce access in user mode -->
<apex:remoteObjects><apex:remoteObjectModel name="Contact" fields="Id,Name,Email"/></apex:remoteObjects>
```

---

## Static Resources & Lightning Experience

### Load libraries from versioned static resources

Serve third-party JavaScript and CSS as static resources with the version in the resource or file name, and load them with `apex:includeScript` and `apex:stylesheet`. A CDN URL runs code nobody reviewed, and an unversioned resource hides which release the page uses; the RetireJS rules flag known-vulnerable libraries in static resources ([Tooling](platform.md#tooling)).

```html
<!-- ❌ Unpinned code from a CDN, and a resource name that hides the version -->
<script src="https://cdn.example.com/chart.js"></script>
<apex:includeScript value="{!$Resource.chartlib}"/>

<!-- ✅ Pinned libraries from static resource archives -->
<apex:includeScript value="{!URLFOR($Resource.chartjs_4_4, 'chart.umd.min.js')}"/>
<apex:stylesheet value="{!URLFOR($Resource.app_styles_2_1, 'app.css')}"/>
```

### Work with the Lightning container: navigate with sforce.one, style with lightningStylesheets

In Lightning Experience and the mobile app, a Visualforce page runs in an iframe on a separate domain: its JavaScript can't reach the parent window, setting `window.location` directly bypasses the app's navigation, and hand-built URLs such as `'/' + id + '/e'` break across interfaces. Use `sforce.one` when it exists and `URLFOR($Action...)` otherwise. `lightningStylesheets="true"` gives standard components the Lightning look there and leaves Salesforce Classic unchanged; it isn't supported in Experience Cloud sites or with `renderAs="pdf"`, and a page with `applyBodyTag="false"` adds the `slds-vf-scope` class to `<body>` itself.

```html
<!-- ❌ Classic styling, a reach for the parent window, and a Classic URL built by hand -->
<apex:page standardController="Account"><script>function openAccount(id) { window.top.location.href = '/' + id + '/e'; }</script></apex:page>

<!-- ✅ Lightning styling; sforce.one inside Lightning Experience and the mobile app, URLFOR elsewhere -->
<apex:page standardController="Account" lightningStylesheets="true">
    <script>
        function openAccount() {
            if (typeof sforce !== 'undefined' && sforce.one) {
                sforce.one.navigateToSObject('{!JSENCODE(Account.Id)}');
            } else {
                window.location.href = '{!JSENCODE(URLFOR($Action.Account.View, Account.Id))}';
            }
        }
    </script>
</apex:page>
```

---

## Testing Controllers

### Test controllers through the page context, as a restricted user

General test rules (assertions, test data, `runAs`, `startTest`) are in [Testing](apex.md#testing). Set the page with `Test.setCurrentPage`, put the URL parameters a caller would send, construct the controller the way the page does, and assert the navigation (`PageReference.getUrl()`), the messages (`ApexPages.hasMessages(ApexPages.Severity.ERROR)`), and the data. Cover hostile input: an Id of another type, a record the user can't see, a `retURL` to another host, and markup in text parameters. Call `@RemoteAction` methods directly, inside `System.runAs`.

```apex
// ✅ Page context, a least-privilege user, and asserted outcomes, instead of an admin run with no asserts
@IsTest
private inherited sharing class InvoiceVoidExtensionTest {
    @IsTest
    static void viewerCannotVoid() {
        Invoice__c invoice = TestDataFactory.createInvoice();
        Test.setCurrentPage(Page.InvoiceVoid);
        ApexPages.currentPage().getParameters().put('id', invoice.Id);
        System.runAs(TestDataFactory.createUser('Invoice_Viewer')) { // the factory wraps setup-object DML in runAs
            try {
                new InvoiceVoidExtension(new ApexPages.StandardController(invoice)).voidInvoice();
                Assert.fail('A read-only user must not void invoices');
            } catch (DmlException expected) { /* user-mode DML rejected the write */ }
        }
        Assert.areNotEqual('Void', [SELECT Status__c FROM Invoice__c WHERE Id = :invoice.Id].Status__c, 'The invoice is unchanged');
    }
}
```

---

## Review Checklist

### Encoding
- [ ] No `escape="false"` or `itemEscaped="false"` around data the page doesn't control; wrapped values use `HTMLENCODE`
- [ ] Merge fields in `<script>` and event handlers use `JSENCODE`; values written to `innerHTML` use `JSENCODE(HTMLENCODE())`
- [ ] The page fixes each URL's scheme and host and `URLENCODE`s parameters; no merge fields in `<style>` or `style`
- [ ] Page parameters stay data in Apex; no `addError(message, false)` with user input

### CSRF
- [ ] No DML in constructors, getters, initializers, `init()` methods, or `<apex:page action>`
- [ ] State changes happen only in form POSTs the user starts; nothing auto-submits on load
- [ ] Delete-button overrides that act on load set `confirmationTokenRequired`

### Controller security
- [ ] The controller's `<apiVersion>` was read; every controller and extension declares its sharing and uses user mode
- [ ] Extensions don't copy protected fields into String or wrapper properties
- [ ] URL Ids are parsed, type-checked, bound, and looked up in user mode; redirects stay local

### View state & performance
- [ ] Rebuildable fields are `transient`, one `<apex:form>` per page, and view state stays well under 170 KB
- [ ] Large lists page through `StandardSetController`; getters query at most once per request
- [ ] Large read-only pages use `readOnly="true"`; pollers are slow, light, and switched off when done

### Remoting
- [ ] Every `@RemoteAction` class declares sharing, validates arguments, and queries in user mode
- [ ] Remoting keeps `escape: true` or writes raw values only as text; Remote Objects list only needed fields

### Tests
- [ ] Controller tests set the page and parameters, run as a least-privilege user, and assert navigation, messages, and data
- [ ] Hostile inputs (foreign Ids, hidden records, external `retURL`, markup) have tests

---

## References

- [Security Tips for Apex and Visualforce Development (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_security_tips_intro.htm)
- [Cross-Site Request Forgery (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_security_tips_csrf.htm)
- [Secure Coding: Cross Site Scripting (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.secure_coding_guide.meta/secure_coding_guide/secure_coding_cross_site_scripting.htm)
- [View State best practices (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_best_practices_perf_view_state.htm)
- [Visualforce limits (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_apex_governor_limits.htm)
- [JavaScript Remoting for Apex Controllers (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_js_remoting.htm)
- [Visualforce Remote Objects (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_remote_objects.htm)
- [ApexPage metadata type (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_pages.htm)
- [PMD Visualforce rules](https://docs.pmd-code.org/latest/pmd_rules_visualforce.html)
- [PMD Apex security rules](https://docs.pmd-code.org/latest/pmd_rules_apex_security.html)
