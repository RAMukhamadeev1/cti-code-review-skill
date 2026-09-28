# Lightning Web Components (LWC) Code Review Guide

Review rules for Lightning Web Component bundles (`.js`, `.html`, `.css`, `.js-meta.xml`, Jest tests) and the `@AuraEnabled` Apex they call. Judge each component against its own `<apiVersion>` and the release of the orgs it deploys to: Summer '26 is API 67.0, Winter '27 is API 68.0. General JavaScript rules live in the [JavaScript Guide](../javascript.md). `.ts` components also load the [TypeScript Guide](../typescript.md); LWC TypeScript is a Developer Preview, so never require it. Examples call `reduceErrors` from a shared `c/ldsUtils` module ([Normalize client errors](#normalize-client-errors-with-one-shared-utility)).

> Load [platform.md](platform.md) first. Related: [Apex](apex.md) · [SOQL & SOSL](soql-sosl.md) · [Aura](aura.md) when an Aura component hosts the LWC

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.
Pre-existing code is a finding only when the change makes it worse. When the repo runs `@salesforce/eslint-config-lwc`, the rules it enforces are lint output, not review findings. Take default tiers from the [severity table](platform.md#severity-calibration).

### Data flow & reactivity → [Data Flow & Reactivity](#data-flow--reactivity)

- [ ] Children never write to `@api` properties or objects received through them; changes go up as lowercase events without an `on` prefix
- [ ] Events keep `bubbles` and `composed` at `false` unless they must cross a shadow boundary, and `detail` carries primitives or a copy
- [ ] Unrelated components talk through a Lightning Message Service channel carrying Ids, not window events, pub/sub modules, or module-level state
- [ ] Arrays and objects are reassigned (or deliberately `@track`ed), and getters have no side effects

### Templates → [Templates](#templates)

- [ ] New markup uses `lwc:if` / `lwc:elseif` / `lwc:else` with loading, error, and empty branches; `if:true` in new code is 🟢 [nit], and untouched legacy markup is not a finding
- [ ] `for:each` keys are stable, unique ids, such as the record Id
- [ ] Elements are reached with `lwc:ref`, or `data-*` selectors on `this.template` inside loops, never with `id` selectors or `document`
- [ ] Complex template expressions appear only at `apiVersion` 66.0+, and logic worth testing stays in getters

### Lifecycle → [Lifecycle](#lifecycle)

- [ ] `connectedCallback` is safe to run twice, and `disconnectedCallback` releases every listener, timer, subscription, and library instance it added
- [ ] `renderedCallback` sets state only on change and puts one-time work behind a flag
- [ ] Async hooks and handlers catch their own errors; children that can fail sit inside an `errorCallback` boundary

### Data access → [Data Access](#data-access)

- [ ] LDS, the base record forms, or GraphQL serve what they can; Apex serves the rest, with one data source per record
- [ ] Field references come from `@salesforce/schema` imports unless the field is chosen at runtime
- [ ] Reads are wired and writes imperative. After an Apex write, each view that shows the data is refreshed: `refreshApex` for Apex wires, `notifyRecordUpdateAvailable` for LDS records, `RefreshEvent` for standard components. LDS writes need neither
- [ ] Input-driven calls are debounced, and stale imperative responses are dropped

### Apex contract → [The LWC-Apex Contract](#the-lwc-apex-contract)

- [ ] `cacheable=true` methods have no DML or other side effects
- [ ] Each `@AuraEnabled` method validates and bounds its arguments, enforces access on the server (with a permission check for privileged actions), and returns only the fields the component shows
- [ ] Server errors reach the client as `AuraHandledException` with a safe message after the cause is logged; the client normalizes them in one shared utility and never swallows them

### Browser security → [Security in the Browser](#security-in-the-browser)

- [ ] No `innerHTML` with untrusted data in `lwc:dom="manual"` containers
- [ ] Navigation uses `NavigationMixin` page references, and URLs from data are protocol-checked before binding
- [ ] Third-party libraries come from versioned static resources; no API keys or tokens ship in component files, static resources, or Custom Labels

### Styling, performance & configuration → [Styling](#styling) · [Performance](#performance) · [Component Configuration](#component-configuration)

- [ ] Base components are styled through `--slds-c-*` hooks, never by overriding their internal or SLDS classes
- [ ] Heavy, rarely used children load lazily, and a list loads its data in one call and pages
- [ ] Targets are minimal; when the PR adds an Experience Cloud target, the Apex behind the component holds up for site and guest users
- [ ] `apiVersion` changes are deliberate, `lwc:component` has the `lightning__dynamicComponent` capability, and builder properties are typed, bounded, and validated in code
- [ ] Text comes from Custom Labels, values from `lightning-formatted-*` (`time-zone="UTC"` for date-only fields), and controls are labeled base components

### Tests & lint → [Testing with Jest](#testing-with-jest)

- [ ] Jest tests drive the DOM, emit wire data and errors, mock imperative Apex for success and failure, assert dispatched events, and reset the DOM after each test
- [ ] Every disabled ESLint rule has a stated reason

---

## Data Flow & Reactivity

### Treat `@api` properties as read-only; send changes up with a `CustomEvent`

The parent owns public properties. Objects and arrays arrive read-only, and a primitive the child reassigns can be overwritten by the parent; take an editable copy in an `@api` setter if needed. Name events in lowercase without an `on` prefix (the parent listens with `onstatuschange`). Leave `bubbles` and `composed` at their `false` defaults unless the event must reach an ancestor across a shadow boundary; with both on, the event crosses every boundary and becomes public API of every ancestor.

```javascript
// ❌ Writes to the parent's data (throws "Invalid mutation: Cannot set ... is read-only")
this.invoice.status = 'Paid';

// ❌ Crosses every shadow boundary, has an "on" prefix and capitals, and hands out the whole object
this.dispatchEvent(new CustomEvent('onStatusChange', { bubbles: true, composed: true, detail: this.invoice }));

// ✅ Ask the owner: a lowercase, non-bubbling event with primitives (or a fresh object) in detail
this.dispatchEvent(new CustomEvent('statuschange', { detail: { invoiceId: this.invoice.invoiceId, status: 'Paid' } }));
```

ESLint `@lwc/lwc/no-api-reassignments` (in `recommended`) catches the reassignment.

### Use Lightning Message Service between unrelated components

Components outside one tree (a utility bar and a record page, LWC and Aura, Visualforce) talk through a message channel. Publish Ids, not records: every subscriber can read the payload, and each should load data through its own access checks.

```javascript
// ❌ A window event (or the old c/pubsub sample): no contract, invisible to Aura and Visualforce, easy to leak
window.dispatchEvent(new CustomEvent('invoiceselected', { detail: { invoiceId } }));

// ✅ A declared channel: publish and MessageContext from lightning/messageService,
//    INVOICE_SELECTED from @salesforce/messageChannel/InvoiceSelected__c
@wire(MessageContext) messageContext;
handleSelect(event) {
    publish(this.messageContext, INVOICE_SELECTED, { invoiceId: event.detail.invoiceId });
}
```

### Reassign fields instead of mutating them; use `@track` only for deep changes

Every field is reactive to reassignment, but the framework sees changes inside a plain object or array only when the field has `@track`, and never inside a `Date`, `Set`, `Map`, or class instance ([Mutation and copying](../javascript.md#mutation-and-copying)).

```javascript
// ❌ In-place push on an undecorated array: the template does not re-render
this.selectedIds.push(invoiceId);

// ✅ Assign a new array
this.selectedIds = [...this.selectedIds, invoiceId];

// @track is for in-place edits of a plain object or array (this.filters.status = 'Paid');
// on a primitive or an always-reassigned field it is legacy noise, not a bug
@track filters = { status: 'Open' };
```

### Keep getters pure and cheap

Template getters run on every render. A getter that writes state schedules another render, and one that sorts or copies a large array repeats the work each time. Derive values once, when the data arrives ([Read with `@wire`, write imperatively](#read-with-wire-write-imperatively)).

```javascript
// ❌ On every render: sorts the read-only wired array in place (this throws) and writes a field
get sortedRows() {
    this.rowCount = this.invoices.data.length;
    return this.invoices.data.sort((a, b) => b.amount - a.amount);
}

// ✅ Reads a value the wire handler already derived
get hasRows() {
    return this.rows.length > 0;
}
```

### Share state deliberately (Summer '26+ for state managers)

Use `@api` and events inside a tree, and Lightning Message Service across trees and frameworks. For state a component tree shares, use a state manager from `@lwc/state` (GA in Summer '26; not available in Experience Cloud, verify). Module-level variables are shared by every instance on the page and survive navigation, so they are not a store.

```javascript
// ❌ Module scope: one array for every instance of the component, kept across navigation
let cachedInvoices = [];

// ✅ Summer '26+: a state manager module (c/invoiceFilterState). The owner creates it with
//    filter = invoiceFilterState(), and templates read {filter.value.status}
import { defineState } from '@lwc/state';

export default defineState(({ atom, computed, setAtom }, initialStatus = 'Open') => {
    const status = atom(initialStatus);
    const isOpenOnly = computed([status], (value) => value === 'Open');
    return { status, isOpenOnly, setStatus: (value) => setAtom(status, value) }; // never assign status.value
});
```

---

## Templates

Templates bind properties and apply directives; logic, formatting, and element lookup live in JavaScript. Prefer `lightning-*` base components and SLDS to hand-built widgets: they bring labels, keyboard support, validation, and localization.

### Use `lwc:if`, `lwc:elseif`, and `lwc:else` in new code (Spring '23+)

`if:true` and `if:false` still work but are no longer recommended and may be removed. In new code they are a 🟢 [nit] (the legacy-idioms row of the [severity table](platform.md#severity-calibration)); in untouched legacy markup they are not a finding. Give loading, error, empty, and data their own branch.

```html
<!-- ❌ Legacy directives: a separate condition per branch, and no error or empty state -->
<template if:true={isLoading}><lightning-spinner alternative-text={labels.loading}></lightning-spinner></template>
<template if:false={isLoading}><c-invoice-table rows={rows}></c-invoice-table></template>

<!-- ✅ One chain (lwc:elseif and lwc:else directly follow their sibling); isLoading is true
     until the wire returns data or an error -->
<template lwc:if={isLoading}><lightning-spinner alternative-text={labels.loading}></lightning-spinner></template>
<template lwc:elseif={errorMessages}><c-error-panel errors={errorMessages}></c-error-panel></template>
<template lwc:elseif={hasRows}><c-invoice-table rows={rows}></c-invoice-table></template>
<template lwc:else><p>{labels.noInvoices}</p></template>
```

### Key `for:each` items by a stable, unique id

The key goes on the first element inside the iteration. The compiler rejects `key={index}`, but an index smuggled in from JavaScript, or any non-unique value, has the same effect: rows re-render or swap state when the list changes.

```html
<!-- ❌ Not unique: two invoices with the same name collide -->
<template for:each={rows} for:item="row"><c-invoice-row key={row.name} invoice={row}></c-invoice-row></template>

<!-- ✅ The record Id: stable across inserts, deletes, and sorts -->
<template for:each={rows} for:item="row"><c-invoice-row key={row.invoiceId} invoice={row}></c-invoice-row></template>
```

### Reach elements with `lwc:ref`, not id selectors (Spring '23+)

The framework can rewrite `id` values when it renders, and `document` queries reach outside the component. `this.refs` exists after rendering, not in `connectedCallback`, and `lwc:ref` inside `for:each` or `iterator` is a compile error; in loops, select `data-*` attributes on `this.template`.

```javascript
// ❌ The id may be rewritten, and the document query ignores component boundaries
this.template.querySelector('#amount').focus();
document.querySelector('c-invoice-row').highlight();

// ✅ Template: <lightning-input lwc:ref="amountInput" label={labels.amount} type="number">
this.refs.amountInput.focus();
```

ESLint `@lwc/lwc/no-document-query` (in `recommended`) catches the `document` query.

### Keep template expressions simple; compute values in getters

Below `apiVersion` 66.0 a template accepts only property references (`{amount}`, `{invoice.amount}`). Complex template expressions are GA in Winter '27 for components at `apiVersion` 66.0+. Even there, keep formatting, filtering, and logic you want to test in getters.

```html
<!-- ❌ Arithmetic in markup: a compile error below apiVersion 66.0, and logic that is easy to miss -->
<p>{invoice.amount * (1 + taxRate)}</p>

<!-- ✅ A getter computes the value; a base component formats it -->
<lightning-formatted-number value={amountWithTax} format-style="currency" currency-code={currencyCode}></lightning-formatted-number>
```

---

## Lifecycle

Hooks run in this order: `constructor`, `connectedCallback`, `render`, then `renderedCallback` (children before parents). `disconnectedCallback` runs on removal, and `errorCallback` receives descendants' errors. The framework does not await promises that hooks return, so an `async` hook catches its own errors ([No floating promises](../javascript.md#no-floating-promises)).

### Make `connectedCallback` idempotent and undo it in `disconnectedCallback`

`connectedCallback` runs every time the element is inserted, including when a list moves it. Parent properties are set, but children and wired data are not there yet. Register only what `disconnectedCallback` removes, with stable references ([Clean up listeners, timers, and observers](../javascript.md#clean-up-listeners-timers-and-observers)). LMS releases `@wire(MessageContext)` subscriptions when the component is destroyed, but unsubscribing explicitly keeps re-inserted components correct. `lightning/empApi` subscriptions end only with its own `unsubscribe()`.

```javascript
// ❌ bind() makes a new function per insertion, so listeners pile up and can never be removed,
//    and the poll keeps calling Apex after the user navigates away
connectedCallback() {
    window.addEventListener('resize', this.handleResize.bind(this));
    this.pollId = setInterval(() => this.refreshTotals(), 60000);
}

// ✅ A stable reference (adding it again is a no-op), and everything released on disconnect
handleResize = () => {
    this.isNarrow = window.innerWidth < 768;
};
connectedCallback() {
    window.addEventListener('resize', this.handleResize);
    // eslint-disable-next-line @lwc/lwc/no-async-operation
    this.pollId = setInterval(() => this.refreshTotals(), 60000); // refreshTotals() catches its own errors
}
disconnectedCallback() {
    window.removeEventListener('resize', this.handleResize);
    clearInterval(this.pollId);
    unsubscribe(this.subscription); // lightning/messageService; also destroy() library instances here
    this.subscription = null;
}
```

ESLint `@lwc/lwc/no-leaky-event-listeners` catches the leak, but it isn't in `recommended`; a project must enable it.

### Guard `renderedCallback` against render loops

It runs after every render, so state set there triggers another render. Assign only when a value changes, and put one-time work behind a flag.

```javascript
// ❌ A new object on every render (layout is used in the template): an endless loop
renderedCallback() {
    this.layout = { width: this.refs.container.clientWidth };
}

// ✅ Assign only on change; one-time work goes behind a flag (if (!this.hasFocused) { ... })
renderedCallback() {
    const width = this.refs.container.clientWidth;
    if (width !== this.layout?.width) {
        this.layout = { width };
    }
}
```

### Use `errorCallback` as an error boundary

`errorCallback(error, stack)` receives errors thrown in descendants' lifecycle hooks and template event handlers, so one failing child doesn't blank the page. Wrap children that can fail in a boundary component that sets `this.errorMessages = reduceErrors(error)`, renders `<c-error-panel>` instead of its `<slot>`, and reports the error and stack to the project's logger. Rejected promises never reach it.

---

## Data Access

### Choose the data source: LDS first, Apex last

Lightning Data Service (LDS) enforces CRUD, FLS, and sharing, keeps one cache for the page, and pushes record changes to every component. Apex results are cached separately and refreshed by hand, so use one source per record: the two caches can disagree.

| Need | Use |
|---|---|
| A standard view or edit form | `lightning-record-form`, `lightning-record-view-form`, `lightning-record-edit-form` |
| Custom UI over single records | `lightning/uiRecordApi`: `getRecord`, `updateRecord`, `createRecord`, `deleteRecord` |
| Several objects in one read | The GraphQL wire adapter in `lightning/graphql`, which supersedes `lightning/uiGraphQLApi`; results carry `errors` (not `error`) and a `refresh` function |
| Several records in one transaction (each LDS call is its own), aggregates, unsupported objects | `@AuraEnabled` Apex |

### Import schema references instead of field-name strings

The platform checks `@salesforce/schema` imports: they must exist, a referenced field can't be deleted, and a rename can't silently break the component. String field names are fine where the field is chosen at runtime, for example from a builder property.

```javascript
// ❌ A typo fails at runtime, and nothing protects the field from deletion or a rename
@wire(getRecord, { recordId: '$recordId', fields: ['Invoice__c.Status__c'] })
invoice;

// ✅ Imported references (getRecord and getFieldValue from lightning/uiRecordApi); optionalFields
//    skips fields this user can't read instead of failing the whole wire
import STATUS_FIELD from '@salesforce/schema/Invoice__c.Status__c';
import NOTES_FIELD from '@salesforce/schema/Invoice__c.Notes__c';

@wire(getRecord, { recordId: '$recordId', fields: [STATUS_FIELD], optionalFields: [NOTES_FIELD] })
invoice;
get status() {
    return getFieldValue(this.invoice.data, STATUS_FIELD);
}
```

### Read with `@wire`, write imperatively

A wire re-runs when its `$` parameters change and shares the client cache; it needs LDS or a `cacheable=true` Apex method. Writes and user-triggered actions are imperative calls. Both render loading, error, and empty states ([the `lwc:if` chain](#use-lwcif-lwcelseif-and-lwcelse-in-new-code-spring-23)).

```javascript
// ❌ An imperative read: never re-runs when recordId changes, nothing refreshes it after a save,
//    and a rejection goes unhandled (the framework ignores the promise the hook returns)
async connectedCallback() {
    this.rows = await getOpenInvoices({ accountId: this.recordId });
}

// ✅ Wire the read and keep the whole provisioned result for refreshApex()
@wire(getOpenInvoices, { accountId: '$recordId' })
wiredInvoices(result) {
    this.wiredInvoicesResult = result;
    if (result.data) {
        this.rows = result.data.map((row) => ({ ...row })); // wired data is read-only: copy once to edit
        this.errorMessages = undefined;
    } else if (result.error) {
        this.rows = [];
        this.errorMessages = reduceErrors(result.error);
    }
}
```

### Refresh the views that show changed data

Refresh what displays the changed records:

- `refreshApex` (from `@salesforce/apex`) takes the whole object the wire provisioned and refreshes that Apex wire.
- LDS-backed views (`getRecord`, `lightning-record-form`) learn about Apex writes through `notifyRecordUpdateAvailable`, which replaces the deprecated `getRecordNotifyChange`.
- `RefreshEvent` from `lightning/refresh` asks the container to refresh standard components, such as the record page's details and related lists.

Writes made through LDS (`updateRecord`, `lightning-record-edit-form`) update the LDS cache themselves. An Apex wire that shows the same data still needs `refreshApex`.

```javascript
// ❌ Refreshes the data array instead of the provisioned result; LDS views keep the old status
await markInvoicesPaid({ invoiceIds });
await refreshApex(this.rows);

// ✅ Refresh the Apex wire, tell LDS which records changed, and show errors instead of swallowing them
try {
    await markInvoicesPaid({ invoiceIds });
    await Promise.all([
        refreshApex(this.wiredInvoicesResult),
        notifyRecordUpdateAvailable(invoiceIds.map((recordId) => ({ recordId })))
    ]);
} catch (error) {
    this.errorMessages = reduceErrors(error);
}
// ✅ When standard components on the page show the records too: this.dispatchEvent(new RefreshEvent());
```

### Debounce input and batch server calls

A wired parameter bound to an input fires one call per keystroke: debounce it and clear the timer on disconnect. Load what a view needs in one call instead of chaining several. Imperative calls can't be aborted, so drop stale responses with the request-id pattern in [Race conditions](../javascript.md#race-conditions-cancel-or-ignore-stale-results), keeping the counter on the instance: a module-level counter is shared by every instance on the page.

```javascript
// ❌ handleSearchChange(event) { this.searchTerm = event.target.value; }: one Apex call per keystroke

// ✅ Update the wired parameter ($searchTerm) only after typing pauses
handleSearchChange(event) {
    const value = event.target.value;
    clearTimeout(this.searchTimer);
    // eslint-disable-next-line @lwc/lwc/no-async-operation
    this.searchTimer = setTimeout(() => {
        this.searchTerm = value;
    }, 300);
}
```

---

## The LWC-Apex Contract

Every `@AuraEnabled` method is a public endpoint: any user with access to the Apex class can call it with any arguments, without your component. The trust-boundary rules are in [Security Model](platform.md#security-model). Hiding a button protects nothing. A privileged action checks in Apex the same custom permission the component reads from `@salesforce/customPermission/...` (`FeatureManagement.checkPermission('Void_Invoices')`), and every argument is validated, including each Id's `getSObjectType()`. These rules apply to Aura server actions too. Check each class's `<apiVersion>` first; writes, mass assignment, and `stripInaccessible` are covered in [Data Access Security](apex.md#data-access-security).

### Mark only side-effect-free methods `cacheable=true`

`@wire` requires `cacheable=true`, and the client may answer from its cache without running the method. DML in a cacheable method fails at runtime (`System.LimitException: Too many DML statements: 1`), and other side effects run unpredictably.

```apex
// ❌ A write inside a cacheable read: the insert fails, and a cached response skips the method entirely
@AuraEnabled(cacheable=true)
public static Integer countAndTrackView(Id accountId) {
    insert as user new Invoice_View__c(Account__c = accountId);
    return [SELECT COUNT() FROM Invoice__c WHERE Account__c = :accountId WITH USER_MODE];
}

// ✅ The read stays cacheable; recording the view is a separate @AuraEnabled method called imperatively
@AuraEnabled(cacheable=true)
public static Integer countOpenInvoices(Id accountId) {
    return [SELECT COUNT() FROM Invoice__c WHERE Account__c = :accountId AND Status__c = 'Open' WITH USER_MODE];
}
```

### Return only the fields the component needs

Whatever a method returns reaches the browser, every field included. Returning sObjects queried in user mode with only the fields the component renders is fine, and it's the lwc-recipes pattern. Flag a return that carries fields the component doesn't show, or data read in system mode. A DTO class with `@AuraEnabled` members is a 💡 [suggestion] when the component needs a stable shape or derived values. An `@AuraEnabled` property with a private or protected getter is unreadable from LWC and Aura (PMD `InaccessibleAuraEnabledGetter`).

```apex
// ❌ Internal_Margin__c travels to a table that shows only the name and amount
return [SELECT Id, Name, Amount__c, Internal_Margin__c FROM Invoice__c WHERE Account__c = :accountId WITH USER_MODE LIMIT 200];

// ✅ Only what the component renders, in user mode
return [SELECT Id, Name, Amount__c FROM Invoice__c WHERE Account__c = :accountId WITH USER_MODE ORDER BY Name LIMIT 200];
```

### Throw `AuraHandledException` with a safe message and log the cause

An uncaught exception shows the user whatever the platform puts in its text (DML status codes, record Ids, or a generic server error), and nothing useful gets logged. Bound the input, catch the specific exception, log it, and throw an `AuraHandledException` with an actionable message. Call `setMessage()` too, or `getMessage()` returns "Script-thrown exception" on the server, in tests, and in logs ([Error Handling Principles](../cross-cutting/error-handling-principles.md#core-principles); Apex side: [Transactions & Error Handling](apex.md#transactions--error-handling)).

```apex
// ❌ A bare `update invoices;`: the raw DML error text reaches the browser, and nothing is logged

// ✅ Bounded input, user-mode DML, the cause logged, and a safe, translatable message
if (invoiceIds == null || invoiceIds.isEmpty() || invoiceIds.size() > 200) {
    throw new AuraHandledException(System.Label.Invoice_Selection_Invalid);
}
try {
    update as user invoices; // built from invoiceIds after each Id's getSObjectType() was checked
} catch (DmlException e) {
    // log e.getMessage() and e.getStackTraceString() with the project's logger here
    AuraHandledException error = new AuraHandledException(System.Label.Invoice_Update_Failed);
    error.setMessage(System.Label.Invoice_Update_Failed);
    throw error;
}
```

### Normalize client errors with one shared utility

Errors arrive in several shapes:

- `body.message` (Apex, UI API)
- an array `body` (UI API reads)
- `body.pageErrors` and `body.fieldErrors` (DML)
- `body.output.errors` and `body.output.fieldErrors` (UI API DML)
- plain JavaScript and network errors

Pass them through one shared utility, such as `reduceErrors` in lwc-recipes' `ldsUtils`. A `console` call alone swallows the error.

```javascript
// ❌ One assumed shape: an error without a body throws a TypeError, and UI API errors show nothing
this.errorMessage = error.body.message;

// ✅ One utility that handles every shape and returns a list of messages
this.errorMessages = reduceErrors(error);
```

### Keep parameters few and typed

Positional primitives grow with every feature, and the JavaScript call must match the Apex parameter names exactly. Take one request class with `@AuraEnabled` members, and bound every field on the server ([Parameter Sprawl](../code-quality-universal.md#parameter-sprawl)).

```apex
// ❌ searchInvoices(String status, Decimal minAmount, Date fromDate, Date toDate, Id ownerId, ...)

// ✅ LWC calls searchInvoices({ request: { status: 'Open', pageSize: 50 } }); the server clamps what it receives
public class SearchRequest {
    @AuraEnabled public String status { get; set; }
    @AuraEnabled public Integer pageSize { get; set; }
}
Integer pageSize = Math.min(Math.max(request?.pageSize ?? 50, 1), 200); // ?? needs API 60.0+
```

---

## Security in the Browser

### Treat Lightning Web Security as isolation, not authorization

Lightning Web Security (LWS) gives each namespace's JavaScript its own sandbox and restricts risky APIs; dynamic components require it. LWS is on by default in new orgs, while orgs that never switched still run Lightning Locker. Aura components run under LWS only where the org has enabled it for Aura, so Aura code must work under both. When the target orgs run LWS, question new Locker-era workarounds, such as forked "Locker-compatible" library builds or Visualforce iframes used only to escape the sandbox. Ask which architecture each target org runs.

| Concern | Handled by |
|---|---|
| One namespace's script reading or patching another's | LWS, or Locker in orgs without LWS |
| Who may read or change a record or field | LDS, or Apex in user mode with a sharing keyword |
| Who may run a privileged action | A permission check in Apex; the component's check only shapes the UI |
| Data rendered as markup | Template binding (always escaped) or `lightning-formatted-rich-text` |
| API keys and tokens | A Named Credential that Apex calls through: every component file, static resource, and Custom Label is readable by any user who can load the page |

### Never render untrusted HTML through `lwc:dom="manual"`

`lwc:dom="manual"` exists for libraries that manage their own DOM. Writing record data into such a container with `innerHTML` is stored XSS, and LWS is not a sanitizer to rely on ([Safe DOM updates](../javascript.md#safe-dom-updates); severity: the XSS escape hatch row of the [severity table](platform.md#severity-calibration)).

```javascript
// ❌ Template: <div lwc:dom="manual" lwc:ref="notes"></div>; the record's notes become live markup
this.refs.notes.innerHTML = this.invoice.notes;

// ✅ Plain text: bind {invoice.notes} (always escaped) or set textContent
this.refs.notes.textContent = this.invoice.notes;

// ✅ Rich text: <lightning-formatted-rich-text value={invoice.notes}> keeps only allowlisted tags
```

ESLint `@lwc/lwc/no-inner-html` (in `recommended`) flags every `innerHTML` assignment.

### Navigate with page references

Navigate with `NavigationMixin` page references (`this[NavigationMixin.Navigate]({ type: 'standard__recordPage', ... })`), never with `window.location` set from page state or a record field. Bind a URL from data (such as `Account.Website`) only after `new URL(value).protocol` is `http:` or `https:`. The open-redirect rules live in [Allowlist redirect targets](visualforce.md#allowlist-redirect-targets).

### Load third-party libraries from static resources

Lightning Experience can't load JavaScript from a third-party host, even one listed as a Trusted URL (formerly CSP Trusted Sites), so a CDN script fails at runtime whatever the org's settings. Ship a pinned copy as a static resource, with the version in its name or description, and load it once. Trusted URLs cover other resource types, such as API calls, images, fonts, styles, and frames; review each new one as an exception ([Integration Endpoints & Credentials](metadata.md#integration-endpoints--credentials)). Code Analyzer's RetireJS rules flag static resources that contain JavaScript libraries with known vulnerabilities ([Tooling](platform.md#tooling)).

```javascript
// ❌ Blocked in Lightning Experience whatever the Trusted URLs say, and unpinned
loadScript(this, 'https://cdn.example.com/chart.js/latest/chart.umd.js');

// ✅ A versioned static resource (import CHART_JS from '@salesforce/resourceUrl/chartJs_4_4'), loaded once,
//    drawing into a container the library owns: <div lwc:dom="manual" lwc:ref="chart"></div>
renderedCallback() {
    if (this.chartInitialized) return;
    this.chartInitialized = true;
    loadScript(this, CHART_JS)
        .then(() => this.initializeChart())
        .catch((error) => {
            this.errorMessages = reduceErrors(error);
        });
}
```

---

## Styling

Component styles are scoped by the shadow DOM, and base component markup can change in any release. Salesforce doesn't support styling the rendered markup of base components or overriding SLDS classes.

- Style base components through their styling hooks (`--slds-c-*`), set on `:host`. Selectors aimed at their internal classes don't cross the shadow boundary, so they end up in a global `loadStyle()` sheet with `!important`, leak to every component on the page, and break when SLDS changes.
- Prefer SLDS utility classes (`slds-p-around_medium`) in markup. In CSS, use global styling hooks (`--slds-g-*`) with an SLDS 1 fallback; design tokens (`--lwc-*`) still work in SLDS 1 themes but aren't part of SLDS 2.
- Components render in narrow regions and on mobile. Avoid fixed widths and `:host` margins, keep focus visible (`:focus-visible`, never a bare `outline: none`), animate only cheap properties, and respect `prefers-reduced-motion`.

SLDS Linter (`@salesforce-ux/slds-linter`) checks CSS and markup against SLDS 2 guidance. When the repo runs it, its hits are lint output, not review findings.

```css
/* ❌ A base component's internals, from a global sheet, forced with !important */
.slds-button_brand { background-color: #0b5cab !important; }

/* ✅ The documented hook, set once on the host */
:host { --slds-c-button-brand-color-background: #0b5cab; }
```

---

## Performance

Most LWC performance problems are server round trips and oversized renders. A child per row that calls Apex, imperatively or through its own `@wire`, turns N rows into N requests. Load the list's data in one call in the parent and pass each row its values ([N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow)). The page-level view is in [Salesforce Platform Performance](../performance-review-guide.md#salesforce-platform-performance).

### Lazy-load heavy components (Winter '24+ for dynamic components)

A heavy child that most users never open still downloads when it is referenced statically. Load it on first use with `import()` and render it with `<lwc:component lwc:is={...}>`. Dynamic components require LWS, the `lightning__dynamicComponent` capability, and `apiVersion` 55.0+ ([Dynamic import() and code splitting](../javascript.md#dynamic-import-and-code-splitting)).

```javascript
// ❌ Template: <c-invoice-chart invoices={rows}></c-invoice-chart> inside a tab most users never open

// ✅ Template: <lightning-tab label={labels.chart} onactive={handleChartTabActive}>
//                  <lwc:component lwc:is={chartConstructor} invoices={rows}></lwc:component></lightning-tab>
async handleChartTabActive() {
    if (this.chartConstructor) return;
    try {
        const { default: ctor } = await import('c/invoiceChart'); // a literal specifier
        this.chartConstructor = ctor;
    } catch (error) {
        this.errorMessages = reduceErrors(error);
    }
}
```

### Page large lists

Thousands of rows cost heap and CPU on the server and render time in the browser. Page with `lightning-datatable` infinite loading:

1. Bind `enable-infinite-loading={hasMore}`.
2. In the `onloadmore` handler, set `event.target.isLoading` while an `async` call fetches the next page, inside `try`/`catch`/`finally`.
3. Append the page as a new array.

Apex serves keyset pages (`WHERE Id > :afterId ORDER BY Id LIMIT :pageSize`); `OFFSET` works only while the whole list stays under 2,000 rows ([Pagination & Cursors](soql-sosl.md#pagination--cursors)).

---

## Component Configuration

### Expose only the targets you need

`isExposed` and `targets` decide where admins can place a component. Experience Cloud targets (`lightningCommunity__Page`, `lightningCommunity__Default`) put it on sites. Its Apex is then called by site users whose profile or permission sets grant the class, and by guests only when the site's guest profile grants it (`classAccesses`). Check those grants when the PR touches profiles or permission sets; otherwise ask the author. Either way, that Apex must hold up for external users ([Security Model](platform.md#security-model)).

```xml
<!-- ❌ Exposed everywhere "just in case", including Experience Cloud sites -->
<targets>
    <target>lightning__AppPage</target>
    <target>lightning__RecordPage</target>
    <target>lightningCommunity__Page</target>
    <target>lightningCommunity__Default</target>
</targets>

<!-- ✅ Only the record page it was built for, limited to the object it understands -->
<targets>
    <target>lightning__RecordPage</target>
</targets>
<targetConfigs>
    <targetConfig targets="lightning__RecordPage">
        <objects>
            <object>Account</object>
        </objects>
    </targetConfig>
</targetConfigs>
```

### Set `apiVersion` and capabilities deliberately

A component's `apiVersion` decides which framework behavior it gets (complex template expressions need 66.0+, dynamic components 55.0+), while the Apex it calls follows its own class version. Review a bump as a behavior change with its own retest ([API Versions](platform.md#api-versions)), and declare the capabilities the code relies on.

```xml
<!-- ✅ A deliberate version, and the capability that lwc:component needs -->
<apiVersion>67.0</apiVersion>
<capabilities>
    <capability>lightning__dynamicComponent</capability>
</capabilities>
```

### Validate builder properties like any other input

Admins set `targetConfig` properties in Lightning App Builder. Type, bound, and default them in metadata, then still validate them in code. A property never flows unchecked into dynamic SOQL, field names, or markup, and the Apex that receives it allowlists it.

```xml
<!-- ✅ Typed, bounded, defaulted properties (the component still clamps maxRows before using it) -->
<property name="maxRows" type="Integer" label="Maximum rows" default="50" min="1" max="200"/>
<property name="statusFilter" type="String" label="Status" datasource="Open,Paid,Void" default="Open"/>
```

---

## Accessibility & Localization

- User-facing text comes from Custom Labels (`@salesforce/label/c.Name`).
- Numbers, currency, and dates go through `lightning-formatted-*` components, which follow the user's locale, currency, and time zone. Formatting done in JavaScript reads `@salesforce/i18n/locale`, `currency`, and `timeZone`, not the browser's `toLocaleDateString()`.
- Date-only fields need `time-zone="UTC"`, or users west of UTC see the previous day.
- Every input has a label; `variant="label-hidden"` keeps it for assistive technology when the design hides it.
- Every icon-only control has `alternative-text`, and anything clickable is a button or a base component that keyboards and screen readers can reach.
- `@sa11y/jest` adds `await expect(element).toBeAccessible()` to Jest tests.

```html
<!-- ❌ A div posing as a control, an unlabeled icon, and a placeholder standing in for a label -->
<div class="dropdown" onclick={toggleMenu}><lightning-icon icon-name="utility:down"></lightning-icon></div>
<lightning-input placeholder="Amount" type="number"></lightning-input>

<!-- ✅ Base components with accessible names; a hidden label kept for assistive technology -->
<lightning-button-icon icon-name="utility:down" alternative-text={labels.showMenu} onclick={toggleMenu}></lightning-button-icon>
<lightning-input label={labels.amount} variant="label-hidden" type="number"></lightning-input>
<lightning-formatted-date-time value={invoice.dueDate} time-zone="UTC"></lightning-formatted-date-time>
```

---

## Testing with Jest

Tests run locally through `@salesforce/sfdx-lwc-jest`, which stubs the `lightning` base components. Map other modules with `moduleNameMapper` in a `jest.config.js` that spreads `jestConfig` from `@salesforce/sfdx-lwc-jest/config`. General rules: [Testing](../javascript.md#testing).

### Test through the DOM with `@salesforce/sfdx-lwc-jest`

- Create the element with `createElement` from `@lwc/engine-dom`, attach it to `document.body`, and drive it with wire data or clicks.
- Flush microtasks (`await Promise.resolve()`) before asserting on `element.shadowRoot`.
- Emit wire data and errors through the test wire adapters. LDS adapters such as `getRecord` come pre-stubbed (`getRecord.emit(data)`), and `create*TestWireAdapter` supersedes the older `register*TestWireAdapter` helpers.
- Mock each imperative Apex method as a `jest.fn()` default export, and resolve or reject it per test. Cover the failure path and assert the events the component dispatches (`addEventListener` plus a `jest.fn()` handler), not only the happy path.
- Remove the elements and reset mocks in `afterEach`: every test in a file shares one jsdom instance.

```javascript
// ✅ An Apex wire the test controls: getOpenInvoices.emit(rows) or getOpenInvoices.error(), then assert
jest.mock('@salesforce/apex/InvoiceController.getOpenInvoices', () => {
    const { createApexTestWireAdapter } = require('@salesforce/sfdx-lwc-jest');
    return { default: createApexTestWireAdapter(jest.fn()) };
}, { virtual: true });
```

### Lint with the Salesforce ESLint configs

`@salesforce/eslint-config-lwc` `recommended` (ESLint 9 flat config; packages in [Tooling](platform.md#tooling)) enables `@lwc/lwc/no-inner-html`, `no-document-query`, `no-api-reassignments`, and `no-async-operation`. It also enables core `no-void`, so the JavaScript Guide's `void promise` opt-out fails lint in LWC: attach a `.catch()` instead. `@lwc/lwc/no-leaky-event-listeners` is opt-in. When the repo runs this config, its hits are lint output, not review findings. Ask for a reason when a diff disables a rule. ESLint executes the repo's config and plugins, so run it only on trusted code.

---

## References

- [Data Guidelines (LWC Developer Guide)](https://developer.salesforce.com/docs/platform/lwc/guide/data-guidelines.html)
- [Secure Apex Classes (LWC Developer Guide)](https://developer.salesforce.com/docs/platform/lwc/guide/apex-security.html)
- [Use Third-Party JavaScript Libraries (LWC Developer Guide)](https://developer.salesforce.com/docs/platform/lwc/guide/js-third-party-library.html)
- [Lightning Web Security (Salesforce Developers)](https://developer.salesforce.com/docs/platform/lightning-components-security/guide/lws-intro.html)
- [trailheadapps/lwc-recipes (GitHub)](https://github.com/trailheadapps/lwc-recipes)
