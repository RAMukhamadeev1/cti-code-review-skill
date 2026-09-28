#!/usr/bin/env python3
"""Tests for pr-analyzer.py (stdlib unittest, no extra deps)."""

import contextlib
import importlib.util
import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# The script has a hyphen in its name, so load it by path.
_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(_HERE, 'pr-analyzer.py')
_spec = importlib.util.spec_from_file_location('pr_analyzer', SCRIPT)
pr_analyzer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr_analyzer)

# Convenient aliases
FileStats = pr_analyzer.FileStats
RISK_NO_TESTS = pr_analyzer.RISK_NO_TESTS
RISK_APEX_NO_TESTS = pr_analyzer.RISK_APEX_NO_TESTS

# Default Salesforce DX package directory
SF = 'force-app/main/default/'

GUIDE_PLATFORM = 'reference/salesforce/platform.md'
GUIDE_APEX = 'reference/salesforce/apex.md'
GUIDE_TRIGGERS = 'reference/salesforce/apex-triggers.md'
GUIDE_SOQL = 'reference/salesforce/soql-sosl.md'
GUIDE_LWC = 'reference/salesforce/lwc.md'
GUIDE_AURA = 'reference/salesforce/aura.md'
GUIDE_VISUALFORCE = 'reference/salesforce/visualforce.md'
GUIDE_FLOWS = 'reference/salesforce/flows.md'
GUIDE_METADATA = 'reference/salesforce/metadata.md'
GUIDE_JAVASCRIPT = 'reference/javascript.md'
GUIDE_TYPESCRIPT = 'reference/typescript.md'
GUIDE_NODEJS = 'reference/nodejs.md'
GUIDE_NESTJS = 'reference/nestjs.md'
GUIDE_PYTHON = 'reference/python.md'


def make_file(filename, additions=10, deletions=0, change_type='modified'):
    """Build FileStats the way parse_diff does (detected language/test/config)."""
    return FileStats(
        filename=filename,
        additions=additions,
        deletions=deletions,
        is_test=pr_analyzer.is_test_file(filename),
        is_config=pr_analyzer.is_config_file(filename),
        language=pr_analyzer.detect_language(filename),
        change_type=change_type,
    )


def has_risk_code(risks, code):
    """True when a risk line starts with the code (the analyzer's format)."""
    return any(r.startswith(code + ':') for r in risks)


# ═══════════════════════════════════════════════════════════════
# parse_diff — filename extraction (existing tests)
# ═══════════════════════════════════════════════════════════════

class ParseDiffFilenameTest(unittest.TestCase):
    def test_lib_prefixed_path(self):
        # "lib/" embeds a literal "b/" that the old regex swallowed.
        diff = (
            "diff --git a/lib/foo.py b/lib/foo.py\n"
            "index 1234567..89abcde 100644\n"
            "--- a/lib/foo.py\n"
            "+++ b/lib/foo.py\n"
            "@@ -1,2 +1,3 @@\n"
            " unchanged\n"
            "+added line\n"
            "-removed line\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, 'lib/foo.py')
        self.assertEqual(files[0].additions, 1)
        self.assertEqual(files[0].deletions, 1)

    def test_normal_path(self):
        diff = (
            "diff --git a/src/main.py b/src/main.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -0,0 +1 @@\n"
            "+print('hi')\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, 'src/main.py')

    def test_other_embedded_b_slash_prefixes(self):
        # web/ and db/ also contain a literal "b/".
        diff = (
            "diff --git a/web/x.js b/web/x.js\n"
            "+++ b/web/x.js\n"
            "+console.log(1)\n"
            "diff --git a/db/y.sql b/db/y.sql\n"
            "+++ b/db/y.sql\n"
            "+SELECT 1;\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual([f.filename for f in files], ['web/x.js', 'db/y.sql'])

    def test_rename_falls_back_to_b_side(self):
        diff = (
            "diff --git a/old/name.py b/new/name.py\n"
            "similarity index 100%\n"
            "rename from old/name.py\n"
            "rename to new/name.py\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, 'new/name.py')

    def test_rename_to_a_longer_path_uses_b_side(self):
        # The new path starts with the old one, so the backreference must
        # match the whole b/ side, not a prefix of it.
        for old, new in (('README', 'README.md'), ('src/app.py', 'src/app.py.bak')):
            with self.subTest(new=new):
                diff = (
                    f"diff --git a/{old} b/{new}\n"
                    "similarity index 90%\n"
                    f"rename from {old}\n"
                    f"rename to {new}\n"
                )
                files = pr_analyzer.parse_diff(diff)
                self.assertEqual([f.filename for f in files], [new])
                self.assertEqual(files[0].change_type, 'renamed')

    def test_quoted_paths_are_decoded(self):
        # With the default core.quotePath, git C-quotes non-ASCII paths and
        # writes their UTF-8 bytes as octal escapes.
        quoted = SF + 'layouts/Account-Kontakt\\303\\274bersicht.layout-meta.xml'
        diff = (
            f'diff --git "a/{quoted}" "b/{quoted}"\n'
            "index 1111111..2222222 100644\n"
            f'--- "a/{quoted}"\n'
            f'+++ "b/{quoted}"\n'
            "@@ -1 +1 @@\n"
            "-    <label>Alt</label>\n"
            "+    <label>Neu</label>\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename,
                         SF + 'layouts/Account-Kontaktübersicht.layout-meta.xml')
        self.assertEqual(files[0].language, 'Salesforce Metadata')
        self.assertEqual((files[0].additions, files[0].deletions), (1, 1))

    def test_rename_with_one_quoted_side(self):
        cases = (
            # ASCII -> non-ASCII: only the b/ side is quoted
            ('diff --git a/docs/cafe.md "b/docs/caf\\303\\251.md"', 'docs/café.md'),
            # non-ASCII -> ASCII: only the a/ side is quoted
            ('diff --git "a/docs/caf\\303\\251.md" b/docs/cafe.md', 'docs/cafe.md'),
            # A quoted path with an escaped quote and backslash
            ('diff --git "a/say \\"hi\\".md" "b/say \\\\ \\"hi\\".md"', 'say \\ "hi".md'),
        )
        for header, expected in cases:
            with self.subTest(header=header):
                files = pr_analyzer.parse_diff(header + "\nsimilarity index 100%\n")
                self.assertEqual([f.filename for f in files], [expected])

    def test_crlf_line_endings(self):
        diff = (
            "diff --git a/lib/foo.py b/lib/foo.py\r\n"
            "--- a/lib/foo.py\r\n"
            "+++ b/lib/foo.py\r\n"
            "@@ -1 +1 @@\r\n"
            "-x = 1\r\n"
            "+x = 2\r\n"
            "diff --git a/old/name.py b/new/name.py\r\n"
            "rename from old/name.py\r\n"
            "rename to new/name.py\r\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual([f.filename for f in files], ['lib/foo.py', 'new/name.py'])
        self.assertEqual([f.language for f in files], ['Python', 'Python'])
        self.assertEqual([f.change_type for f in files], ['modified', 'renamed'])
        self.assertEqual((files[0].additions, files[0].deletions), (1, 1))

    def test_unparsable_header_skips_the_file(self):
        # A header without a b/ path (e.g. from diff.noprefix) names no file.
        # Its lines are dropped instead of being added to the previous file.
        for header in ('diff --git', 'diff --git app.py app.py', 'diff --git "a/x" "b/"'):
            with self.subTest(header=header):
                diff = (
                    "diff --git a/src/app.py b/src/app.py\n"
                    "@@ -1 +1 @@\n"
                    "-a = 1\n"
                    "+a = 2\n"
                    f"{header}\n"
                    "@@ -1 +1,2 @@\n"
                    "+b = 1\n"
                    "+b = 2\n"
                    "diff --git a/src/util.py b/src/util.py\n"
                    "@@ -1 +1 @@\n"
                    "+c = 1\n"
                )
                files = pr_analyzer.parse_diff(diff)
                self.assertEqual([(f.filename, f.additions, f.deletions) for f in files],
                                 [('src/app.py', 1, 1), ('src/util.py', 1, 0)])


class UnquoteCStyleTest(unittest.TestCase):
    def test_escapes(self):
        cases = {
            '"caf\\303\\251.md"': 'café.md',  # octal UTF-8 bytes
            '"say \\"hi\\".md"': 'say "hi".md',
            '"back\\\\slash.md"': 'back\\slash.md',
            '"tab\\there.md"': 'tab\there.md',
            '"\\a\\b\\f\\n\\r\\v"': '\a\b\f\n\r\v',
            '"plain.md"': 'plain.md',
            '""': '',
        }
        for quoted, expected in cases.items():
            with self.subTest(quoted=quoted):
                self.assertEqual(pr_analyzer._unquote_c_style(quoted), expected)

    def test_malformed_input_does_not_raise(self):
        # A byte that is not valid UTF-8 becomes U+FFFD; \777 is not a byte
        self.assertEqual(pr_analyzer._unquote_c_style('"x\\377.md"'), 'x�.md')
        self.assertEqual(pr_analyzer._unquote_c_style('"x\\777"'), 'x777')


# ═══════════════════════════════════════════════════════════════
# parse_diff — change type and apiVersion
# ═══════════════════════════════════════════════════════════════

class ParseDiffHeaderTest(unittest.TestCase):
    def test_new_file_is_added(self):
        diff = (
            "diff --git a/src/new.py b/src/new.py\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/src/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+import os\n"
            "+print(os.name)\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(files[0].change_type, 'added')
        self.assertEqual((files[0].additions, files[0].deletions), (2, 0))

    def test_deleted_file_is_deleted(self):
        diff = (
            "diff --git a/src/old.py b/src/old.py\n"
            "deleted file mode 100644\n"
            "index 1111111..0000000\n"
            "--- a/src/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-import os\n"
            "-print(os.name)\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(files[0].change_type, 'deleted')
        self.assertEqual((files[0].additions, files[0].deletions), (0, 2))

    def test_rename_is_renamed(self):
        diff = (
            "diff --git a/old/name.py b/new/name.py\n"
            "similarity index 90%\n"
            "rename from old/name.py\n"
            "rename to new/name.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/old/name.py\n"
            "+++ b/new/name.py\n"
            "@@ -1 +1 @@\n"
            "-x = 1\n"
            "+x = 2\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(files[0].filename, 'new/name.py')
        self.assertEqual(files[0].change_type, 'renamed')
        self.assertEqual((files[0].additions, files[0].deletions), (1, 1))

    def test_copy_is_added(self):
        diff = (
            "diff --git a/objects/Account/fields/Tier__c.field-meta.xml "
            "b/objects/Account/fields/Level__c.field-meta.xml\n"
            "similarity index 95%\n"
            "copy from objects/Account/fields/Tier__c.field-meta.xml\n"
            "copy to objects/Account/fields/Level__c.field-meta.xml\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(files[0].filename, 'objects/Account/fields/Level__c.field-meta.xml')
        self.assertEqual(files[0].change_type, 'added')

    def test_change_type_is_tracked_per_file(self):
        diff = (
            "diff --git a/src/new.py b/src/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new.py\n"
            "@@ -0,0 +1 @@\n"
            "+x = 1\n"
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-y = 1\n"
            "+y = 2\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual([f.change_type for f in files], ['added', 'modified'])
        self.assertIsNone(files[1].api_version_before)
        self.assertIsNone(files[1].api_version_after)

    def test_marker_like_lines_inside_hunk_are_counted(self):
        # Removing "---" and adding "+++" front matter shows up as "----"
        # and "++++" lines; inside a hunk they are content, not headers.
        diff = (
            "diff --git a/docs/guide.md b/docs/guide.md\n"
            "index 1111111..2222222 100644\n"
            "--- a/docs/guide.md\n"
            "+++ b/docs/guide.md\n"
            "@@ -1,3 +1,3 @@\n"
            "----\n"
            "-title: Guide\n"
            "----\n"
            "++++\n"
            "+title = 'Guide'\n"
            "++++\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual((files[0].additions, files[0].deletions), (3, 3))

    def test_api_version_captured_for_class_meta(self):
        path = SF + 'classes/AccountService.cls-meta.xml'
        diff = (
            f"diff --git a/{path} b/{path}\n"
            "index 1111111..2222222 100644\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,5 +1,5 @@\n"
            ' <?xml version="1.0" encoding="UTF-8"?>\n'
            ' <ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">\n'
            "-    <apiVersion>66.0</apiVersion>\n"
            "+    <apiVersion>67.0</apiVersion>\n"
            "     <status>Active</status>\n"
            " </ApexClass>\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(files[0].api_version_before, 66.0)
        self.assertEqual(files[0].api_version_after, 67.0)
        self.assertEqual((files[0].additions, files[0].deletions), (1, 1))

    def test_api_version_captured_for_new_trigger_meta(self):
        path = SF + 'triggers/AccountTrigger.trigger-meta.xml'
        diff = (
            f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{path}\n"
            "@@ -0,0 +1,5 @@\n"
            '+<?xml version="1.0" encoding="UTF-8"?>\n'
            '+<ApexTrigger xmlns="http://soap.sforce.com/2006/04/metadata">\n'
            "+    <apiVersion>67.0</apiVersion>\n"
            "+    <status>Active</status>\n"
            "+</ApexTrigger>\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(files[0].change_type, 'added')
        self.assertIsNone(files[0].api_version_before)
        self.assertEqual(files[0].api_version_after, 67.0)
        self.assertEqual(files[0].additions, 5)

    def test_api_version_ignored_for_other_files(self):
        path = SF + 'flows/Account_Update.flow-meta.xml'
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,2 +1,2 @@\n"
            "-    <apiVersion>60.0</apiVersion>\n"
            "+    <apiVersion>67.0</apiVersion>\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertIsNone(files[0].api_version_before)
        self.assertIsNone(files[0].api_version_after)
        self.assertEqual((files[0].additions, files[0].deletions), (1, 1))

    def test_text_before_the_first_file_is_ignored(self):
        # git show and git format-patch put the commit message first
        diff = (
            "commit 0123456789abcdef0123456789abcdef01234567\n"
            "Author: Dev <dev@example.com>\n"
            "\n"
            "    Fix totals\n"
            "-not a diff line\n"
            "+not a diff line\n"
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-a = 1\n"
            "+a = 2\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual([(f.filename, f.additions, f.deletions) for f in files],
                         [('src/app.py', 1, 1)])

    def test_no_newline_marker_is_not_counted(self):
        diff = (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-a = 1\n"
            "\\ No newline at end of file\n"
            "+a = 2\n"
            "\\ No newline at end of file\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual((files[0].additions, files[0].deletions), (1, 1))

    def test_binary_and_mode_only_changes(self):
        diff = (
            "diff --git a/assets/logo.png b/assets/logo.png\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "Binary files /dev/null and b/assets/logo.png differ\n"
            "diff --git a/scripts/run.sh b/scripts/run.sh\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        files = pr_analyzer.parse_diff(diff)
        self.assertEqual(
            [(f.filename, f.change_type, f.additions, f.deletions) for f in files],
            [('assets/logo.png', 'added', 0, 0), ('scripts/run.sh', 'modified', 0, 0)])


# ═══════════════════════════════════════════════════════════════
# detect_language
# ═══════════════════════════════════════════════════════════════

class DetectLanguageTest(unittest.TestCase):
    def test_common_extensions(self):
        cases = {
            'app.py': 'Python',
            'index.ts': 'TypeScript',
            'server.js': 'JavaScript',
            'app.tsx': 'TypeScript',
            'Button.jsx': 'JavaScript',
            'loader.mjs': 'JavaScript',
            'babel.cjs': 'JavaScript',
            'worker.mts': 'TypeScript',
            'legacy.cts': 'TypeScript',
            'style.css': 'CSS',
            'query.sql': 'SQL',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(pr_analyzer.detect_language(filename), expected)

    def test_data_and_markup_extensions(self):
        cases = {
            'README.md': 'Markdown',
            'data/users.json': 'JSON',
            'openapi.yaml': 'YAML',
            '.github/workflows/ci.yml': 'YAML',
            'pyproject.toml': 'TOML',
            'styles/theme.scss': 'SCSS',
            'styles/theme.less': 'Less',
            'public/index.html': 'HTML',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(pr_analyzer.detect_language(filename), expected)

    def test_extension_case_is_ignored(self):
        cases = {
            'LEGACY.PY': 'Python',
            'src/App.TSX': 'TypeScript',
            SF + 'classes/Legacy.CLS': 'Apex',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(pr_analyzer.detect_language(filename), expected)

    def test_unknown_extension(self):
        self.assertEqual(pr_analyzer.detect_language('data.xyz'), 'unknown')
        self.assertEqual(pr_analyzer.detect_language('Makefile'), 'unknown')

    def test_removed_languages_are_unknown(self):
        for filename in ('main.rs', 'handler.go', 'App.java', 'file.cpp', 'lib.zig',
                         'mix.exs', 'Main.kt', 'View.swift', 'App.vue', 'Page.svelte'):
            with self.subTest(filename=filename):
                self.assertEqual(pr_analyzer.detect_language(filename), 'unknown')


# ═══════════════════════════════════════════════════════════════
# detect_language — Salesforce DX
# ═══════════════════════════════════════════════════════════════

class DetectSalesforceLanguageTest(unittest.TestCase):
    def assertLanguages(self, cases):
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(pr_analyzer.detect_language(filename), expected)

    def test_labels_are_module_constants(self):
        labels = {
            pr_analyzer.LANG_APEX: 'Apex',
            pr_analyzer.LANG_LWC: 'LWC',
            pr_analyzer.LANG_AURA: 'Aura',
            pr_analyzer.LANG_VISUALFORCE: 'Visualforce',
            pr_analyzer.LANG_FLOW: 'Salesforce Flow',
            pr_analyzer.LANG_SF_METADATA: 'Salesforce Metadata',
            pr_analyzer.LANG_SOQL: 'SOQL',
        }
        for constant, expected in labels.items():
            self.assertEqual(constant, expected)
        self.assertEqual(set(pr_analyzer.SALESFORCE_LANGUAGES), set(labels))

    def test_apex_sources(self):
        self.assertLanguages({
            SF + 'classes/AccountService.cls': 'Apex',
            SF + 'triggers/AccountTrigger.trigger': 'Apex',
            'scripts/apex/hello.apex': 'Apex',
            # '.cls' is also a LaTeX class file; the collision is accepted.
            'tex/thesis.cls': 'Apex',
        })

    def test_code_meta_companions_take_source_label(self):
        self.assertLanguages({
            SF + 'classes/AccountService.cls-meta.xml': 'Apex',
            SF + 'triggers/AccountTrigger.trigger-meta.xml': 'Apex',
            SF + 'pages/AccountPage.page-meta.xml': 'Visualforce',
            SF + 'components/AccountHeader.component-meta.xml': 'Visualforce',
            SF + 'flows/Account_Update.flow-meta.xml': 'Salesforce Flow',
            SF + 'flowDefinitions/Account_Update.flowDefinition-meta.xml': 'Salesforce Flow',
        })

    def test_visualforce_sources(self):
        self.assertLanguages({
            SF + 'pages/AccountPage.page': 'Visualforce',
            SF + 'components/AccountHeader.component': 'Visualforce',
        })

    def test_lwc_bundle_files(self):
        bundle = SF + 'lwc/accountList/'
        for name in ('accountList.js', 'accountList.ts', 'accountList.html',
                     'accountList.css', 'accountList.svg', 'accountList.js-meta.xml',
                     'utils.js', '__tests__/accountList.test.js',
                     '__tests__/data/getRecord.json'):
            with self.subTest(name=name):
                self.assertEqual(pr_analyzer.detect_language(bundle + name), 'LWC')

    def test_aura_bundle_files(self):
        bundle = SF + 'aura/AccountCard/'
        cases = {bundle + name: 'Aura' for name in (
            'AccountCard.cmp', 'AccountCardController.js', 'AccountCardHelper.js',
            'AccountCardRenderer.js', 'AccountCard.css', 'AccountCard.design',
            'AccountCard.auradoc', 'AccountCard.svg', 'AccountCard.cmp-meta.xml',
        )}
        cases.update({
            SF + 'aura/SalesApp/SalesApp.app': 'Aura',
            SF + 'aura/RecordSaved/RecordSaved.evt': 'Aura',
            SF + 'aura/Selectable/Selectable.intf': 'Aura',
            SF + 'aura/brandTokens/brandTokens.tokens': 'Aura',
        })
        self.assertLanguages(cases)

    def test_aura_markup_outside_bundle(self):
        self.assertLanguages({
            'markup/AccountCard.cmp': 'Aura',
            'markup/RecordSaved.evt': 'Aura',
            'markup/Selectable.intf': 'Aura',
            # Too generic to claim outside an aura/ bundle
            'markup/Sales.app': 'unknown',
            'markup/AccountCard.design': 'unknown',
            'markup/brand.tokens': 'unknown',
        })

    def test_metadata_source_format(self):
        cases = {SF + path: 'Salesforce Metadata' for path in (
            'objects/Account/Account.object-meta.xml',
            'objects/Account/fields/Tier__c.field-meta.xml',
            'objects/Account/validationRules/Tier_Required.validationRule-meta.xml',
            'objects/Account/recordTypes/Partner.recordType-meta.xml',
            'permissionsets/Sales.permissionset-meta.xml',
            'permissionsetgroups/Sales.permissionsetgroup-meta.xml',
            'profiles/Admin.profile-meta.xml',
            'labels/CustomLabels.labels-meta.xml',
            'layouts/Account-Account Layout.layout-meta.xml',
            'customMetadata/Feature_Flag.Checkout.md-meta.xml',
            'namedCredentials/Billing.namedCredential-meta.xml',
            'remoteSiteSettings/Billing.remoteSite-meta.xml',
            'staticresources/chart.resource-meta.xml',
            'applications/Sales.app-meta.xml',
        )}
        self.assertLanguages(cases)

    def test_manifests(self):
        self.assertLanguages({
            'manifest/package.xml': 'Salesforce Metadata',
            'src/package.xml': 'Salesforce Metadata',
            'destructiveChanges.xml': 'Salesforce Metadata',
            'manifest/destructiveChangesPre.xml': 'Salesforce Metadata',
            'deploy/destructiveChangesPost.xml': 'Salesforce Metadata',
        })

    def test_mdapi_layout(self):
        cases = {'src/' + path: 'Salesforce Metadata' for path in (
            'objects/Account.object',
            'profiles/Admin.profile',
            'permissionsets/Sales.permissionset',
            'permissionsetgroups/Sales.permissionsetgroup',
            'sharingRules/Account.sharingRules',
            'namedCredentials/Billing.namedCredential',
            'remoteSiteSettings/Billing.remoteSite',
            'cspTrustedSites/Cdn.cspTrustedSite',
            'connectedApps/Portal.connectedApp',
            'layouts/Account-Account Layout.layout',
            'labels/CustomLabels.labels',
            'workflows/Case.workflow',
            'flexipages/Account_Record_Page.flexipage',
            'customPermissions/Bypass_Validation.customPermission',
            'customMetadata/Feature_Flag.Checkout.md',
            'settings/Account.settings',
            # Compared case-insensitively
            'SharingRules/Contact.SHARINGRULES',
        )}
        cases['src/flows/Account_Update.flow'] = 'Salesforce Flow'
        self.assertLanguages(cases)

    def test_mdapi_requires_directory_and_suffix_pair(self):
        self.assertLanguages({
            'src/objects/Account.profile': 'unknown',
            'src/profiles/Admin.object': 'unknown',
            'misc/Admin.profile': 'unknown',
            'src/customMetadata/notes.txt': 'unknown',
        })

    def test_soql_file(self):
        self.assertEqual(
            pr_analyzer.detect_language('scripts/soql/openOpportunities.soql'), 'SOQL')

    def test_look_alikes_not_misclassified(self):
        cases = {
            'app/settings/base.py': 'Python',
            'docs/README.md': 'Markdown',
            'ros_ws/src/pkg/package.xml': 'unknown',
            SF + 'staticresources/chart.js': 'JavaScript',
            SF + 'lwc/jsconfig.json': 'JSON',
            SF + 'lwc/.eslintrc.json': 'JSON',
            # Only bundle file types are claimed inside lwc/ and aura/ folders
            'aura/core/models.py': 'Python',
            'src/index.ts': 'TypeScript',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertIsNone(pr_analyzer.detect_salesforce_language(filename))
                self.assertEqual(pr_analyzer.detect_language(filename), expected)

    def test_backslash_paths(self):
        self.assertLanguages({
            'force-app\\main\\default\\lwc\\accountList\\accountList.js': 'LWC',
            'force-app\\main\\default\\classes\\AccountService.cls-meta.xml': 'Apex',
        })


# ═══════════════════════════════════════════════════════════════
# is_test_file
# ═══════════════════════════════════════════════════════════════

class IsTestFileTest(unittest.TestCase):
    def test_python_test_prefix(self):
        self.assertTrue(pr_analyzer.is_test_file('tests/test_handler.py'))
        self.assertTrue(pr_analyzer.is_test_file('test_utils.py'))

    def test_python_test_suffix(self):
        self.assertTrue(pr_analyzer.is_test_file('handler_test.py'))

    def test_generic_test_suffix_python(self):
        self.assertTrue(pr_analyzer.is_test_file('src/my_module_test.py'))
        self.assertTrue(pr_analyzer.is_test_file('parser_test.py'))

    def test_generic_test_suffix_js(self):
        self.assertTrue(pr_analyzer.is_test_file('handler_test.js'))
        self.assertTrue(pr_analyzer.is_test_file('pkg/auth_test.ts'))

    def test_js_ts_test_and_spec(self):
        self.assertTrue(pr_analyzer.is_test_file('handler.test.ts'))
        self.assertTrue(pr_analyzer.is_test_file('utils.spec.js'))
        self.assertTrue(pr_analyzer.is_test_file('App.test.tsx'))
        self.assertTrue(pr_analyzer.is_test_file('loader.test.mjs'))
        self.assertTrue(pr_analyzer.is_test_file('worker.spec.mts'))

    def test_tests_directory(self):
        self.assertTrue(pr_analyzer.is_test_file('tests/conftest.py'))
        self.assertTrue(pr_analyzer.is_test_file('test/helpers.js'))

    def test_dunder_tests_directory(self):
        self.assertTrue(pr_analyzer.is_test_file('__tests__/Button.test.tsx'))

    def test_spec_directory(self):
        self.assertTrue(pr_analyzer.is_test_file('spec/helpers.js'))
        self.assertTrue(pr_analyzer.is_test_file('client/spec/app.js'))
        # Anchored to a path segment
        self.assertFalse(pr_analyzer.is_test_file('respec/app.js'))

    def test_backslash_paths(self):
        self.assertTrue(pr_analyzer.is_test_file('tests\\test_app.py'))
        self.assertTrue(pr_analyzer.is_test_file(
            'force-app\\main\\default\\classes\\AccountServiceTest.cls'))
        self.assertFalse(pr_analyzer.is_test_file(
            'force-app\\main\\default\\classes\\AccountService.cls'))

    def test_non_test_files_rejected(self):
        self.assertFalse(pr_analyzer.is_test_file('classes/AccountController.cls'))
        self.assertFalse(pr_analyzer.is_test_file('classes/TestimonialService.cls'))
        self.assertFalse(pr_analyzer.is_test_file('src/utils.py'))
        self.assertFalse(pr_analyzer.is_test_file('lib/parser.js'))
        self.assertFalse(pr_analyzer.is_test_file('contest.py'))

    def test_test_substring_not_matched(self):
        """Files containing 'test_' as substring must NOT be flagged."""
        self.assertFalse(pr_analyzer.is_test_file('latest_report.py'))
        self.assertFalse(pr_analyzer.is_test_file('contest_utils.py'))
        self.assertFalse(pr_analyzer.is_test_file('src/latest_handler.py'))

    def test_apex_test_class_names(self):
        for name in ('AccountServiceTest', 'AccountService_Test', 'AccountServiceTests',
                     'Test_AccountService', 'TestAccountService', 'TestDataFactory',
                     'AccountTestDataFactory', 'Test_Utils'):
            with self.subTest(name=name):
                self.assertTrue(pr_analyzer.is_test_file(f'{SF}classes/{name}.cls'))
                self.assertTrue(pr_analyzer.is_test_file(f'{SF}classes/{name}.cls-meta.xml'))

    def test_apex_non_test_class_names(self):
        for name in ('AccountController', 'TestimonialService', 'Contest', 'LatestNews',
                     'AttestationHelper', 'ContestDataService', 'Testing'):
            with self.subTest(name=name):
                self.assertFalse(pr_analyzer.is_test_file(f'{SF}classes/{name}.cls'))
                self.assertFalse(pr_analyzer.is_test_file(f'{SF}classes/{name}.cls-meta.xml'))

    def test_lwc_jest_tests(self):
        bundle = SF + 'lwc/accountList/'
        self.assertTrue(pr_analyzer.is_test_file(bundle + '__tests__/accountList.test.js'))
        self.assertTrue(pr_analyzer.is_test_file(bundle + '__tests__/data/getRecord.json'))
        self.assertFalse(pr_analyzer.is_test_file(bundle + 'accountList.js'))


# ═══════════════════════════════════════════════════════════════
# is_config_file
# ═══════════════════════════════════════════════════════════════

class IsConfigFileTest(unittest.TestCase):
    def test_known_json_configs(self):
        self.assertTrue(pr_analyzer.is_config_file('package.json'))
        self.assertTrue(pr_analyzer.is_config_file('tsconfig.json'))
        self.assertTrue(pr_analyzer.is_config_file('.eslintrc.json'))

    def test_known_yaml_configs(self):
        self.assertTrue(pr_analyzer.is_config_file('docker-compose.yml'))
        self.assertTrue(pr_analyzer.is_config_file('.github/workflows/ci.yml'))
        self.assertTrue(pr_analyzer.is_config_file('.prettierrc.yml'))

    def test_known_toml_configs(self):
        self.assertTrue(pr_analyzer.is_config_file('pyproject.toml'))
        self.assertTrue(pr_analyzer.is_config_file('poetry.toml'))

    def test_env_files(self):
        self.assertTrue(pr_analyzer.is_config_file('.env'))
        self.assertTrue(pr_analyzer.is_config_file('.env.local'))
        self.assertTrue(pr_analyzer.is_config_file('.env.production'))

    def test_config_in_filename(self):
        self.assertTrue(pr_analyzer.is_config_file('app.config.ts'))
        self.assertTrue(pr_analyzer.is_config_file('database_config.yml'))

    def test_data_files_rejected(self):
        """Data files must NOT be flagged as config."""
        self.assertFalse(pr_analyzer.is_config_file('data.json'))
        self.assertFalse(pr_analyzer.is_config_file('openapi.yaml'))
        self.assertFalse(pr_analyzer.is_config_file('swagger.json'))
        self.assertFalse(pr_analyzer.is_config_file('fixtures/sample.yml'))
        self.assertFalse(pr_analyzer.is_config_file('translations.json'))
        self.assertFalse(pr_analyzer.is_config_file('schema.toml'))

    def test_config_directory(self):
        self.assertTrue(pr_analyzer.is_config_file('config/settings.yaml'))
        self.assertTrue(pr_analyzer.is_config_file('config/database.yml'))
        self.assertTrue(pr_analyzer.is_config_file('src/config/settings.json'))

    def test_source_files_rejected(self):
        self.assertFalse(pr_analyzer.is_config_file('src/index.ts'))
        self.assertFalse(pr_analyzer.is_config_file('lib/utils.py'))

    def test_removed_ecosystem_configs_not_known(self):
        for name in ('Cargo.toml', 'Cargo.lock', 'go.mod', 'go.sum', 'Gemfile',
                     'Gemfile.lock', 'composer.json', 'Podfile', 'Package.swift',
                     'build.gradle', 'settings.gradle.kts', 'CMakeLists.txt'):
            with self.subTest(name=name):
                self.assertFalse(pr_analyzer.is_config_file(name))
        self.assertTrue(pr_analyzer.is_config_file('Makefile'))

    def test_salesforce_project_configs(self):
        for path in ('sfdx-project.json', '.forceignore', 'manifest/package.xml',
                     'src/package.xml', 'destructiveChanges.xml',
                     'manifest/destructiveChangesPre.xml', 'destructiveChangesPost.xml',
                     '.sfdx/sfdx-config.json', '.sf/config.json',
                     'config/project-scratch-def.json'):
            with self.subTest(path=path):
                self.assertTrue(pr_analyzer.is_config_file(path))

    def test_salesforce_metadata_is_not_config(self):
        for path in ('permissionsets/Sales.permissionset-meta.xml',
                     'profiles/Admin.profile-meta.xml',
                     'objects/Account/fields/Tier__c.field-meta.xml',
                     'namedCredentials/Billing.namedCredential-meta.xml',
                     'classes/AccountService.cls',
                     'flows/Account_Update.flow-meta.xml'):
            with self.subTest(path=path):
                self.assertFalse(pr_analyzer.is_config_file(SF + path))

    def test_salesforce_code_in_config_folders_is_not_config(self):
        for path in ('lwc/config/config.js', 'aura/config/configController.js',
                     'classes/config/FeatureFlags.cls'):
            with self.subTest(path=path):
                self.assertFalse(pr_analyzer.is_config_file(SF + path))

    def test_lwc_tooling_configs_are_config(self):
        self.assertTrue(pr_analyzer.is_config_file(SF + 'lwc/jsconfig.json'))
        self.assertTrue(pr_analyzer.is_config_file(SF + 'lwc/.eslintrc.json'))
        self.assertTrue(pr_analyzer.is_config_file('jest.config.js'))

    def test_nested_package_xml_is_not_config(self):
        self.assertFalse(pr_analyzer.is_config_file('ros_ws/src/pkg/package.xml'))

    def test_editor_and_repository_configs(self):
        for path in ('.vscode/settings.json', '.idea/workspace.xml', '.gitignore',
                     '.gitattributes', 'Dockerfile', 'docker-compose.yaml', 'tox.ini',
                     'setup.cfg', 'package-lock.json'):
            with self.subTest(path=path):
                self.assertTrue(pr_analyzer.is_config_file(path))

    def test_backslash_paths(self):
        self.assertTrue(pr_analyzer.is_config_file('.github\\workflows\\ci.yml'))
        self.assertTrue(pr_analyzer.is_config_file('src\\config\\settings.json'))
        self.assertFalse(pr_analyzer.is_config_file(
            'force-app\\main\\default\\lwc\\config\\config.js'))


# ═══════════════════════════════════════════════════════════════
# Metadata types and lookup tables
# ═══════════════════════════════════════════════════════════════

class MetadataTypeTest(unittest.TestCase):
    def test_source_format_and_mdapi(self):
        cases = {
            SF + 'profiles/Admin.profile-meta.xml': 'profile',
            SF + 'objects/Account/fields/Tier__c.field-meta.xml': 'field',
            SF + 'namedCredentials/Billing.namedCredential-meta.xml': 'namedcredential',
            SF + 'classes/AccountService.cls-meta.xml': 'cls',
            'src/profiles/Admin.profile': 'profile',
            'src\\sharingRules\\Account.sharingRules': 'sharingrules',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(pr_analyzer._metadata_type(filename), expected)

    def test_non_metadata_is_none(self):
        for filename in ('src/app.py', SF + 'classes/AccountService.cls',
                         'manifest/package.xml', 'package-meta.xml', 'Admin.profile',
                         'src/objects/Account'):
            with self.subTest(filename=filename):
                self.assertIsNone(pr_analyzer._metadata_type(filename))


class LookupTableTest(unittest.TestCase):
    def test_tables_are_lowercase(self):
        # File names are lowercased before every lookup, so a mixed-case
        # entry would never match.
        tables = {
            '_SALESFORCE_EXTENSIONS': pr_analyzer._SALESFORCE_EXTENSIONS,
            '_SOURCE_TYPE_LANGUAGES': pr_analyzer._SOURCE_TYPE_LANGUAGES,
            '_MDAPI_SUFFIX_BY_DIRECTORY': pr_analyzer._MDAPI_SUFFIX_BY_DIRECTORY,
            '_MDAPI_SUFFIX_BY_DIRECTORY values':
                pr_analyzer._MDAPI_SUFFIX_BY_DIRECTORY.values(),
            '_LWC_BUNDLE_EXTENSIONS': pr_analyzer._LWC_BUNDLE_EXTENSIONS,
            '_AURA_BUNDLE_EXTENSIONS': pr_analyzer._AURA_BUNDLE_EXTENSIONS,
            '_ACCESS_CONTROL_TYPES': pr_analyzer._ACCESS_CONTROL_TYPES,
            '_INTEGRATION_TYPES': pr_analyzer._INTEGRATION_TYPES,
            '_SCHEMA_TYPES': pr_analyzer._SCHEMA_TYPES,
        }
        for name, entries in tables.items():
            with self.subTest(table=name):
                self.assertEqual([e for e in entries if e != e.lower()], [])

    def test_guide_order_lists_every_guide_once(self):
        # recommend_guides() filters through GUIDE_ORDER, so a guide missing
        # from it would never be recommended.
        guides = {value for key, value in vars(pr_analyzer).items()
                  if key.startswith('GUIDE_') and key != 'GUIDE_ORDER'}
        self.assertEqual(len(pr_analyzer.GUIDE_ORDER), len(set(pr_analyzer.GUIDE_ORDER)))
        self.assertEqual(set(pr_analyzer.GUIDE_ORDER), guides)


# ═══════════════════════════════════════════════════════════════
# calculate_complexity
# ═══════════════════════════════════════════════════════════════

class CalculateComplexityTest(unittest.TestCase):
    def test_empty_files(self):
        self.assertEqual(pr_analyzer.calculate_complexity([]), 0.0)

    def test_weighted_formula(self):
        # size 1000/1000 * 0.4 + files 2/20 * 0.2 + non-test 0.5 * 0.2
        # + languages 1/5 * 0.2 = 0.56
        files = [
            FileStats(filename='src/app.py', additions=400, deletions=100, language='Python'),
            FileStats(filename='tests/test_app.py', additions=500, language='Python',
                      is_test=True),
        ]
        self.assertEqual(pr_analyzer.calculate_complexity(files), 0.56)

    def test_factors_are_capped(self):
        # 2000 lines, 25 files, 6 languages, no tests: every factor at its maximum
        names = ['a.py', 'b.js', 'c.ts', 'd.sql', 'e.css', 'f.html']
        names += [f'g{i}.py' for i in range(19)]
        files = [make_file(name, 80, 0) for name in names]
        self.assertEqual(pr_analyzer.calculate_complexity(files), 1.0)

    def test_test_only_change_has_no_non_test_weight(self):
        # 1/1000 * 0.4 + 1/20 * 0.2 + 0.0 * 0.2 + 1/5 * 0.2 = 0.0504
        files = [make_file('tests/test_app.py', 1, 0)]
        self.assertEqual(pr_analyzer.calculate_complexity(files), 0.05)

    def test_file_factor_reaches_its_cap_at_20_files(self):
        # 20/1000 * 0.4 + 20/20 * 0.2 + 1.0 * 0.2 + 1/5 * 0.2 = 0.448
        files = [make_file(f'src/module_{i}.py', 1, 0) for i in range(20)]
        self.assertEqual(pr_analyzer.calculate_complexity(files), 0.45)

    def test_unknown_language_is_not_diversity(self):
        # 10/1000 * 0.4 + 2/20 * 0.2 + 1.0 * 0.2 + 1/5 * 0.2 = 0.264; counting
        # 'unknown' as a second language would give 0.30.
        files = [FileStats(filename='src/app.py', additions=10, language='Python'),
                 FileStats(filename='Makefile', language='unknown')]
        self.assertEqual(pr_analyzer.calculate_complexity(files), 0.26)

    def test_small_simple_change(self):
        files = [FileStats(filename='app.py', additions=5, deletions=2,
                           language='Python')]
        score = pr_analyzer.calculate_complexity(files)
        self.assertLess(score, 0.3)

    def test_large_multi_language_change(self):
        files = [
            FileStats(filename='app.py', additions=300, deletions=100, language='Python'),
            FileStats(filename='index.ts', additions=150, deletions=80, language='TypeScript'),
            FileStats(filename=SF + 'classes/AccountService.cls', additions=200,
                      deletions=50, language='Apex'),
            FileStats(filename=SF + 'lwc/accountList/accountList.js', additions=100,
                      deletions=30, language='LWC'),
            FileStats(filename='App.tsx', additions=50, deletions=20, language='TypeScript'),
        ]
        score = pr_analyzer.calculate_complexity(files)
        self.assertGreater(score, 0.5)

    def test_test_heavy_change_is_lower(self):
        """Changes with high test ratio should have lower complexity."""
        prod_files = [FileStats(filename='app.py', additions=100, deletions=50,
                                language='Python')]
        test_files = [
            FileStats(filename='app.py', additions=100, deletions=50,
                      language='Python'),
            FileStats(filename='tests/test_app.py', additions=100, deletions=0,
                      language='Python', is_test=True),
        ]
        score_prod = pr_analyzer.calculate_complexity(prod_files)
        score_test = pr_analyzer.calculate_complexity(test_files)
        self.assertLess(score_test, score_prod)

    def test_paired_code_meta_files_not_counted(self):
        classes = [make_file(f'{SF}classes/Service{i}.cls', 20, 5) for i in range(10)]
        metas = [make_file(f'{SF}classes/Service{i}.cls-meta.xml', 0, 0) for i in range(10)]
        self.assertEqual(pr_analyzer.calculate_complexity(classes + metas),
                         pr_analyzer.calculate_complexity(classes))

    def test_unpaired_meta_files_counted(self):
        classes = [make_file(f'{SF}classes/Service{i}.cls', 20, 5) for i in range(10)]
        others = [make_file(f'{SF}classes/Other{i}.cls-meta.xml', 0, 0) for i in range(10)]
        self.assertGreater(pr_analyzer.calculate_complexity(classes + others),
                           pr_analyzer.calculate_complexity(classes))


# ═══════════════════════════════════════════════════════════════
# categorize_size and estimate_review_time
# ═══════════════════════════════════════════════════════════════

class CategorizeSizeTest(unittest.TestCase):
    def test_boundaries(self):
        cases = (
            (0, 'XS (Extra Small)'), (49, 'XS (Extra Small)'),
            (50, 'S (Small)'), (199, 'S (Small)'),
            (200, 'M (Medium)'), (399, 'M (Medium)'),
            (400, 'L (Large)'), (799, 'L (Large)'),
            (800, 'XL (Extra Large) - Consider splitting'),
            (10_000, 'XL (Extra Large) - Consider splitting'),
        )
        for total_changes, expected in cases:
            with self.subTest(total_changes=total_changes):
                self.assertEqual(pr_analyzer.categorize_size(total_changes), expected)


class EstimateReviewTimeTest(unittest.TestCase):
    def test_scales_with_size_and_complexity(self):
        files = [FileStats(filename='src/app.py', additions=300, deletions=100,
                           language='Python')]
        self.assertEqual(pr_analyzer.estimate_review_time(files, 0.0), 20)  # 400 / 20
        self.assertEqual(pr_analyzer.estimate_review_time(files, 0.5), 30)  # 20 * 1.5

    def test_fractional_minutes_are_truncated(self):
        files = [FileStats(filename='src/app.py', additions=219, language='Python')]
        self.assertEqual(pr_analyzer.estimate_review_time(files, 0.0), 10)  # 10.95

    def test_clamped_to_5_and_120_minutes(self):
        self.assertEqual(pr_analyzer.estimate_review_time([], 0.0), 5)
        small = [FileStats(filename='src/app.py', additions=40, language='Python')]
        self.assertEqual(pr_analyzer.estimate_review_time(small, 1.0), 5)  # 4
        huge = [FileStats(filename='src/app.py', additions=5000, language='Python')]
        self.assertEqual(pr_analyzer.estimate_review_time(huge, 1.0), 120)  # 500


# ═══════════════════════════════════════════════════════════════
# identify_risk_factors
# ═══════════════════════════════════════════════════════════════

class IdentifyRiskFactorsTest(unittest.TestCase):
    def test_large_pr_flagged(self):
        files = [FileStats(filename='big.py', additions=300, deletions=200,
                           language='Python')]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertTrue(any('Large PR' in r for r in risks))

    def test_no_tests_flagged(self):
        files = [FileStats(filename='app.py', additions=40, deletions=20,
                           language='Python')]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertTrue(any(pr_analyzer.RISK_NO_TESTS in r for r in risks))

    def test_with_tests_not_flagged(self):
        files = [
            FileStats(filename='app.py', additions=40, deletions=20,
                      language='Python'),
            FileStats(filename='tests/test_app.py', additions=30, deletions=0,
                      language='Python', is_test=True),
        ]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertFalse(any(pr_analyzer.RISK_NO_TESTS in r for r in risks))

    def test_security_sensitive_file(self):
        files = [FileStats(filename='src/auth/login.py', additions=10, deletions=5,
                           language='Python')]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertTrue(any('Security-sensitive' in r for r in risks))

    def test_database_migration(self):
        files = [FileStats(filename='migrations/001_init.sql', additions=20, deletions=0,
                           language='SQL')]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertTrue(any('Database' in r for r in risks))

    def test_soql_file_counts_as_database_change(self):
        files = [make_file('scripts/soql/openOpportunities.soql', 5, 0)]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertIn("Database changes detected - review carefully", risks)

    def test_test_substring_files_still_flag_no_tests(self):
        """Files like latest_report.py must not suppress NO_TEST_CHANGES."""
        files = [
            FileStats(filename='latest_report.py', additions=40, deletions=20,
                      language='Python'),
            FileStats(filename='contest_utils.py', additions=30, deletions=10,
                      language='Python'),
        ]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertTrue(any(pr_analyzer.RISK_NO_TESTS in r for r in risks))

    @staticmethod
    def risks_for(code_lines, test_lines=0):
        files = [FileStats(filename='src/app.py', additions=code_lines, language='Python')]
        if test_lines:
            files.append(FileStats(filename='tests/test_app.py', additions=test_lines,
                                   language='Python', is_test=True))
        return pr_analyzer.identify_risk_factors(files)

    def test_large_pr_threshold(self):
        self.assertFalse(any('Large PR' in r for r in self.risks_for(400)))
        self.assertIn("Large PR (>400 lines) - harder to review thoroughly",
                      self.risks_for(401))

    def test_no_tests_threshold(self):
        self.assertFalse(has_risk_code(self.risks_for(50), RISK_NO_TESTS))
        self.assertIn(f"{RISK_NO_TESTS}: No test changes - verify test coverage",
                      self.risks_for(51))

    def test_low_test_ratio_threshold(self):
        low_ratio = "Low test ratio (<20%) - consider adding more tests"
        cases = (
            (100, 0, False),  # not more than 100 lines
            (101, 0, True),
            (400, 100, False),  # exactly 20% tests
            (401, 100, True),
        )
        for code_lines, test_lines, flagged in cases:
            with self.subTest(code_lines=code_lines, test_lines=test_lines):
                self.assertEqual(low_ratio in self.risks_for(code_lines, test_lines), flagged)

    def test_security_sensitive_patterns(self):
        for filename in ('.env.production', 'src/oauth.py', 'security/policy.py',
                         'src/reset_password.py', 'src/TokenStore.ts', 'src/secret_manager.py'):
            with self.subTest(filename=filename):
                risks = pr_analyzer.identify_risk_factors([make_file(filename)])
                self.assertIn(f"Security-sensitive file: {filename}", risks)
        self.assertFalse(any('Security-sensitive' in r for r in
                             pr_analyzer.identify_risk_factors([make_file('src/app.py')])))

    def test_security_and_database_reported_once(self):
        files = [
            make_file('src/auth/login.py'),
            make_file('config/secrets.yml'),
            make_file('db/001_init.sql'),
            make_file('alembic/versions/002_users_migration.py'),
        ]
        risks = pr_analyzer.identify_risk_factors(files)
        self.assertEqual([r for r in risks if r.startswith('Security-sensitive')],
                         ["Security-sensitive file: src/auth/login.py"])
        self.assertEqual(risks.count("Database changes detected - review carefully"), 1)

    def test_migration_named_file_is_database_change(self):
        risks = pr_analyzer.identify_risk_factors(
            [make_file('alembic/versions/002_users_migration.py')])
        self.assertIn("Database changes detected - review carefully", risks)

    def test_config_file_count(self):
        files = [make_file('package.json'), make_file('tsconfig.json'), make_file('src/app.py')]
        self.assertIn("Configuration changes in 2 file(s)",
                      pr_analyzer.identify_risk_factors(files))

    def test_no_files_no_risks(self):
        self.assertEqual(pr_analyzer.identify_risk_factors([]), [])


class HasRiskTest(unittest.TestCase):
    def test_codes_match_as_whole_tokens(self):
        generic = [f"{RISK_NO_TESTS}: No test changes - verify test coverage"]
        apex = [f"{RISK_APEX_NO_TESTS}: 1 Apex class/trigger file(s) changed"]
        self.assertTrue(pr_analyzer._has_risk(generic, RISK_NO_TESTS))
        self.assertFalse(pr_analyzer._has_risk(generic, RISK_APEX_NO_TESTS))
        self.assertTrue(pr_analyzer._has_risk(apex, RISK_APEX_NO_TESTS))
        self.assertFalse(pr_analyzer._has_risk(apex, RISK_NO_TESTS))
        self.assertTrue(pr_analyzer._has_risk(generic + apex, RISK_NO_TESTS))
        self.assertFalse(pr_analyzer._has_risk([], RISK_NO_TESTS))
        self.assertFalse(pr_analyzer._has_risk(['NO_TEST_CHANGES_X', 'X_NO_TEST_CHANGES'],
                                               RISK_NO_TESTS))


# ═══════════════════════════════════════════════════════════════
# identify_risk_factors — Salesforce
# ═══════════════════════════════════════════════════════════════

class SalesforceRiskTest(unittest.TestCase):
    def risks(self, *files):
        return pr_analyzer.identify_risk_factors(list(files))

    def assertRiskContains(self, risks, text):
        self.assertTrue(any(text in r for r in risks), f"{text!r} not found in {risks}")

    def assertNoRiskContains(self, risks, text):
        self.assertFalse(any(text in r for r in risks), f"{text!r} found in {risks}")

    def test_access_control_metadata(self):
        risks = self.risks(
            make_file(SF + 'permissionsets/Sales.permissionset-meta.xml'),
            make_file(SF + 'profiles/Admin.profile-meta.xml'),
            make_file('src/sharingRules/Account.sharingRules'),
        )
        self.assertIn(
            "Salesforce access-control metadata changed (3 file(s): profiles/permission "
            "sets/sharing) - check least privilege and field-level security", risks)

    def test_decomposed_permission_set_and_sharing_rules(self):
        risks = self.risks(
            make_file(SF + 'permissionsets/Sales/objectSettings/Account.objectSettings-meta.xml'),
            make_file(SF + 'sharingRules/Account/sharingCriteriaRules/'
                           'Partner_Access.sharingCriteriaRule-meta.xml'),
        )
        self.assertRiskContains(risks, 'access-control metadata changed (2 file(s)')

    def test_integration_metadata(self):
        risks = self.risks(
            make_file(SF + 'namedCredentials/Billing.namedCredential-meta.xml'),
            make_file(SF + 'externalCredentials/Billing.externalCredential-meta.xml'),
            make_file(SF + 'remoteSiteSettings/Billing.remoteSite-meta.xml'),
            make_file(SF + 'cspTrustedSites/Cdn.cspTrustedSite-meta.xml'),
            make_file(SF + 'connectedApps/Portal.connectedApp-meta.xml'),
            make_file(SF + 'externalClientApps/Portal.eca-meta.xml'),
            make_file(SF + 'extlClntAppOauthSettings/Portal_oauth.ecaOauth-meta.xml'),
        )
        self.assertRiskContains(risks, 'integration/credential metadata changed (7 file(s)')
        self.assertRiskContains(risks, 'that no secrets are committed')

    def test_apex_without_apex_tests_flagged(self):
        risks = self.risks(
            make_file(SF + 'classes/AccountService.cls', 30, 5),
            make_file(SF + 'triggers/AccountTrigger.trigger', 5, 0),
        )
        apex_risks = [r for r in risks if r.startswith(RISK_APEX_NO_TESTS + ':')]
        self.assertEqual(len(apex_risks), 1)
        self.assertIn('2 Apex class/trigger file(s) changed without Apex test class changes',
                      apex_risks[0])
        self.assertIn('75% org-wide coverage and coverage for every trigger', apex_risks[0])

    def test_apex_with_apex_tests_not_flagged(self):
        risks = self.risks(
            make_file(SF + 'classes/AccountService.cls', 30, 5),
            make_file(SF + 'classes/AccountServiceTest.cls', 40, 0),
        )
        self.assertFalse(has_risk_code(risks, RISK_APEX_NO_TESTS))

    def test_jest_test_does_not_satisfy_apex_tests(self):
        risks = self.risks(
            make_file(SF + 'classes/AccountService.cls', 30, 5),
            make_file(SF + 'lwc/accountList/__tests__/accountList.test.js', 40, 0),
        )
        self.assertTrue(has_risk_code(risks, RISK_APEX_NO_TESTS))
        # The Jest test still counts for the generic check
        self.assertFalse(has_risk_code(risks, RISK_NO_TESTS))

    def test_meta_only_change_not_flagged(self):
        risks = self.risks(make_file(SF + 'classes/AccountService.cls-meta.xml', 1, 1))
        self.assertFalse(has_risk_code(risks, RISK_APEX_NO_TESTS))

    def test_deleted_apex_not_flagged_as_untested(self):
        risks = self.risks(
            make_file(SF + 'classes/LegacyService.cls', 0, 80, change_type='deleted'))
        self.assertFalse(has_risk_code(risks, RISK_APEX_NO_TESTS))

    def test_deleted_apex_test_does_not_satisfy_apex_tests(self):
        risks = self.risks(
            make_file(SF + 'classes/AccountService.cls', 30, 5),
            make_file(SF + 'classes/AccountServiceTest.cls', 0, 60, change_type='deleted'),
        )
        self.assertTrue(has_risk_code(risks, RISK_APEX_NO_TESTS))

    def test_trigger_changed(self):
        risks = self.risks(
            make_file(SF + 'triggers/AccountTrigger.trigger', 5, 1),
            make_file(SF + 'triggers/AccountTrigger.trigger-meta.xml', 1, 1),
        )
        self.assertIn(
            "Apex trigger changed (1 file(s)) - check one trigger per object, logic in a "
            "handler, 200-record bulk safety, and recursion guards", risks)

    def test_flow_changed(self):
        risks = self.risks(
            make_file(SF + 'flows/Account_Update.flow-meta.xml'),
            make_file(SF + 'flowDefinitions/Account_Update.flowDefinition-meta.xml'),
        )
        self.assertRiskContains(risks, 'Flow changed (2 file(s)) - check active status')

    def test_schema_changed(self):
        risks = self.risks(
            make_file(SF + 'objects/Invoice__c/Invoice__c.object-meta.xml'),
            make_file(SF + 'objects/Invoice__c/fields/Amount__c.field-meta.xml'),
            make_file(SF + 'objects/Invoice__c/validationRules/Amount_Positive.validationRule-meta.xml'),
            make_file(SF + 'objects/Invoice__c/recordTypes/Standard.recordType-meta.xml'),
            make_file(SF + 'globalValueSets/Region.globalValueSet-meta.xml'),
        )
        self.assertIn(
            "Salesforce schema changed (5 object/field/validation rule file(s)) - check "
            "data impact, integrations, and deploy order", risks)

    def test_new_field_without_access_control(self):
        risks = self.risks(
            make_file(SF + 'objects/Account/fields/Tier__c.field-meta.xml', 12, 0,
                      change_type='added'))
        self.assertIn(
            "1 new custom field(s) without permission set/profile changes - verify "
            "field-level security is granted", risks)

    def test_new_field_with_permission_set_not_flagged(self):
        risks = self.risks(
            make_file(SF + 'objects/Account/fields/Tier__c.field-meta.xml', 12, 0,
                      change_type='added'),
            make_file(SF + 'permissionsets/Sales.permissionset-meta.xml', 5, 0),
        )
        self.assertNoRiskContains(risks, 'new custom field')
        self.assertRiskContains(risks, 'access-control metadata changed (1 file(s)')

    def test_modified_field_not_counted_as_new(self):
        risks = self.risks(make_file(SF + 'objects/Account/fields/Tier__c.field-meta.xml', 1, 1))
        self.assertNoRiskContains(risks, 'new custom field')
        self.assertRiskContains(risks, 'Salesforce schema changed (1 ')

    def test_destructive_manifest(self):
        risks = self.risks(make_file('manifest/destructiveChanges.xml', 8, 0))
        self.assertIn(
            "Destructive changes manifest present - deletions are irreversible in the "
            "target org and can drop data", risks)

    def test_deleted_metadata(self):
        risks = self.risks(
            make_file(SF + 'classes/LegacyService.cls', 0, 80, change_type='deleted'),
            make_file(SF + 'classes/LegacyService.cls-meta.xml', 0, 5, change_type='deleted'),
            make_file(SF + 'objects/Account/fields/Legacy__c.field-meta.xml', 0, 12,
                      change_type='deleted'),
            # Not deployable metadata: scripts and Jest tests
            make_file('scripts/apex/cleanup.apex', 0, 4, change_type='deleted'),
            make_file('scripts/soql/legacy.soql', 0, 2, change_type='deleted'),
            make_file(SF + 'lwc/legacyList/__tests__/legacyList.test.js', 0, 20,
                      change_type='deleted'),
        )
        self.assertIn(
            "Salesforce metadata deleted from source (3 file(s)) - this does not delete it "
            "from orgs; deploying deletions needs destructiveChanges and may drop data", risks)
        # A deleted field is not a schema change to review, and not a new field
        self.assertNoRiskContains(risks, 'Salesforce schema changed')

    def test_api_version_raised_to_67_flagged(self):
        path = SF + 'classes/AccountService.cls-meta.xml'
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,3 +1,3 @@\n"
            "-    <apiVersion>66.0</apiVersion>\n"
            "+    <apiVersion>67.0</apiVersion>\n"
        )
        risks = pr_analyzer.identify_risk_factors(pr_analyzer.parse_diff(diff))
        self.assertIn(
            "Apex class apiVersion raised to 67.0+ on 1 file(s) - classes without a sharing "
            "keyword (and undeclared classes in their inheritance chain) become 'with sharing', "
            "database operations run in user mode, and WITH SECURITY_ENFORCED no longer "
            "compiles", risks)

    def test_trigger_api_version_raised_to_67_not_flagged(self):
        # Triggers run in system mode at every API version, so the bump changes nothing there.
        path = SF + 'triggers/AccountTrigger.trigger-meta.xml'
        diff = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,3 +1,3 @@\n"
            "-    <apiVersion>66.0</apiVersion>\n"
            "+    <apiVersion>67.0</apiVersion>\n"
        )
        risks = pr_analyzer.identify_risk_factors(pr_analyzer.parse_diff(diff))
        self.assertNoRiskContains(risks, 'apiVersion raised')

    def test_api_version_change_without_crossing_67_not_flagged(self):
        for before, after in ((67.0, 68.0), (None, 67.0), (60.0, 66.0), (67.0, 66.0)):
            with self.subTest(before=before, after=after):
                f = make_file(SF + 'classes/AccountService.cls-meta.xml', 1, 1)
                f.api_version_before = before
                f.api_version_after = after
                self.assertNoRiskContains(self.risks(f), 'apiVersion raised')

    def test_non_salesforce_pr_has_no_salesforce_risks(self):
        risks = self.risks(
            make_file('src/app.py', 300, 100),
            make_file('src/index.ts', 50, 10),
            make_file('package.json', 2, 1),
            make_file('db/migrations/001_init.sql', 20, 0),
        )
        self.assertTrue(risks)
        for marker in ('Salesforce', 'Apex', RISK_APEX_NO_TESTS, 'Flow changed',
                       'Destructive', 'custom field'):
            self.assertNoRiskContains(risks, marker)

    def test_every_access_control_file_type(self):
        for path in (
            SF + 'profiles/Admin.profile-meta.xml',
            SF + 'permissionsets/Sales.permissionset-meta.xml',
            SF + 'permissionsetgroups/Sales_Bundle.permissionsetgroup-meta.xml',
            SF + 'mutingpermissionsets/Sales_Mute.mutingpermissionset-meta.xml',
            SF + 'sharingRules/Account.sharingRules-meta.xml',
            SF + 'sharingRules/Account/sharingCriteriaRules/Partner.sharingCriteriaRule-meta.xml',
            SF + 'sharingRules/Account/sharingOwnerRules/Sales.sharingOwnerRule-meta.xml',
            SF + 'sharingRules/Account/sharingGuestRules/Guest.sharingGuestRule-meta.xml',
            SF + 'sharingRules/Account/sharingTerritoryRules/Emea.sharingTerritoryRule-meta.xml',
            SF + 'roles/CEO.role-meta.xml',
            SF + 'groups/Sales_Team.group-meta.xml',
            SF + 'sharingSets/Portal_Users.sharingSet-meta.xml',
            'src/roles/CEO.role',
            'src/groups/Sales_Team.group',
        ):
            with self.subTest(path=path):
                self.assertRiskContains(self.risks(make_file(path)),
                                        'access-control metadata changed (1 file(s)')

    def test_every_integration_file_type(self):
        paths = [SF + path for path in (
            'namedCredentials/Billing.namedCredential-meta.xml',
            'externalCredentials/Billing.externalCredential-meta.xml',
            'remoteSiteSettings/Billing.remoteSite-meta.xml',
            'cspTrustedSites/Cdn.cspTrustedSite-meta.xml',
            'connectedApps/Portal.connectedApp-meta.xml',
            'authproviders/Google.authprovider-meta.xml',
            'corsWhitelistOrigins/App.corsWhitelistOrigin-meta.xml',
            'samlssoconfigs/Okta.samlssoconfig-meta.xml',
        )]
        # External Client App settings are recognized by suffix
        paths += [f'{SF}externalClientApps/Portal.{suffix}-meta.xml' for suffix in (
            'eca', 'ecaOauth', 'ecaGlblOauth', 'ecaOauthPlcy', 'ecaOauthSecurity', 'ecaPlcy',
            'ecaCanvas', 'ecaMobile', 'ecaMobilePlcy', 'ecaNotifications', 'ecaPush',
            'ecaPushPlcy', 'ecaSamlPlcy',
        )]
        paths += ['src/namedCredentials/Billing.namedCredential',
                  'src/connectedApps/Portal.connectedApp']
        for path in paths:
            with self.subTest(path=path):
                self.assertRiskContains(self.risks(make_file(path)),
                                        'integration/credential metadata changed (1 file(s)')

    def test_standard_value_set_is_schema(self):
        risks = self.risks(make_file(SF + 'standardValueSets/Industry.standardValueSet-meta.xml'))
        self.assertRiskContains(risks, 'Salesforce schema changed (1 ')

    def test_deleted_access_control_reported_as_deletion_only(self):
        risks = self.risks(make_file(SF + 'permissionsets/Legacy.permissionset-meta.xml', 0, 30,
                                     change_type='deleted'))
        self.assertNoRiskContains(risks, 'access-control metadata changed')
        self.assertRiskContains(risks, 'Salesforce metadata deleted from source (1 file(s))')

    def test_deleted_manifests_are_not_flagged(self):
        risks = self.risks(
            make_file('manifest/package.xml', 0, 20, change_type='deleted'),
            make_file('manifest/destructiveChanges.xml', 0, 8, change_type='deleted'),
        )
        self.assertNoRiskContains(risks, 'Destructive changes manifest present')
        self.assertNoRiskContains(risks, 'metadata deleted from source')

    def test_salesforce_risk_order(self):
        class_meta = make_file(SF + 'classes/Billing.cls-meta.xml', 1, 1)
        class_meta.api_version_before, class_meta.api_version_after = 66.0, 67.0
        risks = self.risks(
            make_file(SF + 'permissionsets/Sales.permissionset-meta.xml'),
            make_file(SF + 'namedCredentials/Billing.namedCredential-meta.xml'),
            make_file(SF + 'classes/AccountService.cls'),
            make_file(SF + 'triggers/AccountTrigger.trigger'),
            make_file(SF + 'flows/Account_Update.flow-meta.xml'),
            make_file(SF + 'objects/Account/fields/Tier__c.field-meta.xml'),
            make_file('manifest/destructiveChanges.xml'),
            make_file(SF + 'classes/Legacy.cls', 0, 10, change_type='deleted'),
            class_meta,
        )
        # Generic risks come first, then the Salesforce ones in a fixed order
        prefixes = (
            RISK_NO_TESTS + ':',
            'Configuration changes in 1 file(s)',
            'Salesforce access-control metadata changed (1 file(s):',
            'Salesforce integration/credential metadata changed (1 file(s):',
            f'{RISK_APEX_NO_TESTS}: 2 Apex class/trigger file(s) changed',
            'Apex trigger changed (1 file(s))',
            'Flow changed (1 file(s))',
            'Salesforce schema changed (1 object/field/validation rule file(s))',
            'Destructive changes manifest present',
            'Salesforce metadata deleted from source (1 file(s))',
            'Apex class apiVersion raised to 67.0+ on 1 file(s)',
        )
        self.assertEqual(len(risks), len(prefixes), risks)
        for risk, prefix in zip(risks, prefixes):
            self.assertTrue(risk.startswith(prefix), (risk, prefix))

    def test_code_files_do_not_count_as_access_control(self):
        # Only metadata can be access control, so Apex next to a new field
        # still leaves the field's FLS unverified.
        risks = self.risks(
            make_file(SF + 'classes/AccountService.cls'),
            make_file(SF + 'classes/AccountServiceTest.cls'),
            make_file(SF + 'lwc/accountList/accountList.js'),
            make_file(SF + 'objects/Account/fields/Tier__c.field-meta.xml', change_type='added'),
        )
        self.assertNoRiskContains(risks, 'access-control metadata changed')
        self.assertIn(
            "1 new custom field(s) without permission set/profile changes - verify "
            "field-level security is granted", risks)


# ═══════════════════════════════════════════════════════════════
# generate_suggestions
# ═══════════════════════════════════════════════════════════════

class GenerateSuggestionsTest(unittest.TestCase):
    STATIC_REVIEW_LINE = (
        "Salesforce change: follow the Salesforce Review Path in SKILL.md - static review "
        "only; never deploy, run Apex or tests, or run data commands against an org"
    )

    def test_returns_list(self):
        files = [FileStats(filename='app.py', additions=10, deletions=5,
                           language='Python')]
        result = pr_analyzer.generate_suggestions(files, 0.1, [])
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_large_pr_split_suggestion(self):
        files = [FileStats(filename='big.py', additions=600, deletions=300,
                           language='Python')]
        result = pr_analyzer.generate_suggestions(files, 0.3, [])
        self.assertTrue(any('splitting' in s.lower() for s in result))

    def test_no_tests_suggestion(self):
        files = [FileStats(filename='app.py', additions=40, deletions=20,
                           language='Python')]
        risks = [f"{pr_analyzer.RISK_NO_TESTS}: no tests"]
        result = pr_analyzer.generate_suggestions(files, 0.2, risks)
        self.assertTrue(any('test' in s.lower() for s in result))

    def test_typescript_any_suggestion(self):
        for filename in ('src/index.ts', 'src/App.tsx', SF + 'lwc/accountList/accountList.ts'):
            with self.subTest(filename=filename):
                result = pr_analyzer.generate_suggestions([make_file(filename)], 0.1, [])
                self.assertIn("Check for proper type usage (avoid 'any')", result)

    def test_no_typescript_suggestion_for_javascript_bundles(self):
        for filename in ('src/server.js', SF + 'lwc/accountList/accountList.js',
                         SF + 'aura/AccountCard/AccountCardController.js'):
            with self.subTest(filename=filename):
                result = pr_analyzer.generate_suggestions([make_file(filename)], 0.1, [])
                self.assertNotIn("Check for proper type usage (avoid 'any')", result)

    def test_no_removed_language_suggestions(self):
        files = [make_file('src/main.rs', 30, 5), make_file('src/lib.cpp', 30, 5),
                 make_file('src/main.go', 10, 0)]
        joined = ' '.join(pr_analyzer.generate_suggestions(files, 0.2, [])).lower()
        for word in ('unwrap', 'memory safety', 'bounds checks', 'rust', 'c++'):
            self.assertNotIn(word, joined)

    def test_salesforce_static_review_line(self):
        result = pr_analyzer.generate_suggestions(
            [make_file(SF + 'profiles/Admin.profile-meta.xml')], 0.1, [])
        self.assertIn(self.STATIC_REVIEW_LINE, result)
        # Metadata alone gets no code-specific hints
        self.assertFalse(any(s.startswith(('Apex:', 'LWC/Aura:', 'Visualforce:', 'Flows:'))
                             for s in result))

    def test_salesforce_hints_per_language(self):
        cases = {
            SF + 'classes/AccountService.cls': 'Apex: check bulkification (no SOQL/DML in loops)',
            SF + 'lwc/accountList/accountList.js': 'LWC/Aura: check the Apex contract',
            SF + 'aura/AccountCard/AccountCard.cmp': 'LWC/Aura: check the Apex contract',
            SF + 'pages/AccountPage.page': 'Visualforce: check output encoding (escape="false"',
            SF + 'flows/Account_Update.flow-meta.xml': 'Flows: check entry conditions',
        }
        for filename, prefix in cases.items():
            with self.subTest(filename=filename):
                result = pr_analyzer.generate_suggestions([make_file(filename)], 0.1, [])
                self.assertIn(self.STATIC_REVIEW_LINE, result)
                self.assertTrue(any(s.startswith(prefix) for s in result), result)

    def test_apex_tests_request(self):
        risks = [f"{RISK_APEX_NO_TESTS}: 1 Apex class/trigger file(s) changed without Apex "
                 "test class changes"]
        result = pr_analyzer.generate_suggestions(
            [make_file(SF + 'classes/AccountService.cls')], 0.1, risks)
        self.assertIn(
            "Request Apex test updates: bulk (200+ records), negative paths, and "
            "System.runAs() permission cases with meaningful Assert messages", result)
        # APEX_NO_TEST_CHANGES must not be mistaken for NO_TEST_CHANGES
        self.assertNotIn("Request test additions before approval", result)

    def test_load_guides_line(self):
        files = [make_file(SF + 'classes/AccountService.cls'),
                 make_file(SF + 'lwc/accountList/accountList.js')]
        result = pr_analyzer.generate_suggestions(files, 0.1, [])
        self.assertEqual(
            result[-1],
            "Load guides: reference/salesforce/platform.md, reference/salesforce/apex.md, "
            "reference/salesforce/lwc.md, reference/javascript.md")

    def test_fallback_kept_before_guides_line(self):
        result = pr_analyzer.generate_suggestions([make_file('src/app.py', 3, 1)], 0.1, [])
        self.assertEqual(result, ["Standard review process should suffice",
                                  "Load guides: reference/python.md"])

    def test_fallback_for_unknown_files_only(self):
        result = pr_analyzer.generate_suggestions([make_file('Makefile', 3, 1)], 0.1, [])
        self.assertEqual(result, ["Standard review process should suffice"])

    def test_no_salesforce_lines_for_non_salesforce_diff(self):
        files = [make_file('src/app.py'), make_file('src/index.ts')]
        result = pr_analyzer.generate_suggestions(files, 0.1, [])
        self.assertFalse(any('Salesforce' in s for s in result))

    def test_split_threshold(self):
        split = "Consider splitting this PR into smaller, focused changes"
        at_limit = [FileStats(filename='big.py', additions=800, language='Python')]
        over_limit = [FileStats(filename='big.py', additions=801, language='Python')]
        self.assertNotIn(split, pr_analyzer.generate_suggestions(at_limit, 0.3, []))
        self.assertIn(split, pr_analyzer.generate_suggestions(over_limit, 0.3, []))

    def test_high_complexity_threshold(self):
        high = ["High complexity - allocate extra review time",
                "Consider pair reviewing for critical sections"]
        files = [make_file('src/app.py')]
        at_limit = pr_analyzer.generate_suggestions(files, 0.7, [])
        self.assertFalse(set(high) & set(at_limit))
        self.assertEqual(pr_analyzer.generate_suggestions(files, 0.71, [])[:2], high)

    def test_sql_suggestion(self):
        sql = "Review for SQL injection and query performance"
        self.assertIn(sql, pr_analyzer.generate_suggestions(
            [make_file('db/migrations/001_init.sql')], 0.1, []))
        # SOQL files follow the Salesforce path instead
        self.assertNotIn(sql, pr_analyzer.generate_suggestions(
            [make_file('scripts/soql/openOpportunities.soql')], 0.1, []))

    def test_project_file_alone_is_a_salesforce_change(self):
        for name in ('.forceignore', 'sfdx-project.json'):
            with self.subTest(name=name):
                result = pr_analyzer.generate_suggestions([make_file(name, 1, 0)], 0.1, [])
                self.assertEqual(result, [
                    self.STATIC_REVIEW_LINE,
                    "Load guides: reference/salesforce/platform.md, "
                    "reference/salesforce/metadata.md",
                ])

    def test_suggestion_order(self):
        files = [
            make_file('src/index.ts', 500, 301),
            make_file('db/schema.sql', 1, 0),
            make_file(SF + 'classes/AccountService.cls'),
            make_file(SF + 'lwc/accountList/accountList.js'),
            make_file(SF + 'pages/AccountPage.page'),
            make_file(SF + 'flows/Account_Update.flow-meta.xml'),
        ]
        risks = pr_analyzer.identify_risk_factors(files)
        result = pr_analyzer.generate_suggestions(files, 0.9, risks)
        prefixes = (
            'Consider splitting', 'High complexity', 'Consider pair reviewing',
            'Request test additions', 'Check for proper type usage', 'Review for SQL injection',
            'Salesforce change:', 'Apex:', 'LWC/Aura:', 'Visualforce:', 'Flows:',
            'Request Apex test updates', 'Load guides:',
        )
        self.assertEqual(len(result), len(prefixes), result)
        for suggestion, prefix in zip(result, prefixes):
            self.assertTrue(suggestion.startswith(prefix), (suggestion, prefix))

    def test_no_files(self):
        self.assertEqual(pr_analyzer.generate_suggestions([], 0.0, []),
                         ["Standard review process should suffice"])


# ═══════════════════════════════════════════════════════════════
# recommend_guides
# ═══════════════════════════════════════════════════════════════

class RecommendGuidesTest(unittest.TestCase):
    def guides(self, *filenames):
        return pr_analyzer.recommend_guides([make_file(name) for name in filenames])

    def test_guide_order_contract(self):
        self.assertEqual(list(pr_analyzer.GUIDE_ORDER), [
            GUIDE_PLATFORM, GUIDE_APEX, GUIDE_TRIGGERS, GUIDE_SOQL, GUIDE_LWC, GUIDE_AURA,
            GUIDE_VISUALFORCE, GUIDE_FLOWS, GUIDE_METADATA, GUIDE_JAVASCRIPT,
            GUIDE_TYPESCRIPT, GUIDE_NODEJS, GUIDE_NESTJS, GUIDE_PYTHON,
        ])

    def test_apex_class(self):
        self.assertEqual(
            self.guides(SF + 'classes/AccountService.cls',
                        SF + 'classes/AccountService.cls-meta.xml'),
            [GUIDE_PLATFORM, GUIDE_APEX])

    def test_trigger(self):
        self.assertEqual(self.guides(SF + 'triggers/AccountTrigger.trigger'),
                         [GUIDE_PLATFORM, GUIDE_APEX, GUIDE_TRIGGERS])

    def test_trigger_meta_alone_adds_triggers_guide(self):
        self.assertEqual(self.guides(SF + 'triggers/AccountTrigger.trigger-meta.xml'),
                         [GUIDE_PLATFORM, GUIDE_APEX, GUIDE_TRIGGERS])

    def test_destructive_manifests(self):
        for name in ('src/package.xml', 'destructiveChanges.xml',
                     'manifest/destructiveChangesPost.xml'):
            with self.subTest(name=name):
                self.assertEqual(self.guides(name), [GUIDE_PLATFORM, GUIDE_METADATA])

    def test_script_guides(self):
        self.assertEqual(pr_analyzer._script_guides('.js'), [GUIDE_JAVASCRIPT])
        self.assertEqual(pr_analyzer._script_guides('.ts'), [GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT])
        for ext in ('.html', '.css', '.xml', '.cmp', ''):
            with self.subTest(ext=ext):
                self.assertEqual(pr_analyzer._script_guides(ext), [])

    def test_no_files(self):
        self.assertEqual(pr_analyzer.recommend_guides([]), [])

    def test_lwc_js_adds_javascript(self):
        self.assertEqual(
            self.guides(SF + 'lwc/accountList/accountList.js',
                        SF + 'lwc/accountList/accountList.html'),
            [GUIDE_PLATFORM, GUIDE_LWC, GUIDE_JAVASCRIPT])

    def test_lwc_ts_adds_typescript(self):
        self.assertEqual(self.guides(SF + 'lwc/accountList/accountList.ts'),
                         [GUIDE_PLATFORM, GUIDE_LWC, GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT])

    def test_lwc_template_only_skips_javascript(self):
        self.assertEqual(
            self.guides(SF + 'lwc/accountList/accountList.html',
                        SF + 'lwc/accountList/accountList.css',
                        SF + 'lwc/accountList/accountList.js-meta.xml'),
            [GUIDE_PLATFORM, GUIDE_LWC])

    def test_aura(self):
        self.assertEqual(
            self.guides(SF + 'aura/AccountCard/AccountCard.cmp',
                        SF + 'aura/AccountCard/AccountCardController.js'),
            [GUIDE_PLATFORM, GUIDE_AURA, GUIDE_JAVASCRIPT])
        self.assertEqual(self.guides(SF + 'aura/AccountCard/AccountCard.cmp'),
                         [GUIDE_PLATFORM, GUIDE_AURA])

    def test_visualforce_flow_and_metadata(self):
        self.assertEqual(
            self.guides(SF + 'pages/AccountPage.page',
                        SF + 'flows/Account_Update.flow-meta.xml',
                        SF + 'permissionsets/Sales.permissionset-meta.xml'),
            [GUIDE_PLATFORM, GUIDE_VISUALFORCE, GUIDE_FLOWS, GUIDE_METADATA])

    def test_sfdx_project_files_only(self):
        for name in ('sfdx-project.json', '.forceignore', 'manifest/package.xml'):
            with self.subTest(name=name):
                self.assertEqual(self.guides(name), [GUIDE_PLATFORM, GUIDE_METADATA])

    def test_soql_file(self):
        self.assertEqual(self.guides('scripts/soql/openOpportunities.soql'),
                         [GUIDE_PLATFORM, GUIDE_SOQL])

    def test_non_salesforce_stacks(self):
        cases = {
            'src/app.py': [GUIDE_PYTHON],
            'src/server.js': [GUIDE_JAVASCRIPT],
            'src/index.ts': [GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT],
            'src/App.tsx': [GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT],
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(self.guides(filename), expected)

    def test_nest_files(self):
        expected = [GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT, GUIDE_NODEJS, GUIDE_NESTJS]
        for filename in ('src/users/users.controller.ts', 'src/users/users.module.ts',
                         'src/users/dto/create-user.dto.ts',
                         'test/users.controller.e2e-spec.ts'):
            with self.subTest(filename=filename):
                self.assertEqual(self.guides(filename), expected)

    def test_nest_cli_json(self):
        self.assertEqual(self.guides('nest-cli.json'), [GUIDE_NODEJS, GUIDE_NESTJS])

    def test_package_json_does_not_add_nodejs(self):
        self.assertEqual(self.guides('package.json'), [])
        self.assertEqual(self.guides('package.json', SF + 'classes/AccountService.cls'),
                         [GUIDE_PLATFORM, GUIDE_APEX])

    def test_order_stable_and_deduplicated(self):
        filenames = [
            'src/app.py',
            SF + 'flows/Account_Update.flow-meta.xml',
            'src/users/users.controller.ts',
            SF + 'lwc/accountList/accountList.ts',
            SF + 'triggers/AccountTrigger.trigger',
            'scripts/soql/openOpportunities.soql',
            SF + 'aura/AccountCard/AccountCardController.js',
            SF + 'pages/AccountPage.page',
            SF + 'profiles/Admin.profile-meta.xml',
            SF + 'classes/AccountService.cls',
            SF + 'classes/AccountServiceTest.cls',
            'src/server.js',
        ]
        expected = list(pr_analyzer.GUIDE_ORDER)
        self.assertEqual(self.guides(*filenames), expected)
        self.assertEqual(self.guides(*reversed(filenames)), expected)

    def test_unknown_files_no_guides(self):
        self.assertEqual(self.guides('Makefile', 'data.xyz', 'README.md', 'src/main.rs'), [])

    def test_soql_hint_adds_soql_guide(self):
        f = make_file(SF + 'classes/AccountService.cls')
        f.has_soql = True
        self.assertEqual(pr_analyzer.recommend_guides([f]),
                         [GUIDE_PLATFORM, GUIDE_APEX, GUIDE_SOQL])

    def test_node_hint_adds_nodejs_guide(self):
        f = make_file('server/app.js')
        f.uses_node = True
        self.assertEqual(pr_analyzer.recommend_guides([f]), [GUIDE_JAVASCRIPT, GUIDE_NODEJS])


class ContentHintTest(unittest.TestCase):
    @staticmethod
    def diff_for(path, *added):
        body = ''.join(f'+{line}\n' for line in added)
        return (f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n'
                f'@@ -1,1 +1,{len(added)} @@\n{body}')

    def parse_one(self, path, *added):
        return pr_analyzer.parse_diff(self.diff_for(path, *added))[0]

    def test_soql_detected_in_added_apex_lines(self):
        for line in ('    List<Account> a = [SELECT Id FROM Account WITH USER_MODE];',
                     '    return [select Id from Contact];',
                     '    List<List<SObject>> r = [FIND :term IN ALL FIELDS RETURNING Account];',
                     '    return Database.query(soql, AccessLevel.USER_MODE);',
                     '    Database.getQueryLocator(q);',
                     '    Database.queryWithBinds(q, binds, AccessLevel.USER_MODE);',
                     '    Search.query(sosl);'):
            with self.subTest(line=line):
                self.assertTrue(self.parse_one(SF + 'classes/AccountService.cls', line).has_soql)
        self.assertTrue(self.parse_one(SF + 'triggers/AccountTrigger.trigger',
                                       '    [SELECT Id FROM Case]').has_soql)

    def test_soql_not_detected_elsewhere(self):
        self.assertFalse(self.parse_one(SF + 'classes/AccountService.cls',
                                        '    insert as user accounts;').has_soql)
        self.assertFalse(self.parse_one(SF + 'classes/AccountService.cls-meta.xml',
                                        '<!-- [SELECT Id FROM Account] -->').has_soql)
        self.assertFalse(self.parse_one('src/query.js', "const q = '[SELECT Id FROM Account]';").has_soql)

    def test_soql_in_removed_lines_ignored(self):
        path = SF + 'classes/AccountService.cls'
        diff = (f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n'
                '@@ -1,1 +1,1 @@\n-    return [SELECT Id FROM Account];\n+    return cached;\n')
        self.assertFalse(pr_analyzer.parse_diff(diff)[0].has_soql)

    def test_node_detected_in_added_js_ts_lines(self):
        cases = (
            ('server/app.js', "const express = require('express');"),
            ('server/app.js', "import { readFile } from 'node:fs/promises';"),
            ('server/app.mjs', "import { exec } from 'child_process';"),
            ('server/index.ts', "import express from 'express';"),
            ('server/index.ts', 'const port = Number(process.env.PORT ?? 3000);'),
            ('server/worker.js', "const { Worker } = await import('node:worker_threads');"),
        )
        for path, line in cases:
            with self.subTest(path=path, line=line):
                self.assertTrue(self.parse_one(path, line).uses_node)

    def test_node_not_detected_for_browser_or_lwc_code(self):
        self.assertFalse(self.parse_one('web/app.js', "import { html } from 'lit';").uses_node)
        self.assertFalse(self.parse_one('web/app.js', "import path from './path.js';").uses_node)
        # LWC bundles are labeled LWC, not JavaScript, so they never get the Node hint
        lwc = self.parse_one(SF + 'lwc/accountList/accountList.js',
                             "import { LightningElement } from 'lwc';", 'process.env.X;')
        self.assertFalse(lwc.uses_node)

    def test_end_to_end_guides_line_uses_hints(self):
        apex = SF + 'classes/AccountService.cls'
        diff = (self.diff_for(apex, 'public with sharing class AccountService {',
                              '    List<Account> a = [SELECT Id FROM Account WITH USER_MODE];', '}')
                + self.diff_for('server/app.js', "const express = require('express');"))
        analysis = pr_analyzer.analyze_pr(diff)
        guides_line = next(s for s in analysis.suggestions if s.startswith('Load guides: '))
        self.assertIn(GUIDE_SOQL, guides_line)
        self.assertIn(GUIDE_NODEJS, guides_line)


# ═══════════════════════════════════════════════════════════════
# analyze_pr — end-to-end integration
# ═══════════════════════════════════════════════════════════════

class AnalyzePRTest(unittest.TestCase):
    def test_end_to_end(self):
        diff = (
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,3 +1,5 @@\n"
            " import os\n"
            "+import sys\n"
            "+import json\n"
            " def main():\n"
            "+    print('hello')\n"
            "+    return 0\n"
            "diff --git a/tests/test_app.py b/tests/test_app.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/tests/test_app.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+from app import main\n"
            "+def test_main():\n"
            "+    assert main() == 0\n"
        )
        analysis = pr_analyzer.analyze_pr(diff)

        self.assertEqual(analysis.total_files, 2)
        self.assertEqual(analysis.total_additions, 7)  # 4 + 3
        self.assertEqual(analysis.total_deletions, 0)
        self.assertGreater(len(analysis.suggestions), 0)
        self.assertIn('XS (Extra Small)', analysis.size_category)

        # Verify test file was detected
        test_file = [f for f in analysis.files if 'test' in f.filename][0]
        self.assertTrue(test_file.is_test)

        # Verify no "NO_TEST_CHANGES" risk since tests are present
        self.assertFalse(
            any(pr_analyzer.RISK_NO_TESTS in r for r in analysis.risk_factors)
        )

    def test_empty_diff(self):
        analysis = pr_analyzer.analyze_pr("")
        self.assertEqual(analysis.total_files, 0)
        self.assertEqual(analysis.complexity_score, 0.0)

    def test_binary_only_diff(self):
        # No changed lines at all, e.g. a new static resource archive
        path = SF + 'staticresources/charts.resource'
        diff = (
            f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            f"Binary files /dev/null and b/{path} differ\n"
        )
        analysis = pr_analyzer.analyze_pr(diff)
        self.assertEqual((analysis.total_files, analysis.total_additions,
                          analysis.total_deletions), (1, 0, 0))
        self.assertEqual(analysis.size_category, 'XS (Extra Small)')
        self.assertEqual(analysis.estimated_review_time, 5)
        # 0 * 0.4 + 1/20 * 0.2 + 1.0 * 0.2 + 1/5 * 0.2
        self.assertEqual(analysis.complexity_score, 0.25)

    def test_salesforce_end_to_end(self):
        cls = SF + 'classes/AccountService.cls'
        meta = cls + '-meta.xml'
        js = SF + 'lwc/accountList/accountList.js'
        diff = (
            f"diff --git a/{cls} b/{cls}\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            f"+++ b/{cls}\n"
            "@@ -0,0 +1,6 @@\n"
            "+public with sharing class AccountService {\n"
            "+    @AuraEnabled(cacheable=true)\n"
            "+    public static List<Account> getAccounts() {\n"
            "+        return [SELECT Id, Name FROM Account WITH USER_MODE LIMIT 50];\n"
            "+    }\n"
            "+}\n"
            f"diff --git a/{meta} b/{meta}\n"
            "new file mode 100644\n"
            "index 0000000..2222222\n"
            "--- /dev/null\n"
            f"+++ b/{meta}\n"
            "@@ -0,0 +1,5 @@\n"
            '+<?xml version="1.0" encoding="UTF-8"?>\n'
            '+<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">\n'
            "+    <apiVersion>66.0</apiVersion>\n"
            "+    <status>Active</status>\n"
            "+</ApexClass>\n"
            f"diff --git a/{js} b/{js}\n"
            "index 3333333..4444444 100644\n"
            f"--- a/{js}\n"
            f"+++ b/{js}\n"
            "@@ -1,4 +1,5 @@\n"
            " import { LightningElement, wire } from 'lwc';\n"
            "+import getAccounts from '@salesforce/apex/AccountService.getAccounts';\n"
            " export default class AccountList extends LightningElement {\n"
            "-    accounts;\n"
            "+    @wire(getAccounts) accounts;\n"
            " }\n"
        )
        analysis = pr_analyzer.analyze_pr(diff)

        self.assertEqual(analysis.total_files, 3)
        self.assertEqual(analysis.total_additions, 13)  # 6 + 5 + 2
        self.assertEqual(analysis.total_deletions, 1)
        self.assertEqual([f.language for f in analysis.files], ['Apex', 'Apex', 'LWC'])
        self.assertEqual([f.change_type for f in analysis.files],
                         ['added', 'added', 'modified'])
        self.assertEqual(analysis.files[1].api_version_after, 66.0)

        self.assertTrue(has_risk_code(analysis.risk_factors, RISK_APEX_NO_TESTS))
        self.assertIn(
            "Load guides: reference/salesforce/platform.md, reference/salesforce/apex.md, "
            "reference/salesforce/soql-sosl.md, reference/salesforce/lwc.md, "
            "reference/javascript.md", analysis.suggestions)
        self.assertTrue(any(s.startswith("Request Apex test updates")
                            for s in analysis.suggestions))

    def test_scores_and_messages(self):
        added = ''.join(f"+line_{i} = {i}\n" for i in range(250))
        diff = (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -0,0 +1,250 @@\n" + added
        )
        analysis = pr_analyzer.analyze_pr(diff)
        self.assertEqual(analysis.size_category, 'M (Medium)')
        # 250/1000 * 0.4 + 1/20 * 0.2 + 1.0 * 0.2 + 1/5 * 0.2
        self.assertEqual(analysis.complexity_score, 0.35)
        self.assertEqual(analysis.estimated_review_time, 16)  # 250 / 20 * 1.35
        self.assertEqual(analysis.risk_factors, [
            f"{RISK_NO_TESTS}: No test changes - verify test coverage",
            "Low test ratio (<20%) - consider adding more tests",
        ])
        self.assertEqual(analysis.suggestions, [
            "Request test additions before approval",
            "Load guides: reference/python.md",
        ])


# ═══════════════════════════════════════════════════════════════
# print_analysis
# ═══════════════════════════════════════════════════════════════

RULE = '=' * 60


class PrintAnalysisTest(unittest.TestCase):
    @staticmethod
    def analysis(risk_factors):
        return pr_analyzer.PRAnalysis(
            total_files=3,
            total_additions=12,
            total_deletions=3,
            files=[
                FileStats(filename='src/app.py', additions=8, deletions=2, language='Python'),
                FileStats(filename='tests/test_app.py', additions=3, is_test=True,
                          language='Python'),
                FileStats(filename='package.json', additions=1, deletions=1, is_config=True,
                          language='JSON'),
            ],
            complexity_score=0.25,
            size_category='XS (Extra Small)',
            estimated_review_time=5,
            risk_factors=risk_factors,
            suggestions=["Standard review process should suffice",
                         "Load guides: reference/python.md"],
        )

    @staticmethod
    def render(analysis, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pr_analyzer.print_analysis(analysis, **kwargs)
        return out.getvalue()

    def test_report(self):
        output = self.render(self.analysis(["Configuration changes in 1 file(s)"]))
        self.assertEqual(output, '\n'.join([
            '',
            RULE,
            'PR ANALYSIS REPORT',
            RULE,
            '',
            '📊 SUMMARY',
            '   Files changed: 3',
            '   Additions: +12',
            '   Deletions: -3',
            '   Total changes: 15',
            '',
            '📏 SIZE: XS (Extra Small)',
            '   Complexity score: 0.25/1.0',
            '   Estimated review time: ~5 minutes',
            '',
            '⚠️  RISK FACTORS:',
            '   • Configuration changes in 1 file(s)',
            '',
            '💡 SUGGESTIONS:',
            '   • Standard review process should suffice',
            '   • Load guides: reference/python.md',
            '',
            RULE,
            '',
        ]))

    def test_no_risk_section_without_risks(self):
        output = self.render(self.analysis([]))
        self.assertNotIn('RISK FACTORS', output)
        self.assertIn('\n💡 SUGGESTIONS:\n', output)
        self.assertEqual(output, self.render(self.analysis([]), show_files=False))

    def test_files_grouped_by_language(self):
        output = self.render(self.analysis([]), show_files=True)
        files_section = output[output.index('📁 FILES:'):]
        self.assertEqual(files_section, '\n'.join([
            '📁 FILES:',
            '',
            '   [JSON]',
            '   ⚙️ package.json (+1/-1)',
            '',
            '   [Python]',
            '   📄 src/app.py (+8/-2)',
            '   🧪 tests/test_app.py (+3/-0)',
            '',
            RULE,
            '',
        ]))


# ═══════════════════════════════════════════════════════════════
# main — command line
# ═══════════════════════════════════════════════════════════════

SAMPLE_DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1 +1,2 @@\n"
    "-x = 1\n"
    "+x = 2\n"
    "+y = 3\n"
)


class FakeStdin:
    """Stand-in for sys.stdin: a byte buffer and a fixed isatty() answer."""

    def __init__(self, data=b'', tty=False):
        self.buffer = io.BytesIO(data)
        self.tty = tty

    def isatty(self):
        return self.tty


class MainTest(unittest.TestCase):
    def write_diff(self, content):
        """Write a diff (str or bytes) to a temporary file and return its path."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, 'change.diff')
        with open(path, 'wb') as fh:
            fh.write(content.encode('utf-8') if isinstance(content, str) else content)
        return path

    @staticmethod
    def run_main(*args, stdin=None):
        """Run main() with the given arguments; return (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, 'argv', ['pr-analyzer.py', *args]), \
                mock.patch.object(sys, 'stdin', stdin or FakeStdin(tty=True)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                pr_analyzer.main()
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def test_reads_diff_file(self):
        for option in ('-f', '--diff-file'):
            with self.subTest(option=option):
                code, out, err = self.run_main(option, self.write_diff(SAMPLE_DIFF))
                self.assertEqual((code, err), (0, ''))
                self.assertIn('PR ANALYSIS REPORT', out)
                self.assertIn('   Files changed: 1\n   Additions: +2\n   Deletions: -1\n', out)
                self.assertNotIn('FILES:', out)

    def test_stats_lists_files(self):
        for option in ('-s', '--stats'):
            with self.subTest(option=option):
                code, out, _ = self.run_main('-f', self.write_diff(SAMPLE_DIFF), option)
                self.assertEqual(code, 0)
                self.assertIn('   [Python]\n   📄 src/app.py (+2/-1)\n', out)

    def test_reads_piped_stdin(self):
        code, out, err = self.run_main(stdin=FakeStdin(SAMPLE_DIFF.encode('utf-8')))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('   Files changed: 1\n', out)

    def test_diff_file_takes_precedence_over_stdin(self):
        other = SAMPLE_DIFF.replace('src/app.py', 'src/other.py')
        code, out, _ = self.run_main('-s', '-f', self.write_diff(SAMPLE_DIFF),
                                     stdin=FakeStdin(other.encode('utf-8')))
        self.assertEqual(code, 0)
        self.assertIn('src/app.py', out)
        self.assertNotIn('src/other.py', out)

    def test_invalid_utf8_is_replaced(self):
        data = SAMPLE_DIFF.replace('app.py', 'caf\udcff.py').encode('utf-8', 'surrogateescape')
        for source in ('file', 'stdin'):
            with self.subTest(source=source):
                if source == 'file':
                    code, out, _ = self.run_main('-s', '-f', self.write_diff(data))
                else:
                    code, out, _ = self.run_main('-s', stdin=FakeStdin(data))
                self.assertEqual(code, 0)
                self.assertIn('📄 src/caf�.py (+2/-1)', out)

    def test_terminal_without_input_prints_usage(self):
        code, out, err = self.run_main(stdin=FakeStdin(tty=True))
        self.assertEqual(code, 1)
        self.assertEqual(out, "Usage: git diff main...HEAD | python3 pr-analyzer.py\n"
                              "       python3 pr-analyzer.py -f diff.txt\n")
        self.assertEqual(err, '')

    def test_unreadable_file_reports_error(self):
        missing = os.path.join(os.path.dirname(self.write_diff(SAMPLE_DIFF)), 'missing.diff')
        code, out, err = self.run_main('-f', missing)
        self.assertEqual((code, out), (1, ''))
        self.assertTrue(err.startswith('Error reading diff input: '), err)
        self.assertIn('missing.diff', err)

    def test_empty_input(self):
        for content in ('', ' \n\n\t\n'):
            with self.subTest(content=content, source='file'):
                code, out, _ = self.run_main('-f', self.write_diff(content))
                self.assertEqual((code, out), (1, "No diff content provided\n"))
            with self.subTest(content=content, source='stdin'):
                code, out, _ = self.run_main(stdin=FakeStdin(content.encode('utf-8')))
                self.assertEqual((code, out), (1, "No diff content provided\n"))

    def test_report_is_utf8_on_a_legacy_code_page(self):
        # Windows pipes default to an ANSI code page such as cp1252, which
        # has no emoji; main() switches stdout to UTF-8.
        path = self.write_diff(SAMPLE_DIFF)
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding='cp1252')
        with mock.patch.object(sys, 'argv', ['pr-analyzer.py', '-f', path]), \
                contextlib.redirect_stdout(stdout):
            pr_analyzer.main()
        stdout.flush()
        self.assertEqual(stdout.encoding, 'utf-8')
        self.assertIn('📊 SUMMARY', raw.getvalue().decode('utf-8'))


class ScriptEntryPointTest(unittest.TestCase):
    def test_runs_as_main_module(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, 'change.diff')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(SAMPLE_DIFF)
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', [SCRIPT, '-f', path]), \
                contextlib.redirect_stdout(out):
            runpy.run_path(SCRIPT, run_name='__main__')
        self.assertIn('PR ANALYSIS REPORT', out.getvalue())

    def test_pipe_in_a_subprocess_with_a_legacy_code_page(self):
        # The way the skill runs it: git diff ... | python3 pr-analyzer.py
        env = dict(os.environ, PYTHONIOENCODING='cp1252')
        result = subprocess.run([sys.executable, SCRIPT, '--stats'],
                                input=SAMPLE_DIFF.encode('utf-8'), capture_output=True,
                                env=env, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        out = result.stdout.decode('utf-8')
        self.assertIn('📊 SUMMARY', out)
        self.assertIn('📄 src/app.py (+2/-1)', out)


if __name__ == '__main__':
    unittest.main()
