# Visualforce Code Review Guide

Review rules for Visualforce pages, components, and email templates (`.page`, `.component`, `<messaging:emailTemplate>`), their custom controllers and extensions, and JavaScript remoting. Read two versions before judging behavior. The page's `.page-meta.xml` `<apiVersion>` sets Visualforce behavior. The controller's `.cls-meta.xml` sets its Apex defaults, including user mode and implicit `with sharing` at API 67.0+ ([Security Model](platform.md#security-model)). A diff that bumps only one of them changes only that side.

> Load [platform.md](platform.md) first. Related: [Apex](apex.md) · [SOQL Injection](soql-sosl.md#soql-injection) · [LWC](lwc.md) for pages being replaced

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.
Pre-existing code is a finding only when the change makes it worse. Take default tiers from the [severity table](platform.md#severity-calibration) (the XSS escape hatch, DML on page load, and entry-point access rows).

### Encoding → [Output Encoding](#output-encoding)

- [ ] No `escape="false"` or `itemEscaped="false"` around data the page doesn't control; values inside such markup use `HTMLENCODE`
- [ ] Merge fields in `<script>` strings and `on*` handlers use `JSENCODE`; values written to `innerHTML` use `JSENCODE(HTMLENCODE())`
- [ ] The page fixes each URL's scheme and host and `URLENCODE`s parameters; no merge fields in `<style>` or `style` attributes
- [ ] Page parameters stay data in Apex; no `addError(message, false)` with user input

### CSRF → [CSRF & State Changes](#csrf--state-changes)

- [ ] No DML runs on GET (constructors, getters, initializer blocks, or a method wired to `<apex:page action>`) unless the page sets `confirmationTokenRequired`
- [ ] State changes happen only in form POSTs the user starts; nothing auto-submits on load

### Controller security → [Controller Security](#controller-security)

- [ ] Below API 67.0, every controller and extension declares its sharing and queries in user mode; at 67.0+ the defaults cover a missing keyword
- [ ] Extensions don't copy protected fields into String or wrapper properties
- [ ] URL Ids are parsed, type-checked, bound, and looked up in user mode; redirects stay local

### View state & performance → [View State & Performance](#view-state--performance)

- [ ] Rebuildable fields are `transient` and the page has one `<apex:form>`; for large pages, ask the author for the view-state size (limit 170 KB)
- [ ] Large lists page through `StandardSetController` over a query bounded to 10,000 rows; getters query at most once per request
- [ ] Large read-only pages use `readOnly="true"`; pollers are slow, light, and switched off when done

### Remoting → [JavaScript Remoting & Remote Objects](#javascript-remoting--remote-objects)

- [ ] Every `@RemoteAction` class declares sharing, validates arguments, queries in user mode, and returns only the fields the page shows
- [ ] Remoting keeps `escape: true` or writes raw values only as text; Remote Objects list only the fields the page needs

### Pages, resources & Lightning → [Static Resources & Lightning Experience](#static-resources--lightning-experience)

- [ ] A new page for general UI documents why LWC doesn't fit (without that, 🟡 [important]); PDFs, email templates, and maintained overrides are fine
- [ ] Libraries come from versioned static resources; in Lightning Experience, navigation uses `sforce.one` or `URLFOR($Action...)`, not hand-built URLs

### Tests → [Testing Controllers](#testing-controllers)

- [ ] Controller tests set the page and its parameters, run as a least-privilege user, assert navigation, messages, and data, and cover hostile input (foreign Ids, hidden records, an external `retURL`, markup)

---

## Output Encoding

Every merge field is HTML-encoded automatically unless it sits inside `<script>` or `<style>`, or in a component with `escape="false"`. That encoding runs last, covers `<`, `>`, and quotes, and makes HTML text and quoted attributes safe, nothing else. Wherever a value passes through JavaScript, a URL, or CSS, the page encodes for that context itself ([XSS Prevention](../cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce)).

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

`JSINHTMLENCODE` predates automatic encoding. In an event handler it double-encodes (safe, but users see entities), and in a script it is shorthand for `JSENCODE(HTMLENCODE())`. Encoding can't make a CSS value safe, so keep merge fields out of `<style>` and `style` attributes.

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

Static analysis: PMD `VfUnescapeEl` and `VfHtmlStyleTagXss`. The second accepts `HTMLENCODE` or `URLENCODE` in `<style>`, which satisfies the rule but not the attack.

### Never combine escape="false" with data the page doesn't control

`escape="false"` on `apex:outputText`, `apex:outputLabel`, `apex:pageMessage`, or `apex:pageMessages`, and `itemEscaped="false"` on `apex:selectOption`, switch encoding off for everything inside. Put markup outside the component and let the platform encode the data. Visualforce markup is XML, so a literal `<` inside an attribute value doesn't compile. When `escape="false"` is truly needed, write the markup as entities and `HTMLENCODE` each value. `apex:outputField` renders rich text fields. The Apex twin is `record.addError(message, false)`, which unescapes an error shown on the page.

```html
<!-- ❌ User data rendered as markup -->
<apex:outputText value="{!comment.Body__c}" escape="false"/>
<apex:pageMessages escape="false"/> <!-- messages built from user input -->

<!-- ✅ Markup from the page, data encoded by the platform; rich text through outputField -->
<b><apex:outputText value="{!Account.Name}"/></b> updated this record
<apex:outputText escape="false" value="&lt;b&gt;{!HTMLENCODE(Account.Name)}&lt;/b&gt; updated this record"/>
<apex:outputField value="{!Account.Rich_Notes__c}"/>
```

Static analysis: PMD `VfUnescapeEl`, and `ApexXSSFromEscapeFalse` for the `addError` form.

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

Visualforce puts an anti-CSRF token in every `<apex:form>` and checks it on the POST; nothing checks GET requests. A state change that runs on page load or from URL parameters can be triggered by a link or an image tag on another site ([CSRF Prevention](../security-review-guide.md#csrf-prevention)).

### Keep DML out of page load

`<apex:page action="...">` runs on the GET that loads the page, and Visualforce doesn't allow DML in getters or controller constructors, so writes on load usually hide in an `init()` wired to `action=`. Load, validate, and display on GET; change data only in an action method that a form calls (`apex:commandButton`, `apex:commandLink`, `apex:actionFunction`). Severity is in the DML-on-page-load row of the [severity table](platform.md#severity-calibration). Judge a method by how the page invokes it, not by its name: an `init()` called from a command button is fine. A page that sets `confirmationTokenRequired` requires a CSRF token on GET ([below](#never-change-state-from-get-parameters-or-on-load)), so DML on load is protected there.

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

Static analysis: PMD `VfCsrf` flags a page `action`. PMD `ApexCSRF` flags DML in constructors, initializer blocks, and every method named `init`, so confirm how each hit is invoked.

### Never change state from GET parameters or on load

A URL such as `/apex/ApproveInvoice?id=...&approve=1` must not approve anything. Scripts must not submit a form or call an `apex:actionFunction` on load: the POST then carries a valid token, but the user never chose it. When a page opened from a custom button must act at once, show an intermediate confirmation page. A page that overrides the standard Delete button can require a token on GET: set Require CSRF protection on GET requests, which is `<confirmationTokenRequired>true</confirmationTokenRequired>` in `.page-meta.xml`.

```html
<!-- ❌ Auto-submits on load: every visit, including one forced by another site, approves -->
<apex:form><apex:actionFunction name="approve" action="{!approve}"/></apex:form>
<script>window.onload = function () { approve(); };</script>

<!-- ✅ The user starts the change -->
<apex:form><apex:commandButton action="{!approve}" value="Approve invoice {!invoice.Name}"/></apex:form>
```

---

## Controller Security

Standard controllers enforce the user's object permissions, FLS, and sharing. Custom controllers, extensions, and `@RemoteAction` methods are ordinary Apex that follows its class's `<apiVersion>`. Below API 67.0 they run in system mode, with sharing set by the keyword; at 67.0+ they run in user mode, and `with sharing` when undeclared ([Security Model](platform.md#security-model)). Every URL parameter is attacker-controlled.

### Declare with sharing and query in user mode in every controller and extension

A Visualforce controller is an entry point, so below API 67.0 a class without a keyword runs without sharing. Declare `with sharing` (`inherited sharing` for shared helpers), and query and write in user mode ([Data Access Security](apex.md#data-access-security)). At API 67.0+ the defaults cover a missing keyword; an explicit one is still preferred, per the sharing-keyword row of the [severity table](platform.md#severity-calibration).

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

A standard controller checks access to the record it loads, and `apex:inputField`, `apex:outputField`, and merge fields bound to sObject fields honor FLS. An extension's own queries and DML don't inherit that. A value copied into a controller property (a String, wrapper, or map) loses FLS, because the page can't tell where it came from.

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

An `id` parameter can name a record of another type, a record the user can't see, or garbage. Parse it (`Id.valueOf` throws `StringException` on bad input), check its sObject type, bind it, and look it up in user mode. Never concatenate a parameter into a query ([SOQL Injection](soql-sosl.md#soql-injection); client-supplied Ids: [Data Access Security](apex.md#data-access-security)).

```apex
// ❌ Any object type, an unhandled exception on garbage, and a system-mode lookup
Id invoiceId = ApexPages.currentPage().getParameters().get('id');
Invoice__c inv = [SELECT Id, Name FROM Invoice__c WHERE Id = :invoiceId];

// ✅ Garbage and foreign types become null (handled like a missing parameter); the lookup binds, in user mode, into a list
String raw = ApexPages.currentPage().getParameters().get('id');
Id invoiceId;
try { invoiceId = String.isBlank(raw) ? null : Id.valueOf(raw); } catch (StringException e) { invoiceId = null; }
if (invoiceId?.getSObjectType() != Invoice__c.SObjectType) { invoiceId = null; }
List<Invoice__c> rows = [SELECT Id, Name FROM Invoice__c WHERE Id = :invoiceId WITH USER_MODE LIMIT 1];
```

### Allowlist redirect targets

This is the open-redirect rule for all Salesforce UI code; LWC and Aura navigation link here. `new PageReference(retURL)` with a caller-supplied `retURL` sends users wherever an attacker chooses, typically a copy of the login page. Accept only local paths, or choose the destination in code. A local path starts with one `/`, contains only printable ASCII, and has no backslash. Browsers strip tabs and line breaks from URLs, so `/`, a tab, then `/evil.example` becomes `//evil.example`.

```apex
// ❌ Open redirect
return new PageReference(ApexPages.currentPage().getParameters().get('retURL'));

// ✅ Local paths only; anything else falls back to a page the code chose, such as stdController.view()
public inherited sharing class SafeRedirect {
    public static PageReference toLocal(String target, PageReference fallback) {
        Boolean isLocal = String.isNotBlank(target) && target.startsWith('/') && !target.startsWith('//')
            && Pattern.matches('[\\x21-\\x7E]*', target) && !target.contains('\\');
        return isLocal ? new PageReference(target) : fallback;
    }
}
```

Static analysis: PMD `ApexOpenRedirect`.

---

## View State & Performance

Every postback carries the page's view state: the non-transient fields of the controller and extensions plus component state, serialized, encrypted, and limited to 170 KB. Pages also count against Apex limits ([Governor Limits](platform.md#governor-limits)).

### Keep view state small

Mark fields the next request can rebuild as `transient`, and keep Ids instead of record lists. Use one `<apex:form>` per page, with `<apex:actionRegion>` to limit what a partial request processes. Static variables, `PageReference` objects, and most system objects are never saved.

```apex
// ❌ Thousands of rows and a derived report serialized into every postback
public List<Invoice__c> allInvoices { get; set; }
public Map<Id, Decimal> totalsByAccount { get; set; }

// ✅ Small state survives; derived data is transient and rebuilt per request
public Id selectedAccountId { get; set; }
public transient Map<Id, Decimal> totalsByAccount { get; private set; }
```

### Page lists with StandardSetController and keep getters idempotent

`ApexPages.StandardSetController` pages a query in the database and holds one page of rows; `next()`, `previous()`, and `getHasNext()` drive navigation. It handles at most 10,000 records. Built from a `QueryLocator` whose query returns more, it throws a `LimitException`, which can't be caught. Built from a list, it truncates to 10,000 records, and `getCompleteResult()` then reports that the set is incomplete. So bound the locator's query with a selective filter or `LIMIT 10000`. Iteration components render at most 1,000 items outside read-only mode. Visualforce calls getters in no defined order and any number of times per request, so a getter must not query on every call or have side effects.

```apex
// ❌ Every matching record, queried again on each evaluation, rendered in one table
public List<Contact> getContacts() { return [SELECT Id, Name FROM Contact WHERE AccountId = :accountId WITH USER_MODE]; }

// ✅ The database pages over a bounded query; the getter builds the controller once and returns 25 rows
public with sharing class AccountContactsController {
    public Id accountId { get; set; }
    public ApexPages.StandardSetController setCon {
        get {
            if (setCon == null) {
                setCon = new ApexPages.StandardSetController(Database.getQueryLocator(
                    [SELECT Id, Name FROM Contact WHERE AccountId = :accountId WITH USER_MODE ORDER BY Name LIMIT 10000]));
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

Each `apex:actionPoller` tick is a request that runs its action and rerenders. The interval must be at least 5 seconds (default 60), and a polling page keeps the session alive indefinitely. Keep the action light (no DML or callouts), avoid pollers on pages with enhanced lists, and switch the poller off with `enabled` when nothing is left to wait for.

```html
<!-- ❌ Fast, endless polling with a heavy action -->
<apex:actionPoller action="{!refreshAllInvoices}" interval="5" reRender="board"/>

<!-- ✅ Slow, light, and switched off once the job finishes -->
<apex:actionPoller action="{!checkJobStatus}" interval="30" reRender="status" enabled="{!jobRunning}"/>
```

---

## JavaScript Remoting & Remote Objects

Remoting calls `@RemoteAction` methods without view state or a form post. Remote Objects give JavaScript direct create, read, update, and delete access to declared objects and fields. The server-side rules of [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract) apply here too.

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

### Build new UI in LWC; keep Visualforce where it still fits

Salesforce recommends Lightning Web Components over Visualforce for custom functionality. A new Visualforce page for general UI is a 🟡 [important] finding unless the PR says why LWC doesn't fit. Visualforce still fits print-ready PDFs (`renderAs="pdf"`), Visualforce email templates, and existing pages and overrides under maintenance. PDF rendering runs no JavaScript, supports no web fonts, and needs a response under 15 MB.

### Load libraries from versioned static resources

Serve third-party JavaScript and CSS as static resources with the version in the resource or file name, and load them with `apex:includeScript` and `apex:stylesheet` (`{!URLFOR($Resource.chartjs_4_4, 'chart.umd.min.js')}`). A CDN URL runs unpinned code nobody reviewed, and an unversioned resource hides which release the page uses. The rules, including the RetireJS scan, live in [Load third-party libraries from static resources](lwc.md#load-third-party-libraries-from-static-resources).

### Work with the Lightning container: navigate with sforce.one, style with lightningStylesheets

In Lightning Experience and the mobile app, a Visualforce page runs in an iframe on a separate domain. Its JavaScript can't reach the parent window, setting `window.location` directly bypasses the app's navigation, and hand-built URLs such as `'/' + id + '/e'` break across interfaces. Use `sforce.one` when it exists and `URLFOR($Action...)` otherwise. `lightningStylesheets="true"` gives standard components the Lightning look there and leaves Salesforce Classic unchanged. It isn't supported in Experience Cloud sites or with `renderAs="pdf"`, and a page with `applyBodyTag="false"` adds the `slds-vf-scope` class to `<body>` itself.

```html
<!-- ❌ Classic styling, a reach for the parent window, and a Classic URL built by hand -->
<apex:page standardController="Account"><script>function openAccount(id) { window.top.location.href = '/' + id + '/e'; }</script></apex:page>

<!-- ✅ Lightning styling; sforce.one in Lightning Experience and the mobile app, URLFOR elsewhere -->
<apex:page standardController="Account" lightningStylesheets="true"><script>
    function openAccount() {
        if (typeof sforce !== 'undefined' && sforce.one) { sforce.one.navigateToSObject('{!JSENCODE(Account.Id)}'); }
        else { window.location.href = '{!JSENCODE(URLFOR($Action.Account.View, Account.Id))}'; }
    }
</script></apex:page>
```

---

## Testing Controllers

### Test controllers through the page context, as a restricted user

General test rules (assertions, test data, `runAs`, `startTest`) are in [Testing](apex.md#testing).

- Set the page with `Test.setCurrentPage`, put the URL parameters a caller would send, and construct the controller the way the page does.
- Assert the navigation (`PageReference.getUrl()`), the messages (`ApexPages.hasMessages(ApexPages.Severity.ERROR)`), and the data.
- Cover hostile input: an Id of another type, a record the user can't see, a `retURL` to another host, and markup in text parameters.
- Call `@RemoteAction` methods directly, inside `System.runAs`.

```apex
// ✅ Page context, a least-privilege user, and asserted outcomes (the factory wraps setup-object DML in runAs)
Test.setCurrentPage(Page.InvoiceVoid);
ApexPages.currentPage().getParameters().put('id', invoice.Id);
System.runAs(TestDataFactory.createUser('Invoice_Viewer')) {
    try {
        new InvoiceVoidExtension(new ApexPages.StandardController(invoice)).voidInvoice();
        Assert.fail('A read-only user must not void invoices');
    } catch (DmlException expected) { /* user-mode DML rejected the write */ }
}
Assert.areNotEqual('Void', [SELECT Status__c FROM Invoice__c WHERE Id = :invoice.Id].Status__c, 'The invoice is unchanged');
```

---

## References

- [Security Tips for Apex and Visualforce Development (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_security_tips_intro.htm)
- [Cross-Site Request Forgery (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_security_tips_csrf.htm)
- [Secure Coding: Cross Site Scripting (Salesforce Developers)](https://developer.salesforce.com/docs/atlas.en-us.secure_coding_guide.meta/secure_coding_guide/secure_coding_cross_site_scripting.htm)
- [Visualforce limits (Visualforce Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.pages.meta/pages/pages_apex_governor_limits.htm)
- [StandardSetController Class (Apex Reference Guide)](https://developer.salesforce.com/docs/atlas.en-us.apexref.meta/apexref/apex_pages_standardsetcontroller.htm)
