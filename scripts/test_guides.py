#!/usr/bin/env python3
"""Tests for the reference guides (stdlib unittest; the Node.js check skips without node).

Structure checks keep every guide cheap to load: the review checklist comes
first, so a reviewer can read it and open only the sections the diff needs,
reference lists stay short, and each guide stays under a size cap. Content
checks pin corrected facts so they cannot regress, and example checks run the
✅ code from the guides against the attacks the guides describe.
"""

import os
import re
import json
import shutil
import subprocess
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(_HERE)

# Guides that are a checklist or a human-process document, not a stack guide
CHECKLIST_FIRST_EXEMPT = frozenset({
    'reference/common-bugs-checklist.md',
    'reference/code-review-best-practices.md',
})
CHECKLIST_WITHIN_LINES = 40
MAX_REFERENCE_LINKS = 5
MAX_GUIDE_CHARS = 45_000

_MD_LINK_RE = re.compile(r'\[[^\]]*\]\([^)\s]+\)')
_FENCE_RE = re.compile(r'^\s*(`{3,}|~{3,})\s*([\w+-]*)')


def read(relative):
    with open(os.path.join(SKILL_ROOT, relative), encoding='utf-8') as fh:
        return fh.read()


def guides():
    """Relative paths of every Markdown guide under reference/."""
    found = []
    for directory, subdirs, names in os.walk(os.path.join(SKILL_ROOT, 'reference')):
        subdirs.sort()
        for name in sorted(names):
            if name.endswith('.md'):
                path = os.path.join(directory, name)
                found.append(os.path.relpath(path, SKILL_ROOT).replace(os.sep, '/'))
    return found


def fenced_blocks(text):
    """(language, code) for each fenced code block."""
    blocks, fence, language, lines = [], None, '', []
    for line in text.split('\n'):
        match = _FENCE_RE.match(line)
        if fence is None and match:
            fence, language, lines = match.group(1), match.group(2).lower(), []
        elif fence is not None and line.strip() == fence[0] * len(line.strip()) \
                and len(line.strip()) >= len(fence):
            blocks.append((language, '\n'.join(lines)))
            fence = None
        elif fence is not None:
            lines.append(line)
    return blocks


def section(text, heading):
    """Body of the section whose heading line is exactly `heading`, up to the next
    heading of the same or a higher level ('' when there is no such heading)."""
    level = len(heading) - len(heading.lstrip('#'))
    lines = text.split('\n')
    if heading not in lines:
        return ''
    start = lines.index(heading) + 1
    body = []
    for line in lines[start:]:
        match = re.match(r'^(#{1,6})\s', line)
        if match and len(match.group(1)) <= level:
            break
        body.append(line)
    return '\n'.join(body)


def code_block_containing(text, marker, language=None):
    """The first fenced block (optionally of a language) whose code contains marker."""
    for block_language, code in fenced_blocks(text):
        if marker in code and (language is None or block_language == language):
            return code
    raise AssertionError(f'no {language or ""} code block contains {marker!r}')


class GuideTestCase(unittest.TestCase):
    def assertAbsent(self, phrase, text):
        """assertNotIn without printing the whole guide on failure."""
        self.assertFalse(phrase in text, f'{phrase!r} is still in the guide')


class HelperTest(unittest.TestCase):
    """The helpers above, so the guide tests cannot pass vacuously."""

    def test_fenced_blocks(self):
        text = '\n'.join(['intro', '````js', 'a()', '```', 'b()', '````', 'x', '~~~', 'c()', '~~~'])
        self.assertEqual(fenced_blocks(text), [('js', 'a()\n```\nb()'), ('', 'c()')])

    def test_section(self):
        text = '\n'.join(['# T', '## A', 'one', '### A.1', 'two', '## B', 'three'])
        self.assertEqual(section(text, '## A'), 'one\n### A.1\ntwo')
        self.assertEqual(section(text, '### A.1'), 'two')
        self.assertEqual(section(text, '## Missing'), '')

    def test_code_block_containing(self):
        text = '```python\nx = 1\n```\n```js\nconst y = 2;\n```'
        self.assertEqual(code_block_containing(text, 'const y'), 'const y = 2;')
        with self.assertRaises(AssertionError):
            code_block_containing(text, 'x = 1', language='js')

    def test_guides_are_found(self):
        found = guides()
        self.assertIn('reference/salesforce/apex.md', found)
        self.assertIn('reference/cross-cutting/xss-prevention.md', found)


# ═══════════════════════════════════════════════════════════════
# Structure: cheap to load
# ═══════════════════════════════════════════════════════════════

class GuideStructureTest(unittest.TestCase):
    def test_review_checklist_comes_first(self):
        # SKILL.md tells the reviewer to read a guide's checklist first and open
        # other sections only for patterns present in the diff.
        for guide in guides():
            if guide in CHECKLIST_FIRST_EXEMPT:
                continue
            with self.subTest(guide=guide):
                lines = read(guide).split('\n')
                positions = [i for i, line in enumerate(lines) if line == '## Review Checklist']
                self.assertEqual(len(positions), 1, 'exactly one "## Review Checklist"')
                self.assertLess(positions[0], CHECKLIST_WITHIN_LINES)
                self.assertNotIn('## Table of Contents', lines)

    def test_reference_lists_are_short(self):
        # Reviews cannot follow most documentation links (developer.salesforce.com
        # answers fetch tools with 403), so each link costs tokens for nothing.
        for guide in guides():
            with self.subTest(guide=guide):
                links = _MD_LINK_RE.findall(section(read(guide), '## References'))
                self.assertLessEqual(len(links), MAX_REFERENCE_LINKS)

    def test_guides_fit_the_size_cap(self):
        for guide in guides():
            with self.subTest(guide=guide):
                self.assertLessEqual(len(read(guide)), MAX_GUIDE_CHARS)

    def test_no_shell_search_recipes_or_live_scanners(self):
        # Searches go through the Grep tool (ripgrep syntax); shell pipelines need
        # permission prompts, and live scanners attack running systems.
        shell_search = re.compile(r'(?m)^\s*(?:\$\s*)?(?:grep|egrep|fgrep|xargs)\s|\|\s*xargs\s')
        for guide in guides():
            text = read(guide)
            with self.subTest(guide=guide):
                self.assertNotRegex(text, shell_search)
                self.assertNotRegex(text, r'(?i)\bsqlmap\b|\bzap-cli\b')


# ═══════════════════════════════════════════════════════════════
# Content: corrected facts
# ═══════════════════════════════════════════════════════════════

class CorrectedFactsTest(GuideTestCase):
    def test_trigger_bodies_run_in_user_mode_at_api_67(self):
        # Apex Developer Guide v67.0, "Implementation in Apex Triggers": database
        # operations within trigger bodies run in user mode unless system mode is
        # explicitly specified; the trigger context itself stays without sharing.
        for path in ('SKILL.md', 'reference/salesforce/platform.md',
                     'reference/salesforce/apex-triggers.md', 'scripts/pr-analyzer.py'):
            with self.subTest(path=path):
                self.assertNotRegex(read(path), r'(?i)system mode at every API version')
        for path in ('reference/salesforce/platform.md', 'reference/salesforce/apex-triggers.md'):
            with self.subTest(path=path):
                self.assertRegex(read(path), r'(?is)trigger bod(?:y|ies).{0,250}?user mode')

    def test_guest_reachability_needs_class_access(self):
        # Since the @AuraEnabled guest restriction, a guest calls Apex only when the
        # guest profile or a permission set grants the class.
        text = section(read('reference/salesforce/platform.md'), '### Guest and Experience Cloud users')
        self.assertRegex(text, r'(?is)\bonly (?:when|if)\b[^.]{0,250}classAccesses')

    def test_async_triggers_respect_the_enqueue_limit(self):
        # One enqueue per asynchronous transaction: a second chunk that enqueues
        # again throws an uncatchable LimitException.
        text = read('reference/salesforce/apex-triggers.md')
        self.assertAbsent('enqueue at most once per chunk', text)
        self.assertRegex(text, r'Limits\.getQueueableJobs\(\)|System\.is(?:Batch|Queueable|Future)\(\)')

    def test_finalizers_are_not_mandatory(self):
        text = read('reference/salesforce/apex.md')
        self.assertAbsent('Finalizer to every Queueable', text)
        self.assertAbsent('Every Queueable attaches a Finalizer', text)

    def test_standard_set_controller_limit(self):
        # A QueryLocator over 10,000 rows throws LimitException; only the List
        # constructor truncates and reports getCompleteResult() == false.
        text = read('reference/salesforce/visualforce.md')
        self.assertAbsent('`getCompleteResult()` returns false when the query matched more', text)
        self.assertIn('LimitException', text)

    def test_lwc_cannot_load_third_party_scripts(self):
        text = read('reference/salesforce/lwc.md')
        self.assertAbsent('A CDN script needs a CSP Trusted Site', text)
        self.assertAbsent('blocked unless someone adds a CSP Trusted Site', text)
        self.assertRegex(text, r"(?is)(?:can't|cannot|can not) load[^.]{0,120}(?:third-party|CDN|external)")

    def test_lwc_allows_sobject_returns(self):
        self.assertAbsent('### Return DTOs, not raw sObjects', read('reference/salesforce/lwc.md'))

    def test_new_field_permissions_exempt_required_fields(self):
        # PermissionSet fieldPermissions: permissions for required fields can't be
        # retrieved or deployed (API 30.0+).
        text = section(read('reference/salesforce/metadata.md'),
                       '### Ship field-level security with every new field')
        self.assertTrue(text, 'section heading changed; update this test')
        self.assertRegex(text, r"(?is)required fields.{0,200}(?:can't|cannot) be retrieved or deployed")
        self.assertIn('master-detail', text)

    def test_flow_loop_limit_math(self):
        self.assertAbsent('the 101st throws, and all 200 saves roll back', read('reference/salesforce/flows.md'))

    def test_visualforce_contexts_use_jsencode(self):
        # Secure Coding Guide: with automatic HTML encoding, JSENCODE is enough;
        # JSINHTMLENCODE double-encodes.
        self.assertAbsent('JSINHTMLENCODE', read('reference/cross-cutting/xss-prevention.md'))

    def test_csp_nonce_is_per_request(self):
        for guide in guides():
            with self.subTest(guide=guide):
                self.assertAbsent("'nonce-{random}'", read(guide))

    def test_one_severity_scale(self):
        # SKILL.md: 🔴 / 🟡 / 🟢 are the severity tiers for every finding.
        text = read('reference/security-review-guide.md')
        self.assertNotRegex(text, r'\|\s*\*\*(?:Critical|High|Medium|Low|Info)\*\*\s*\|')
        self.assertIn('🔴', text)

    def test_font_display_swap_is_not_a_cls_fix(self):
        self.assertAbsent('Does font loading use `font-display: swap`?', read('reference/performance-review-guide.md'))

    def test_eafp_is_not_an_anti_pattern(self):
        # `.get(...) or default` replaces valid falsy values such as 0.
        self.assertAbsent('users.get(name) or create_default_user(name)', read('reference/cross-cutting/error-handling-principles.md'))

    def test_awaiting_loops_are_cancellable(self):
        self.assertAbsent("Can't be cancelled cleanly", read('reference/python.md'))

    def test_type_assertion_example_really_lies(self):
        # Strings have .length too, so this assertion was harmless.
        self.assertAbsent('(value as string[]).length', read('reference/typescript.md'))


# ═══════════════════════════════════════════════════════════════
# Examples: the ✅ code holds up against the attacks it claims to stop
# ═══════════════════════════════════════════════════════════════

class ExampleCodeTest(unittest.TestCase):
    def test_python_ssrf_allowlist_rejects_parser_confusion(self):
        code = code_block_containing(read('reference/security-review-guide.md'),
                                     'def is_safe_url', language='python')
        good = code[code.rindex('✅', 0, code.index('def is_safe_url')):]
        good = good.split('\n', 1)[1]  # drop the ✅ comment line
        fake_requests = types.ModuleType('requests')
        fake_requests.get = lambda *args, **kwargs: None
        namespace = {}
        saved = sys.modules.get('requests')
        sys.modules['requests'] = fake_requests
        try:
            exec(compile(good, 'security-review-guide.md', 'exec'), namespace)
        finally:
            if saved is None:
                del sys.modules['requests']
            else:
                sys.modules['requests'] = saved
        is_safe_url = namespace['is_safe_url']
        for url in ('https://api.example.com/v1/items?id=3', 'https://cdn.example.com/logo.png'):
            with self.subTest(url=url):
                self.assertTrue(is_safe_url(url))
        for url in (
            'https://evil.com\\@api.example.com/',   # urlparse sees api.example.com; requests connects to evil.com
            'https://user:pw@api.example.com/',     # userinfo
            'https://api.example.com@evil.com/',
            'http://api.example.com/',              # not HTTPS
            'https://api.example.com.evil.com/',
            'https://evil.com/',
        ):
            with self.subTest(url=url):
                self.assertFalse(is_safe_url(url))

    @unittest.skipUnless(shutil.which('node'), 'needs Node.js')
    def test_node_redirect_target_stays_on_origin(self):
        code = code_block_containing(read('reference/nodejs.md'), 'function safeRedirectTarget')
        start = code.index('function safeRedirectTarget')
        end = code.index('\n}', start) + 2
        script = '\n'.join([
            "const config = { APP_ORIGIN: 'https://app.example.com' };",
            code[start:end],
            'const inputs = JSON.parse(process.argv[1]);',
            'const out = inputs.map((input) => {',
            '  const target = safeRedirectTarget(input);',
            '  const resolved = new URL(target, config.APP_ORIGIN);',
            '  return [input, target, resolved.origin, resolved.pathname + resolved.search];',
            '});',
            'console.log(JSON.stringify(out));',
        ])
        attacks = ['/.//evil.example', '/a/..//evil.example', '/%2e//evil.example',
                   'https://app.example.com//evil.example', '//evil.example', '/\\evil.example',
                   'https://evil.example/', 'javascript:alert(1)']
        valid = ['/orders/42?tab=items']
        result = subprocess.run(['node', '-e', script, json.dumps(attacks + valid)],
                                capture_output=True, text=True, timeout=30, check=True)
        for input_value, target, origin, path in json.loads(result.stdout):
            with self.subTest(input=input_value):
                self.assertEqual(origin, 'https://app.example.com')
                # A protocol-relative Location header leaves the site
                self.assertFalse(target.startswith(('//', '/\\')), target)
        self.assertEqual(json.loads(result.stdout)[-1][3], '/orders/42?tab=items')


if __name__ == '__main__':
    unittest.main()
