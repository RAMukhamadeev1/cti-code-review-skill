# Aura Components Code Review Guide

Review rules for Aura bundles (`.cmp`, `.app`, `.evt`, `.design`, and their `Controller.js`, `Helper.js`, and `Renderer.js` files) and the Apex they call. Aura is still supported, but new UI belongs in LWC, so most findings here keep existing components safe until they migrate. Controller, helper, and renderer files also load the [JavaScript Guide](../javascript.md). The Apex named in `controller="..."` follows [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract).

> Load [platform.md](platform.md) first. Related: [LWC](lwc.md) · [Security in the Browser](lwc.md#security-in-the-browser)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.
Pre-existing code is a finding only when the change makes it worse; fixes and small changes to existing Aura components don't justify demanding a rewrite. Take default tiers from the [severity table](platform.md#severity-calibration).

### New UI & migration → [Migration to LWC](#migration-to-lwc)

- [ ] A new `aura/` bundle documents the gap LWC can't fill (without that, 🟡 [important]); Aura stays at most a thin wrapper where a container still requires it
- [ ] Migration moves leaf components to LWC and embeds them in the Aura parent, never the reverse

### Server actions → [Server Actions](#server-actions)

- [ ] Every callback handles `SUCCESS`, `ERROR`, and `INCOMPLETE`, and clears loading state
- [ ] Code in timers, promises, and library callbacks is wrapped in `$A.getCallback()` and checks `component.isValid()`
- [ ] Callbacks of cacheable (storable) actions are safe to run twice; a view loads with one action, and slow actions use `setBackground()`

### Events → [Events & Communication](#events--communication)

- [ ] Component events carry parent-child communication, application events only app-wide signals, and Lightning Message Service reaches LWC or Visualforce
- [ ] Parents call children through `aura:method`; every fired event is registered with `<aura:registerEvent>`; a `destroy` handler removes window listeners and timers

### Rendering → [Rendering & Performance](#rendering--performance)

- [ ] `aura:if` and CSS toggling are chosen deliberately, and neither is treated as access control
- [ ] Large lists page through Apex or `lightning:datatable` infinite loading
- [ ] DOM work runs after rendering (a `render` event handler, or a renderer that calls its super methods), never in `init` or another controller action

### Security → [Security](#security)

- [ ] No `aura:unescapedHtml` or renderer `innerHTML` with record data or URL parameters
- [ ] No `force:navigateToURL` with a URL from page state, a record field, or an attribute the caller sets
- [ ] Access checks in markup are mirrored in Apex; custom controllers enforce sharing and CRUD/FLS; LDS forms are used where they fit

### Code organization & tests → [Code Organization](#code-organization) · [Testing](#testing)

- [ ] Controllers delegate to helpers, and no per-instance state lives on the shared helper
- [ ] Attributes have specific types and defaults, and `.design` attributes are bounded and still validated in code
- [ ] Business rules live in Apex or migrated LWC, where tests run; when the repo lints Aura as ES5, no ES6+ syntax is requested

---

## Migration to LWC

Lightning Web Components are the recommended model for new UI. A new `aura/` bundle is a 🟡 [important] finding unless the change documents the gap LWC can't fill; the same panel belongs in an LWC with a `lightning__RecordPage` target. An Aura component can contain an LWC, but an LWC can't contain an Aura component. So migrate leaf components first and embed them in the existing Aura parent: data goes down through attributes, and events come back through `on<event>` handlers. Lightning Message Service connects unrelated Aura, LWC, and Visualforce components during the move.

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

A server action calls an `@AuraEnabled` Apex method. The method's own rules (cacheable reads, server-side access checks, `AuraHandledException`) are in [The LWC-Apex Contract](lwc.md#the-lwc-apex-contract).

### Handle SUCCESS, ERROR, and INCOMPLETE in every callback

`ERROR` carries the server's errors, and `INCOMPLETE` means the server was unreachable (offline or timed out). Route every callback through one helper that clears the loading state. `helper.loadInvoices`, used in later examples, enqueues `c.getOpenInvoices` the way `loadAgingReport` does [below](#batch-related-calls-and-send-slow-ones-in-the-background).

```javascript
// ❌ A callback that reads only response.getReturnValue(): an error or a dropped connection
//    leaves the spinner running and the user uninformed

// ✅ invoiceListHelper.js: callbacks call this.applyResponse (setCallback(this, ...) keeps the helper as `this`)
applyResponse: function (component, response, attributeName) {
    var state = response.getState();
    var errors = response.getError();
    component.set('v.isLoading', false);
    if (state === 'SUCCESS') {
        component.set(attributeName, response.getReturnValue());
    } else if (state === 'ERROR') {
        component.set('v.errorMessage', (errors && errors[0] && errors[0].message) || $A.get('$Label.c.Invoice_Load_Failed'));
    } else if (state === 'INCOMPLETE') {
        component.set('v.errorMessage', $A.get('$Label.c.Invoice_Offline'));
    }
}
```

### Wrap code outside the Aura lifecycle in `$A.getCallback()`

Timer, promise, and third-party library callbacks run outside the framework, so their attribute changes aren't rendered and their enqueued actions aren't sent. `$A.getCallback()` brings the code back into the lifecycle. `component.isValid()` returns `false` once the user has navigated away and the component was destroyed.

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

For components at API 44.0 or later, `@AuraEnabled(cacheable=true)` on the Apex method makes the action storable; older components call `action.setStorable()`. The framework can call the callback first with cached data, then again with fresh data if it changed. So callbacks must be safe to run twice, and cacheable methods must not write.

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

A component event travels only to the containers above its source, so its reach is visible in the markup. An application event is a broadcast that every handler in the app receives. Keep application events for truly app-wide signals, and use Lightning Message Service to reach LWC or Visualforce.

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

### Use unbound expressions only for values fixed at creation

A bound expression (`{!v.x}`) is the default, and it is correct. It registers change handlers, and passed to a child it creates two-way binding, so the child can change the parent's attribute. An unbound expression (`{#v.x}`) is evaluated once, when the child is created, and later changes never reach it. Switching to unbound is a 💡 [suggestion] only for values fixed at creation, such as a label. A value that arrives later, from a server callback or async init, must stay bound. Don't flag bound expressions.

```html
<!-- ✅ Bound (the default): the child follows the invoice when a server callback sets it -->
<c:invoiceHeader invoice="{!v.invoice}"/>

<!-- ✅ Unbound for a label fixed at creation; a value set later would never reach the child -->
<c:invoiceHeader title="{#$Label.c.Invoice_Header}" invoice="{!v.invoice}"/>
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

### Touch the DOM only after rendering

`init` and other controller actions can run before the element exists, and the next rerender can overwrite their changes. DOM work belongs after rendering:

- in a `render` event handler (`<aura:handler name="render" value="{!this}" action="{!c.handleRender}"/>`), which the Aura docs prefer to a custom renderer. It fires after every render and rerender, so put one-time work behind a flag.
- or in a renderer's `afterRender` and `rerender`, each calling its super method first.

Clean up in the renderer's `unrender` or in a `destroy` handler.

```javascript
// ❌ In invoiceChartController.js init: component.find('chart').getElement().style.height = '300px';
//    the element may not exist yet, and the next rerender undoes the change

// ✅ A render handler; chartDrawn is a private Boolean attribute, so the next render event skips the drawing
handleRender: function (component, event, helper) {
    if (!component.get('v.chartDrawn')) {
        component.set('v.chartDrawn', true);
        helper.drawChart(component);
    }
}
```

---

## Security

### Never render user data with `aura:unescapedHtml` or `innerHTML`

Expressions in markup are escaped. `aura:unescapedHtml`, or `innerHTML` in a renderer, turns record text and URL parameters into live markup: stored or reflected XSS. The severity is in the XSS escape hatch row of the [severity table](platform.md#severity-calibration).

```html
<!-- ❌ Stored XSS: record text rendered as markup -->
<aura:unescapedHtml value="{!v.invoice.Notes__c}"/>

<!-- ✅ Plain text through an escaped expression; rich text through the allowlist sanitizer -->
<p>{!v.invoice.Memo__c}</p>
<lightning:formattedRichText value="{!v.invoice.Notes__c}"/>
```

### Mirror markup checks in Apex, and let LDS enforce access where it fits

A check in markup only shapes the UI: any user with access to the Apex class can call the method directly. Lightning Locker and Lightning Web Security isolate namespaces in the browser, but neither authorizes anything; which one runs, and what it covers, is in [Security in the Browser](lwc.md#security-in-the-browser). `lightning:recordForm`, `lightning:recordEditForm`, `lightning:recordViewForm`, and `force:recordData` enforce CRUD, FLS, and sharing for the running user. A custom Apex controller gets none of that: its methods enforce access themselves ([The LWC-Apex Contract](lwc.md#the-lwc-apex-contract)), judged against the class's `<apiVersion>` ([Security Model](platform.md#security-model)).

```html
<!-- ❌ The only check is in markup: any user with access to the Apex class can call voidInvoice directly -->
<aura:if isTrue="{!v.isManager}"><lightning:button label="{!$Label.c.Invoice_Void}" onclick="{!c.handleVoid}"/></aura:if>
<!-- ✅ Keep the markup check for the UI, and enforce the same custom permission in the Apex method -->

<!-- ✅ No Apex to secure: the form shows and saves only what the user may see and edit -->
<lightning:recordEditForm recordId="{!v.recordId}" objectApiName="Invoice__c">
    <lightning:messages/>
    <lightning:inputField fieldName="Status__c"/>
    <lightning:button type="submit" label="{!$Label.c.Invoice_Save}"/>
</lightning:recordEditForm>
```

### Navigate with `lightning:navigation`

Navigate with `lightning:navigation` page references (`component.find('nav').navigate({ type: 'standard__recordPage', ... })`), never with `force:navigateToURL` and a URL from page state, a record field, or an attribute the caller sets. The open-redirect rules live in [Allowlist redirect targets](visualforce.md#allowlist-redirect-targets).

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

An `Object` attribute without a default makes every consumer guess the shape and lets `undefined` leak into expressions. Prefer specific types (`Integer`, `Boolean`, `Account[]`, an Apex class) with defaults; `Object` with a default stays acceptable for loosely shaped server data. `.design` attributes are set by admins in Lightning App Builder: bound them in metadata and still validate them in code.

```html
<!-- ❌ An untyped attribute with no default -->
<aura:attribute name="config" type="Object"/>

<!-- ✅ Specific types, defaults, and private access for internal state -->
<aura:attribute name="maxRows" type="Integer" default="50"/>
<aura:attribute name="invoices" type="Object[]" default="[]" access="private"/>

<!-- ✅ invoiceList.design: a bounded builder property -->
<design:component label="Open Invoices">
    <design:attribute name="maxRows" label="Maximum rows" min="1" max="200"/>
</design:component>
```

---

## Testing

### Keep logic where it can be tested

Aura has no maintained unit-test runner. Lightning Testing Service is archived and no longer supported, and it ran inside an org, which a static review can't do. Keep business rules in Apex, where Apex tests cover them and the server enforces them, or migrate the slice to LWC, where Jest runs locally ([Testing with Jest](lwc.md#testing-with-jest)).

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

`@salesforce/eslint-plugin-aura` 3.x supports ESLint 9 only ([Tooling](platform.md#tooling)).

- Its `recommended` config parses Aura files as ES5 scripts (`ecmaVersion: 5`) and enables `vars-on-top`, `no-console`, and `@salesforce/aura/aura-api` for `$A` usage.
- `locker` adds `ecma-intrinsics`, `secure-document`, and `secure-window`.

The examples here therefore use `var` and function expressions. Where a project lints Aura with this config, don't ask for `const`, arrow functions, or `async`/`await` in Aura files; that part of the JavaScript Guide applies to LWC. Bundle files are a bare object literal, so projects put `// eslint-disable-next-line no-unused-expressions` above `({`. When the repo runs the linter, its hits are lint output, not review findings. ESLint executes the repo's config and plugins, so run it only on trusted code.

---

## References

- [Calling a Server-Side Action (Aura Components Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/controllers_server_actions_call.htm)
- [Storable Actions (Aura Components Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/controllers_server_storable_actions.htm)
- [Handle the render Event (Aura Components Developer Guide)](https://developer.salesforce.com/docs/platform/aura-platform/guide/js-render-handler.html)
- [Enforcing CRUD and FLS in Aura Components (Salesforce Developers)](https://developer.salesforce.com/docs/platform/aura-platform/guide/apex-crud-fls.html)
- [forcedotcom/eslint-plugin-aura (GitHub)](https://github.com/forcedotcom/eslint-plugin-aura)
