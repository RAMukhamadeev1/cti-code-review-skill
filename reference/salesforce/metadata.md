# Salesforce Metadata & Permissions Code Review Guide

Review guidance for declarative metadata in source format (`force-app/**`): permissions, sharing, objects and fields, validation rules, endpoints and credentials, configuration, and deployment manifests. Current for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs; flows are in [flows.md](flows.md).

> Load [platform.md](platform.md) first (security model, API versions, severity calibration). Related: [Apex data access](apex.md#data-access-security) · [Security Review Guide](../security-review-guide.md#salesforce-platform-security)

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Review statically: ask the author or CI for org evidence such as assignments, data volumes, and deployment results ([Static Review Only](platform.md#static-review-only)). Severities (🔴 [blocking], 🟡 [important], 🟢 [nit], 💡 [suggestion]) default to [Severity Calibration](platform.md#severity-calibration). Unchanged metadata is not a finding unless the change makes it worse.

### Reading diffs → [Reading Metadata Diffs](#reading-metadata-diffs)

- [ ] Permission set diffs were read as replacements (a removed block revokes, unless `viewAllFields` turned on for that object) and profile diffs as overlays (only an explicit `false` revokes)
- [ ] With decomposed source (`sourceBehaviorOptions`), a deleted child file is a removed permission or rule

### Permissions → [Permission Sets, Groups & Profiles](#permission-sets-groups--profiles)

- [ ] New high-risk user permissions and object View All, Modify All, and View All Fields grants have a named owner and a reason, in an admin or integration permission set
- [ ] New fields ship with `fieldPermissions`, except required and master-detail fields, which can't carry them
- [ ] `classAccesses`, `pageAccesses`, and `flowAccesses` match the feature; muting permission sets were read with `true` meaning muted
- [ ] Guest and portal profile changes: ask for security sign-off
- [ ] 💡 A new grant on a profile: suggest a permission set only when the repo already follows a permission-set model

### Sharing → [Sharing Configuration](#sharing-configuration)

- [ ] `sharingModel` or `externalSharingModel` changes: ask the author for the rollout and recalculation plan
- [ ] Sharing rules grant the narrowest audience and access level; guest sharing rules are intended
- [ ] `doesIncludeBosses`, `parentRole` moves, and restriction or scoping rules were checked for reach; no literal Ids in `userCriteria`
- [ ] A removed sharing reason is intended, with every share that uses it

### Schema → [Objects & Fields](#objects--fields)

- [ ] No API-name renames; no narrowing of type, length, precision, or scale without the author's data check
- [ ] Required and unique fields roll out in steps; a field that turns required loses its `fieldPermissions` in the same PR
- [ ] Delete behavior and master-detail consequences are deliberate; roll-ups and formula filters were weighed at volume
- [ ] Picklist value API names stay stable; sensitive fields carry classification, encryption, and help text where needed

### Validation rules → [Validation Rules](#validation-rules)

- [ ] Transition rules check `ISNEW()` or `ISCHANGED()` on every field they read; invariant rules fire on every save by design
- [ ] The bypass is a custom permission, or the repo's existing `$Setup` bypass; never a profile name or username
- [ ] The error sits on the field, with actionable text of 255 characters at most
- [ ] A rule that reads fields set by before-save flows or before triggers was checked against the save order

### Endpoints & credentials → [Integration Endpoints & Credentials](#integration-endpoints--credentials)

- [ ] New callouts use Named Credentials backed by External Credentials; principal access goes through permission sets
- [ ] No secrets in source; an auth provider `consumerSecret` is a finding only when it isn't the retrieve placeholder
- [ ] Remote Sites use HTTPS with protocol security on; CSP Trusted Sites and CORS origins are exact and minimal
- [ ] New integrations use external client apps with least-privilege scopes, pre-authorized users, org IP rules, and expiring tokens
- [ ] Auth provider and SSO changes: ask for security review

### Configuration → [Configuration Metadata](#configuration-metadata)

- [ ] Deployable configuration lives in custom metadata, runtime switches in hierarchy custom settings, user-facing text in labels, and secrets in none of them
- [ ] Platform events set `publishBehavior` deliberately

### Deployment → [Deployment Impact](#deployment-impact)

- [ ] Destructive changes delete post, after references are gone, with a data plan; a deleted source file has a destructive entry or deactivation
- [ ] `package.xml`, `.forceignore`, and `sfdx-project.json` changes were read for what stops or starts deploying
- [ ] Dependent components deploy together; per-environment values come from `replacements` or credentials
- [ ] Ask the author for the production test level and results; `RunSpecifiedTests` and `RunRelevantTests` need 75% per deployed class and trigger

### Other metadata → [Other Metadata Worth a Glance](#other-metadata-worth-a-glance)

- [ ] `SpecifiedUser` dashboards, email template merge fields, `visibilityRule`, static resource caching, and site settings were checked for exposure

---

## Reading Metadata Diffs

Metadata diffs mix intent with retrieve noise: reordered blocks, dropped entries, and values that differ only because the source org differs. Read each file against what a deployment will do with it; the examples are excerpts.

### Know what a deployment does with each file

- **Permission sets are replaced** on deploy (API 40.0+): a deployment carries all of a permission set's metadata, so whatever the file no longer lists is removed in the target org. Exceptions: when `viewAllFields` is true for an object, its fields aren't listed under `fieldPermissions` (turning it on drops those blocks from a retrieve; turning it off brings them back), and required fields never appear there (API 30.0+).
- **Profiles are overlays**: entries in the file are applied, missing entries stay as they are, and a retrieve returns only the entries for components in the same retrieve (user permissions, login IP ranges, and login hours always come back). A deleted block changes nothing in a profile; a `true` to `false` flip revokes access in both types.
- **Decomposed source**: with `sourceBehaviorOptions` presets (Beta) such as `decomposePermissionSetBeta2` or `decomposeSharingRulesBeta` in `sfdx-project.json`, one component becomes a directory (a permission set gets one `objectSettings/` file per object), and a deleted child file is a removed permission or rule, not a move.

```xml
<!-- ❌ A readable fieldPermissions block deleted from permissionsets/Invoice_Manager.permissionset-meta.xml
     in an unrelated PR: its users lose the field -->

<!-- ✅ In profiles/Sales.profile-meta.xml, revoking must be explicit; deleting the block there does nothing -->
<fieldPermissions><editable>false</editable><field>Invoice__c.Credit_Note__c</field><readable>false</readable></fieldPermissions>
```

### Search the diff with the Grep tool

Run these Grep patterns on the changed files (`git diff --name-only` lists them) and read each hit's whole block; an `<enabled>` flip on an existing permission shows in the diff without its `<name>` line.

- `<name>(ModifyAllData|ViewAllData|QueryAllFiles|ViewAllUsers|AuthorApex|CustomizeApplication|ModifyMetadata|ManageUsers|ManageInternalUsers|ResetPasswords|ManageProfilesPermissionsets|AssignPermissionSets|ManageRoles|ManageSharing|ManageRemoteAccess|ManageAuthProviders|ManageNamedCredentials|ManageEncryptionKeys|ViewEncryptedData|BypassMFAForUiLogins|PasswordNeverExpires|ManageIpAddresses|ApiEnabled|ExportReport|ViewSetup|ManageDataIntegrations)</name>`: every [high-risk permission](#treat-high-risk-permissions-as-a-security-review)
- `<(modifyAllRecords|viewAllRecords|viewAllFields)>true<`: object-level bypasses of sharing and FLS
- `<(classAccesses|pageAccesses|flowAccesses|externalCredentialPrincipalAccesses|loginIpRanges|loginHours)>`: entry points, credentials, logins
- `<(sharingModel|externalSharingModel|accessLevel|sharedTo|doesIncludeBosses|parentRole)>`: who gains access
- `<(type|length|precision|scale|required|unique|deleteConstraint)>` in `*.field-meta.xml`: narrowing and constraints
- `<(password|oauthToken|awsAccessSecret|consumerSecret)>`, and files named `*.ecaGlblOauth-meta.xml`: secrets
- `<(url|endpointUrl|urlPattern|disableProtocolSecurity|scopes|callbackUrl)>`: hosts, protocols, OAuth scopes

---

## Permission Sets, Groups & Profiles

Object and field permissions are the CRUD and FLS layers of the security model ([Security Model](platform.md#security-model)); read every added `true` as access granted to everyone who holds the permission set, group, or profile.

### Grant access through permission sets and permission set groups

Permission sets grant and never deny; bundle them per job in permission set groups and keep profiles to what only profiles hold (login hours and IP ranges, page layout assignments, record type defaults). The plan to retire permissions on profiles was cancelled (Help 003834041), but permission-set-led access remains the recommended model: each grant is reviewable per feature and assignable per user. A new profile grant is a 💡, and only when the repo already follows a permission-set model; high-risk grants keep their own severity.

```xml
<!-- ❌ In a repo that grants features through permission sets: profiles/Sales.profile-meta.xml gains
     <objectPermissions> for Invoice__c -->

<!-- ✅ The block goes in permissionsets/Invoice_Manager, which the Billing Team group bundles -->
<permissionSets>Invoice_Manager</permissionSets>
```

### Treat high-risk permissions as a security review

These user permissions (the `<name>` in `userPermissions`) and object flags let a user see everything, change code or configuration, or change who can do what. Each new grant needs a named owner and a reason, in a dedicated admin or integration permission set rather than a feature set (🔴; 🟡 in a documented integration or admin permission set group). Object-level `viewAllRecords` and `modifyAllRecords` bypass sharing for one object (Modify All also allows delete), and `viewAllFields` (API 63.0+) reads every field of it.

| API name | Label | Why it matters |
|---|---|---|
| `ModifyAllData`, `ViewAllData` | Modify All Data, View All Data | Every record, regardless of sharing |
| `QueryAllFiles`, `ViewAllUsers` | Query All Files, View All Users | Every file; every user record |
| `AuthorApex`, `CustomizeApplication`, `ModifyMetadata` | Author Apex, Customize Application, Modify Metadata Through Metadata API Functions | Change code and configuration, including other safeguards |
| `ManageUsers`, `ManageInternalUsers`, `ResetPasswords` | Manage Users, Manage Internal Users, Reset User Passwords and Unlock Users | Create or take over accounts |
| `ManageProfilesPermissionsets`, `AssignPermissionSets`, `ManageRoles`, `ManageSharing` | Manage Profiles and Permission Sets, Assign Permission Sets, Manage Roles, Manage Sharing | Grant themselves or others more access |
| `ManageRemoteAccess`, `ManageAuthProviders`, `ManageNamedCredentials` | Manage Connected Apps, Manage Auth. Providers, modify Named and External Credentials | Change how integrations and logins authenticate |
| `ManageEncryptionKeys`, `ViewEncryptedData` | Manage Encryption Keys, View Encrypted Data | Keys and decrypted values |
| `BypassMFAForUiLogins`, `PasswordNeverExpires`, `ManageIpAddresses` | Waive Multi-Factor Authentication for Exempt Users, Password Never Expires, Manage IP Addresses | Weaker login controls |
| `ApiEnabled`, `ExportReport`, `ViewSetup`, `ManageDataIntegrations` | API Enabled, Export Reports, View Setup and Configuration, Manage Data Integrations | Bulk data leaves the org; configuration becomes visible |

```xml
<!-- ❌ permissionsets/Billing_Integration.permissionset-meta.xml: the integration can read and change everything -->
<userPermissions><enabled>true</enabled><name>ModifyAllData</name></userPermissions>

<!-- ✅ API access plus objectPermissions and fieldPermissions for exactly what the integration syncs,
     with viewAllRecords and modifyAllRecords false so sharing still applies -->
<userPermissions><enabled>true</enabled><name>ApiEnabled</name></userPermissions>
```

### Ship field-level security with every new field

A new field is readable only where a permission set or profile grants it, and Apex at API 67.0+ reads it in user mode by default, so a field without FLS breaks the page and the code (🟡; [Security Model](platform.md#security-model)). Add `fieldPermissions` for the intended permission sets in the same change, as narrow as the feature needs. Exception: required fields, including master-detail fields, can't carry `fieldPermissions` (API 30.0+: permissions for required fields can't be retrieved or deployed, so a deployment that lists them fails); their missing entries are correct.

```xml
<!-- ❌ objects/Invoice__c/fields/Credit_Note__c.field-meta.xml, an optional field, with no fieldPermissions anywhere in the PR -->

<!-- ✅ In the same PR: read for the billing team, edit only where the feature needs it -->
<fieldPermissions><editable>false</editable><field>Invoice__c.Credit_Note__c</field><readable>true</readable></fieldPermissions>
```

### Grant class, page, and flow access only where the entry point needs it

`classAccesses` opens a class's entry points (the `@AuraEnabled` methods behind LWC and Aura, Apex REST), and `pageAccesses` opens Visualforce pages. `flowAccesses` grants flows: since the Restrict User Access to Run Flows release update (enforced in Winter '26), users without Run Flows or Manage Flow (guest, portal, and restricted internal users) run a screen or autolaunched flow only through such a grant, and a flow that sets `isAdditionalPermissionRequiredToRun` runs only for granted users ([Run Context & Security](flows.md#run-context--security)); record-triggered and schedule-triggered flows need none. Flows don't need `classAccesses` for the invocable classes they call; the release update that required it was retired (verify for guest and Experience Cloud users). Grant each in the feature's permission set, and check guest and portal profiles separately.

```xml
<!-- ❌ classAccesses for every controller in an "All Users" permission set -->

<!-- ✅ The feature's permission set opens exactly the controller, flow, and page the feature uses -->
<classAccesses><apexClass>InvoiceController</apexClass><enabled>true</enabled></classAccesses>
<flowAccesses><enabled>true</enabled><flow>Invoice_Approval</flow></flowAccesses>
<pageAccesses><apexPage>InvoicePdf</apexPage><enabled>true</enabled></pageAccesses>
```

### Read muting permission sets inverted

A muting permission set exists only inside a permission set group (one per group, listed in `<mutingPermissionSets>`) and removes permissions from that group's members; in its file, `true` means muted. For example, `<allowDelete>true</allowDelete>` in the `Invoice__c` `<objectPermissions>` of `mutingpermissionsets/Billing_Team_Muted.mutingpermissionset-meta.xml` takes Delete on invoices away from the Billing Team group.

### Send guest user profile changes to security review

A site's guest user profile serves anonymous internet users, so an added object permission, field permission, or class access there exposes data to anyone. The platform already caps guests ([Guest and Experience Cloud users](platform.md#guest-and-experience-cloud-users)); a diff that works around those caps, or adds access at all, needs a security sign-off.

```xml
<!-- ❌ The guest user profile gains classAccesses for InvoiceController and readable fieldPermissions for Invoice__c.Amount__c -->

<!-- ✅ After sign-off: a narrow with-sharing controller that returns only what the public page shows -->
<classAccesses><apexClass>PublicInvoiceStatusController</apexClass><enabled>true</enabled></classAccesses>
```

---

## Sharing Configuration

Sharing decides which records users see; the CRUD and FLS layers above decide what they can do with them.

### Treat org-wide default changes as data exposure events

`sharingModel` (internal users) and `externalSharingModel` (external users, never more open than internal) set the baseline for every record of the object: `Private`, `Read`, `ReadWrite`, `ControlledByParent`, and object-specific values such as `ReadWriteTransfer` and `FullAccess`. Loosening exposes every record at once (🔴), tightening breaks users and integrations that relied on access, and either starts an org-wide sharing recalculation that can run long on large objects: ask when and how it rolls out.

```xml
<!-- ❌ objects/Invoice__c/Invoice__c.object-meta.xml: every internal user can now read and edit every invoice -->
<sharingModel>ReadWrite</sharingModel>

<!-- ✅ Private baseline; the teams that need invoices get them through a sharing rule -->
<externalSharingModel>Private</externalSharingModel>
<sharingModel>Private</sharingModel>
```

### Check who a sharing rule, group, or role change reaches

Sharing rules only widen access, so read `sharedTo` and `accessLevel` first. `allInternalUsers`, `allPartnerUsers`, and `roleAndSubordinates` (which includes portal roles below it, unlike `roleAndSubordinatesInternal`) reach far, `Edit` lets them change records, and `sharingGuestRules` give anonymous users Read. `doesIncludeBosses` (Grant Access Using Hierarchies) on a public group, or on a queue at API 67.0+, also shares with everyone above the members in the role hierarchy, and a changed `parentRole` moves a whole branch under new managers, who then see its records.

```xml
<!-- ❌ A criteria rule with <accessLevel>Edit</accessLevel> and <sharedTo><allInternalUsers></allInternalUsers></sharedTo> -->

<!-- ✅ Read only, for the finance roles that review approved invoices, internal users only -->
<accessLevel>Read</accessLevel>
<sharedTo><roleAndSubordinatesInternal>Finance_Manager</roleAndSubordinatesInternal></sharedTo>
```

A group that is the whole audience, not its members' managers too, keeps `<doesIncludeBosses>false</doesIncludeBosses>`.

### Don't count on restriction or scoping rules to limit system-mode code

A restriction rule (`enforcementType` `Restrict`) narrows the records matching users can access, while a scoping rule (`Scoping`) only sets the records they see by default. User-mode access honors them (`WITH USER_MODE` supports both), so code that runs in system mode is not held to them; and a `userCriteria` that compares `$User.UserRoleId` or `$User.ProfileId` with a literal Id works in one org only.

```xml
<!-- ❌ <userCriteria>$User.UserRoleId = '00E000000000000AAA'</userCriteria>: a role Id from one org -->

<!-- ✅ restrictionRules/Invoices_You_Own.rule-meta.xml (excerpt): the description states the limit -->
<description>Users see only the invoices they own. System-mode Apex is not restricted by this rule.</description>
<recordFilter>OwnerId = $User.Id</recordFilter>
```

### Keep sharing reasons in step with Apex managed sharing

A sharing reason (`objects/<Object>/sharingReasons/*.sharingReason-meta.xml`, custom objects only) is the `RowCause` of Apex managed sharing ([Data Access Security](apex.md#data-access-security)). Deleting it deletes every share that uses it, so a removed reason revokes access across the org: ❌ `sharingReasons/Reviewer__c` in a destructive manifest while Apex still writes `Schema.Invoice__Share.RowCause.Reviewer__c`.

---

## Objects & Fields

Schema is a contract with every consumer of the org's data: Apex, flows, formulas, reports, integrations, and LWC imports (`@salesforce/schema`).

### Treat API names as contracts

The Metadata API has no rename: a new `fullName` in source deploys a new, empty field next to the old one, and removing the old one is a destructive change ([Deployment Impact](#deployment-impact)). ❌ `fields/Tier__c.field-meta.xml` renamed to `Customer_Tier__c.field-meta.xml` adds an empty `Customer_Tier__c` while `Tier__c`, its data, and every reference remain. ✅ Keep the API name and change the `<label>`, or add the new field, migrate the data, move every reference, and delete the old field in a later release.

### Don't narrow types, lengths, or precision without a data plan

Shrinking `length`, `precision`, or `scale`, or changing `type`, can truncate or drop existing values and break writers that send longer ones (🔴 without a data plan, 🟡 when there is no production data yet). Ask the author for the production data check (longest value, largest number) before approving: ❌ `<length>40</length>` on `External_Reference__c`, down from 255; ✅ keep 255 until production data is shown to fit, or add a new field and migrate.

### Roll out required and unique fields in steps

`<required>true</required>` makes every writer (integrations, data loads, Apex tests, flows that create records) supply a value, and saving an existing record that is still blank can then fail; `<unique>true</unique>` fails while existing values repeat. Add the field as optional, backfill it, then tighten it in a later release, or enforce it with a validation rule that has a bypass ([Validation Rules](#validation-rules)). The release that sets `required` also deletes the field's `fieldPermissions` from every permission set and profile in source, because permissions for required fields can't be deployed (API 30.0+).

```xml
<!-- ❌ Required and unique from day one on an object that integrations write -->
<required>true</required>
<unique>true</unique>

<!-- ✅ Release 1: optional external Id, backfilled; release 2: required and unique, its fieldPermissions removed -->
<externalId>true</externalId>
<required>false</required>
<unique>false</unique>
```

### Choose lookup delete behavior and master-detail deliberately

`deleteConstraint` decides what deleting the parent does: `SetNull` (the default) clears the lookup, `Restrict` blocks the delete, `Cascade` deletes the children. A master-detail field makes the child's `sharingModel` `ControlledByParent`, removes the child's owner, and deletes children with their parent; `writeRequiresMasterRead` true lets users with only Read on the parent create and edit children.

```xml
<!-- ❌ <deleteConstraint>SetNull</deleteConstraint> on a lookup the business treats as required:
     deleting an account leaves invoices that belong to nobody -->

<!-- ✅ objects/Invoice__c/fields/Account__c.field-meta.xml: invoices block deleting their account -->
<deleteConstraint>Restrict</deleteConstraint>
```

### Weigh the cost of formula and roll-up summary fields

Formula fields are computed when read, so filters on them usually can't use an index ([Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes)). A roll-up summary updates the parent on every child change, which locks the parent and contends when many children share one parent, and creating or changing one recalculates every parent. ❌ A new roll-up on Account counting `Invoice__c` where some accounts hold tens of thousands of invoices: every invoice save locks the account, and bulk loads fail on locks. ✅ Ask for the data distribution first; for skewed parents keep the total out of the save path (a scheduled flow or a Queueable), and keep formula fields out of filters on large objects.

### Keep picklists restricted and value API names stable

`<restricted>true</restricted>` rejects values outside the set, including from the API; a field on a global value set (`<valueSetName>`) is always restricted and changes only through the global value set. Code and automation compare a value's `fullName`, so change its `label` instead, and deactivate (`isActive` false) values that records still hold instead of deleting them.

```xml
<!-- ✅ objects/Invoice__c/fields/Status__c.field-meta.xml (excerpt): a relabeled value and a retired one -->
<value><fullName>Approved</fullName><default>false</default><label>Approved for Payment</label></value>
<value><fullName>On_Hold</fullName><default>false</default><isActive>false</isActive><label>On Hold (retired)</label></value>
```

### Document sensitive fields and check encryption and history settings

`encryptionScheme` (Shield Platform Encryption) changes what queries can do with a field: probabilistic encryption can't be filtered or sorted, while deterministic encryption allows exact-match filters. `trackHistory` needs `enableHistory` on the object, and `securityClassification`, `complianceGroup`, `description`, and `inlineHelpText` tell admins and users what the field holds.

```xml
<!-- ✅ objects/Invoice__c/fields/Bank_Account__c.field-meta.xml (excerpt): classified, and still filterable by exact match -->
<complianceGroup>PII</complianceGroup>
<encryptionScheme>CaseSensitiveDeterministicEncryption</encryptionScheme>
<securityClassification>Restricted</securityClassification>
```

---

## Validation Rules

Validation rules run on every save, from the UI, the API, Apex, flows, and data loads, so a new rule can stop an integration mid-sync. They run after before-save flows and Apex before triggers (so either can set the field a rule checks) and don't run again after a workflow field update ([Order of Execution](apex-triggers.md#order-of-execution)).

### Make rules bypassable, change-aware, and blank-safe

Decide first whether the rule guards a transition or an invariant. A transition rule ("closing needs a reason") checks `ISNEW()` or `ISCHANGED()` on every field it reads, so old records that never met it still save and a later edit can't clear what the transition required; an invariant rule ("the amount is never negative") fires on every save by design. Test blanks with `ISBLANK()`. Put the bypass in a custom permission (`$Permission.Bypass_Validation_Rules`) assigned through the integration or migration permission set, or in a hierarchy custom setting (`$Setup`) when the repo already bypasses that way; never in profile names or usernames. A missing bypass or change check is 🟡 at most.

```text
❌ AND($Profile.Name <> "Integration User", ISPICKVAL(Status__c, "Closed"), Closed_Reason__c = "")
   Profile-name bypass, and every edit of an old closed invoice without a reason fails, even a phone fix
❌ AND(OR(ISNEW(), ISCHANGED(Status__c)), ISPICKVAL(Status__c, "Closed"), ISBLANK(Closed_Reason__c))
   A user can blank Closed_Reason__c on a closed invoice: Status didn't change, so the rule never fires

✅ AND(
       NOT($Permission.Bypass_Validation_Rules),
       OR(ISNEW(), ISCHANGED(Status__c), ISCHANGED(Closed_Reason__c)),
       ISPICKVAL(Status__c, "Closed"),
       ISBLANK(Closed_Reason__c)
   )
```

### Put the error on the field with actionable text

`errorDisplayField` shows the message next to the field (at the top of the page when the field isn't on the layout), and `errorMessage` (255 characters at most) should say what to do, because users read it on screen and integrations log it verbatim. A rule that spans several fields may leave `errorDisplayField` empty. Translate the message through the Translation Workbench (`objectTranslations`).

```xml
<!-- ❌ <errorMessage>Invalid data</errorMessage> with no errorDisplayField on a single-field rule -->

<!-- ✅ objects/Invoice__c/validationRules/Closed_Requires_Reason.validationRule-meta.xml (excerpt; formula above) -->
<errorDisplayField>Closed_Reason__c</errorDisplayField>
<errorMessage>Enter a closed reason before you close the invoice.</errorMessage>
```

---

## Integration Endpoints & Credentials

Endpoints and credentials decide where data can go and as whom; the Apex side of callouts is in [Callouts & Integrations](apex.md#callouts--integrations).

### Use Named Credentials backed by External Credentials

A Named Credential holds the endpoint, and an External Credential holds the authentication protocol and principals; users reach a principal only through a permission set's `externalCredentialPrincipalAccesses` (`<ExternalCredential>-<Principal>`). Legacy named credentials (`namedCredentialType` `Legacy`, with `endpoint`, `principalType`, `protocol`) remain for backward compatibility and are deprecated; new ones use `SecuredEndpoint`, and an unchanged legacy credential is not a finding. Callouts through a Named Credential need no Remote Site Setting.

```xml
<!-- ❌ A new legacy named credential with <username> and <password> in the file -->

<!-- ✅ namedCredentials/Billing_API.namedCredential-meta.xml (excerpt): authentication comes from an External Credential -->
<namedCredentialParameters><externalCredential>Billing_OAuth</externalCredential><parameterName>ExternalCredential</parameterName><parameterType>Authentication</parameterType></namedCredentialParameters>
<namedCredentialType>SecuredEndpoint</namedCredentialType>

<!-- ✅ permissionsets/Billing_Integration.permissionset-meta.xml: only holders of this set use the principal -->
<externalCredentialPrincipalAccesses><enabled>true</enabled><externalCredentialPrincipal>Billing_OAuth-Integration</externalCredentialPrincipal></externalCredentialPrincipalAccesses>
```

### Keep secrets out of the repository

Anything in source control is in every clone and every deployment (🔴). Secrets belong in the org (a principal's authentication parameters, set per org and referenced through `$Credential` formulas), never in these places:

| Where | Element or file |
|---|---|
| Legacy named credentials | `password`, `oauthToken`, `awsAccessSecret` |
| Connected apps | `consumerSecret`: a retrieve never returns it, so a value in the file was added by hand |
| Auth providers | `consumerSecret`: a retrieve always writes a placeholder, so the element alone is normal; a finding only when the value isn't that placeholder |
| External client apps | `*.ecaGlblOauth-meta.xml` (global OAuth settings with the consumer key and secret), which must not be added to source control |
| External Credentials | A literal token in `parameterValue` |
| Configuration | Custom Metadata values, Custom Labels, custom settings, static resources, flow and Apex literals |

### Keep Remote Sites, CSP Trusted Sites, and CORS origins exact

Each of these allowlists a host. On a Remote Site Setting, `disableProtocolSecurity` true lets code pass data from an HTTPS session to an HTTP one: keep it false and the URL on `https://` (or use a Named Credential, which needs no Remote Site). On a CSP Trusted Site, each `isApplicableTo...Src` flag opens one Content Security Policy directive for `endpointUrl` (wildcards such as `*.example.com` are allowed) in a `context` (`All`, `LEX`, `Communities`, `VisualForce`, ...): enable only what the component needs, for one host ([Security in the Browser](lwc.md#security-in-the-browser)). A CORS `urlPattern` must be HTTPS and may put `*` in front of the second-level domain, admitting every subdomain, including ones someone else controls: list exact origins.

```xml
<!-- ❌ <url>http://billing.example.com</url> with <disableProtocolSecurity>true</disableProtocolSecurity>; a CSP Trusted
     Site for https://*.example.com with every flag true in context All; <urlPattern>https://*.example.com</urlPattern> -->

<!-- ✅ A Remote Site, a CSP Trusted Site for images from one host in Lightning Experience (other flags false),
     and one exact CORS origin -->
<disableProtocolSecurity>false</disableProtocolSecurity><url>https://rates.example.com</url>
<context>LEX</context><endpointUrl>https://tiles.example.com</endpointUrl><isApplicableToImgSrc>true</isApplicableToImgSrc>
<urlPattern>https://portal.example.com</urlPattern>
```

### Review connected apps and external client apps like login configuration

Since Spring '26, new connected apps can't be created through the UI or the API, package installs aside, unless Salesforce Support re-enables creation for the org (Help 005228017), so a new `*.connectedApp-meta.xml` usually fails to deploy: ask for an External Client App (`externalClientApps/*.eca-meta.xml` with its `.ecaOauth` settings and `.ecaOauthPlcy` policies). For both, check the scopes (`Full`, `Api`, and `RefreshToken` are broad), who may use the app (admin-approved and pre-authorized, not self-authorized), IP relaxation, refresh-token lifetime, the callback URL, and any client-credentials execution user (`oauthClientCredentialUser`, `clientCredentialsFlowUser`).

```xml
<!-- ❌ An existing connected app widened: full scope, anyone self-authorizes, org IP ranges bypassed, tokens never expire -->
<oauthConfig><isAdminApproved>false</isAdminApproved><scopes>Full</scopes><scopes>RefreshToken</scopes></oauthConfig>
<oauthPolicy><ipRelaxation>BYPASS</ipRelaxation><refreshTokenPolicy>infinite</refreshTokenPolicy></oauthPolicy>

<!-- ✅ extlClntAppOauthPolicies/Billing_Portal.ecaOauthPlcy-meta.xml (excerpt) -->
<ipRelaxationPolicyType>Enforce</ipRelaxationPolicyType>
<permittedUsersPolicyType>AdminApprovedPreAuthorized</permittedUsersPolicyType>
<refreshTokenPolicyType>SpecificInactivity</refreshTokenPolicyType>
<refreshTokenValidityPeriod>30</refreshTokenValidityPeriod><refreshTokenValidityUnit>Days</refreshTokenValidityUnit>
```

### Send auth provider and SSO changes to security review

An auth provider's registration handler (`registrationHandler`, an `Auth.RegistrationHandler` class, or a flow) creates and updates users as `executionUser`, who must have Manage Users, so a bug there can create users or change their access. Treat `AuthProvider` and `SamlSsoConfig` changes as changes to who can log in, and as whom.

```xml
<!-- ❌ authproviders/Partner_Idp.authprovider-meta.xml: a real secret typed into the file, and an admin running the handler -->
<consumerSecret>example-secret</consumerSecret>
<executionUser>admin@example.com</executionUser>

<!-- ✅ The org holds the secret; a dedicated system user runs a handler whose user mapping has tests and review -->
<executionUser>partner-idp-handler@example.com</executionUser>
```

---

## Configuration Metadata

Pick the store by who changes the value and whether it deploys with the source; reading these values from code is in [Org-Agnostic Code](platform.md#org-agnostic-code), and from flows in [Org-Agnostic Values](flows.md#org-agnostic-values).

| Value | Store | Deploys with source | Notes |
|---|---|---|---|
| Business rules, mappings, feature flags, thresholds | Custom metadata (`customMetadata/*.md-meta.xml`) | Yes | Read from Apex without SOQL queries; Get Records in flows |
| User-facing text | Custom Labels | Yes | Translatable; not for configuration or secrets |
| Switches changed at runtime per user, profile, or org | Hierarchy custom settings | The definition only; values are data | `$Setup` in formulas and flows |
| Endpoints and credentials | Named and External Credentials | Endpoints yes; secrets no | [Integration Endpoints & Credentials](#integration-endpoints--credentials) |

### Keep deployable configuration in custom metadata types

Custom metadata records deploy, version, and test like code, so a threshold or mapping changes in a reviewed PR; Custom Labels are for text users read. Record values sit in the repository in clear text: `protected` and `visibility` limit access from packaged code and subscriber orgs, not who can read the repo.

```xml
<!-- ❌ labels/CustomLabels.labels-meta.xml: a <labels> entry Invoice_Review_Threshold whose <value> is 10000 -->

<!-- ✅ customMetadata/Invoice_Setting.Default.md-meta.xml (excerpt; the root declares the xsi and xsd namespaces) -->
<values><field>Review_Threshold__c</field><value xsi:type="xsd:double">10000.0</value></values>
```

### Use hierarchy custom settings for runtime switches, not for configuration that should deploy

A custom setting's definition deploys, but its values are records that each org sets by hand, so thresholds or endpoints kept there drift between orgs. Keep hierarchy settings (`<customSettingsType>Hierarchy</customSettingsType>`) for switches an admin flips per user, profile, or org at runtime, such as pausing an integration: ❌ a list custom setting holding endpoints, whose values never deploy and belong in Named Credentials.

### Set platform event publish behavior explicitly

`publishBehavior` decides when subscribers see an event published from Apex or Flow: `PublishAfterCommit` only after the transaction commits, `PublishImmediately` at once, even if the transaction rolls back. Without the element the event publishes immediately. Business events usually need `PublishAfterCommit`, and logging events `PublishImmediately` ([Callouts & Integrations](apex.md#callouts--integrations)): ❌ `objects/Invoice_Approved__e/Invoice_Approved__e.object-meta.xml` without `<publishBehavior>`, so subscribers can act on approvals that later rolled back; ✅ `<publishBehavior>PublishAfterCommit</publishBehavior>`.

---

## Deployment Impact

This section stands alone for PRs that touch `manifest/`, `destructiveChanges*.xml`, `.forceignore`, or `sfdx-project.json`. These files decide what the pipeline deploys, deletes, and tests: read them as code, and ask the author or CI for the plan and results instead of running anything against an org ([Static Review Only](platform.md#static-review-only)). Per [Severity Calibration](platform.md#severity-calibration), a destructive change, field narrowing, or new required or unique field without a data plan is 🔴 (🟡 with no production data yet).

A deployment resolves dependencies among the components it contains, so a field, the permission sets that grant it, and the Apex and flows that use it belong in one deployment; split across pull requests, the dependent part fails in every org that lacks the field, unless the pipeline deploys them in order (ask the author).

### Treat destructive changes as irreversible

`destructiveChangesPre.xml` deletes components before the rest of the deployment and `destructiveChangesPost.xml` after it; destructive manifests don't support wildcards, and a component still referenced elsewhere fails to delete, so remove the references in the same deployment and delete post. Deleting a field or object takes its data with it: deleted components go to the Recycle Bin, restorable in the org but not by redeploying (`purgeOnDelete` skips it, in sandboxes and Developer Edition orgs only), a roll-up summary field deleted through the Metadata API is purged at once, and redeploying the API name later creates an empty component. Ask for the export or migration plan.

The reverse also holds: deleting a file from the repository deletes nothing in the org (source tracking in scratch orgs and sandboxes aside), so a removed flow or class stays active until a destructive manifest or a deactivation removes it. A flow version can be deleted only when it is inactive and has no paused interviews; deactivation is in [Activation, Versions & Deployment](flows.md#activation-versions--deployment).

```xml
<!-- ❌ The field in destructiveChangesPre.xml while InvoiceService.cls still reads it: the deployment fails.
     ❌ A PR that only deletes flows/Invoice_Legacy_Sync.flow-meta.xml: the flow keeps running in production -->

<!-- ✅ destructiveChangesPost.xml (excerpt): deleted after this deployment removes the last Apex and flow references -->
<types>
    <members>Invoice__c.Legacy_Code__c</members>
    <name>CustomField</name>
</types>
```

### Review package.xml and .forceignore changes as scope changes

A manifest lists what a deployment or retrieve covers: a removed `<types>` block or member stops deploying it, `*` covers all components of the types that support it (some don't: `ValidationRule` needs `Object.Rule` names such as `Invoice__c.Closed_Requires_Reason`), and `<version>` sets the API version of the operation. A new `.forceignore` pattern silently stops deploying and retrieving every matching file: ❌ removing the `ValidationRule` block, or adding `**/validationRules/**` to `.forceignore`, stops rule changes from deploying, and nothing fails.

### Review sfdx-project.json changes, and inject per-environment values

`sourceApiVersion` is the API version the source format uses for deploy and retrieve (each file's `<apiVersion>` still sets its runtime, see [API Versions](platform.md#api-versions)); `packageDirectories` decide what deploys, and in which package; `namespace` and package dependencies change how names resolve; `sourceBehaviorOptions` changes the file layout ([Reading Metadata Diffs](#reading-metadata-diffs)). Hosts, usernames, and emails differ per org (a sandbox username ends in the sandbox name), so inject them at deploy time with `replacements` instead of committing one org's values.

```json
{
  "replacements": [
    { "glob": "force-app/main/default/namedCredentials/*.namedCredential-meta.xml",
      "stringToReplace": "https://billing.sandbox.example.com", "replaceWithEnv": "BILLING_API_URL" }
  ]
}
```

### Know the test level and the coverage gates

Ask the author or CI which test level the production deployment uses and for its results; coverage is org-side evidence, not something to compute in review ([Testing](apex.md#testing)).

| Gate | Rule |
|---|---|
| No test level set (production) | All local tests run when the package contains Apex classes or triggers; otherwise no tests run |
| `RunLocalTests`, `RunAllTestsInOrg` | At least 75% org-wide coverage, every trigger covered by at least one line, all tests pass |
| `RunSpecifiedTests`, `RunRelevantTests` (Beta since Spring '26) | The executed tests cover each class and trigger in the package by at least 75%, computed per component, not org-wide |
| `NoTestRun` | Development environments only (sandbox, Developer Edition, trial orgs), never production |
| Flows deployed as active | Production keeps them inactive unless "Deploy processes and flows as active" is on; then Apex tests must launch 75% of active processes and autolaunched flows (screen flows exempt), or the deployment rolls back ([Activation](flows.md#activation-versions--deployment)) |

---

## Other Metadata Worth a Glance

These types rarely carry code, but a one-line change can expose data or weaken a site.

### Check dashboards that run as a specified user

With `dashboardType` `SpecifiedUser`, every viewer sees data as `runningUser`, whatever their own access, and when that username doesn't exist in the target org the deployment sets the deploying user (often an admin) as the running user. Prefer `LoggedInUser` for dashboards with sensitive data: ❌ `dashboards/Finance/Invoice_Overview.dashboard-meta.xml` with `<dashboardType>SpecifiedUser</dashboardType>` and `<runningUser>admin@example.com</runningUser>`, so everyone who opens it sees the admin's data; ✅ `<dashboardType>LoggedInUser</dashboardType>`.

### Glance at email templates, Lightning pages, static resources, and sites

- Email templates (`email/**/*.email-meta.xml`): merge fields that show record data to recipients who shouldn't see it; `visualforce` templates run Visualforce markup and its controllers.
- Lightning pages (`flexipages/*.flexipage-meta.xml`): a `visibilityRule` only hides a component and restricts no data, so it is not access control.
- Static resources (`staticresources/*.resource-meta.xml`): the vendor library's name, version, and license; `cacheControl` `Public` lets third-party caches keep the file, so nothing sensitive.
- Sites and Experience Cloud (`sites/`, `networks/`): `siteGuestRecordDefaultOwner`; `clickjackProtectionLevel` (`AllowAllFraming` means no protection); `selfRegistration` and `selfRegProfile`; `enableGuestFileAccess`, `enableGuestMemberVisibility`; the [guest user profile](#send-guest-user-profile-changes-to-security-review).

---

## References

- [PermissionSet (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_permissionset.htm)
- [Profile (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_profile.htm)
- [Deleting Components from an Organization (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_deploy_deleting_files.htm)
- [Salesforce DX Project Configuration (sfdx-project.json)](https://developer.salesforce.com/docs/atlas.en-us.sfdx_dev.meta/sfdx_dev/sfdx_dev_ws_config.htm)
- [New connected apps restricted (Salesforce Help 005228017)](https://help.salesforce.com/s/articleView?id=005228017&language=en_US&type=1)
