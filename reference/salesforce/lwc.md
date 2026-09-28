# Lightning Web Components (LWC) Code Review Guide

Review guidance for Lightning Web Component bundles (`.js`, `.html`, `.css`, `.js-meta.xml`, Jest tests) and the `@AuraEnabled` Apex they call. Written for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs: judge each component against its own `<apiVersion>` and the release of the orgs it deploys to.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
>
> 📖 General JavaScript rules (language semantics, async and Promise pitfalls, DOM safety, test basics) live in the [JavaScript Guide](../javascript.md); this guide covers LWC-specific behavior only.
>
> Related: [Apex](apex.md) · [SOQL & SOSL](soql-sosl.md) · [XSS Prevention](../cross-cutting/xss-prevention.md#salesforce-lwc-aura-visualforce) · [TypeScript](../typescript.md) for .ts components

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Data Flow & Reactivity](#data-flow--reactivity)
- [Templates](#templates)
- [Lifecycle](#lifecycle)
- [Data Access](#data-access)
- [The LWC-Apex Contract](#the-lwc-apex-contract)
- [Security in the Browser](#security-in-the-browser)
- [Styling](#styling)
- [Performance](#performance)
- [Component Configuration](#component-configuration)
- [Accessibility & Localization](#accessibility--localization)
- [Testing with Jest](#testing-with-jest)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Code under review | Load |
|---|---|
| `lwc/<bundle>/*.js`, `*.html`, `*.css` | This guide + the [JavaScript Guide](../javascript.md) |
| `lwc/<bundle>/*.ts` (LWC TypeScript is a Developer Preview: never require it) | This guide + the [TypeScript Guide](../typescript.md) |
| `lwc/<bundle>/*.js-meta.xml` | [Component Configuration](#component-configuration) + [API Versions](platform.md#api-versions) |
| `@AuraEnabled` Apex called from LWC or Aura | [The LWC-Apex Contract](#the-lwc-apex-contract) + the [Apex Guide](apex.md) |
| `__tests__/*.test.js`, `jest.config.js`, `eslint.config.js` | [Testing with Jest](#testing-with-jest) |
| An Aura component that hosts an LWC | The [Aura Guide](aura.md) + this guide |

Examples use an `InvoiceController` Apex class and `reduceErrors` from a shared `c/ldsUtils` module ([Normalize client errors with one shared utility](#normalize-client-errors-with-one-shared-utility)).

---

## Data Flow & Reactivity

### Treat `@api` properties as read-only; send changes up with a `CustomEvent`

The parent owns public properties: objects and arrays arrive read-only, and a primitive the child reassigns is overwritten on the parent's next render (take an editable copy in an `@api` setter if needed). Name events in lowercase without an `on` prefix (the parent listens with `onstatuschange`) and leave `bubbles` and `composed` at their `false` defaults; with both on, the event crosses every shadow boundary and becomes public API of every ancestor.

```javascript
// ❌ Writes to the parent's data (throws "Invalid mutation: Cannot set ... is read-only")
this.invoice.status = 'Paid';

// ❌ Crosses every shadow boundary, has an "on" prefix and capitals, and hands out the whole object
this.dispatchEvent(new CustomEvent('onStatusChange', { bubbles: true, composed: true, detail: this.invoice }));

// ✅ Ask the owner: a lowercase, non-bubbling event with primitives (or a fresh object) in detail
this.dispatchEvent(new CustomEvent('statuschange', { detail: { invoiceId: this.invoice.invoiceId, status: 'Paid' } }));
```

Static analysis: ESLint `@lwc/lwc/no-api-reassignments` (in `recommended`).

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

// 💡 @track is for in-place edits of a plain object or array (this.filters.status = 'Paid');
//    on a primitive or an always-reassigned field it is legacy noise, not a bug
@track filters = { status: 'Open' };
```

### Keep getters pure and cheap

Template getters run on every render: one that writes state schedules another render, and one that sorts or copies a large array repeats the work each time. Derive values once, when the data arrives ([Read with `@wire`, write imperatively](#read-with-wire-write-imperatively)).

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

Use `@api` and events inside a tree, Lightning Message Service across trees and frameworks, and a state manager from `@lwc/state` (GA in Summer '26, not available in Experience Cloud) for state a component tree shares. Module-level variables are shared by every instance on the page and survive navigation, so they are not a store.

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

Templates bind properties and apply directives; logic, formatting, and element lookup live in JavaScript. Prefer `lightning-*` base components and SLDS to hand-built widgets: they bring labels, keyboard support, validation, and localization ([Build accessible markup](#build-accessible-markup)).

### Use `lwc:if`, `lwc:elseif`, and `lwc:else` in new code (Spring '23+)

`if:true` and `if:false` still work but are no longer recommended and may be removed; in untouched legacy markup they rate a suggestion at most ([Severity Calibration](platform.md#severity-calibration)). Give loading, error, empty, and data their own branch.

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

The key goes on the first element inside the iteration. The compiler rejects `key={index}`, but an index smuggled in from JavaScript or a non-unique value has the same effect: rows re-render or swap state when the list changes.

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

Static analysis: ESLint `@lwc/lwc/no-document-query`.

### Keep template expressions simple; compute values in getters

Below `apiVersion` 66.0 a template accepts only property references (`{amount}`, `{invoice.amount}`). Complex template expressions were a beta from Spring '26 and are GA in Winter '27 for components at `apiVersion` 66.0+; even there, keep formatting, filtering, and logic you want to test in getters.

```html
<!-- ❌ Arithmetic in markup: a compile error below apiVersion 66.0, and logic that is easy to miss -->
<p>{invoice.amount * (1 + taxRate)}</p>

<!-- ✅ A getter computes the value; a base component formats it -->
<lightning-formatted-number value={amountWithTax} format-style="currency" currency-code={currencyCode}>
</lightning-formatted-number>
```

---

## Lifecycle

Hooks run in order: `constructor`, `connectedCallback`, `render`, `renderedCallback` (children before parents), then `disconnectedCallback` on removal; `errorCallback` receives descendants' errors. The framework does not await promises that hooks return, so an `async` hook catches its own errors ([No floating promises](../javascript.md#no-floating-promises)).

### Make `connectedCallback` idempotent and undo it in `disconnectedCallback`

`connectedCallback` runs every time the element is inserted, including when a list moves it; parent properties are set, but children and wired data are not there yet. Register only what `disconnectedCallback` removes, with stable references ([Clean up listeners, timers, and observers](../javascript.md#clean-up-listeners-timers-and-observers)). LMS releases `@wire(MessageContext)` subscriptions when the component is destroyed, but unsubscribing explicitly keeps re-inserted components correct; `lightning/empApi` subscriptions end only with its own `unsubscribe()`.

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

Static analysis: ESLint `@lwc/lwc/no-leaky-event-listeners` (not in `recommended`; enable it).

### Guard `renderedCallback` against render loops

It runs after every render, so state set there triggers another render: assign only when a value changes, and put one-time work behind a flag.

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

`errorCallback(error, stack)` receives errors thrown in descendants' lifecycle hooks and template event handlers, so one failing child does not blank the page. Wrap children that can fail in a boundary component that sets `this.errorMessages = reduceErrors(error)`, renders `<c-error-panel>` instead of its `<slot>`, and reports the error and stack to the project's logger. Rejected promises never reach it.

---

## Data Access

### Choose the data source: LDS first, Apex last

Lightning Data Service (LDS) enforces CRUD, FLS, and sharing, keeps one cache for the page, and pushes record changes to every component. Apex results are cached separately and refreshed by hand, so use one source per record: the two caches can disagree.

| Need | Use |
|---|---|
| A standard view or edit form | `lightning-record-form`, `lightning-record-view-form`, `lightning-record-edit-form` |
| Custom UI over single records | `lightning/uiRecordApi`: `getRecord`, `updateRecord`, `createRecord`, `deleteRecord` |
| Several objects in one read | The GraphQL wire adapter in `lightning/graphql`, which supersedes `lightning/uiGraphQLApi` (GA in Winter '24); results carry `errors` (not `error`) and a `refresh` function |
| Several records in one transaction (each LDS call is its own), aggregates, unsupported objects | `@AuraEnabled` Apex |

### Import schema references instead of field-name strings

The platform checks `@salesforce/schema` imports: they must exist, a referenced field can't be deleted, and a rename can't silently break the component.

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

A wire re-runs when its `$` parameters change and shares the client cache; it needs LDS or a `cacheable=true` Apex method. Writes and user-triggered actions are imperative calls, and both render loading, error, and empty states ([the `lwc:if` chain](#use-lwcif-lwcelseif-and-lwcelse-in-new-code-spring-23)).

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

### Refresh caches after every write

`refreshApex` (from `@salesforce/apex`) takes the whole object the wire provisioned and refreshes only Apex wires. LDS-backed views (record pages, `lightning-record-form`, `getRecord`) learn about Apex writes only through `notifyRecordUpdateAvailable`, which replaces the deprecated `getRecordNotifyChange`.

```javascript
// ❌ Refreshes the data array instead of the provisioned result; LDS views keep the old status
await markInvoicesPaid({ invoiceIds });
await refreshApex(this.rows);

// ✅ Refresh the wired result, notify LDS, and show progress and errors
async handleMarkPaid() {
    const invoiceIds = this.selectedIds;
    this.isSaving = true;
    try {
        await markInvoicesPaid({ invoiceIds });
        await Promise.all([
            refreshApex(this.wiredInvoicesResult),
            notifyRecordUpdateAvailable(invoiceIds.map((recordId) => ({ recordId })))
        ]);
    } catch (error) {
        this.errorMessages = reduceErrors(error);
    } finally {
        this.isSaving = false;
    }
}
```

### Debounce input and batch server calls

A wired parameter bound to an input fires one call per keystroke: debounce it (and clear the timer on disconnect), and load what a view needs in one call instead of chaining several. Imperative calls can't be aborted, so drop stale responses with the request-id pattern in [Race conditions](../javascript.md#race-conditions-cancel-or-ignore-stale-results), keeping the counter on the instance: a module-level counter is shared by every instance on the page.

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

Every `@AuraEnabled` method is a public endpoint: any user with access to the Apex class can call it with any arguments, without your component ([Security Model](platform.md#security-model)). These rules apply to Aura server actions too. Check each class's `<apiVersion>` first; writes, mass assignment, and `stripInaccessible` are covered in [Data Access Security](apex.md#data-access-security).

### Mark only side-effect-free methods `cacheable=true`

`@wire` requires `cacheable=true`, and the client may answer from its cache without running the method. DML in a cacheable method fails at runtime (`System.LimitException: Too many DML statements: 1`), and other side effects run unpredictably.

```apex
public with sharing class InvoiceController {
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
}
```

### Enforce access on the server; client checks are UX

Hiding a button protects nothing. User mode enforces CRUD, FLS, and sharing; a privileged action also needs an explicit permission check in Apex, and every argument needs validation.

```apex
public with sharing class InvoiceController {
    // ❌ Relies on the component hiding the Void button: any user who can edit invoices can void one
    @AuraEnabled
    public static void voidInvoice(Id invoiceId) {
        update as user new Invoice__c(Id = invoiceId, Status__c = 'Void');
    }

    // ✅ The component shows the button from @salesforce/customPermission/Void_Invoices (UX only);
    //    Apex enforces the same permission, validates the Id, and writes in user mode
    @AuraEnabled
    public static void voidInvoice(Id invoiceId) {
        if (!FeatureManagement.checkPermission('Void_Invoices')) {
            throw new AuraHandledException(System.Label.Invoice_Void_Not_Allowed);
        }
        if (invoiceId == null || invoiceId.getSObjectType() != Invoice__c.SObjectType) {
            throw new AuraHandledException(System.Label.Invoice_Selection_Invalid);
        }
        update as user new Invoice__c(Id = invoiceId, Status__c = 'Void');
    }
}
```

Static analysis: PMD `ApexCRUDViolation`, `ApexSharingViolations`.

### Return DTOs, not raw sObjects

A returned sObject sends every queried field to the browser and ties the component to the schema. Return a class whose `@AuraEnabled` members carry what the component renders; when sObjects must go back, sanitize them ([Data Access Security](apex.md#data-access-security)).

```apex
public with sharing class InvoiceController {
    // ❌ A List<Invoice__c> carrying Internal_Margin__c to a table that shows only name and amount

    // ✅ Only what the component renders
    public class InvoiceSummary {
        @AuraEnabled public Id invoiceId;
        @AuraEnabled public String name;
        @AuraEnabled public Decimal amount;
    }

    @AuraEnabled(cacheable=true)
    public static List<InvoiceSummary> getOpenInvoices(Id accountId) {
        return toSummaries([
            SELECT Id, Name, Amount__c FROM Invoice__c
            WHERE Account__c = :accountId AND Status__c = 'Open' WITH USER_MODE ORDER BY Name LIMIT 200
        ]);
    }

    private static List<InvoiceSummary> toSummaries(List<Invoice__c> invoices) {
        List<InvoiceSummary> rows = new List<InvoiceSummary>();
        for (Invoice__c inv : invoices) {
            InvoiceSummary row = new InvoiceSummary();
            row.invoiceId = inv.Id;
            row.name = inv.Name;
            row.amount = inv.Amount__c;
            rows.add(row);
        }
        return rows;
    }
}
```

Static analysis: PMD `InaccessibleAuraEnabledGetter` (an `@AuraEnabled` property with a private or protected getter is unreadable from LWC and Aura).

### Throw `AuraHandledException` with a safe message and log the cause

An uncaught exception shows the user whatever the platform puts in its text (DML status codes, record Ids, or a generic server error) and logs nothing useful. Catch the specific exception, log it, and throw an `AuraHandledException` with an actionable message; call `setMessage()` too, or `getMessage()` returns "Script-thrown exception" on the server, in tests and logs.

```apex
public with sharing class InvoiceController {
    // ✅ Bounded input, user-mode DML, the cause logged, and a safe, translatable message
    //    (the ❌ version is a bare `update invoices;` whose raw DML error text reaches the browser)
    @AuraEnabled
    public static void markInvoicesPaid(List<Id> invoiceIds) {
        if (invoiceIds == null || invoiceIds.isEmpty() || invoiceIds.size() > 200) {
            throw new AuraHandledException(System.Label.Invoice_Selection_Invalid);
        }
        List<Invoice__c> invoices = new List<Invoice__c>();
        for (Id invoiceId : invoiceIds) {
            if (invoiceId?.getSObjectType() != Invoice__c.SObjectType) {
                throw new AuraHandledException(System.Label.Invoice_Selection_Invalid);
            }
            invoices.add(new Invoice__c(Id = invoiceId, Status__c = 'Paid'));
        }
        try {
            update as user invoices;
        } catch (DmlException e) {
            // log e.getMessage() and e.getStackTraceString() with the project's logger here
            AuraHandledException error = new AuraHandledException(System.Label.Invoice_Update_Failed);
            error.setMessage(System.Label.Invoice_Update_Failed);
            throw error;
        }
    }
}
```

> 📖 [Error Handling Principles](../cross-cutting/error-handling-principles.md#core-principles) · Apex side: [Transactions & Error Handling](apex.md#transactions--error-handling)

### Normalize client errors with one shared utility

Errors arrive as `body.message` (Apex, UI API), an array `body` (UI API reads), `body.pageErrors` and `body.fieldErrors` (DML), or plain JavaScript and network errors. One shared utility, like `reduceErrors` in lwc-recipes' `ldsUtils`, turns them into messages; a `console` call alone swallows the error.

```javascript
// ❌ One assumed shape: an error without a body throws a TypeError, and UI API errors show nothing
this.errorMessage = error.body.message;

// ✅ c/ldsUtils (condensed; the lwc-recipes version also reads body.output for UI API DML errors)
export function reduceErrors(errors) {
    return (Array.isArray(errors) ? errors : [errors])
        .filter(Boolean)
        .flatMap((error) => {
            const body = error.body;
            if (Array.isArray(body)) {
                return body.map((entry) => entry.message);
            }
            if (body?.pageErrors?.length) {
                return body.pageErrors.map((entry) => entry.message);
            }
            if (body?.fieldErrors && Object.keys(body.fieldErrors).length) {
                return Object.values(body.fieldErrors).flat().map((entry) => entry.message);
            }
            if (typeof body?.message === 'string') {
                return [body.message];
            }
            return [typeof error.message === 'string' ? error.message : error.statusText];
        })
        .filter(Boolean);
}
```

### Keep parameters few and typed

Positional primitives grow with every feature, and the JavaScript call must match the Apex parameter names exactly. Take one request class with `@AuraEnabled` members, and bound every field on the server ([Parameter Sprawl](../code-quality-universal.md#parameter-sprawl)).

```apex
public with sharing class InvoiceController {
    // ❌ searchInvoices(String status, Decimal minAmount, Date fromDate, Date toDate, Id ownerId, ...)

    // ✅ LWC calls searchInvoices({ request: { status: 'Open', pageSize: 50 } }); ?? needs API 60.0+
    public class SearchRequest {
        @AuraEnabled public String status { get; set; }
        @AuraEnabled public Integer pageSize { get; set; }
    }

    @AuraEnabled(cacheable=true)
    public static List<InvoiceSummary> searchInvoices(SearchRequest request) {
        String status = String.isBlank(request?.status) ? 'Open' : request.status;
        Integer pageSize = Math.min(Math.max(request?.pageSize ?? 50, 1), 200); // the client can send anything
        return toSummaries([
            SELECT Id, Name, Amount__c FROM Invoice__c
            WHERE Status__c = :status WITH USER_MODE ORDER BY Name LIMIT :pageSize
        ]);
    }
}
```

---

## Security in the Browser

### Treat Lightning Web Security as isolation, not authorization

Lightning Web Security (LWS; GA for LWC in Spring '22 and on by default in new orgs since Winter '23, while orgs that never switched still run Lightning Locker) gives each namespace's JavaScript its own sandbox and restricts risky APIs; dynamic components require it. When the target orgs run LWS, question new Locker-era workarounds (forked "Locker-compatible" library builds, Visualforce iframes used only to escape the sandbox) and ask which architecture each target org runs.

| Concern | Handled by |
|---|---|
| One namespace's script reading or patching another's | LWS, or Locker in orgs without LWS |
| Who may read or change a record or field | LDS, or Apex in user mode with a sharing keyword |
| Who may run a privileged action | A permission check in Apex; the component's check only shapes the UI |
| Data rendered as markup | Template binding (always escaped) or `lightning-formatted-rich-text` |
| API keys and tokens | A Named Credential that Apex calls through: every component file, static resource, and Custom Label is readable by any user who can load the page |

### Never render untrusted HTML through `lwc:dom="manual"`

`lwc:dom="manual"` exists for libraries that manage their own DOM. Writing record data into such a container with `innerHTML` is stored XSS, and LWS is not a sanitizer to rely on ([Safe DOM updates](../javascript.md#safe-dom-updates)).

```javascript
// ❌ Template: <div lwc:dom="manual" lwc:ref="notes"></div>; the record's notes become live markup
this.refs.notes.innerHTML = this.invoice.notes;

// ✅ Plain text: bind {invoice.notes} (always escaped) or set textContent
this.refs.notes.textContent = this.invoice.notes;

// ✅ Rich text: <lightning-formatted-rich-text value={invoice.notes}> keeps only allowlisted tags
```

Static analysis: ESLint `@lwc/lwc/no-inner-html`.

### Validate URLs and navigate with page references

A URL from a page parameter or a record field can point anywhere, including a `javascript:` URL. Navigate with `NavigationMixin` page references, and bind a URL from data only after checking its protocol.

```javascript
// ❌ Open redirect: the destination comes from the URL (?c__returnUrl=...), read via CurrentPageReference
window.location.assign(this.pageRef.state.c__returnUrl);

// ✅ Navigate by page reference (the class extends NavigationMixin(LightningElement))
this[NavigationMixin.Navigate]({
    type: 'standard__recordPage',
    attributes: { recordId: this.recordId, objectApiName: INVOICE_OBJECT.objectApiName, actionName: 'view' }
});

// ✅ A URL from data (for example Account.Website) is bound only when it is http or https
get safeWebsite() {
    try {
        const url = new URL(this.website);
        return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
    } catch {
        return undefined;
    }
}
```

### Load third-party libraries from static resources

A CDN script needs a CSP Trusted Site, can change without review, and escapes the repository. Ship a pinned copy as a static resource (with the version in its name or description), load it once, and treat any new CSP Trusted Site as a reviewed exception ([Integration Endpoints & Credentials](metadata.md#integration-endpoints--credentials)).

```javascript
// ❌ Unpinned, unreviewed, and blocked unless someone adds a CSP Trusted Site
loadScript(this, 'https://cdn.example.com/chart.js/latest/chart.umd.js');

// ✅ A static resource (import CHART_JS from '@salesforce/resourceUrl/chartJs'), loaded once
//    into a container the library owns: <div lwc:dom="manual" lwc:ref="chart"></div>
renderedCallback() {
    if (this.chartInitialized) return;
    this.chartInitialized = true;
    loadScript(this, CHART_JS)
        .then(() => {
            const canvas = document.createElement('canvas');
            this.refs.chart.appendChild(canvas);
            this.chart = new window.Chart(canvas.getContext('2d'), this.chartConfig);
        })
        .catch((error) => {
            this.errorMessages = reduceErrors(error);
        });
}
```

Static analysis: Code Analyzer's RetireJS rules flag static resources that contain JavaScript libraries with known vulnerabilities ([Tooling](platform.md#tooling)).

---

## Styling

Component styles are scoped by the shadow DOM, and base component markup can change in any release: Salesforce does not support styling the rendered markup of base components or overriding SLDS classes.

### Style base components through styling hooks, never their internals

Base components expose component styling hooks (`--slds-c-*`). Selectors aimed at their internal classes don't cross the shadow boundary, so they end up in a global `loadStyle()` sheet with `!important`, leak to every component on the page, and break when SLDS changes. Keep `:host` to what the component itself needs; outer margins and fixed widths belong to the parent.

```css
/* ❌ A base component's internals, from a global sheet, forced with !important; placement on :host */
.slds-button_brand { background-color: #0b5cab !important; }
:host { margin: 24px; width: 640px; }

/* ✅ The documented hooks, set once on the host */
:host {
    --slds-c-button-brand-color-background: #0b5cab;
    --slds-c-button-brand-color-border: #0b5cab;
}
```

### Use SLDS hooks with SLDS 1 fallbacks, fluid widths, and visible focus

Prefer SLDS utility classes (`slds-p-around_medium`, `slds-text-color_error`) in markup. In CSS, use global styling hooks (`--slds-g-*`, from SLDS 2, introduced in Spring '25) with an SLDS 1 fallback: design tokens (`--lwc-*`) still work in SLDS 1 themes but are not part of SLDS 2. Components render in narrow regions and on mobile, so avoid fixed widths, keep focus visible, animate only cheap properties, and respect reduced motion.

```css
/* ❌ Hard-coded values, a fixed width, transition: all, and the focus outline removed */
.summary { padding: 16px; background-color: #f3f3f3; width: 960px; transition: all 0.3s; }
.summary button:focus { outline: none; }

/* ✅ Global hooks with the SLDS 1 token (and a plain value) as fallbacks, fluid and focus-visible */
.summary {
    padding: var(--slds-g-spacing-4, var(--lwc-spacingMedium, 1rem));
    background-color: var(--slds-g-color-surface-container-1, var(--lwc-colorBackgroundAlt));
    max-width: 100%;
    transition: opacity 0.2s ease; /* and none under @media (prefers-reduced-motion: reduce) */
}
.summary button:focus-visible { outline: 2px solid currentColor; }
```

Static analysis: SLDS Linter (`npx @salesforce-ux/slds-linter lint force-app/main/default/lwc`) checks CSS and markup against SLDS 2 guidance.

---

## Performance

Most LWC performance problems are server round trips and oversized renders. A child per row that calls Apex (imperatively or through its own `@wire`) turns N rows into N requests: load the list's data in one call in the parent and pass each row its values ([N+1 Queries](../cross-cutting/n-plus-one-queries.md#salesforce-apex-lwc-flow)). The page-level view is in [Salesforce Platform Performance](../performance-review-guide.md#salesforce-platform-performance).

### Lazy-load heavy components (Winter '24+ for dynamic components)

A heavy child that most users never open still downloads when it is referenced statically. Load it on first use with `import()` and render it with `<lwc:component lwc:is={...}>`: dynamic components require LWS, the `lightning__dynamicComponent` capability, and `apiVersion` 55.0+ ([Dynamic import() and code splitting](../javascript.md#dynamic-import-and-code-splitting)).

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

Thousands of rows cost heap and CPU on the server and render time in the browser. Page with `lightning-datatable` infinite loading: bind `enable-infinite-loading={hasMore}`, and in the `onloadmore` handler set `event.target.isLoading` while an `async` call fetches the next page (in `try`/`catch`/`finally`), then append it with a new array. Apex serves keyset pages (`WHERE Id > :afterId ORDER BY Id LIMIT :pageSize`), not `OFFSET` ([Pagination & Cursors](soql-sosl.md#pagination--cursors)).

---

## Component Configuration

### Expose only the targets you need

`isExposed` and `targets` decide where admins can place a component. Experience Cloud targets (`lightningCommunity__Page`, `lightningCommunity__Default`) make the Apex it calls reachable by site users, including guests when the guest profile has access to the class, so that Apex must hold up for them ([Security Model](platform.md#security-model)).

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

Admins set `targetConfig` properties in Lightning App Builder. Type, bound, and default them in metadata, then still validate them in code: a property never flows unchecked into dynamic SOQL, field names, or markup, and the Apex that receives it allowlists it.

```xml
<!-- ✅ Typed, bounded, defaulted properties (the component still clamps maxRows before using it) -->
<property name="maxRows" type="Integer" label="Maximum rows" default="50" min="1" max="200"/>
<property name="statusFilter" type="String" label="Status" datasource="Open,Paid,Void" default="Open"/>
```

---

## Accessibility & Localization

### Use Custom Labels and `lightning-formatted-*` components

User-facing text comes from Custom Labels (`@salesforce/label/c.Name`), and numbers, currency, and dates go through `lightning-formatted-*` components, which follow the user's locale, currency, and time zone (`@salesforce/i18n/locale`, `currency`, and `timeZone` cover formatting done in JavaScript). Date-only fields need `time-zone="UTC"`, or users west of UTC see the previous day.

```javascript
// ❌ Hard-coded English and hand-built formatting: wrong in every other locale and time zone
get dueText() {
    return 'Due ' + new Date(this.invoice.dueDate).toLocaleDateString();
}

// ✅ labels = { due: DUE_LABEL } (import DUE_LABEL from '@salesforce/label/c.Invoice_Due'); in the template:
//    {labels.due} <lightning-formatted-date-time value={invoice.dueDate} time-zone="UTC"></lightning-formatted-date-time>
//    <lightning-formatted-number value={invoice.amount} format-style="currency" currency-code={invoice.currencyCode}>
```

### Build accessible markup

Every input needs a label (keep it with `variant="label-hidden"` when the design hides it), every icon-only control needs `alternative-text`, and anything clickable is a button or a base component that keyboards and screen readers can reach.

```html
<!-- ❌ A div posing as a control, an unlabeled icon, and a placeholder standing in for a label -->
<div class="dropdown" onclick={toggleMenu}><lightning-icon icon-name="utility:down"></lightning-icon></div>
<lightning-input placeholder="Amount" type="number"></lightning-input>

<!-- ✅ Base components with accessible names, and a label kept for assistive technology -->
<lightning-combobox label={labels.status} value={status} options={statusOptions} onchange={handleStatusChange}>
</lightning-combobox>
<lightning-button-icon icon-name="utility:delete" alternative-text={labels.voidInvoice} onclick={handleVoid}>
</lightning-button-icon>
<lightning-input label={labels.amount} variant="label-hidden" type="number"></lightning-input>
```

Automated check: `@sa11y/jest` adds `await expect(element).toBeAccessible()` to Jest tests once `registerSa11yMatcher()` runs in a setup file, as in lwc-recipes.

---

## Testing with Jest

Tests run locally through `@salesforce/sfdx-lwc-jest`, which stubs the `lightning` base components and bundles its own Jest (29.7 in version 7.9.0); map other modules with `moduleNameMapper` in a `jest.config.js` that spreads `jestConfig` from `@salesforce/sfdx-lwc-jest/config`. General guidance: [Testing](../javascript.md#testing).

### Test through the DOM with `@salesforce/sfdx-lwc-jest`

Create the element, attach it, drive it with wire data or clicks, and assert on its shadow DOM. Emit wire data and errors through the test wire adapters, and reset the DOM and mocks after each test, because every test in a file shares one jsdom instance.

```javascript
import { createElement } from '@lwc/engine-dom';
import InvoiceList from 'c/invoiceList';
import getOpenInvoices from '@salesforce/apex/InvoiceController.getOpenInvoices';

jest.mock('@salesforce/apex/InvoiceController.getOpenInvoices', () => {
    const { createApexTestWireAdapter } = require('@salesforce/sfdx-lwc-jest');
    return { default: createApexTestWireAdapter(jest.fn()) };
}, { virtual: true });

afterEach(() => {
    while (document.body.firstChild) {
        document.body.removeChild(document.body.firstChild);
    }
    jest.clearAllMocks();
});

it('shows the error panel when the wire fails', async () => {
    const element = createElement('c-invoice-list', { is: InvoiceList });
    document.body.appendChild(element);
    getOpenInvoices.error(); // getOpenInvoices.emit(rows) provisions data the same way
    await Promise.resolve();
    expect(element.shadowRoot.querySelector('c-error-panel')).not.toBeNull();
});
```

LDS adapters such as `getRecord` come pre-stubbed, so a test calls `getRecord.emit(data)` directly; `create*TestWireAdapter` supersedes the older `register*TestWireAdapter` helpers.

### Mock imperative Apex, and assert failures and events

Mock each imperative method as a `jest.fn()` default export, resolve or reject it per test, and flush microtasks before asserting. Cover the failure path and the events the component dispatches, not only the happy path.

```javascript
// Imports as above: createElement, the components under test, and the Apex method being mocked
jest.mock('@salesforce/apex/InvoiceController.markInvoicesPaid', () => ({ default: jest.fn() }), { virtual: true });

it('shows the server message when the update fails', async () => {
    markInvoicesPaid.mockRejectedValue({ body: { message: 'The invoices could not be updated.' } });
    const element = createElement('c-invoice-actions', { is: InvoiceActions });
    document.body.appendChild(element);
    element.shadowRoot.querySelector('lightning-button').click();
    await Promise.resolve();
    await Promise.resolve();
    expect(element.shadowRoot.querySelector('c-error-panel')).not.toBeNull();
});

it('fires statuschange with the invoice id', () => {
    const element = createElement('c-invoice-row', { is: InvoiceRow });
    element.invoice = { invoiceId: 'inv-1', name: 'INV-0001', amount: 120 };
    document.body.appendChild(element);
    const handler = jest.fn();
    element.addEventListener('statuschange', handler);
    element.shadowRoot.querySelector('lightning-button').click();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].detail).toEqual({ invoiceId: 'inv-1', status: 'Paid' });
});
```

### Lint with the Salesforce ESLint configs

Use `@salesforce/eslint-config-lwc` `recommended` in flat config (packages: [Tooling](platform.md#tooling)). It enables `@lwc/lwc/no-inner-html`, `no-document-query`, `no-api-reassignments`, and `no-async-operation`, plus core `no-void`, so the JavaScript Guide's `void promise` opt-out fails lint in LWC: attach a `.catch()` instead. Version 4.1.2 (like `@salesforce/eslint-plugin-aura` 3.0.0) declares `eslint: ^9` as its peer, so an ESLint 10 upgrade in a Salesforce project waits for those packages.

```javascript
// eslint.config.js, following the lwc-recipes layout; no-leaky-event-listeners is opt-in
const { defineConfig } = require('eslint/config');
const lwcRecommended = require('@salesforce/eslint-config-lwc/recommended');

module.exports = defineConfig([
    { files: ['force-app/main/default/lwc/**/*.js'], extends: [lwcRecommended],
      rules: { '@lwc/lwc/no-leaky-event-listeners': 'error' } }
]);
```

---

## Review Checklist

### Data flow & templates
- [ ] Children never write to `@api` properties or objects received through them; changes go up as lowercase, non-bubbling events carrying primitives
- [ ] Unrelated components use a message channel carrying Ids; no window events, pub/sub modules, or module-level state
- [ ] Arrays and objects are reassigned (or deliberately `@track`ed), and getters have no side effects
- [ ] New markup uses `lwc:if` chains with loading, error, and empty branches, keys lists by record Id, reaches elements with `lwc:ref`, and keeps logic out of template expressions
- [ ] Text comes from Custom Labels, values from `lightning-formatted-*` (`time-zone="UTC"` for date-only fields), and controls are labeled base components

### Lifecycle
- [ ] `connectedCallback` is safe to run twice, `renderedCallback` sets state only on change, and `disconnectedCallback` releases every listener, timer, subscription, and library instance
- [ ] Async hooks and handlers catch their own errors, and children that can fail sit inside an `errorCallback` boundary

### Data access & Apex contract
- [ ] LDS or GraphQL is used where it fits and Apex for the rest, with one data source per record and fields from `@salesforce/schema`
- [ ] Reads are wired and writes imperative; writes are followed by `refreshApex` on the provisioned result and `notifyRecordUpdateAvailable`
- [ ] Input-driven calls are debounced, and stale imperative responses are dropped
- [ ] `cacheable=true` methods have no DML or other side effects
- [ ] Each `@AuraEnabled` method takes typed arguments, validates them, enforces access (with a permission check for privileged actions), returns DTOs, and throws `AuraHandledException` with safe text after logging the cause
- [ ] Client errors pass through one shared `reduceErrors`-style utility and are never swallowed

### Security
- [ ] No `innerHTML` into `lwc:dom="manual"` containers with untrusted data
- [ ] Navigation uses page references, and URLs from data are protocol-checked
- [ ] Libraries come from pinned static resources, each CSP Trusted Site is justified, and no keys or tokens ship in client code

### Styling, performance & config
- [ ] Base components are styled only through `--slds-c-*` hooks, other styles use SLDS classes or `--slds-g-*` hooks with fallbacks, and nothing overrides SLDS classes or uses `!important`
- [ ] Heavy, rarely used children load lazily; lists load in one call and page
- [ ] Targets are minimal, and Experience Cloud exposure has a server-side security review
- [ ] `apiVersion` changes are deliberate, capabilities are declared, and builder properties are typed and bounded

### Tests
- [ ] Jest tests drive the DOM, emit wire data and errors, and mock imperative Apex for success and failure
- [ ] The DOM and mocks are reset after each test, and dispatched events are asserted
- [ ] ESLint runs `@salesforce/eslint-config-lwc` `recommended`, and every disabled rule has a reason

---

## References

- LWC Developer Guide: [Data Flow](https://developer.salesforce.com/docs/platform/lwc/guide/create-components-data-flow.html) · [Lifecycle Hooks](https://developer.salesforce.com/docs/platform/lwc/guide/create-lifecycle-hooks.html) · [HTML Template Directives](https://developer.salesforce.com/docs/platform/lwc/guide/reference-directives.html) · [Template Expressions](https://developer.salesforce.com/docs/platform/lwc/guide/create-components-html-expressions.html) · [Manage State](https://developer.salesforce.com/docs/platform/lwc/guide/state-management.html) · [Dynamic Components](https://developer.salesforce.com/docs/platform/lwc/guide/js-dynamic-components.html) · [TypeScript (Developer Preview)](https://developer.salesforce.com/docs/platform/lwc/guide/ts.html)
- Data: [Data Guidelines](https://developer.salesforce.com/docs/platform/lwc/guide/data-guidelines.html) · [Wire Service](https://developer.salesforce.com/docs/platform/lwc/guide/data-wire-service-about.html) · [lightning/uiRecordApi](https://developer.salesforce.com/docs/platform/lwc/guide/reference-lightning-ui-api-record.html) · [notifyRecordUpdateAvailable](https://developer.salesforce.com/docs/platform/lwc/guide/reference-notify-record-update.html) · [lightning/graphql](https://developer.salesforce.com/docs/platform/lwc/guide/reference-lightning-graphql-module.html)
- Apex: [Call Apex Methods](https://developer.salesforce.com/docs/platform/lwc/guide/apex.html) · [Wire Apex Methods](https://developer.salesforce.com/docs/platform/lwc/guide/apex-wire-method.html) · [Secure Apex Classes](https://developer.salesforce.com/docs/platform/lwc/guide/apex-security.html) · [Handle Errors](https://developer.salesforce.com/docs/platform/lwc/guide/apex-error-handling.html) · [PMD Apex error-prone rules](https://docs.pmd-code.org/latest/pmd_rules_apex_errorprone.html)
- Security and styling: [Lightning Web Security](https://developer.salesforce.com/docs/platform/lightning-components-security/guide/lws-intro.html) · [SLDS Styling Hooks](https://developer.salesforce.com/docs/platform/lwc/guide/create-components-css-custom-properties.html) · [Anti-Patterns for Component Styling](https://developer.salesforce.com/docs/platform/lwc/guide/create-components-css-antipatterns.html) · [SLDS Linter Rules](https://developer.salesforce.com/docs/platform/slds-linter/guide/reference-rules.html) · [Internationalization](https://developer.salesforce.com/docs/platform/lwc/guide/create-i18n.html)
- Testing and linting: [Write Jest Tests](https://developer.salesforce.com/docs/platform/lwc/guide/unit-testing-using-jest-create-tests.html) · [Jest Test Patterns](https://developer.salesforce.com/docs/platform/lwc/guide/unit-testing-using-jest-patterns.html) · [salesforce/sfdx-lwc-jest](https://github.com/salesforce/sfdx-lwc-jest) · [salesforce/wire-service-jest-util](https://github.com/salesforce/wire-service-jest-util) · [salesforce/eslint-config-lwc](https://github.com/salesforce/eslint-config-lwc) · [salesforce/eslint-plugin-lwc](https://github.com/salesforce/eslint-plugin-lwc)
- Samples: [trailheadapps/lwc-recipes](https://github.com/trailheadapps/lwc-recipes)
