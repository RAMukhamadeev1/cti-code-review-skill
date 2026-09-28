# Salesforce Metadata & Permissions Code Review Guide

Review guidance for declarative metadata in pull requests: permission sets, permission set groups and profiles, sharing configuration, objects and fields, validation rules, integration endpoints and credentials, configuration metadata, and deployment manifests, in source format (`force-app/**`). Current for Summer '26 (API 67.0) and Winter '27 (API 68.0) orgs.

> Load the [Salesforce Platform Guide](platform.md) first — it defines governor limits, the security model and API-version rules, and severity calibration.
> Related: [Apex data access](apex.md#data-access-security) · [Flows](flows.md) · [Security Review Guide](../security-review-guide.md#salesforce-platform-security)

## Table of Contents

- [When to Use This Guide](#when-to-use-this-guide)
- [Reading Metadata Diffs](#reading-metadata-diffs)
- [Permission Sets, Groups & Profiles](#permission-sets-groups--profiles)
- [Sharing Configuration](#sharing-configuration)
- [Objects & Fields](#objects--fields)
- [Validation Rules](#validation-rules)
- [Integration Endpoints & Credentials](#integration-endpoints--credentials)
- [Configuration Metadata](#configuration-metadata)
- [Deployment Impact](#deployment-impact)
- [Other Metadata Worth a Glance](#other-metadata-worth-a-glance)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## When to Use This Guide

| Changed files | Section |
|---|---|
| `permissionsets/`, `permissionsetgroups/`, `mutingpermissionsets/`, `profiles/` | [Permission Sets, Groups & Profiles](#permission-sets-groups--profiles) |
| `sharingModel` in `objects/<Object>/<Object>.object-meta.xml`; `sharingRules/`, `roles/`, `groups/`, `queues/`, `restrictionRules/`, `objects/<Object>/sharingReasons/` | [Sharing Configuration](#sharing-configuration) |
| `objects/<Object>/fields/*.field-meta.xml`, `globalValueSets/` | [Objects & Fields](#objects--fields) |
| `objects/<Object>/validationRules/*.validationRule-meta.xml` | [Validation Rules](#validation-rules) |
| `namedCredentials/`, `externalCredentials/`, `remoteSiteSettings/`, `cspTrustedSites/`, `corsWhitelistOrigins/`, `connectedApps/`, `externalClientApps/` and the `extlClntApp*` folders, `authproviders/`, `samlssoconfigs/` | [Integration Endpoints & Credentials](#integration-endpoints--credentials) |
| `customMetadata/`, `labels/`, custom settings and platform events (`*__e`) under `objects/` | [Configuration Metadata](#configuration-metadata) |
| `manifest/*.xml`, `destructiveChanges*.xml`, `.forceignore`, `sfdx-project.json` | [Deployment Impact](#deployment-impact) |
| `dashboards/`, `email/`, `flexipages/`, `staticresources/`, `sites/`, `networks/` | [Other Metadata Worth a Glance](#other-metadata-worth-a-glance) |
| `flows/*.flow-meta.xml` | [Flows](flows.md) |

Metadata review is static: ask the author or CI for org-side evidence such as current assignments, data volumes, and deployment results ([Static Review Only](platform.md#static-review-only)), and rate findings with [Severity Calibration](platform.md#severity-calibration).

---

## Reading Metadata Diffs

Metadata diffs mix intent with retrieve noise: reordered blocks, dropped entries, and values that differ only because the source org differs. Read each changed file against what a deployment will do with it. The examples are excerpts; each file's root element and `xmlns` are shown only where they matter.

### Know what a deployment does with each file

Permission sets are replaced on deploy (API 40.0 and later): whatever the file no longer lists is removed in the target org. Profiles are overlays: entries in the file are applied, entries missing from it stay as they are, and a retrieve returns only the entries for components in the same retrieve (user permissions, login IP ranges, and login hours always come back). A deleted block therefore revokes access in a permission set and changes nothing in a profile, while a `true` to `false` flip revokes access in both. When `sfdx-project.json` lists `sourceBehaviorOptions` presets (Beta) such as `decomposePermissionSetBeta2` or `decomposeSharingRulesBeta`, one component is split into a directory of files (for a permission set, one `objectSettings/` file per object), and a deleted child file is a removed permission or rule, not a move.

```xml
<!-- ❌ Deleted from permissionsets/Invoice_Manager.permissionset-meta.xml in a PR about something else:
     the deployment replaces the permission set, and its users lose the field in every org -->
<fieldPermissions>
    <editable>false</editable>
    <field>Invoice__c.Credit_Note__c</field>
    <readable>true</readable>
</fieldPermissions>

<!-- ✅ Revoking through profiles/Sales.profile-meta.xml must be explicit; deleting the block there does nothing -->
<fieldPermissions>
    <editable>false</editable>
    <field>Invoice__c.Credit_Note__c</field>
    <readable>false</readable>
</fieldPermissions>
```

### Read the elements that carry access and risk

Most of a large metadata diff is safe to skim; these elements are not.

| File | Elements to read | Watch for |
|---|---|---|
| `*.permissionset-meta.xml`, `*.profile-meta.xml` | `userPermissions`, `objectPermissions`, `fieldPermissions`, `classAccesses`, `pageAccesses`, `flowAccesses`, `customPermissions`, `externalCredentialPrincipalAccesses`, `recordTypeVisibilities`; in profiles also `loginIpRanges`, `loginHours` | New grants, `true`/`false` flips, removed blocks in permission sets |
| `*.permissionsetgroup-meta.xml`, `*.mutingpermissionset-meta.xml` | `permissionSets`, `mutingPermissionSets` | What a group bundles and what it mutes |
| `*.object-meta.xml` | `sharingModel`, `externalSharingModel`, `enableHistory`, `visibility`, `customSettingsType`, `publishBehavior` | Org-wide default changes, custom settings, platform events |
| `*.field-meta.xml` | `type`, `length`, `precision`, `scale`, `required`, `unique`, `externalId`, `deleteConstraint`, `formula`, `valueSet`, `encryptionScheme` | Narrowing, new constraints, delete behavior |
| `*.validationRule-meta.xml` | `active`, `errorConditionFormula`, `errorDisplayField`, `errorMessage` | Bypass, change awareness |
| `*.sharingRules-meta.xml` | `accessLevel`, `sharedTo`, `criteriaItems` | Who gains access, and how much |
| Credentials and endpoints | `namedCredentialParameters`, `url`, `endpointUrl`, `urlPattern`, `disableProtocolSecurity`, `scopes`, `consumerSecret` | Hosts, protocols, wildcards, scopes, secrets |

```bash
# Read-only: high-risk grants added on this branch; read each hit's block
# (an <enabled> flip on an existing permission shows without its <name> line)
git diff origin/main...HEAD -- '*.permissionset-meta.xml' '*.profile-meta.xml' \
  | grep -nE '^\+.*(<name>(ModifyAllData|ViewAllData|AuthorApex|CustomizeApplication|ManageUsers|ModifyMetadata)</name>|<(modifyAllRecords|viewAllRecords|viewAllFields)>true<)'
```

---

## Permission Sets, Groups & Profiles

Object and field permissions are the CRUD and FLS layers of the security model ([Security Model](platform.md#security-model)); read every added `true` as access granted to everyone who holds the permission set, group, or profile.

### Grant access through permission sets and permission set groups

Permission sets grant and never deny; bundle them per job in permission set groups and keep profiles to what only profiles hold (login hours and IP ranges, page layout assignments, record type defaults). The plan to retire permissions on profiles was cancelled (Help 003834041), but permission-set-led access remains the recommended model: each grant is reviewable per feature and assignable per user.

```xml
<!-- ❌ profiles/Sales.profile-meta.xml gains <objectPermissions> for Invoice__c for a new feature -->

<!-- ✅ The same block in permissionsets/Invoice_Manager.permissionset-meta.xml, bundled per job by a group -->
<PermissionSetGroup xmlns="http://soap.sforce.com/2006/04/metadata">
    <description>Billing team: invoice management and approval</description>
    <label>Billing Team</label>
    <permissionSets>Invoice_Manager</permissionSets>
    <permissionSets>Invoice_Approver</permissionSets>
</PermissionSetGroup>
```

### Treat high-risk permissions as a security review

These user permissions (the `<name>` in `userPermissions`) and object flags let a user see everything, change code or configuration, or change who can do what. Each new grant needs a named owner and a reason, in a dedicated admin or integration permission set rather than a feature set. Object-level `viewAllRecords` and `modifyAllRecords` bypass sharing for one object (Modify All also allows delete), and `viewAllFields` (API 63.0+) reads every field of it.

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

A new field is readable only where a permission set or profile grants it, and Apex at API 67.0+ reads it in user mode by default, so a field without FLS breaks the page and the code ([Security Model](platform.md#security-model)). Add `fieldPermissions` for the intended permission sets in the same change, as narrow as the feature needs.

```xml
<!-- ❌ objects/Invoice__c/fields/Credit_Note__c.field-meta.xml with no fieldPermissions anywhere in the PR -->

<!-- ✅ In the same PR: read for the billing team, edit only where the feature needs it -->
<fieldPermissions>
    <editable>false</editable>
    <field>Invoice__c.Credit_Note__c</field>
    <readable>true</readable>
</fieldPermissions>
```

### Grant class, page, and flow access only where the entry point needs it

`classAccesses` lets users run a class's entry points (the `@AuraEnabled` methods behind LWC and Aura, Apex REST), `pageAccesses` opens Visualforce pages, and `flowAccesses` opens flows that set `isAdditionalPermissionRequiredToRun` ([Run Context & Security](flows.md#run-context--security)). Put them in the permission set of the feature that uses them, and check guest and portal profiles separately.

```xml
<!-- ❌ classAccesses for every controller in an "All Users" permission set -->

<!-- ✅ The feature's permission set opens exactly the controller, flow, and page the feature uses -->
<classAccesses><apexClass>InvoiceController</apexClass><enabled>true</enabled></classAccesses>
<flowAccesses><enabled>true</enabled><flow>Invoice_Approval</flow></flowAccesses>
<pageAccesses><apexPage>InvoicePdf</apexPage><enabled>true</enabled></pageAccesses>
```

### Read muting permission sets inverted

A muting permission set exists only inside a permission set group (one per group, listed in `<mutingPermissionSets>`) and removes permissions from that group's members; in its file, `true` means muted.

```xml
<!-- ✅ mutingpermissionsets/Billing_Team_Muted.mutingpermissionset-meta.xml:
     allowDelete true here takes Delete on Invoice__c away from the Billing Team group -->
<objectPermissions>
    <allowCreate>false</allowCreate>
    <allowDelete>true</allowDelete>
    <allowEdit>false</allowEdit>
    <allowRead>false</allowRead>
    <modifyAllRecords>false</modifyAllRecords>
    <object>Invoice__c</object>
    <viewAllRecords>false</viewAllRecords>
</objectPermissions>
```

### Send guest user profile changes to security review

A site's guest user profile serves anonymous internet users, so an added object permission, field permission, or class access there exposes data to anyone. The platform already caps guests (the limits are in [Security Model](platform.md#security-model)); a diff that works around them, or adds access at all, needs a security sign-off.

```xml
<!-- ❌ The guest user profile gains the invoice controller and invoice amounts -->
<classAccesses><apexClass>InvoiceController</apexClass><enabled>true</enabled></classAccesses>
<fieldPermissions><editable>false</editable><field>Invoice__c.Amount__c</field><readable>true</readable></fieldPermissions>

<!-- ✅ Public pages get a narrow with-sharing controller that returns only what the page shows, after sign-off -->
<classAccesses><apexClass>PublicInvoiceStatusController</apexClass><enabled>true</enabled></classAccesses>
```

---

## Sharing Configuration

Sharing decides which records users see; the CRUD and FLS layers above decide what they can do with them.

### Treat org-wide default changes as data exposure events

`sharingModel` (internal users) and `externalSharingModel` (external users, never more open than internal) set the baseline for every record of the object: `Private`, `Read`, `ReadWrite`, `ReadWriteTransfer`, `FullAccess`, `ControlledByParent`, and a few object-specific values. Loosening exposes every record at once, tightening breaks users and integrations that relied on access, and either starts an org-wide sharing recalculation that can run long on large objects: ask when and how it rolls out.

```xml
<!-- ❌ objects/Invoice__c/Invoice__c.object-meta.xml: every internal user can now read and edit every invoice -->
<externalSharingModel>Private</externalSharingModel>
<sharingModel>ReadWrite</sharingModel>

<!-- ✅ Private baseline; the teams that need invoices get them through a sharing rule -->
<externalSharingModel>Private</externalSharingModel>
<sharingModel>Private</sharingModel>
```

### Check who a sharing rule, group, or role change reaches

Sharing rules only widen access, so read `sharedTo` and `accessLevel` first. `allInternalUsers`, `allPartnerUsers`, and `roleAndSubordinates` (which includes portal roles below it, unlike `roleAndSubordinatesInternal`) reach far, `Edit` lets them change records, and `sharingGuestRules` give anonymous users Read. `doesIncludeBosses` (Grant Access Using Hierarchies) on a public group, or on a queue at API 67.0+, also shares with everyone above the members in the role hierarchy, and a changed `parentRole` moves a whole branch under new managers, who then see its records.

```xml
<!-- ❌ Every internal user can edit every approved invoice -->
<sharingCriteriaRules>
    <fullName>Approved_Invoices_All</fullName>
    <accessLevel>Edit</accessLevel>
    <label>Approved Invoices All</label>
    <sharedTo><allInternalUsers></allInternalUsers></sharedTo>
    <criteriaItems><field>Status__c</field><operation>equals</operation><value>Approved</value></criteriaItems>
</sharingCriteriaRules>

<!-- ✅ Read only, for the finance roles that review them, internal users only -->
<sharingCriteriaRules>
    <fullName>Approved_Invoices_Finance</fullName>
    <accessLevel>Read</accessLevel>
    <label>Approved Invoices Finance</label>
    <sharedTo><roleAndSubordinatesInternal>Finance_Manager</roleAndSubordinatesInternal></sharedTo>
    <criteriaItems><field>Status__c</field><operation>equals</operation><value>Approved</value></criteriaItems>
</sharingCriteriaRules>

<!-- ✅ groups/Invoice_Reviewers.group-meta.xml: the group is the whole audience, not its members' managers too -->
<doesIncludeBosses>false</doesIncludeBosses>
```

### Don't count on restriction or scoping rules to limit system-mode code

A restriction rule (`enforcementType` `Restrict`) narrows the records matching users can access, while a scoping rule (`Scoping`) only sets the records they see by default. User-mode access honors them (`WITH USER_MODE` supports both), so code that runs in system mode is not held to them; and a `userCriteria` that compares `$User.UserRoleId` or `$User.ProfileId` with a literal Id works in one org only.

```xml
<!-- ❌ <userCriteria>$User.UserRoleId = '00E000000000000AAA'</userCriteria>: a role Id from one org -->

<!-- ✅ restrictionRules/Invoices_You_Own.rule-meta.xml -->
<RestrictionRule xmlns="http://soap.sforce.com/2006/04/metadata">
    <active>true</active>
    <description>Users see only the invoices they own. System-mode Apex is not restricted by this rule.</description>
    <enforcementType>Restrict</enforcementType>
    <masterLabel>Invoices You Own</masterLabel>
    <recordFilter>OwnerId = $User.Id</recordFilter>
    <targetEntity>Invoice__c</targetEntity>
    <userCriteria>$User.IsActive = true</userCriteria>
    <version>1</version>
</RestrictionRule>
```

### Keep sharing reasons in step with Apex managed sharing

A sharing reason (`objects/<Object>/sharingReasons/*.sharingReason-meta.xml`, custom objects only) is the `RowCause` of Apex managed sharing ([Data Access Security](apex.md#data-access-security)). Deleting it deletes every share that uses it, so a removed reason revokes access across the org.

```xml
<!-- ❌ The same file listed in destructiveChanges: every Reviewer__c share row is deleted with it -->

<!-- ✅ objects/Invoice__c/sharingReasons/Reviewer__c.sharingReason-meta.xml,
     used in Apex as Schema.Invoice__Share.RowCause.Reviewer__c -->
<SharingReason xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Reviewer__c</fullName>
    <label>Reviewer</label>
</SharingReason>
```

---

## Objects & Fields

Schema is a contract with every consumer of the org's data: Apex, flows, formulas, reports, integrations, and LWC imports (`@salesforce/schema`).

### Treat API names as contracts

The Metadata API has no rename: a new `fullName` in source deploys a new, empty field next to the old one, and removing the old one is a destructive change ([Deployment Impact](#deployment-impact)).

```text
❌ objects/Invoice__c/fields/Tier__c.field-meta.xml renamed to Customer_Tier__c.field-meta.xml
   The deployment adds an empty Customer_Tier__c; Tier__c, its data, and every reference to it remain

✅ Keep the API name and change the <label>, or add the new field, migrate the data, move every
   reference, and delete the old field in a later release
```

### Don't narrow types, lengths, or precision without a data plan

Shrinking `length`, `precision`, or `scale`, or changing `type`, can truncate or drop existing values and break writers that send longer ones. Ask the author for the production data check (longest value, largest number) before approving.

```xml
<!-- ❌ objects/Invoice__c/fields/External_Reference__c.field-meta.xml: 255 down to 40 -->
<length>40</length>
<type>Text</type>

<!-- ✅ Keep <length>255</length> until production data is shown to fit, or add a new field and migrate -->
```

### Roll out required and unique fields in steps

`<required>true</required>` makes every writer (integrations, data loads, Apex tests, flows that create records) supply a value, and saving an existing record that is still blank can then fail; `<unique>true</unique>` fails while existing values repeat. Add the field as optional, backfill it, then tighten it in a later release, or enforce it with a validation rule that has a bypass ([Validation Rules](#validation-rules)).

```xml
<!-- ❌ Required and unique from day one on an object that integrations write -->
<required>true</required>
<unique>true</unique>

<!-- ✅ Release 1: optional external Id, backfilled; release 2: required and unique -->
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
<referenceTo>Account</referenceTo>
<relationshipName>Invoices</relationshipName>
<type>Lookup</type>
```

### Weigh the cost of formula and roll-up summary fields

Formula fields are computed when read, so filters on them usually can't use an index ([Selectivity & Large Data Volumes](soql-sosl.md#selectivity--large-data-volumes)). A roll-up summary updates the parent on every child change, which locks the parent and contends when many children share one parent, and creating or changing one recalculates every parent.

```text
❌ A new roll-up summary on Account counting Invoice__c, where some accounts hold tens of thousands of invoices:
   every invoice save updates and locks the account, and bulk loads start failing on locks

✅ Ask for the data distribution first; for skewed parents keep the total out of the save path
   (a scheduled flow or a Queueable), and keep formula fields out of filters on large objects
```

### Keep picklists restricted and value API names stable

`<restricted>true</restricted>` rejects values outside the set, including from the API; a field on a global value set (`<valueSetName>`) is always restricted and changes only through the global value set. Code and automation compare a value's `fullName`, so change its `label` instead, and deactivate (`isActive` false) values that records still hold instead of deleting them.

```xml
<!-- ✅ objects/Invoice__c/fields/Status__c.field-meta.xml -->
<valueSet>
    <restricted>true</restricted>
    <valueSetDefinition>
        <sorted>false</sorted>
        <value><fullName>Approved</fullName><default>false</default><label>Approved for Payment</label></value>
        <value><fullName>On_Hold</fullName><default>false</default><isActive>false</isActive><label>On Hold (retired)</label></value>
    </valueSetDefinition>
</valueSet>
```

### Document sensitive fields and check encryption and history settings

`encryptionScheme` (Shield Platform Encryption) changes what queries can do with a field (probabilistic encryption can't be filtered or sorted; deterministic allows exact-match filters), `trackHistory` needs `enableHistory` on the object, and `securityClassification`, `complianceGroup`, `description`, and `inlineHelpText` tell admins and users what the field holds.

```xml
<!-- ✅ objects/Invoice__c/fields/Bank_Account__c.field-meta.xml -->
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Bank_Account__c</fullName>
    <complianceGroup>PII</complianceGroup>
    <description>Payout account for refunds. Written by the payments integration only.</description>
    <encryptionScheme>CaseSensitiveDeterministicEncryption</encryptionScheme>
    <inlineHelpText>Filled in by the payments system; contact Billing to change it.</inlineHelpText>
    <label>Bank Account</label>
    <length>34</length>
    <securityClassification>Restricted</securityClassification>
    <type>Text</type>
</CustomField>
```

---

## Validation Rules

Validation rules run on every save, from the UI, the API, Apex, flows, and data loads, so a new rule can stop an integration mid-sync. They run after before-save flows and Apex before triggers (so either can set the field a rule checks) and don't run again after a workflow field update ([Order of Execution](apex-triggers.md#order-of-execution)).

### Make rules bypassable, change-aware, and blank-safe

Put the bypass in a custom permission (`$Permission.Bypass_Validation_Rules`) assigned through the integration or migration permission set, never in profile names or usernames. A rule that checks only current values fails every later edit of old records that never met it, so limit it to new records and real changes with `ISNEW()` and `ISCHANGED()` (or `PRIORVALUE()` where the transition matters), and test blanks with `ISBLANK()`.

```text
❌ AND($Profile.Name <> "Integration User", ISPICKVAL(Status__c, "Closed"), Closed_Reason__c = "")
   Profile-name bypass, and every edit of an old closed invoice without a reason fails, even a phone fix

✅ AND(
       NOT($Permission.Bypass_Validation_Rules),
       OR(ISNEW(), ISCHANGED(Status__c)),
       ISPICKVAL(Status__c, "Closed"),
       ISBLANK(Closed_Reason__c)
   )
```

### Put the error on the field with actionable text

`errorDisplayField` shows the message next to the field (at the top of the page when the field isn't on the layout), and `errorMessage` (255 characters at most) should say what to do, because users read it on screen and integrations log it verbatim. Translate it through the Translation Workbench (`objectTranslations`).

```xml
<!-- ❌ <errorMessage>Invalid data</errorMessage> with no errorDisplayField -->

<!-- ✅ objects/Invoice__c/validationRules/Closed_Requires_Reason.validationRule-meta.xml -->
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Closed_Requires_Reason</fullName>
    <active>true</active>
    <description>Closed invoices need a reason. Bypass: Bypass_Validation_Rules custom permission.</description>
    <errorConditionFormula>AND(NOT($Permission.Bypass_Validation_Rules), OR(ISNEW(), ISCHANGED(Status__c)), ISPICKVAL(Status__c, &quot;Closed&quot;), ISBLANK(Closed_Reason__c))</errorConditionFormula>
    <errorDisplayField>Closed_Reason__c</errorDisplayField>
    <errorMessage>Enter a closed reason before you close the invoice.</errorMessage>
</ValidationRule>
```

---

## Integration Endpoints & Credentials

Endpoints and credentials decide where data can go and as whom; the Apex side of callouts is in [Callouts & Integrations](apex.md#callouts--integrations).

### Use Named Credentials backed by External Credentials

A Named Credential holds the endpoint, and an External Credential holds the authentication protocol and principals; users reach a principal only through a permission set's `externalCredentialPrincipalAccesses` (`<ExternalCredential>-<Principal>`). Legacy named credentials (`namedCredentialType` `Legacy`, with `endpoint`, `principalType`, `protocol`) are deprecated; new ones use `SecuredEndpoint`. Callouts through a Named Credential need no Remote Site Setting.

```xml
<!-- ❌ A legacy named credential (<namedCredentialType>Legacy</namedCredentialType>, <protocol>Password</protocol>)
     with <username> and <password> in the file -->

<!-- ✅ namedCredentials/Billing_API.namedCredential-meta.xml: the endpoint plus a reference to the External Credential -->
<NamedCredential xmlns="http://soap.sforce.com/2006/04/metadata">
    <allowMergeFieldsInBody>false</allowMergeFieldsInBody>
    <allowMergeFieldsInHeader>false</allowMergeFieldsInHeader>
    <calloutStatus>Enabled</calloutStatus>
    <generateAuthorizationHeader>true</generateAuthorizationHeader>
    <label>Billing API</label>
    <namedCredentialParameters><parameterName>Url</parameterName><parameterType>Url</parameterType><parameterValue>https://billing.example.com</parameterValue></namedCredentialParameters>
    <namedCredentialParameters><externalCredential>Billing_OAuth</externalCredential><parameterName>ExternalCredential</parameterName><parameterType>Authentication</parameterType></namedCredentialParameters>
    <namedCredentialType>SecuredEndpoint</namedCredentialType>
</NamedCredential>

<!-- ✅ permissionsets/Billing_Integration.permissionset-meta.xml: only holders of this set use the principal -->
<externalCredentialPrincipalAccesses>
    <enabled>true</enabled>
    <externalCredentialPrincipal>Billing_OAuth-Integration</externalCredentialPrincipal>
</externalCredentialPrincipalAccesses>
```

### Keep secrets out of the repository

Anything in source control is in every clone and every deployment. Secrets belong in the org (a principal's authentication parameters, set per org and referenced through `$Credential` formulas), never in these places:

| Where | Element or file |
|---|---|
| Legacy named credentials | `password`, `oauthToken`, `awsAccessSecret` |
| Connected apps, auth providers | `consumerSecret`; a retrieve never returns a connected app's secret, so one in the file was added by hand |
| External client apps | `*.ecaGlblOauth-meta.xml` (global OAuth settings with the consumer key and secret), which Salesforce says must not be added to source control |
| External Credentials | A literal token in `parameterValue` |
| Configuration | Custom Metadata values, Custom Labels, custom settings, static resources, flow and Apex literals |

```bash
# Read-only: secret-bearing elements and files added on this branch
git diff origin/main...HEAD | grep -nE '^\+.*<(password|consumerSecret|oauthToken|awsAccessSecret)>'
git diff --name-only --diff-filter=A origin/main...HEAD -- '*.ecaGlblOauth-meta.xml'
```

### Keep Remote Sites, CSP Trusted Sites, and CORS origins exact

Each of these allowlists a host. On a Remote Site Setting, `disableProtocolSecurity` true lets code pass data from an HTTPS session to an HTTP one: keep it false and the URL on `https://` (or use a Named Credential, which needs no Remote Site). On a CSP Trusted Site, each `isApplicableTo...Src` flag opens one Content Security Policy directive for `endpointUrl` (wildcards such as `*.example.com` are allowed) in a `context` (`All`, `LEX`, `Communities`, `VisualForce`, ...): enable only what the component needs, for one host ([Security in the Browser](lwc.md#security-in-the-browser)). A CORS `urlPattern` must be HTTPS and may put `*` in front of the second-level domain, which admits every subdomain, including ones someone else may control: list exact origins.

```xml
<!-- ❌ <url>http://billing.example.com</url> with <disableProtocolSecurity>true</disableProtocolSecurity>;
     a CSP Trusted Site for https://*.example.com with every flag true in context All;
     <urlPattern>https://*.example.com</urlPattern> -->

<!-- ✅ remoteSiteSettings/Exchange_Rates.remoteSite-meta.xml: a legacy callout not yet on a Named Credential -->
<RemoteSiteSetting xmlns="http://soap.sforce.com/2006/04/metadata">
    <description>Exchange-rate feed read by CurrencyRateClient</description>
    <disableProtocolSecurity>false</disableProtocolSecurity>
    <isActive>true</isActive>
    <url>https://rates.example.com</url>
</RemoteSiteSetting>

<!-- ✅ cspTrustedSites/Map_Tiles.cspTrustedSite-meta.xml: images from one host, in Lightning Experience only -->
<CspTrustedSite xmlns="http://soap.sforce.com/2006/04/metadata">
    <context>LEX</context>
    <description>Map tiles for the invoiceMap LWC</description>
    <endpointUrl>https://tiles.example.com</endpointUrl>
    <isActive>true</isActive>
    <isApplicableToConnectSrc>false</isApplicableToConnectSrc>
    <isApplicableToFontSrc>false</isApplicableToFontSrc>
    <isApplicableToFrameSrc>false</isApplicableToFrameSrc>
    <isApplicableToImgSrc>true</isApplicableToImgSrc>
    <isApplicableToMediaSrc>false</isApplicableToMediaSrc>
    <isApplicableToStyleSrc>false</isApplicableToStyleSrc>
</CspTrustedSite>

<!-- ✅ corsWhitelistOrigins/Customer_Portal.corsWhitelistOrigin-meta.xml -->
<CorsWhitelistOrigin xmlns="http://soap.sforce.com/2006/04/metadata">
    <urlPattern>https://portal.example.com</urlPattern>
</CorsWhitelistOrigin>
```

### Review connected apps and external client apps like login configuration

New connected apps can't be created since Spring '26 (package installs aside), so a new `*.connectedApp-meta.xml` won't deploy; ask for an External Client App (`externalClientApps/*.eca-meta.xml` with its `.ecaOauth` settings and `.ecaOauthPlcy` policies). For both, check the scopes (`Full`, `Api`, and `RefreshToken` are broad), who may use the app (admin-approved and pre-authorized, not self-authorized), IP relaxation, refresh-token lifetime, the callback URL, and any client-credentials execution user (`oauthClientCredentialUser`, `clientCredentialsFlowUser`).

```xml
<!-- ❌ An existing connected app widened: full scope, anyone self-authorizes, org IP ranges bypassed, tokens never expire -->
<oauthConfig><callbackUrl>http://localhost:8080/callback</callbackUrl><isAdminApproved>false</isAdminApproved><scopes>Full</scopes><scopes>RefreshToken</scopes></oauthConfig>
<oauthPolicy><ipRelaxation>BYPASS</ipRelaxation><refreshTokenPolicy>infinite</refreshTokenPolicy></oauthPolicy>

<!-- ✅ extlClntAppOauthPolicies/Billing_Portal.ecaOauthPlcy-meta.xml: pre-authorized users, org IP rules, expiring tokens -->
<ExtlClntAppOauthConfigurablePolicies xmlns="http://soap.sforce.com/2006/04/metadata">
    <externalClientApplication>Billing_Portal</externalClientApplication>
    <ipRelaxationPolicyType>Enforce</ipRelaxationPolicyType>
    <label>Billing Portal OAuth Policies</label>
    <permittedUsersPolicyType>AdminApprovedPreAuthorized</permittedUsersPolicyType>
    <refreshTokenPolicyType>SpecificInactivity</refreshTokenPolicyType>
    <refreshTokenValidityPeriod>30</refreshTokenValidityPeriod>
    <refreshTokenValidityUnit>Days</refreshTokenValidityUnit>
</ExtlClntAppOauthConfigurablePolicies>
```

### Send auth provider and SSO changes to security review

An auth provider's registration handler (`registrationHandler`, an `Auth.RegistrationHandler` class, or a flow) creates and updates users as `executionUser`, who must have Manage Users, so a bug there can create users or change their access. Treat `AuthProvider` and `SamlSsoConfig` changes as changes to who can log in, and as whom.

```xml
<!-- ❌ authproviders/Partner_Idp.authprovider-meta.xml: the secret in source and an admin running the handler -->
<consumerSecret>example-secret</consumerSecret>
<executionUser>admin@example.com</executionUser>
<registrationHandler>PartnerRegistrationHandler</registrationHandler>

<!-- ✅ No secret in the file (set in each org), a dedicated system user as executionUser, and a handler
     whose user and permission mapping has tests and a security review -->
<executionUser>partner-idp-handler@example.com</executionUser>
<registrationHandler>PartnerRegistrationHandler</registrationHandler>
```

---

## Configuration Metadata

Pick the store by who changes the value and whether it deploys with the source; reading these values from code is in [Org-Agnostic Code](platform.md#org-agnostic-code), and from flows in [Org-Agnostic Values](flows.md#org-agnostic-values).

| Value | Store | Deploys with source | Notes |
|---|---|---|---|
| Business rules, mappings, feature flags, thresholds | Custom metadata type (`__mdt`; records in `customMetadata/*.md-meta.xml`) | Yes | Readable from Apex without spending SOQL queries; Get Records in flows |
| User-facing text | Custom Labels (`labels/CustomLabels.labels-meta.xml`) | Yes | Translatable; not for configuration or secrets |
| Per-user or per-profile switches changed at runtime | Hierarchy custom settings (`customSettingsType` `Hierarchy`) | The definition only; values are data | Set per org; `$Setup` in formulas and flows |
| Endpoints and credentials | Named and External Credentials | Endpoints yes; secrets no | [Integration Endpoints & Credentials](#integration-endpoints--credentials) |

### Keep deployable configuration in custom metadata types

Custom metadata records deploy, version, and test like code, so a threshold or mapping changes in a reviewed PR; Custom Labels are for text users read. Record values sit in the repository in clear text: `protected` and `visibility` limit access from packaged code and subscriber orgs, not who can read the repo.

```xml
<!-- ❌ labels/CustomLabels.labels-meta.xml: a <labels> entry Invoice_Review_Threshold whose <value> is 10000 -->

<!-- ✅ customMetadata/Invoice_Setting.Default.md-meta.xml -->
<CustomMetadata xmlns="http://soap.sforce.com/2006/04/metadata" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
    <label>Default</label>
    <protected>false</protected>
    <values>
        <field>Review_Threshold__c</field>
        <value xsi:type="xsd:double">10000.0</value>
    </values>
</CustomMetadata>
```

### Use hierarchy custom settings for runtime switches, not for configuration that should deploy

A custom setting's definition deploys, but its values are records that each org sets by hand, so thresholds or endpoints kept there drift between orgs. Keep hierarchy settings for switches an admin flips per user, profile, or org at runtime, such as pausing an integration.

```xml
<!-- ❌ A list custom setting holding per-environment endpoints: the values never deploy, so every org differs -->

<!-- ✅ objects/Invoice_Switches__c/Invoice_Switches__c.object-meta.xml: a runtime switch, set per org -->
<customSettingsType>Hierarchy</customSettingsType>
<label>Invoice Switches</label>
<visibility>Public</visibility>
```

### Set platform event publish behavior explicitly

`publishBehavior` decides when subscribers see an event published from Apex or Flow: `PublishAfterCommit` only after the transaction commits, `PublishImmediately` at once, even if the transaction rolls back. Without the element the event publishes immediately. Business events usually need `PublishAfterCommit`, and logging events `PublishImmediately` ([Callouts & Integrations](apex.md#callouts--integrations)).

```xml
<!-- ❌ No <publishBehavior>: subscribers can act on approvals that later rolled back -->

<!-- ✅ objects/Invoice_Approved__e/Invoice_Approved__e.object-meta.xml -->
<deploymentStatus>Deployed</deploymentStatus>
<eventType>HighVolume</eventType>
<label>Invoice Approved</label>
<pluralLabel>Invoices Approved</pluralLabel>
<publishBehavior>PublishAfterCommit</publishBehavior>
```

---

## Deployment Impact

Manifests and project files decide what the pipeline deploys, deletes, and tests. Read them as code, and ask the author or CI for the deployment plan and results instead of running anything against an org ([Static Review Only](platform.md#static-review-only)). A deployment resolves dependencies among the components it contains, so a field, the permission sets that grant it, and the Apex and flows that use it belong in one deployment; split across pull requests, the dependent part fails in every org that doesn't have the field yet.

### Treat destructive changes as irreversible

`destructiveChangesPre.xml` deletes components before the rest of the deployment and `destructiveChangesPost.xml` after it; a component still referenced elsewhere fails to delete, so remove the references in the same deployment and delete post. Deleting a field or object deletes its data, and redeploying it later creates an empty one: ask for the export or migration plan. The reverse also holds: deleting a file from the repository deletes nothing in the org (source tracking in scratch orgs and sandboxes aside), so a removed flow or class stays active until a destructive manifest or a deactivation removes it.

```xml
<!-- ❌ The same entry in destructiveChangesPre.xml while InvoiceService.cls still reads the field: the deployment fails.
     ❌ A PR that only deletes flows/Invoice_Legacy_Sync.flow-meta.xml: the flow keeps running in production -->

<!-- ✅ destructiveChangesPost.xml: deleted after this deployment removes the last Apex and flow references -->
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>Invoice__c.Legacy_Code__c</members>
        <name>CustomField</name>
    </types>
    <version>67.0</version>
</Package>
```

### Review package.xml and .forceignore changes as scope changes

A manifest lists what a deployment or retrieve covers: a removed `<types>` block or member stops deploying it, `*` covers all components of most types (dependent types such as validation rules need dot-qualified names), and `<version>` sets the API version of the operation. A new `.forceignore` pattern silently stops deploying and retrieving every matching file.

```xml
<!-- ❌ Removing the ValidationRule block, or adding **/validationRules/** to .forceignore: rule changes stop
     deploying and nothing fails -->

<!-- ✅ manifest/package.xml -->
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>*</members>
        <name>ApexClass</name>
    </types>
    <types>
        <members>Invoice__c.Closed_Requires_Reason</members>
        <name>ValidationRule</name>
    </types>
    <version>67.0</version>
</Package>
```

### Review sfdx-project.json changes, and inject per-environment values

`sourceApiVersion` is the API version the source format uses for deploy and retrieve (each file's `<apiVersion>` still sets its runtime, see [API Versions](platform.md#api-versions)); `packageDirectories` decide what deploys, and in which package; `namespace` and package dependencies change how names resolve; `sourceBehaviorOptions` changes file layout ([Reading Metadata Diffs](#reading-metadata-diffs)). Hosts, usernames, and emails differ per org (a sandbox username ends in the sandbox name), so inject them at deploy time with `replacements` instead of committing one org's values.

```json
{
  "packageDirectories": [{ "path": "force-app", "default": true }],
  "sourceApiVersion": "67.0",
  "sourceBehaviorOptions": ["decomposePermissionSetBeta2"],
  "replacements": [
    {
      "glob": "force-app/main/default/namedCredentials/*.namedCredential-meta.xml",
      "stringToReplace": "https://billing.sandbox.example.com",
      "replaceWithEnv": "BILLING_API_URL"
    }
  ]
}
```

### Know the test level and the coverage gates

Ask the author or CI which test level the production deployment uses and for its results; coverage is org-side evidence, not something to compute in review ([Testing](apex.md#testing)).

| Gate | Rule |
|---|---|
| Apex in production | At least 75% org-wide coverage, every trigger covered by at least one line, all tests pass |
| Flows deployed as active | Apex tests cover at least 75% of active autolaunched flows and processes ([Activation, Versions & Deployment](flows.md#activation-versions--deployment)) |
| Test levels | `NoTestRun`, `RunSpecifiedTests`, `RunLocalTests`, `RunAllTestsInOrg`; `RunRelevantTests` is Beta (Spring '26) |

---

## Other Metadata Worth a Glance

These types rarely carry code, but a one-line change can expose data or weaken a site.

### Check dashboards that run as a specified user

With `dashboardType` `SpecifiedUser`, every viewer sees data as `runningUser`, whatever their own access, and when that username doesn't exist in the target org the deployment sets the deploying user (often an admin) as the running user. Prefer `LoggedInUser` for dashboards with sensitive data.

```xml
<!-- ❌ dashboards/Finance/Invoice_Overview.dashboard-meta.xml: everyone who opens it sees the admin's data -->
<dashboardType>SpecifiedUser</dashboardType>
<runningUser>admin@example.com</runningUser>

<!-- ✅ Each viewer sees their own data -->
<dashboardType>LoggedInUser</dashboardType>
```

### Glance at email templates, Lightning pages, static resources, and sites

| Type | Look for |
|---|---|
| Email templates (`email/**/*.email-meta.xml`) | Merge fields that put record data in front of recipients who shouldn't see it; `visualforce` templates run Visualforce markup and its controllers |
| Lightning pages (`flexipages/*.flexipage-meta.xml`) | A `visibilityRule` only hides a component and restricts no data: don't accept it as access control |
| Static resources (`staticresources/*.resource-meta.xml`) | The vendor library's name, version, and license; `cacheControl` `Public` lets third-party caches keep the file, so nothing sensitive |
| Sites and Experience Cloud (`sites/*.site-meta.xml`, `networks/*.network-meta.xml`) | `siteGuestRecordDefaultOwner`; `clickjackProtectionLevel` (`AllowAllFraming` means no protection); `selfRegistration` and `selfRegProfile`; `enableGuestFileAccess`, `enableGuestMemberVisibility`; the guest user profile ([Send guest user profile changes to security review](#send-guest-user-profile-changes-to-security-review)) |

---

## Review Checklist

### Permissions
- [ ] Permission set diffs were read as replacements (every removed block is an intended revocation) and profile diffs as overlays
- [ ] New grants live in permission sets and groups, not profiles; high-risk permissions and object View All, Modify All, and View All Fields have a named owner and reason
- [ ] Every new field ships with `fieldPermissions` in the intended permission sets
- [ ] `classAccesses`, `pageAccesses`, and `flowAccesses` match the feature; muting permission sets were read with `true` meaning muted
- [ ] Guest and portal profile changes have security sign-off

### Sharing
- [ ] Org-wide default changes (`sharingModel`, `externalSharingModel`) have a rollout and recalculation plan
- [ ] Sharing rules grant the narrowest audience and access level; guest sharing rules are intended
- [ ] `doesIncludeBosses`, role hierarchy moves, and restriction or scoping rules were checked for reach; no literal Ids in `userCriteria`
- [ ] A removed sharing reason is intended, with its shares

### Schema
- [ ] No API-name renames; no narrowing of type, length, or precision without a data plan
- [ ] New required or unique fields roll out in steps; delete behavior and master-detail consequences are deliberate
- [ ] Picklists stay restricted with stable value API names; roll-ups and formula filters were considered at volume
- [ ] Sensitive fields carry classification, encryption, and help text where needed

### Validation rules
- [ ] Every new rule has a custom-permission bypass and fires only on new records or real changes
- [ ] Errors sit on the field with actionable text
- [ ] The rule's place in the save order was checked against before-save flows and before triggers

### Endpoints & credentials
- [ ] Callouts use Named Credentials backed by External Credentials; principal access goes through permission sets
- [ ] No secrets in metadata or source (`password`, `consumerSecret`, `.ecaGlblOauth-meta.xml`, literal tokens, labels, custom metadata, static resources)
- [ ] Remote Sites use HTTPS with protocol security on; CSP Trusted Sites and CORS origins are exact and minimal
- [ ] No new connected apps; external client apps and auth providers use least scopes, pre-authorized users, and enforced IP rules

### Deployment
- [ ] Destructive changes have a data plan and delete after references are gone; deleted files have a matching destructive entry or deactivation
- [ ] `package.xml`, `.forceignore`, and `sfdx-project.json` changes were reviewed for what stops or starts deploying
- [ ] Dependent components deploy together; per-environment values come from replacements or credentials
- [ ] The production test level and coverage results were requested from the author or CI

---

## References

- [PermissionSet (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_permissionset.htm)
- [Profile (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_profile.htm)
- [Special Behavior in Metadata API Deployments](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_special_behavior.htm)
- [CustomObject (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/customobject.htm)
- [CustomField (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/customfield.htm)
- [ValidationRule (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_validationformulas.htm)
- [SharingRules (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_sharingrules.htm)
- [NamedCredential (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_namedcredential.htm)
- [ExternalCredential (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_externalcredential.htm)
- [RemoteSiteSetting (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_remotesitesetting.htm)
- [CspTrustedSite (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_csptrustedsite.htm)
- [CorsWhitelistOrigin (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_corswhitelistorigin.htm)
- [ConnectedApp (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_connectedapp.htm)
- [ExternalClientApplication (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_externalclientapplication.htm)
- [Deleting Components from an Organization (Metadata API Developer Guide)](https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/meta_deploy_deleting_files.htm)
- [Salesforce DX Project Configuration (sfdx-project.json)](https://developer.salesforce.com/docs/atlas.en-us.sfdx_dev.meta/sfdx_dev/sfdx_dev_ws_config.htm)
- [Exclude Source When Syncing or Converting (.forceignore)](https://developer.salesforce.com/docs/atlas.en-us.sfdx_dev.meta/sfdx_dev/sfdx_dev_exclude_source.htm)
- [sfdx-project.json schema (GitHub, forcedotcom/schemas)](https://github.com/forcedotcom/schemas/blob/main/sfdx-project.schema.json)
- [Guest User Sharing and Access Policies (Salesforce Help)](https://help.salesforce.com/s/articleView?language=en_US&id=platform.networks_guest_policies_timelines.htm&type=5)
- [Mute Permissions in Permission Set Groups (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.perm_set_groups_create_mute.htm&language=en_US&type=5)
- [Create Apex Sharing Reasons (Salesforce Help)](https://help.salesforce.com/s/articleView?id=platform.security_apex_sharing_reasons.htm&language=en_US&type=5)
- [Retirement of permissions on profiles cancelled (Salesforce Help 003834041)](https://help.salesforce.com/s/articleView?id=003834041&language=en_US&type=1)
- [New connected apps restricted (Salesforce Help 005228017)](https://help.salesforce.com/s/articleView?id=005228017&language=en_US&type=1)
- [Write Simplified and Secure Apex with Spring '23 Updates (Salesforce Developers Blog)](https://developer.salesforce.com/blogs/2023/05/write-simplified-and-secure-apex-with-spring-23-updates)
