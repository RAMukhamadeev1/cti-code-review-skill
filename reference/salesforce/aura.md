# Aura Components Code Review Guide

Review guidance for Aura bundles (`.cmp`, `.app`, `.evt`, `.design`, and their `Controller.js`, `Helper.js`, and `Renderer.js` files) and the Apex they call. Aura is still supported, but new UI belongs in LWC, so most findings here keep existing components safe until they migrate.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
>
> 📖 General JavaScript rules (language semantics, async and Promise pitfalls, DOM safety, test basics) live in the [JavaScript Guide](../javascript.md); this guide covers Aura-specific behavior only.
>
> Related: [LWC-Apex contract](lwc.md#the-lwc-apex-contract) (applies to Aura server actions too) · [LWC security](lwc.md#security-in-the-browser)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Aura Today](#aura-today)
- [Server Actions](#server-actions)
- [Events & Communication](#events--communication)
- [Rendering & Performance](#rendering--performance)
- [Security](#security)
- [Code Organization](#code-organization)
- [Testing](#testing)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| `aura/<bundle>/*.cmp`, `*.app`, `*.evt`, `*.design` | This guide |
| `aura/<bundle>/*Controller.js`, `*Helper.js`, `*Renderer.js` | This guide + the [JavaScript Guide](../javascript.md) |
| The Apex class named in `controller="..."` | [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract) + the [Apex Guide](apex.md) |
| An LWC that is embedded in, or replaces, an Aura component | The [LWC Guide](lwc.md) + [Aura Today](#aura-today) |

The Salesforce Aura lint config parses controller, helper, and renderer files as ES5 scripts (`ecmaVersion: 5`) and enables `vars-on-top`, so the examples here use `var` and function expressions. Where a project lints Aura with it, don't ask for `const`, arrow functions, or `async`/`await` in Aura files; that part of the JavaScript Guide applies to LWC.

---

## Aura Today

### Build new UI in LWC

Lightning Web Components are the recommended model for new UI. Treat a new `aura/` bundle as an important (🟡) finding unless the change documents the gap LWC can't fill ([Severity Calibration](platform.md#severity-calibration)): the same panel belongs in an LWC with a `lightning__RecordPage` target, with Aura at most as a thin wrapper where a container still requires it. Fixes and small changes to existing Aura components are fine and don't justify demanding a rewrite.

### Migrate in slices: LWC inside Aura, never the reverse

An Aura component can contain an LWC, but an LWC can't contain an Aura component, so migrate leaf components first and embed them in the existing Aura parent. Data goes down through attributes and events come back through `on<event>` handlers; Lightning Message Service connects unrelated Aura, LWC, and Visualforce components during the move.

```html
<!-- ❌ In an LWC template: <c-legacy-invoice-panel> is an Aura component, which LWC can't contain -->

<!-- ✅ invoicePanel.cmp hosts the migrated c-invoice-list LWC; the controller reads the LWC's
     CustomEvent detail with event.getParam('invoiceId') -->
<aura:component implements="flexipage:availableForRecordHome,force:hasRecordId">
    <c:invoiceList recordId="{!v.recordId}" onstatuschange="{!c.handleStatusChange}"/>
</aura:component>
```

---

## Server Actions

A server action calls an `@AuraEnabled` Apex method; the method's own rules (cacheable reads, server-side access checks, `AuraHandledException`) are in [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract).

### Handle SUCCESS, ERROR, and INCOMPLETE in every callback

`ERROR` carries the server's errors, and `INCOMPLETE` means the server was unreachable (offline or timed out).

```javascript
// invoiceListHelper.js
// ❌ A callback that only reads response.getReturnValue(): an error or a dropped connection
//    leaves the spinner running and the user uninformed

// ✅ Every state handled in one helper; setCallback(this, ...) keeps the helper as `this`
loadInvoices: function (component) {
    var action = component.get('c.getOpenInvoices');
    action.setParams({ accountId: component.get('v.recordId') });
    action.setCallback(this, function (response) {
        this.applyResponse(component, response, 'v.invoices');
    });
    component.set('v.isLoading', true);
    $A.enqueueAction(action);
},

applyResponse: function (component, response, attributeName) {
    var state = response.getState();
    var errors = response.getError();
    component.set('v.isLoading', false);
    if (state === 'SUCCESS') {
        component.set(attributeName, response.getReturnValue());
        component.set('v.errorMessage', null);
    } else if (state === 'ERROR') {
        component.set('v.errorMessage', errors && errors[0] && errors[0].message
            ? errors[0].message : $A.get('$Label.c.Invoice_Load_Failed'));
    } else if (state === 'INCOMPLETE') {
        component.set('v.errorMessage', $A.get('$Label.c.Invoice_Offline'));
    }
}
```

### Wrap code outside the Aura lifecycle in `$A.getCallback()`

Timer, promise, and third-party library callbacks run outside the framework: attribute changes are not rendered and enqueued actions are not sent. `$A.getCallback()` brings the code back into the lifecycle, and `component.isValid()` returns `false` once the user has navigated away and the component was destroyed.

```javascript
// ❌ window.setTimeout(function () { helper.loadInvoices(component); }, 5000): the refresh runs
//    outside the framework and may touch a destroyed component

// ✅ Back inside the lifecycle, and skipped if the component is gone
scheduleRefresh: function (component, event, helper) {
    window.setTimeout($A.getCallback(function () {
        if (component.isValid()) {
            helper.loadInvoices(component);
        }
    }), 5000);
}
```

### Expect storable actions to call back twice

For components at API 44.0 or later, `@AuraEnabled(cacheable=true)` on the Apex method makes the action storable (older components call `action.setStorable()`). The framework can call the callback first with cached data, then again with fresh data if it changed, so callbacks must be safe to run twice, and cacheable methods must not write.

```javascript
// ❌ Appends: when the callback runs twice (cached, then fresh), every row appears twice
component.set('v.invoices', component.get('v.invoices').concat(response.getReturnValue()));

// ✅ Replaces: a second run leaves the same state
component.set('v.invoices', response.getReturnValue());
```

### Batch related calls and send slow ones in the background

The framework groups actions enqueued together into one request, so a slow action holds up the fast ones beside it. Load a view with one action that returns what it needs, instead of a chain of calls, and call `setBackground()` on long-running actions so foreground actions don't wait for them.

```javascript
// ❌ Three chained actions to build one screen, with the slow report in the same batch as the page data

// ✅ One view-model action for the page (enqueued as usual), and the slow report in the background
loadAgingReport: function (component) {
    var action = component.get('c.buildAgingReport');
    action.setParams({ accountId: component.get('v.recordId') });
    action.setBackground();
    action.setCallback(this, function (response) {
        this.applyResponse(component, response, 'v.agingReport');
    });
    $A.enqueueAction(action);
}
```

---

## Events & Communication

### Prefer component events to application events

A component event travels only to the containers above its source, so its reach is visible in the markup. An application event is a broadcast that every handler in the app receives; keep it for truly app-wide signals, and use Lightning Message Service to reach LWC or Visualforce.

```javascript
// ❌ $A.get('e.c:invoiceSelectedApp') for a parent-child conversation: every handler in the app receives it

// ✅ A registered component event (<aura:registerEvent name="invoiceSelected" type="c:invoiceSelected"/>),
//    handled only by containers above this component
handleSelect: function (component, event) {
    var selected = component.getEvent('invoiceSelected');
    selected.setParams({ invoiceId: event.getSource().get('v.value') });
    selected.fire();
}
```

### Call child components through `aura:method`

A parent that reaches into a child's attributes or helpers depends on internals that can change without notice. Expose an `aura:method` as the child's documented public API.

```javascript
// ❌ component.find('invoiceList').set('v.reloadCounter', Date.now()): pokes an internal attribute

// ✅ Calls the child's public method; invoiceList.cmp declares
//    <aura:method name="refresh" action="{!c.handleRefresh}" description="Reloads the invoices"/>
handleStatusChange: function (component) {
    component.find('invoiceList').refresh();
}
```

### Register events explicitly and clean up on destroy

`component.getEvent()` returns nothing useful for an event the component never registered with `<aura:registerEvent>`, so declare every event it fires. Listeners on `window` or `document`, and timers, outlive the component unless a `destroy` handler removes them ([Clean up listeners, timers, and observers](../javascript.md#clean-up-listeners-timers-and-observers)).

```javascript
// Markup: <aura:attribute name="pollTimerId" type="Integer" access="private"/>
//         <aura:handler name="init" value="{!this}" action="{!c.handleInit}"/>
//         <aura:handler name="destroy" value="{!this}" action="{!c.handleDestroy}"/>
// ✅ init starts the poll; destroy stops it
handleInit: function (component, event, helper) {
    var timerId = window.setInterval($A.getCallback(function () {
        if (component.isValid()) {
            helper.loadInvoices(component);
        }
    }), 60000);
    component.set('v.pollTimerId', timerId);
},

handleDestroy: function (component) {
    window.clearInterval(component.get('v.pollTimerId'));
}
```

---

## Rendering & Performance

### Choose between `aura:if` and CSS toggling deliberately

`aura:if` destroys and re-creates its body: state inside is lost, and a heavy body is built again each time it appears. Toggling a CSS class keeps the body alive, with its handlers and server calls. Neither is access control: markup hidden with CSS is still in the DOM, and both still receive the data.

```html
<!-- ✅ Rarely shown, expensive content: built only when needed -->
<aura:if isTrue="{!v.showHistory}">
    <c:invoiceHistory recordId="{!v.recordId}"/>
</aura:if>

<!-- ✅ Toggled often, state must survive: hidden with a class instead of destroyed -->
<div class="{!v.showFilters ? '' : 'slds-hide'}">
    <c:invoiceFilters filters="{!v.filters}"/>
</div>
```

### Use unbound expressions for values that don't change

A bound expression (`{!v.x}`) registers change handlers, and passing one to a child creates two-way binding: the child can silently change the parent's attribute. An unbound expression (`{#v.x}`) is evaluated once and passes a value.

```html
<!-- ❌ Two-way bindings for values the child only displays -->
<c:invoiceHeader title="{!v.title}" currencyCode="{!v.currencyCode}" invoice="{!v.invoice}"/>

<!-- ✅ One-time values unbound; a bound expression only where the child must follow changes -->
<c:invoiceHeader title="{#v.title}" currencyCode="{#v.currencyCode}" invoice="{!v.invoice}"/>
```

### Page large `aura:iteration` lists

Every iterated item creates components and bindings, so rendering thousands of records freezes the page. Return a bounded page from Apex ([Pagination & Cursors](soql-sosl.md#pagination--cursors)) or use `lightning:datatable` with infinite loading.

```html
<!-- ❌ Renders every record the action returned -->
<aura:iteration items="{!v.invoices}" var="invoice">
    <c:invoiceRow invoice="{!invoice}"/>
</aura:iteration>

<!-- ✅ A datatable that asks for the next page as the user scrolls -->
<lightning:datatable keyField="Id" data="{!v.page}" columns="{!v.columns}"
    enableInfiniteLoading="{!v.hasMore}" onloadmore="{!c.handleLoadMore}"/>
```

### Touch the DOM only in renderers

Controllers run before the element exists or before the next rerender overwrites their changes. DOM work belongs in a renderer's `afterRender` and `rerender` (calling the super method first), and cleanup in `unrender`.

```javascript
// ❌ In invoiceChartController.js: component.find('chart').getElement().style.height = '300px';
//    the element may not exist yet, and the next rerender undoes the change

// ✅ invoiceChartRenderer.js
// eslint-disable-next-line no-unused-expressions
({
    afterRender: function (component, helper) {
        this.superAfterRender();
        helper.drawChart(component);
    },
    unrender: function (component, helper) {
        this.superUnrender();
        helper.destroyChart(component);
    }
});
```

---

## Security

### Never render user data with `aura:unescapedHtml` or `innerHTML`

Expressions in markup are escaped. `aura:unescapedHtml`, or `innerHTML` in a renderer, turns record text and URL parameters into live markup: stored or reflected XSS ([XSS Prevention](../cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce)).

```html
<!-- ❌ Stored XSS: record text rendered as markup -->
<aura:unescapedHtml value="{!v.invoice.Notes__c}"/>

<!-- ✅ Plain text through an escaped expression; rich text through the allowlist sanitizer -->
<p>{!v.invoice.Memo__c}</p>
<lightning:formattedRichText value="{!v.invoice.Notes__c}"/>
```

### Treat Locker and Lightning Web Security as isolation, not authorization

Aura runs under Lightning Locker unless the org has turned on Lightning Web Security for Aura (beta in Spring '23, GA in Summer '23; automatic enablement for existing production orgs has been postponed), so Aura code must work under both. Either one isolates namespaces in the browser; neither stops a user from calling the Apex behind the component ([Treat Lightning Web Security as isolation](lwc.md#security-in-the-browser)).

```html
<!-- ❌ The only check is in markup: any user with access to the Apex class can call voidInvoice directly -->
<aura:if isTrue="{!v.isManager}"><lightning:button label="{!$Label.c.Invoice_Void}" onclick="{!c.handleVoid}"/></aura:if>

<!-- ✅ Keep the markup check for the UI, and enforce the same custom permission in the Apex method -->
```

### Don't navigate to user-controlled URLs

`force:navigateToURL` with a URL from page state, a record field, or an attribute the caller sets is an open redirect. Navigate with `lightning:navigation` and a page reference.

```javascript
// ❌ Open redirect: the URL comes from the page state (the component implements lightning:isUrlAddressable)
handleBack: function (component) {
    var navigate = $A.get('e.force:navigateToURL');
    navigate.setParams({ url: component.get('v.pageReference').state.c__returnUrl });
    navigate.fire();
},

// ✅ A page reference built from a known record (<lightning:navigation aura:id="nav"/> in the markup)
handleBack: function (component) {
    component.find('nav').navigate({
        type: 'standard__recordPage',
        attributes: { recordId: component.get('v.recordId'), objectApiName: 'Account', actionName: 'view' }
    });
}
```

### Let LDS enforce access; make custom Apex enforce it too

`lightning:recordForm`, `lightning:recordEditForm`, `lightning:recordViewForm`, and `force:recordData` enforce CRUD, FLS, and sharing for the running user. A custom Apex controller gets none of that: its methods enforce access themselves ([The LWC-Apex Contract](lwc.md#the-lwc-apex-contract)), after you check the class's `<apiVersion>` ([Security Model](platform.md#security-model)).

```html
<!-- ✅ No Apex to secure: the form shows and saves only what the user may see and edit -->
<lightning:recordEditForm recordId="{!v.recordId}" objectApiName="Invoice__c">
    <lightning:messages/>
    <lightning:inputField fieldName="Status__c"/>
    <lightning:inputField fieldName="Amount__c"/>
    <lightning:button type="submit" label="{!$Label.c.Invoice_Save}"/>
</lightning:recordEditForm>
```

---

## Code Organization

### Controllers delegate, helpers hold logic, renderers own the DOM

A controller action handles one event and delegates. Shared logic goes in the helper, which is one object shared by every instance of the component, so per-instance state belongs in component attributes, never on the helper.

```javascript
// invoiceListController.js
// ❌ One action calling another, and per-instance state stored on the shared helper
handleInit: function (component, event, helper) {
    helper.selectedId = null;
    this.handleRefresh(component, event, helper);
},

// ✅ Actions delegate to the helper; state lives in attributes
handleInit: function (component, event, helper) {
    component.set('v.selectedId', null);
    helper.loadInvoices(component);
},
handleRefresh: function (component, event, helper) {
    helper.loadInvoices(component);
}
```

### Declare typed attributes with defaults, and bound design attributes

Untyped `Object` attributes without defaults make every consumer guess the shape and let `undefined` leak into expressions. `.design` attributes are set by admins in Lightning App Builder: bound them in metadata and still validate them in code.

```html
<!-- ❌ An untyped attribute with no default -->
<aura:attribute name="config" type="Object"/>

<!-- ✅ Specific types, defaults, and private access for internal state -->
<aura:attribute name="maxRows" type="Integer" default="50"/>
<aura:attribute name="invoices" type="Object[]" default="[]" access="private"/>
<aura:attribute name="isLoading" type="Boolean" default="false" access="private"/>

<!-- ✅ invoiceList.design: a bounded builder property -->
<design:component label="Open Invoices">
    <design:attribute name="maxRows" label="Maximum rows" min="1" max="200"/>
</design:component>
```

---

## Testing

### Keep logic where it can be tested

Aura has no maintained unit-test runner: Lightning Testing Service is archived and no longer supported, and it ran inside an org, which a static review can't do. Keep business rules in Apex, where Apex tests cover them and the server enforces them, or migrate the slice to LWC, where Jest runs locally ([Testing with Jest](lwc.md#testing-with-jest)).

```javascript
// ❌ A pricing rule in the helper: no test runner covers it, and the browser can bypass it
discountFor: function (invoice) {
    return invoice.Amount__c > 10000 ? invoice.Amount__c * 0.05 : 0;
},

// ✅ Apex computes the discount (tested and enforced on the server); the helper only displays it
showDiscount: function (component, response) {
    component.set('v.discount', response.getReturnValue().discount);
}
```

### Lint Aura JavaScript with the Salesforce configs

`@salesforce/eslint-plugin-aura` 3.x supports ESLint 9 only. Its `recommended` config parses Aura files as ES5 scripts and enables `vars-on-top`, `no-console`, and `@salesforce/aura/aura-api` for `$A` usage; `locker` adds `secure-document`, `secure-window`, and `ecma-intrinsics`. Bundle files are a bare object literal, so projects put `// eslint-disable-next-line no-unused-expressions` above `({`, as lwc-recipes does ([Tooling](platform.md#tooling)).

```javascript
// eslint.config.js, following the lwc-recipes layout
const { defineConfig } = require('eslint/config');
const auraConfig = require('@salesforce/eslint-plugin-aura');

module.exports = defineConfig([
    { files: ['force-app/main/default/aura/**/*.js'], extends: [...auraConfig.configs.recommended, ...auraConfig.configs.locker] }
]);
```

---

## Review Checklist

### Justification
- [ ] A new Aura component documents the gap LWC can't fill; migration moves leaf components to LWC first, never the reverse
- [ ] Business rules live in Apex or LWC, where tests cover them

### Server actions
- [ ] Every callback handles `SUCCESS`, `ERROR`, and `INCOMPLETE`, and clears loading state
- [ ] Code in timers, promises, and library callbacks is wrapped in `$A.getCallback()` and checks `component.isValid()`
- [ ] Storable (cacheable) callbacks are safe to run twice, views load with one action, and slow actions use `setBackground()`

### Events
- [ ] Component events for parent-child communication, application events only for app-wide signals, LMS to reach LWC or Visualforce
- [ ] Parents call children through `aura:method`; fired events are registered, and a `destroy` handler removes listeners and timers

### Rendering
- [ ] `aura:if` and CSS toggling are chosen deliberately, and one-time values use unbound `{#v.x}` expressions
- [ ] Large lists page, and DOM work happens only in renderers that call their super methods

### Security
- [ ] No `aura:unescapedHtml` or `innerHTML` with user data, and no navigation to user-controlled URLs
- [ ] Access checks in markup are mirrored in Apex; custom controllers enforce sharing and CRUD/FLS, and LDS is used where it fits

### Code organization & tests
- [ ] Controllers delegate to helpers, no state lives on the shared helper, and attributes are typed with defaults
- [ ] Aura JavaScript is linted with the `recommended` and `locker` configs

---

## References

- Aura Components Developer Guide: [Introduction](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/intro_framework.htm) · [Calling a Server-Side Action](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/controllers_server_actions_call.htm) · [Storable Actions](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/controllers_server_storable_actions.htm) · [Modifying Components Outside the Framework Lifecycle](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/js_cb_mod_ext_js.htm) · [Checking Component Validity](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/js_cmp_isvalid.htm) · [Events Best Practices](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/events_best_practices.htm) · [Sharing JavaScript Code in a Component Bundle](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/js_helper.htm)
- [Enforcing CRUD and FLS in Aura Components (Salesforce Developers)](https://developer.salesforce.com/docs/platform/aura-platform/guide/apex-crud-fls.html)
- LWC Developer Guide: [Migrate Aura Components](https://developer.salesforce.com/docs/platform/lwc/guide/migrate-introduction.html) · [Aura Coexistence](https://developer.salesforce.com/docs/platform/lwc/guide/interop-intro.html)
- [Lightning Web Security (Salesforce Developers)](https://developer.salesforce.com/docs/platform/lightning-components-security/guide/lws-intro.html)
- [forcedotcom/eslint-plugin-aura (GitHub)](https://github.com/forcedotcom/eslint-plugin-aura) · [forcedotcom/LightningTestingService, archived (GitHub)](https://github.com/forcedotcom/LightningTestingService)
