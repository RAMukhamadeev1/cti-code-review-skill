#!/usr/bin/env python3
"""Tests for the skill package itself (stdlib unittest, no extra deps).

Checks the SKILL.md frontmatter, every local link and heading anchor in the
Markdown files and index.html, the guide registration rule from the README,
and that SKILL.md and scripts/pr-analyzer.py agree: the guides the analyzer
names exist and are linked from SKILL.md, and the Salesforce files SKILL.md
routes are flagged by the analyzer and get the guides SKILL.md lists.
"""

import functools
import html
import importlib.util
import os
import re
import tempfile
import unicodedata
import unittest
from collections import Counter
from urllib.parse import unquote

_HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(_HERE)
SKILL_MD = os.path.join(SKILL_ROOT, 'SKILL.md')
README = os.path.join(SKILL_ROOT, 'README.md')
INDEX_HTML = os.path.join(SKILL_ROOT, 'index.html')
LICENSE = os.path.join(SKILL_ROOT, 'LICENSE')
PR_TEMPLATE = os.path.join(SKILL_ROOT, 'assets', 'pr-review-template.md')
REPOSITORY = 'RAMukhamadeev1/cti-code-review-skill'

# After auto-compaction Claude Code re-attaches only the first 5,000 tokens of a
# skill; at roughly 3.5 characters per token this keeps all of SKILL.md.
SKILL_MD_MAX_CHARS = 15_000

# The script has a hyphen in its name, so load it by path.
_spec = importlib.util.spec_from_file_location(
    'pr_analyzer', os.path.join(_HERE, 'pr-analyzer.py')
)
pr_analyzer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr_analyzer)

# Default Salesforce DX package directory
SF = 'force-app/main/default/'


@functools.lru_cache(maxsize=None)
def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def rel(path):
    """Path relative to the skill root, with forward slashes."""
    return os.path.relpath(path, SKILL_ROOT).replace(os.sep, '/')


def skill_files(*extensions):
    """Files of the skill package with the given extensions (no dot or cache dirs)."""
    found = []
    for directory, subdirs, names in os.walk(SKILL_ROOT):
        subdirs[:] = sorted(d for d in subdirs if not d.startswith('.') and d != '__pycache__')
        found += [os.path.join(directory, n) for n in sorted(names) if n.endswith(extensions)]
    return found


def file_stats(filename):
    """Build FileStats the way parse_diff does (detected language/test/config)."""
    return pr_analyzer.FileStats(
        filename=filename,
        additions=10,
        is_test=pr_analyzer.is_test_file(filename),
        is_config=pr_analyzer.is_config_file(filename),
        is_generated=pr_analyzer.is_generated_file(filename),
        language=pr_analyzer.detect_language(filename),
    )


# ═══════════════════════════════════════════════════════════════
# Helpers: frontmatter, links, and anchors
# ═══════════════════════════════════════════════════════════════

def parse_frontmatter(text):
    """Parse the YAML subset SKILL.md uses: 'key: value', 'key: |' blocks, '- item' lists."""
    lines = text.split('\n')
    if lines[0] != '---' or '---' not in lines[1:]:
        raise ValueError('SKILL.md must open with a --- delimited frontmatter block')
    fields, key, in_block = {}, None, False
    for line in lines[1:lines.index('---', 1)]:
        if isinstance(fields.get(key), list) and line.startswith('  - '):
            fields[key].append(line[4:])
        elif in_block and (line.startswith('  ') or not line.strip()):
            fields[key] += line[2:] + '\n'
        elif line.strip():
            match = re.fullmatch(r'([a-z][a-z-]*):(?: (.+))?', line)
            if not match:
                raise ValueError(f'unsupported frontmatter line: {line!r}')
            key, scalar = match.groups()
            in_block = scalar == '|'
            fields[key] = [] if scalar is None else '' if in_block else scalar
    return fields


_FENCE_RE = re.compile(r'^\s*(`{3,}|~{3,})')
_INLINE_CODE_RE = re.compile(r'(`+).+?\1')
_MD_LINK_RE = re.compile(
    r'\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
_HTML_LINK_RE = re.compile(r'\b(?:href|src)="([^"]*)"')
_HTML_ID_RE = re.compile(r'<[^>]*\b(?:id|name)="([^"]+)"')
_HEADING_RE = re.compile(r'^#{1,6}\s+(.*?)\s*#*\s*$')
_EXTERNAL_RE = re.compile(r'^(?:[a-z][a-z0-9+.-]*:|//)', re.IGNORECASE)


def prose_lines(text):
    """(line number, line) for Markdown lines outside fenced code blocks."""
    fence = None
    for number, line in enumerate(text.split('\n'), 1):
        match = _FENCE_RE.match(line)
        if match and fence is None:
            fence = match.group(1)
        elif (match and match.group(1)[0] == fence[0]
              and len(match.group(1)) >= len(fence) and line.strip() == match.group(1)):
            fence = None
        elif fence is None:
            yield number, line


def github_slug(heading):
    """The anchor GitHub generates for a heading's text."""
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', heading)  # [text](url) -> text
    text = html.unescape(re.sub(r'<[^>]+>', '', text)).lower()
    kept = (c for c in text if c in ' -_' or unicodedata.category(c)[0] in 'LMN')
    return ''.join(kept).replace(' ', '-')


@functools.lru_cache(maxsize=None)
def anchors(path):
    """Fragments a file defines: heading slugs (Markdown) and id/name attributes."""
    text = read(path)
    if path.endswith('.html'):
        return frozenset(_HTML_ID_RE.findall(text))
    found, seen = set(), Counter()
    for _, line in prose_lines(text):
        found.update(_HTML_ID_RE.findall(line))
        match = _HEADING_RE.match(line)
        if match:
            slug = github_slug(match.group(1))
            found.add(f'{slug}-{seen[slug]}' if seen[slug] else slug)
            seen[slug] += 1
    return frozenset(found)


def local_links(path):
    """(line number, target) for each relative link in a Markdown or HTML file."""
    text = read(path)
    if path.endswith('.html'):
        lines = enumerate(text.split('\n'), 1)
        found = [(n, t) for n, line in lines for t in _HTML_LINK_RE.findall(line)]
    else:
        found = []
        for number, line in prose_lines(text):
            prose = _INLINE_CODE_RE.sub('', line)
            found += [(number, t) for t in _MD_LINK_RE.findall(prose)]
            found += [(number, t) for t in _HTML_LINK_RE.findall(prose)]
    return [(n, t) for n, t in found if not _EXTERNAL_RE.match(t)]


def broken_links(path):
    """(line number, target) for each relative link whose file or anchor is missing."""
    broken = []
    for number, target in local_links(path):
        file_part, _, fragment = target.partition('#')
        target_path = path
        if file_part:
            target_path = os.path.normpath(
                os.path.join(os.path.dirname(path), unquote(file_part)))
        if not os.path.exists(target_path):
            broken.append((number, target))
        elif (fragment and target_path.endswith(('.md', '.html'))
              and unquote(fragment) not in anchors(target_path)):
            broken.append((number, target))
    return broken


def markdown_table(text, header):
    """Rows (lists of cells) of the Markdown table whose header row starts with header."""
    lines = text.split('\n')
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith('|'):
            break
        rows.append([cell.strip() for cell in re.split(r'(?<!\\)\|', line.strip())[1:-1]])
    return rows


class LinkCheckerTest(unittest.TestCase):
    """The helpers above, so the link tests cannot pass vacuously."""

    def write(self, directory, name, lines):
        path = os.path.join(directory, name)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        return path

    def test_github_slugs(self):
        cases = {
            'Salesforce Safety: Static Review Only': 'salesforce-safety-static-review-only',
            'The LWC-Apex Contract': 'the-lwc-apex-contract',
            '`@AuraEnabled` Methods': 'auraenabled-methods',
            'Phase 1: Context Gathering (2-3 minutes)': 'phase-1-context-gathering-2-3-minutes',
            'SOQL & SOSL': 'soql--sosl',
            '&#128640; Installation': '-installation',
            '[Deployment Impact](metadata.md) Notes': 'deployment-impact-notes',
            'Änderungen prüfen': 'änderungen-prüfen',
            'snake_case Names': 'snake_case-names',
        }
        for heading, expected in cases.items():
            with self.subTest(heading=heading):
                self.assertEqual(github_slug(heading), expected)

    def test_markdown_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, 'guide.md', [
                '# Guide', '## Deployment Impact', '## Notes', '## Notes',
                '<a id="custom"></a>', '```', '## Not A Heading', '```',
            ])
            index = self.write(tmp, 'index.md', [
                '# Index',
                '[ok](guide.md) and [ok](guide.md#deployment-impact)',
                '[ok](guide.md#notes-1) and [ok](guide.md#custom)',
                '[ok](#index) and [ok](./sub/../guide.md "Title")',
                '[external](https://example.com/missing.md) [mail](mailto:dev@example.com)',
                '`[inline code](missing-inline.md)`',
                '```markdown',
                '[fenced code](missing-fenced.md)',
                '```',
                '[missing](missing.md)',
                '[missing](guide.md#nope) and [missing](guide.md#not-a-heading)',
                '[missing](#nope) and <a href="missing.html">html</a>',
            ])
            self.assertEqual(broken_links(index), [
                (10, 'missing.md'), (11, 'guide.md#nope'), (11, 'guide.md#not-a-heading'),
                (12, '#nope'), (12, 'missing.html'),
            ])

    def test_html_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, 'guide.md', ['# Guide'])
            page = self.write(tmp, 'page.html', [
                '<a href="guide.md#guide">guide</a> <a href="https://example.com">x</a>',
                '<section id="top"><a href="#top">top</a></section>',
                '<a href="#gone">gone</a>',
                '<img src="logo.png">',
            ])
            self.assertEqual(broken_links(page), [(3, '#gone'), (4, 'logo.png')])

    def test_frontmatter_parser(self):
        fields = parse_frontmatter('\n'.join([
            '---', 'name: demo', '', 'description: |', '  First line.', '', '  Second line.',
            'allowed-tools:', '  - Read', '  - Bash(git diff *)', '---', '# Body',
        ]))
        self.assertEqual(fields, {
            'name': 'demo',
            'description': 'First line.\n\nSecond line.\n',
            'allowed-tools': ['Read', 'Bash(git diff *)'],
        })
        for text in ('# No frontmatter', '---\nname: demo\n', '---\n  - orphan item\n---'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_frontmatter(text)

    def test_markdown_table(self):
        text = '\n'.join(['| A | B |', '|---|---|', '| `x \\| y` | 1 |', '| z | 2 |', '', '| q |'])
        self.assertEqual(markdown_table(text, '| A |'), [['`x \\| y`', '1'], ['z', '2']])


# ═══════════════════════════════════════════════════════════════
# SKILL.md frontmatter
# ═══════════════════════════════════════════════════════════════

class FrontmatterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields = parse_frontmatter(read(SKILL_MD))

    def test_name(self):
        name = self.fields['name']
        self.assertRegex(name, r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
        self.assertLessEqual(len(name), 64)
        self.assertNotRegex(name, r'anthropic|claude')

    def test_install_directory_matches_name(self):
        # A skill's directory name should match its name
        directories = re.findall(r'\.claude[/\\]skills[/\\]([\w-]+)', read(README))
        self.assertTrue(directories)
        self.assertEqual(set(directories), {self.fields['name']})

    def test_description(self):
        description = self.fields['description'].strip()
        self.assertTrue(description)
        self.assertLessEqual(len(description), 1024)
        self.assertNotRegex(description, r'<[^>]+>')  # no XML tags

    def test_description_is_a_lean_trigger(self):
        # The description sits in every session's skill listing: keep it to what
        # the skill covers and when to use it. Rules live in the body.
        description = ' '.join(self.fields['description'].split())
        self.assertLessEqual(len(description), 700)
        self.assertTrue(description.startswith('Code review for'), description)
        for phrase in ('mentoring', 'never deploy', 'setting review standards'):
            self.assertNotIn(phrase, description)

    def test_allowed_tools_are_read_only(self):
        # Static review only: read-only tools, read-only git and gh, and the
        # bundled analyzer; never sf/sfdx, a general shell, or unscoped WebFetch
        # (reviewed code is untrusted input, so no pre-approved exfiltration path).
        allowed = self.fields['allowed-tools']
        analyzer = 'Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/pr-analyzer.py *)'
        for required in (analyzer, 'Bash(gh pr view *)', 'Bash(gh pr diff *)',
                         'Bash(git merge-base *)'):
            self.assertIn(required, allowed)
        for tool in allowed:
            with self.subTest(tool=tool):
                self.assertTrue(
                    tool in {'Read', 'Grep', 'Glob', analyzer}
                    or re.fullmatch(r'Bash\(git (?:diff|log|show|status|merge-base|rev-parse'
                                    r'|blame|ls-files) \*\)', tool)
                    or re.fullmatch(r'Bash\(gh pr (?:view|diff|checks) \*\)', tool),
                    tool)
                self.assertFalse(tool.startswith('WebFetch'), tool)

    def test_skill_dir_paths_exist(self):
        paths = set(re.findall(r'\$\{CLAUDE_SKILL_DIR\}/([\w./-]+)', read(SKILL_MD)))
        self.assertIn('scripts/pr-analyzer.py', paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(os.path.join(SKILL_ROOT, path)))


# ═══════════════════════════════════════════════════════════════
# SKILL.md body: an agent's procedure, not a human's
# ═══════════════════════════════════════════════════════════════

class SkillBodyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(SKILL_MD)

    def test_fits_the_compaction_budget(self):
        self.assertLessEqual(len(self.text), SKILL_MD_MAX_CHARS)

    def test_output_format_is_defined(self):
        self.assertIn('output-format', anchors(SKILL_MD))
        body = self.text.split('## Output Format', 1)[1].split('\n## ', 1)[0]
        for marker in ('**Verdict:**', '**Scope:**', '### Findings', '### Questions',
                       '`path/to/file', '(pre-existing)', 'Request changes', 'Approve'):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_standing_rules(self):
        # Reviewed code, comments, and PR text are data; findings are verified
        # before they are reported.
        self.assertRegex(self.text, r'(?i)as data, not (?:as )?instructions')
        self.assertRegex(self.text, r'(?i)verify each (?:candidate )?finding')

    def test_no_human_process_content(self):
        for pattern in (r'\(\d+-\d+ minutes\)', r'(?i)offer to pair', r'(?i)ask to split',
                        r'(?i)question approach', '🎉', r'(?i)\[praise\]'):
            with self.subTest(pattern=pattern):
                self.assertNotRegex(self.text, pattern)

    def test_diff_commands_survive_user_git_config(self):
        # color.ui=always and diff.mnemonicPrefix/noprefix change what git prints
        commands = re.findall(r'`(git diff [^`]*)`', self.text)
        self.assertTrue(any('| python3 ${CLAUDE_SKILL_DIR}/scripts/pr-analyzer.py' in c
                            for c in commands), commands)
        for command in commands:
            with self.subTest(command=command):
                self.assertIn('--no-color', command)
                self.assertIn('--default-prefix', command)
        # Uncommitted work: tracked changes against HEAD, and untracked files
        self.assertIn('`git diff --no-color --default-prefix HEAD`', self.text)
        self.assertIn('git status --porcelain', self.text)

    def test_guides_are_read_checklist_first(self):
        self.assertRegex(self.text, r'(?i)review checklist.{0,120}first')

    def test_template_matches_the_output_format(self):
        template = read(PR_TEMPLATE)
        for marker in ('**Verdict:**', '**Scope:**', '### Findings', '### Questions'):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)
        for gone in ('Review Time', '## Strengths', '- [ ]'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, template)


# ═══════════════════════════════════════════════════════════════
# Repository: license and install instructions
# ═══════════════════════════════════════════════════════════════

class RepositoryTest(unittest.TestCase):
    def test_license_keeps_the_upstream_notice(self):
        # Adapted from awesome-skills/code-review-skill (MIT): the copyright and
        # permission notice must ship with every copy.
        text = read(LICENSE)
        self.assertTrue(text.startswith('MIT License\n'))
        self.assertIn('Copyright (c) 2025 awesome-skills', text)
        self.assertIn('Copyright (c) 2026 Ruslan Mukhamadeev', text)
        self.assertIn('The above copyright notice and this permission notice shall be included '
                      'in all\ncopies or substantial portions of the Software.', text)

    def test_readme_names_the_repository(self):
        text = read(README)
        self.assertNotRegex(text, r'<owner>|<repo>|<repository-url>')
        self.assertIn(f'npx skills add {REPOSITORY}', text)
        self.assertIn(f'https://github.com/{REPOSITORY}.git', text)
        self.assertIn('LICENSE', text)


# ═══════════════════════════════════════════════════════════════
# Links and guide registration
# ═══════════════════════════════════════════════════════════════

class LinksTest(unittest.TestCase):
    def test_every_local_link_resolves(self):
        files = skill_files('.md', '.html')
        self.assertIn(SKILL_MD, files)
        self.assertIn(INDEX_HTML, files)
        broken = {rel(path): links for path in files if (links := broken_links(path))}
        self.assertEqual(broken, {})

    def test_every_guide_is_registered(self):
        # README: "Register new guides in SKILL.md, this README, and index.html."
        # A guide SKILL.md does not link is never loaded.
        skill_targets = {os.path.normpath(t.partition('#')[0]) for _, t in local_links(SKILL_MD)}
        for path in skill_files('.md'):
            relative = rel(path)
            if not relative.startswith(('reference/', 'assets/')):
                continue
            with self.subTest(guide=relative):
                self.assertIn(os.path.normpath(relative), skill_targets)
                if relative.startswith('reference/'):
                    name = rf'(?<![\w-]){re.escape(os.path.basename(path))}'
                    self.assertRegex(read(README), name)
                    self.assertRegex(read(INDEX_HTML), name)


# ═══════════════════════════════════════════════════════════════
# SKILL.md <-> scripts/pr-analyzer.py
# ═══════════════════════════════════════════════════════════════

# One sample per path pattern in SKILL.md's "Use this path when ..." sentence
DETECTION_SAMPLES = {
    'sfdx-project.json': 'sfdx-project.json',
    '*.cls': SF + 'classes/AccountService.cls',
    '*.trigger': SF + 'triggers/AccountTrigger.trigger',
    '*.apex': 'scripts/apex/seed.apex',
    '*.soql': 'scripts/soql/openOpportunities.soql',
    '*.page': SF + 'pages/AccountPage.page',
    '*.component': SF + 'components/AccountHeader.component',
    '*-meta.xml': SF + 'objects/Account/fields/Tier__c.field-meta.xml',
    'lwc/**': SF + 'lwc/accountList/accountList.js',
    'aura/**': SF + 'aura/AccountCard/AccountCard.cmp',
    'manifest/*.xml': 'manifest/package.xml',
    'destructiveChanges*.xml': 'destructiveChangesPost.xml',
}

# Samples per row of the Salesforce routing table, keyed by the start of the
# row's "Changed files" cell
ROUTING_SAMPLES = {
    '`classes/*.cls`': (SF + 'classes/AccountService.cls', 'scripts/apex/seed.apex'),
    '`triggers/*.trigger`': (SF + 'triggers/AccountTrigger.trigger',),
    'Apex test classes': (SF + 'classes/AccountServiceTest.cls',),
    '`*.soql`': ('scripts/soql/openOpportunities.soql',),
    '`lwc/<bundle>/*`': (SF + 'lwc/accountList/accountList.js',),
    '`aura/<bundle>/*`': (SF + 'aura/AccountCard/AccountCardController.js',),
    '`*.page`': (SF + 'pages/AccountPage.page', SF + 'components/AccountHeader.component'),
    '`*.flow-meta.xml`': (SF + 'flows/Account_Update.flow-meta.xml',
                          SF + 'flowDefinitions/Account_Update.flowDefinition-meta.xml',
                          SF + 'flowtests/Account_Update_Test.flowtest-meta.xml'),
    'Permission sets': tuple(SF + path for path in (
        'permissionsets/Sales.permissionset-meta.xml',
        'permissionsetgroups/Sales_Bundle.permissionsetgroup-meta.xml',
        'profiles/Admin.profile-meta.xml',
        'sharingRules/Account.sharingRules-meta.xml',
        'objects/Invoice__c/Invoice__c.object-meta.xml',
        'objects/Account/fields/Tier__c.field-meta.xml',
        'objects/Account/validationRules/Tier_Required.validationRule-meta.xml',
        'namedCredentials/Billing.namedCredential-meta.xml',
        'externalCredentials/Billing.externalCredential-meta.xml',
        'remoteSiteSettings/Billing.remoteSite-meta.xml',
        'cspTrustedSites/Cdn.cspTrustedSite-meta.xml',
        'connectedApps/Portal.connectedApp-meta.xml',
        'customMetadata/Feature_Flag.Checkout.md-meta.xml',
        'labels/CustomLabels.labels-meta.xml',
    )),
    '`sfdx-project.json`': ('sfdx-project.json', '.forceignore', 'manifest/package.xml',
                            'destructiveChanges.xml'),
    'Only `*-meta.xml` apiVersion changes': (
        SF + 'classes/AccountService.cls-meta.xml',
        SF + 'triggers/AccountTrigger.trigger-meta.xml',
    ),
}


class AnalyzerContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_text = read(SKILL_MD)

    def test_recommended_guides_exist_and_are_linked(self):
        skill_targets = {os.path.normpath(t.partition('#')[0]) for _, t in local_links(SKILL_MD)}
        for guide in pr_analyzer.GUIDE_ORDER:
            with self.subTest(guide=guide):
                self.assertTrue(os.path.isfile(os.path.join(SKILL_ROOT, guide)))
                self.assertIn(os.path.normpath(guide), skill_targets)

    def test_review_path_named_by_the_analyzer_exists(self):
        suggestions = pr_analyzer.generate_suggestions([file_stats('sfdx-project.json')], 0.1, [])
        self.assertIn('follow the Salesforce Review Path in SKILL.md', suggestions[0])
        self.assertIn('salesforce-review-path', anchors(SKILL_MD))

    def test_paths_listed_in_skill_md_are_flagged(self):
        # "Use this path when ... the diff touches ... (the analyzer flags these too)"
        sentence = next(line for line in self.skill_text.split('\n')
                        if line.startswith('Use this path when'))
        self.assertIn('(the analyzer flags these too)', sentence)
        self.assertEqual(set(re.findall(r'`([^`]+)`', sentence)), set(DETECTION_SAMPLES))
        for pattern, path in DETECTION_SAMPLES.items():
            with self.subTest(pattern=pattern):
                files = [file_stats(path)]
                suggestions = pr_analyzer.generate_suggestions(files, 0.1, [])
                self.assertTrue(any(s.startswith('Salesforce change: ') for s in suggestions))
                self.assertIn(pr_analyzer.GUIDE_SF_PLATFORM, pr_analyzer.recommend_guides(files))

    def test_routing_table_matches_recommended_guides(self):
        rows = markdown_table(self.skill_text, '| Changed files | Load |')
        self.assertEqual(len(rows), len(ROUTING_SAMPLES))
        for changed, load, _ in rows:
            keys = [key for key in ROUTING_SAMPLES if changed.startswith(key)]
            self.assertEqual(len(keys), 1, f'no single sample set for the row {changed!r}')
            guides = {link.partition('#')[0] for link in re.findall(r'\]\(([^)]+)\)', load)}
            self.assertTrue(guides, load)
            for path in ROUTING_SAMPLES[keys[0]]:
                with self.subTest(row=keys[0], path=path):
                    recommended = pr_analyzer.recommend_guides([file_stats(path)])
                    # The platform guide is always loaded first
                    self.assertEqual(recommended[0], pr_analyzer.GUIDE_SF_PLATFORM)
                    self.assertLessEqual(guides, set(recommended))


if __name__ == '__main__':
    unittest.main()
