#!/usr/bin/env python3
"""
PR Analyzer - Analyze PR complexity and suggest a review approach.

The analysis is name-based: it parses only the diff text it is given and
never reads repository files. It recognizes JavaScript/TypeScript, Node.js,
NestJS, and Python code, and Salesforce DX projects (Apex, triggers, SOQL,
LWC, Aura, Visualforce, flows, and metadata, in source format or the legacy
MDAPI layout). Salesforce changes get platform-specific risk factors, and the
suggestions end with the reference guides to load for the diff.

Usage:
    python3 pr-analyzer.py [--diff-file FILE] [--stats]

    Or pipe a diff directly:
    git diff main...HEAD | python3 pr-analyzer.py
"""

import os
import sys
import re
import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional

RISK_NO_TESTS = "NO_TEST_CHANGES"
RISK_APEX_NO_TESTS = "APEX_NO_TEST_CHANGES"

# Apex saved at this API version or later is secure by default: a class with
# no sharing keyword runs 'with sharing', database operations run in user
# mode, and WITH SECURITY_ENFORCED no longer compiles.
SECURE_BY_DEFAULT_API_VERSION = 67.0  # Summer '26

# Salesforce language labels
LANG_APEX = 'Apex'
LANG_LWC = 'LWC'
LANG_AURA = 'Aura'
LANG_VISUALFORCE = 'Visualforce'
LANG_FLOW = 'Salesforce Flow'
LANG_SF_METADATA = 'Salesforce Metadata'
LANG_SOQL = 'SOQL'

SALESFORCE_LANGUAGES = frozenset({
    LANG_APEX, LANG_LWC, LANG_AURA, LANG_VISUALFORCE,
    LANG_FLOW, LANG_SF_METADATA, LANG_SOQL,
})

# Salesforce DX project files that are not metadata themselves
SALESFORCE_PROJECT_FILES = frozenset({'sfdx-project.json', '.forceignore'})

# FileStats.change_type values
CHANGE_ADDED = 'added'
CHANGE_DELETED = 'deleted'
CHANGE_RENAMED = 'renamed'
CHANGE_MODIFIED = 'modified'

# Review guides (paths relative to the skill root)
GUIDE_SF_PLATFORM = 'reference/salesforce/platform.md'
GUIDE_SF_APEX = 'reference/salesforce/apex.md'
GUIDE_SF_TRIGGERS = 'reference/salesforce/apex-triggers.md'
GUIDE_SF_SOQL = 'reference/salesforce/soql-sosl.md'
GUIDE_SF_LWC = 'reference/salesforce/lwc.md'
GUIDE_SF_AURA = 'reference/salesforce/aura.md'
GUIDE_SF_VISUALFORCE = 'reference/salesforce/visualforce.md'
GUIDE_SF_FLOWS = 'reference/salesforce/flows.md'
GUIDE_SF_METADATA = 'reference/salesforce/metadata.md'
GUIDE_JAVASCRIPT = 'reference/javascript.md'
GUIDE_TYPESCRIPT = 'reference/typescript.md'
GUIDE_NODEJS = 'reference/nodejs.md'
GUIDE_NESTJS = 'reference/nestjs.md'
GUIDE_PYTHON = 'reference/python.md'

# Fixed order in which recommend_guides() lists guides
GUIDE_ORDER = (
    GUIDE_SF_PLATFORM,
    GUIDE_SF_APEX,
    GUIDE_SF_TRIGGERS,
    GUIDE_SF_SOQL,
    GUIDE_SF_LWC,
    GUIDE_SF_AURA,
    GUIDE_SF_VISUALFORCE,
    GUIDE_SF_FLOWS,
    GUIDE_SF_METADATA,
    GUIDE_JAVASCRIPT,
    GUIDE_TYPESCRIPT,
    GUIDE_NODEJS,
    GUIDE_NESTJS,
    GUIDE_PYTHON,
)

# ---------------------------------------------------------------------------
# Salesforce DX detection (path-based)
# ---------------------------------------------------------------------------

_META_XML = '-meta.xml'

# Component bundles: lwc/<bundle>/... and aura/<bundle>/... Only file types a
# bundle can hold are claimed, so a stray aura/ folder in another kind of
# project keeps its own languages.
_LWC_BUNDLE_RE = re.compile(r'(?:^|/)lwc/[^/]+/')
_AURA_BUNDLE_RE = re.compile(r'(?:^|/)aura/[^/]+/')
_LWC_BUNDLE_EXTENSIONS = frozenset({
    '.js', '.ts', '.html', '.css', '.svg', '.xml', '.json',
})
_AURA_BUNDLE_EXTENSIONS = frozenset({
    '.cmp', '.app', '.evt', '.intf', '.design', '.auradoc', '.tokens',
    '.js', '.css', '.svg', '.xml',
})

# Deployment manifests: manifest/*.xml, an MDAPI src/package.xml, and
# destructiveChanges[Pre|Post].xml anywhere
_MANIFEST_RE = re.compile(
    r'(?:^|/)(?:manifest/[^/]+\.xml|src/package\.xml'
    r'|destructiveChanges(?:Pre|Post)?\.xml)$'
)
_DESTRUCTIVE_CHANGES_RE = re.compile(r'(?:^|/)destructiveChanges(?:Pre|Post)?\.xml$')

# Salesforce source extensions. '.cls' is also the LaTeX class-file
# extension; a name-based analyzer accepts that collision. Aura '.app',
# '.design', and '.tokens' files count only inside an aura/ bundle.
_SALESFORCE_EXTENSIONS = {
    '.cls': LANG_APEX,
    '.trigger': LANG_APEX,
    '.apex': LANG_APEX,
    '.page': LANG_VISUALFORCE,
    '.component': LANG_VISUALFORCE,
    '.soql': LANG_SOQL,
    '.cmp': LANG_AURA,
    '.evt': LANG_AURA,
    '.intf': LANG_AURA,
    '.auradoc': LANG_AURA,
}

# A '<Name>.<suffix>-meta.xml' file whose suffix is a source type takes that
# source's label; every other '-meta.xml' file is Salesforce Metadata.
_SOURCE_TYPE_LANGUAGES = {
    'cls': LANG_APEX,
    'trigger': LANG_APEX,
    'apex': LANG_APEX,
    'page': LANG_VISUALFORCE,
    'component': LANG_VISUALFORCE,
    'flow': LANG_FLOW,
    'flowdefinition': LANG_FLOW,
}

# Legacy MDAPI layout ('<dir>/<Name>.<suffix>', no '-meta.xml'): a file counts
# only when its parent directory and its suffix form a known pair (compared
# case-insensitively), so settings/base.py or docs/README.md are left alone.
_MDAPI_SUFFIX_BY_DIRECTORY = {
    'applications': 'app',
    'authproviders': 'authprovider',
    'connectedapps': 'connectedapp',
    'corswhitelistorigins': 'corswhitelistorigin',
    'csptrustedsites': 'csptrustedsite',
    'custommetadata': 'md',
    'custompermissions': 'custompermission',
    'externalclientapps': 'eca',
    'externalcredentials': 'externalcredential',
    'extlclntappglobaloauthsets': 'ecaglbloauth',
    'extlclntappoauthpolicies': 'ecaoauthplcy',
    'extlclntappoauthsettings': 'ecaoauth',
    'extlclntapppolicies': 'ecaplcy',
    'flexipages': 'flexipage',
    'flowdefinitions': 'flowdefinition',
    'flows': 'flow',
    'globalvaluesets': 'globalvalueset',
    'groups': 'group',
    'labels': 'labels',
    'layouts': 'layout',
    'mutingpermissionsets': 'mutingpermissionset',
    'namedcredentials': 'namedcredential',
    'objects': 'object',
    'permissionsetgroups': 'permissionsetgroup',
    'permissionsets': 'permissionset',
    'profiles': 'profile',
    'remotesitesettings': 'remotesite',
    'roles': 'role',
    'samlssoconfigs': 'samlssoconfig',
    'settings': 'settings',
    'sharingrules': 'sharingrules',
    'sharingsets': 'sharingset',
    'standardvaluesets': 'standardvalueset',
    'staticresources': 'resource',
    'tabs': 'tab',
    'workflows': 'workflow',
}

# Salesforce labels that mark code rather than configuration
_SALESFORCE_CODE_LANGUAGES = frozenset({
    LANG_APEX, LANG_LWC, LANG_AURA, LANG_VISUALFORCE, LANG_FLOW, LANG_SOQL,
})

# Apex test classes, matched case-sensitively on the class name:
# AccountServiceTest, AccountService_Test, AccountServiceTests,
# Test_AccountService, TestAccountService, TestDataFactory,
# AccountTestDataFactory (but not Contest, Testing, or TestimonialService)
_APEX_TEST_CLASS_PATTERNS = (
    re.compile(r'(?:^|/)[A-Za-z0-9_]*Tests?\.cls(?:-meta\.xml)?$'),
    re.compile(r'(?:^|/)Test(?:_|[A-Z])[A-Za-z0-9_]*\.cls(?:-meta\.xml)?$'),
    re.compile(
        r'(?:^|/)[A-Za-z0-9_]*Test(?:Data|Factory|Utils?|Utility|Helper|Setup|Builder)'
        r'[A-Za-z0-9_]*\.cls(?:-meta\.xml)?$'
    ),
)

# Metadata type suffixes (lowercase) grouped by review risk
_ACCESS_CONTROL_TYPES = frozenset({
    'profile', 'permissionset', 'permissionsetgroup', 'mutingpermissionset',
    'sharingrules', 'sharingcriteriarule', 'sharingownerrule',
    'sharingguestrule', 'sharingterritoryrule',
    'role', 'group', 'sharingset',
})
# Decomposed permission sets keep their parts under permissionsets/<Name>/
_PERMISSION_SET_DIRECTORY_RE = re.compile(r'(?:^|/)permissionsets/', re.IGNORECASE)
_INTEGRATION_TYPES = frozenset({
    'namedcredential', 'externalcredential', 'remotesite', 'csptrustedsite',
    'connectedapp', 'authprovider', 'corswhitelistorigin', 'samlssoconfig',
    # External Client Apps
    'eca', 'ecaoauth', 'ecaglbloauth', 'ecaoauthplcy', 'ecaoauthsecurity',
    'ecaplcy', 'ecacanvas', 'ecamobile', 'ecamobileplcy', 'ecanotifications',
    'ecapush', 'ecapushplcy', 'ecasamlplcy',
})
_SCHEMA_TYPES = frozenset({
    'object', 'field', 'validationrule', 'recordtype',
    'globalvalueset', 'standardvalueset',
})

# Apex meta files whose <apiVersion> change is tracked by parse_diff()
_APEX_META_SUFFIXES = ('.cls-meta.xml', '.trigger-meta.xml')
_API_VERSION_LINE_RE = re.compile(r'^([+-])\s*<apiVersion>(\d+(?:\.\d+)?)</apiVersion>\s*$')

# Git C-quotes a diff header path that has special characters, including
# non-ASCII names under the default core.quotePath: "b/caf\303\251.md"
_QUOTED_B_PATH_RE = re.compile(r' ("b/(?:[^"\\]|\\.)*")$')
_C_QUOTED_PART_RE = re.compile(r'\\([0-3][0-7]{2}|.)|([^\\]+)')
_C_ESCAPES = {'a': '\a', 'b': '\b', 't': '\t', 'n': '\n', 'v': '\v', 'f': '\f', 'r': '\r'}

# Meta files that only accompany a code file (Foo.cls + Foo.cls-meta.xml)
_CODE_COMPANION_META_RE = re.compile(r'\.(?:cls|trigger|page|component)-meta\.xml$')

_JEST_TESTS_DIRECTORY_RE = re.compile(r'(?:^|/)__tests__/')

# Content hints read from added diff lines (the diff is already in memory;
# repository files are never read). SOQL/SOSL in Apex adds soql-sosl.md;
# Node.js imports or process usage in JS/TS adds nodejs.md.
_SOQL_HINT_RE = re.compile(
    r'\[\s*(?:SELECT|FIND)\b'
    r'|\bDatabase\.(?:query|countQuery|getQueryLocator|getCursor|getPaginationCursor)\w*\s*\('
    r'|\bSearch\.(?:query|find)\s*\(',
    re.IGNORECASE,
)
_NODE_MODULES = (
    r'node:[\w/]+|express|fastify|koa|pg|mysql2|mongodb|mongoose'
    r'|fs|fs/promises|path|child_process|http|https|net|stream|stream/promises|worker_threads|cluster'
)
_NODE_HINT_RE = re.compile(
    r"(?:\brequire\(\s*|\bfrom\s+|\bimport\s*\(\s*)['\"](?:" + _NODE_MODULES + r")['\"]"
    r'|\bprocess\.(?:env|on|once|exit|exitCode|argv|cwd)\b'
)

# NestJS naming conventions (nest-cli.json is matched by name)
_NEST_FILE_RE = re.compile(
    r'\.(?:controller|module|guard|interceptor|pipe|filter|gateway|resolver|dto|entity|strategy)'
    r'(?:\.(?:spec|e2e-spec|test))?\.ts$'
)


@dataclass
class FileStats:
    """Statistics for a single file."""
    filename: str
    additions: int = 0
    deletions: int = 0
    is_test: bool = False
    is_config: bool = False
    language: str = "unknown"
    change_type: str = CHANGE_MODIFIED  # 'added' | 'deleted' | 'renamed' | 'modified'
    api_version_before: Optional[float] = None  # Apex meta files only
    api_version_after: Optional[float] = None  # Apex meta files only
    has_soql: bool = False  # Apex source with SOQL/SOSL in an added line
    uses_node: bool = False  # JS/TS with a Node.js import or process usage in an added line


@dataclass
class PRAnalysis:
    """Complete PR analysis results."""
    total_files: int
    total_additions: int
    total_deletions: int
    files: List[FileStats]
    complexity_score: float
    size_category: str
    estimated_review_time: int
    risk_factors: List[str]
    suggestions: List[str]


def _normalize_path(filename: str) -> str:
    """Use forward slashes so path patterns also match Windows-style paths."""
    return filename.replace('\\', '/')


def _basename(path: str) -> str:
    """Last segment of a normalized path."""
    return path.rpartition('/')[2]


def _suffix(name: str) -> str:
    """Lowercase extension of a file name without the dot ('' if none)."""
    return os.path.splitext(name)[1][1:].lower()


def _mdapi_suffix(path: str) -> Optional[str]:
    """Suffix of a legacy MDAPI file whose parent directory matches it, else None."""
    directory, _, name = path.rpartition('/')
    parent = _basename(directory).lower()
    suffix = _suffix(name)
    if suffix and _MDAPI_SUFFIX_BY_DIRECTORY.get(parent) == suffix:
        return suffix
    return None


def _metadata_type(filename: str) -> Optional[str]:
    """Lowercase metadata type suffix of a Salesforce metadata file, else None.

    Reads '<Name>.<suffix>-meta.xml' in source format and '<dir>/<Name>.<suffix>'
    in the legacy MDAPI layout, e.g. 'profile', 'field', or 'namedcredential'.
    """
    path = _normalize_path(filename)
    name = _basename(path).lower()
    if name.endswith(_META_XML):
        return _suffix(name[:-len(_META_XML)]) or None
    return _mdapi_suffix(path)


def detect_salesforce_language(filename: str) -> Optional[str]:
    """Detect a Salesforce DX language label from the file path alone.

    Returns one of the LANG_* labels, or None when the file is not
    recognizably Salesforce source or metadata.
    """
    path = _normalize_path(filename)
    name = _basename(path).lower()
    ext = os.path.splitext(name)[1]

    # Every file of an LWC or Aura bundle, incl. meta files and Jest tests
    if _LWC_BUNDLE_RE.search(path) and ext in _LWC_BUNDLE_EXTENSIONS:
        return LANG_LWC
    if _AURA_BUNDLE_RE.search(path) and ext in _AURA_BUNDLE_EXTENSIONS:
        return LANG_AURA

    # Source format: Foo.cls-meta.xml -> Apex, Admin.profile-meta.xml -> metadata
    if name.endswith(_META_XML):
        source_type = _suffix(name[:-len(_META_XML)])
        return _SOURCE_TYPE_LANGUAGES.get(source_type, LANG_SF_METADATA)

    if _MANIFEST_RE.search(path):
        return LANG_SF_METADATA

    if ext in _SALESFORCE_EXTENSIONS:
        return _SALESFORCE_EXTENSIONS[ext]

    mdapi_suffix = _mdapi_suffix(path)
    if mdapi_suffix:
        return _SOURCE_TYPE_LANGUAGES.get(mdapi_suffix, LANG_SF_METADATA)

    return None


def detect_language(filename: str) -> str:
    """Detect the language label from the filename (Salesforce paths first)."""
    salesforce_language = detect_salesforce_language(filename)
    if salesforce_language:
        return salesforce_language

    _, ext = os.path.splitext(_basename(_normalize_path(filename)))
    extensions = {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.jsx': 'JavaScript',
        '.mjs': 'JavaScript',
        '.cjs': 'JavaScript',
        '.ts': 'TypeScript',
        '.tsx': 'TypeScript',
        '.mts': 'TypeScript',
        '.cts': 'TypeScript',
        '.sql': 'SQL',
        '.md': 'Markdown',
        '.json': 'JSON',
        '.yaml': 'YAML',
        '.yml': 'YAML',
        '.toml': 'TOML',
        '.css': 'CSS',
        '.scss': 'SCSS',
        '.less': 'Less',
        '.html': 'HTML',
    }
    return extensions.get(ext.lower(), 'unknown')


def is_test_file(filename: str) -> bool:
    """Check if file is a test file (incl. Apex test classes and LWC Jest tests)."""
    path = _normalize_path(filename)
    test_patterns = [
        r'(?:^|/)test_[^/]+\.py$',   # Python: test_handler.py (anchored to path segment)
        r'[^/]+_test\.',             # *_test.<ext>: handler_test.py, parser_test.js
        r'[^/]+\.test\.(?:js|jsx|ts|tsx|mjs|cjs|mts|cts)$',  # JS/TS: handler.test.ts
        r'[^/]+\.spec\.(?:js|jsx|ts|tsx|mjs|cjs|mts|cts)$',  # JS/TS: handler.spec.ts
        r'(?:^|/)tests?/',           # tests/ or test/ directory
        r'(?:^|/)__tests__/',        # __tests__/ directory (Jest, incl. LWC bundles)
        r'(?:^|/)spec/',             # spec/ directory (Jasmine-style suites)
    ]
    if any(re.search(p, path) for p in test_patterns):
        return True
    return any(p.search(path) for p in _APEX_TEST_CLASS_PATTERNS)


def is_config_file(filename: str) -> bool:
    """Check if file is a configuration file.

    Uses explicit known-name matching to avoid flagging data files
    like data.json, openapi.yaml, or swagger.json as config.
    Salesforce metadata such as permission sets is not config; it has
    its own risk factors.
    """
    path = _normalize_path(filename)
    basename = _basename(path)

    # Env files (.env, .env.local, .env.production, ...)
    if basename.startswith('.env'):
        return True

    # Known config filenames (exact match)
    known_config_names = {
        'package.json', 'package-lock.json',
        'tsconfig.json', 'jsconfig.json',
        'babel.config.json', 'babel.config.js',
        'webpack.config.js', 'webpack.config.ts',
        'rollup.config.js', 'vite.config.ts', 'vite.config.js',
        '.eslintrc.json', '.eslintrc.js', '.eslintrc.yml',
        '.prettierrc.json', '.prettierrc.yml', '.prettierrc.js',
        'jest.config.js', 'jest.config.ts',
        'vitest.config.ts', 'vitest.config.js',
        'tailwind.config.js', 'tailwind.config.ts',
        'postcss.config.js',
        'nest-cli.json',
        'docker-compose.yml', 'docker-compose.yaml',
        'Dockerfile',
        'Makefile',
        'pyproject.toml', 'poetry.toml', 'Pipfile',
        'setup.cfg', 'setup.py', 'tox.ini',
        'sfdx-project.json', '.forceignore',
        '.gitignore', '.gitattributes',
    }
    if basename in known_config_names:
        return True

    # Known config path patterns
    config_path_patterns = [
        r'\.github/workflows/[^/]+\.ya?ml$',
        r'\.vscode/',
        r'\.idea/',
        # Salesforce DX: deployment manifests and local CLI state
        r'(?:^|/)manifest/[^/]+\.xml$',
        r'(?:^|/)src/package\.xml$',
        r'(?:^|/)destructiveChanges(?:Pre|Post)?\.xml$',
        r'(?:^|/)\.sfdx?/',
    ]
    if any(re.search(p, path) for p in config_path_patterns):
        return True

    # Salesforce bundles and other Salesforce code stay code even in a folder
    # or file named "config" (lwc/config/config.js is component code).
    if (_LWC_BUNDLE_RE.search(path) or _AURA_BUNDLE_RE.search(path)
            or detect_salesforce_language(path) in _SALESFORCE_CODE_LANGUAGES):
        return False

    # Files with "config" in the name (e.g. app.config.ts, database_config.yml)
    if re.search(r'config\.', basename):
        return True

    # Files under a config/ directory
    if re.search(r'(?:^|/)config/', path):
        return True

    return False


def _record_api_version(stats: FileStats, line: str) -> None:
    """Capture an <apiVersion> change from a '+' or '-' diff line."""
    match = _API_VERSION_LINE_RE.match(line)
    if not match:
        return
    version = float(match.group(2))
    if match.group(1) == '+':
        stats.api_version_after = version
    else:
        stats.api_version_before = version


def _unquote_c_style(quoted: str) -> str:
    """Decode a path git printed in C-style quotes ("caf\\303\\251.md" -> café.md)."""
    raw = bytearray()
    for escape, text in _C_QUOTED_PART_RE.findall(quoted[1:-1]):
        if text:
            raw += text.encode('utf-8')
        elif len(escape) == 3:
            raw.append(int(escape, 8))
        else:
            raw += _C_ESCAPES.get(escape, escape).encode('utf-8')
    return raw.decode('utf-8', errors='replace')


def _diff_header_path(line: str) -> Optional[str]:
    """The b/ side path of a "diff --git a/<path> b/<path>" header, else None.

    The b/ side is matched via a backreference so a literal "b/" inside paths
    like lib/, web/ or db/ can't be mistaken for the prefix. Renames and copies
    have differing paths, so fall back to the b/ side after the separating
    space, which git C-quotes when the path has special characters.
    """
    header = line.rstrip('\r')  # a diff saved with CRLF line endings
    match = re.match(r'diff --git a/(.+?) b/\1$', header)
    if match:
        return match.group(1)
    match = _QUOTED_B_PATH_RE.search(header)
    if match:
        return _unquote_c_style(match.group(1))[len('b/'):]
    match = re.search(r' b/(.+)$', header)
    return match.group(1) if match else None


def parse_diff(diff_content: str) -> List[FileStats]:
    """Parse git diff output and extract file statistics.

    Besides line counts, records each file's change type from the extended
    header lines (new, deleted, renamed, or copied file) and, for Apex class
    and trigger meta files, the <apiVersion> before and after the change.
    Added lines also feed two guide hints: SOQL/SOSL in Apex source
    (has_soql) and Node.js imports or process usage in JS/TS (uses_node).
    """
    files = []
    current_file = None
    in_hunk = False
    track_api_version = False
    scan_soql = False
    scan_node = False

    for line in diff_content.split('\n'):
        # New file header
        if line.startswith('diff --git'):
            if current_file:
                files.append(current_file)
            in_hunk = False
            filename = _diff_header_path(line)
            if filename:
                current_file = FileStats(
                    filename=filename,
                    language=detect_language(filename),
                    is_test=is_test_file(filename),
                    is_config=is_config_file(filename),
                )
                track_api_version = filename.lower().endswith(_APEX_META_SUFFIXES)
                scan_soql = (current_file.language == LANG_APEX
                             and not filename.lower().endswith(_META_XML))
                scan_node = current_file.language in ('JavaScript', 'TypeScript')
            else:
                current_file = None
        elif current_file:
            # Extended header lines come before the first hunk and never
            # start with '+' or '-'. Inside a hunk, "+++"/"---" are content.
            if line.startswith('@@'):
                in_hunk = True
            elif not in_hunk and line.startswith('new file mode'):
                current_file.change_type = CHANGE_ADDED
            elif not in_hunk and line.startswith('deleted file mode'):
                current_file.change_type = CHANGE_DELETED
            elif not in_hunk and line.startswith('rename from '):
                current_file.change_type = CHANGE_RENAMED
            elif not in_hunk and line.startswith('copy from '):
                # A copy creates the destination file
                current_file.change_type = CHANGE_ADDED
            elif line.startswith('+') and (in_hunk or not line.startswith('+++')):
                current_file.additions += 1
                if track_api_version:
                    _record_api_version(current_file, line)
                if scan_soql and not current_file.has_soql and _SOQL_HINT_RE.search(line):
                    current_file.has_soql = True
                if scan_node and not current_file.uses_node and _NODE_HINT_RE.search(line):
                    current_file.uses_node = True
            elif line.startswith('-') and (in_hunk or not line.startswith('---')):
                current_file.deletions += 1
                if track_api_version:
                    _record_api_version(current_file, line)

    if current_file:
        files.append(current_file)

    return files


def calculate_complexity(files: List[FileStats]) -> float:
    """Calculate complexity score (0-1 scale)."""
    if not files:
        return 0.0

    total_changes = sum(f.additions + f.deletions for f in files)

    # Base complexity from size
    size_factor = min(total_changes / 1000, 1.0)

    # Factor for number of files. A code companion meta file changed together
    # with its source (Foo.cls-meta.xml next to Foo.cls) is not counted.
    filenames = {f.filename for f in files}
    counted_files = [
        f for f in files
        if not (_CODE_COMPANION_META_RE.search(f.filename)
                and f.filename[:-len(_META_XML)] in filenames)
    ]
    file_factor = min(len(counted_files) / 20, 1.0)

    # Factor for non-test code ratio
    test_lines = sum(f.additions + f.deletions for f in files if f.is_test)
    non_test_ratio = 1 - (test_lines / max(total_changes, 1))

    # Factor for language diversity
    languages = set(f.language for f in files if f.language != 'unknown')
    lang_factor = min(len(languages) / 5, 1.0)

    complexity = (
        size_factor * 0.4 +
        file_factor * 0.2 +
        non_test_ratio * 0.2 +
        lang_factor * 0.2
    )

    return round(complexity, 2)


def categorize_size(total_changes: int) -> str:
    """Categorize PR size."""
    if total_changes < 50:
        return "XS (Extra Small)"
    elif total_changes < 200:
        return "S (Small)"
    elif total_changes < 400:
        return "M (Medium)"
    elif total_changes < 800:
        return "L (Large)"
    else:
        return "XL (Extra Large) - Consider splitting"


def estimate_review_time(files: List[FileStats], complexity: float) -> int:
    """Estimate review time in minutes."""
    total_changes = sum(f.additions + f.deletions for f in files)

    # Base time: ~1 minute per 20 lines
    base_time = total_changes / 20

    # Adjust for complexity
    adjusted_time = base_time * (1 + complexity)

    # Minimum 5 minutes, maximum 120 minutes
    return max(5, min(120, int(adjusted_time)))


def _is_salesforce_file(f: FileStats) -> bool:
    """Salesforce source, metadata, or a Salesforce DX project file."""
    return (f.language in SALESFORCE_LANGUAGES
            or _basename(_normalize_path(f.filename)) in SALESFORCE_PROJECT_FILES)


def _is_apex_source(f: FileStats) -> bool:
    """Apex class or trigger source (not its -meta.xml, not an anonymous script)."""
    return f.language == LANG_APEX and _suffix(f.filename) in ('cls', 'trigger')


def _is_access_control(f: FileStats) -> bool:
    """Profiles, permission sets (incl. decomposed parts), sharing, roles, groups."""
    metadata_type = _metadata_type(f.filename)
    if metadata_type is None:
        return False
    return (metadata_type in _ACCESS_CONTROL_TYPES
            or bool(_PERMISSION_SET_DIRECTORY_RE.search(_normalize_path(f.filename))))


def _is_deployable_metadata(f: FileStats) -> bool:
    """Salesforce source that deploys as metadata (not scripts, Jest tests, or manifests)."""
    path = _normalize_path(f.filename)
    return (f.language in SALESFORCE_LANGUAGES
            and f.language != LANG_SOQL
            and _suffix(path) != 'apex'
            and not _JEST_TESTS_DIRECTORY_RE.search(path)
            and not _MANIFEST_RE.search(path))


def _crosses_secure_by_default(f: FileStats) -> bool:
    """apiVersion moved from below SECURE_BY_DEFAULT_API_VERSION to at or above it."""
    return (f.api_version_before is not None
            and f.api_version_after is not None
            and f.api_version_before < SECURE_BY_DEFAULT_API_VERSION <= f.api_version_after)


def _salesforce_risks(files: List[FileStats]) -> List[str]:
    """Salesforce-specific risk factors; empty unless Salesforce files changed."""
    if not any(_is_salesforce_file(f) for f in files):
        return []

    risks = []
    present = [f for f in files if f.change_type != CHANGE_DELETED]

    access_control = [f for f in present if _is_access_control(f)]
    if access_control:
        risks.append(
            f"Salesforce access-control metadata changed ({len(access_control)} file(s): "
            "profiles/permission sets/sharing) - check least privilege and field-level security"
        )

    integration = [f for f in present if _metadata_type(f.filename) in _INTEGRATION_TYPES]
    if integration:
        risks.append(
            f"Salesforce integration/credential metadata changed ({len(integration)} file(s): "
            "credentials/endpoints/connected apps) - verify endpoints, OAuth scopes, HTTPS, "
            "and that no secrets are committed"
        )

    apex_sources = [f for f in present if _is_apex_source(f)]
    apex_code = [f for f in apex_sources if not f.is_test]
    apex_tests = [f for f in apex_sources if f.is_test and _suffix(f.filename) == 'cls']
    if apex_code and not apex_tests:
        risks.append(
            f"{RISK_APEX_NO_TESTS}: {len(apex_code)} Apex class/trigger file(s) changed "
            "without Apex test class changes - production deploys need 75% org-wide "
            "coverage and coverage for every trigger"
        )

    triggers = [f for f in apex_sources if _suffix(f.filename) == 'trigger']
    if triggers:
        risks.append(
            f"Apex trigger changed ({len(triggers)} file(s)) - check one trigger per object, "
            "logic in a handler, 200-record bulk safety, and recursion guards"
        )

    flows = [f for f in present if f.language == LANG_FLOW]
    if flows:
        risks.append(
            f"Flow changed ({len(flows)} file(s)) - check active status, entry conditions, "
            "fault paths, data elements inside loops, and run-as context"
        )

    schema = [f for f in present if _metadata_type(f.filename) in _SCHEMA_TYPES]
    if schema:
        risks.append(
            f"Salesforce schema changed ({len(schema)} object/field/validation rule file(s)) "
            "- check data impact, integrations, and deploy order"
        )

    new_fields = [
        f for f in present
        if f.change_type == CHANGE_ADDED and _metadata_type(f.filename) == 'field'
    ]
    if new_fields and not access_control:
        risks.append(
            f"{len(new_fields)} new custom field(s) without permission set/profile changes "
            "- verify field-level security is granted"
        )

    if any(_DESTRUCTIVE_CHANGES_RE.search(_normalize_path(f.filename)) for f in present):
        risks.append(
            "Destructive changes manifest present - deletions are irreversible in the "
            "target org and can drop data"
        )

    deleted = [
        f for f in files
        if f.change_type == CHANGE_DELETED and _is_deployable_metadata(f)
    ]
    if deleted:
        risks.append(
            f"Salesforce metadata deleted from source ({len(deleted)} file(s)) - this does "
            "not delete it from orgs; deploying deletions needs destructiveChanges and may "
            "drop data"
        )

    # Only classes change behavior: triggers run in system mode at every API version.
    raised = [f for f in files
              if f.filename.endswith('.cls-meta.xml') and _crosses_secure_by_default(f)]
    if raised:
        risks.append(
            f"Apex class apiVersion raised to {SECURE_BY_DEFAULT_API_VERSION}+ on {len(raised)} "
            "file(s) - classes without a sharing keyword (and undeclared classes in their "
            "inheritance chain) become 'with sharing', database operations run in user mode, "
            "and WITH SECURITY_ENFORCED no longer compiles"
        )

    return risks


def identify_risk_factors(files: List[FileStats]) -> List[str]:
    """Identify potential risk factors in the PR (Salesforce risks last)."""
    risks = []

    total_changes = sum(f.additions + f.deletions for f in files)
    test_changes = sum(f.additions + f.deletions for f in files if f.is_test)

    if total_changes > 400:
        risks.append("Large PR (>400 lines) - harder to review thoroughly")

    if test_changes == 0 and total_changes > 50:
        risks.append(f"{RISK_NO_TESTS}: No test changes - verify test coverage")

    if total_changes > 100 and test_changes / max(total_changes, 1) < 0.2:
        risks.append("Low test ratio (<20%) - consider adding more tests")

    # Security-sensitive files
    security_patterns = ['.env', 'auth', 'security', 'password', 'token', 'secret']
    for f in files:
        if any(p in f.filename.lower() for p in security_patterns):
            risks.append(f"Security-sensitive file: {f.filename}")
            break

    # Database changes
    for f in files:
        if 'migration' in f.filename.lower() or f.language in ('SQL', LANG_SOQL):
            risks.append("Database changes detected - review carefully")
            break

    # Config changes
    config_files = [f for f in files if f.is_config]
    if config_files:
        risks.append(f"Configuration changes in {len(config_files)} file(s)")

    risks.extend(_salesforce_risks(files))

    return risks


def _has_risk(risks: List[str], code: str) -> bool:
    """True when a risk line carries the code as a whole token.

    RISK_NO_TESTS ("NO_TEST_CHANGES") is a substring of RISK_APEX_NO_TESTS
    ("APEX_NO_TEST_CHANGES"), so a plain substring test would confuse them.
    """
    pattern = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(code) + r'(?![A-Za-z0-9_])')
    return any(pattern.search(r) for r in risks)


def _script_guides(ext: str) -> List[str]:
    """Guides for a bundle script file: JavaScript, plus TypeScript for .ts."""
    if ext == '.js':
        return [GUIDE_JAVASCRIPT]
    if ext == '.ts':
        return [GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT]
    return []


def recommend_guides(files: List[FileStats]) -> List[str]:
    """Recommend reference guides for the changed files.

    Mostly name-based, plus the two content hints set by parse_diff (SOQL/SOSL
    in Apex, Node.js usage in JS/TS). Deterministic: returns guide paths
    (relative to the skill root) in the fixed GUIDE_ORDER, without duplicates.
    """
    selected = set()

    for f in files:
        path = _normalize_path(f.filename)
        basename = _basename(path)
        name = basename.lower()
        ext = os.path.splitext(name)[1]
        language = f.language
        is_project_file = basename in SALESFORCE_PROJECT_FILES

        if language in SALESFORCE_LANGUAGES or is_project_file:
            selected.add(GUIDE_SF_PLATFORM)
        if language == LANG_SF_METADATA or is_project_file or _MANIFEST_RE.search(path):
            selected.add(GUIDE_SF_METADATA)

        if language == LANG_APEX:
            selected.add(GUIDE_SF_APEX)
            if ext == '.trigger' or name.endswith('.trigger' + _META_XML):
                selected.add(GUIDE_SF_TRIGGERS)
        elif language == LANG_SOQL:
            selected.add(GUIDE_SF_SOQL)
        elif language == LANG_LWC:
            selected.add(GUIDE_SF_LWC)
            selected.update(_script_guides(ext))
        elif language == LANG_AURA:
            selected.add(GUIDE_SF_AURA)
            selected.update(_script_guides(ext))
        elif language == LANG_VISUALFORCE:
            selected.add(GUIDE_SF_VISUALFORCE)
        elif language == LANG_FLOW:
            selected.add(GUIDE_SF_FLOWS)
        elif language == 'JavaScript':
            selected.add(GUIDE_JAVASCRIPT)
        elif language == 'TypeScript':
            selected.update((GUIDE_JAVASCRIPT, GUIDE_TYPESCRIPT))
        elif language == 'Python':
            selected.add(GUIDE_PYTHON)

        if basename == 'nest-cli.json' or (language == 'TypeScript' and _NEST_FILE_RE.search(path)):
            selected.update((GUIDE_NESTJS, GUIDE_NODEJS))
        if f.has_soql:
            selected.add(GUIDE_SF_SOQL)
        if f.uses_node:
            selected.update((GUIDE_JAVASCRIPT, GUIDE_NODEJS))

    return [guide for guide in GUIDE_ORDER if guide in selected]


def _salesforce_suggestions(files: List[FileStats]) -> List[str]:
    """Salesforce review hints; empty unless Salesforce files changed."""
    if not any(_is_salesforce_file(f) for f in files):
        return []

    languages = set(f.language for f in files)
    suggestions = [
        "Salesforce change: follow the Salesforce Review Path in SKILL.md - static review "
        "only; never deploy, run Apex or tests, or run data commands against an org"
    ]
    if LANG_APEX in languages:
        suggestions.append(
            "Apex: check bulkification (no SOQL/DML in loops), sharing and CRUD/FLS per the "
            "file's apiVersion, and tests; add soql-sosl.md if queries changed"
        )
    if LANG_LWC in languages or LANG_AURA in languages:
        suggestions.append(
            "LWC/Aura: check the Apex contract (cacheable, AuraHandledException), XSS escape "
            "hatches, and listener cleanup"
        )
    if LANG_VISUALFORCE in languages:
        suggestions.append(
            'Visualforce: check output encoding (escape="false", JSENCODE), CSRF on page '
            'load, and controller sharing'
        )
    if LANG_FLOW in languages:
        suggestions.append(
            "Flows: check entry conditions, fault paths, loops with data elements, and runInMode"
        )
    return suggestions


def generate_suggestions(files: List[FileStats], complexity: float, risks: List[str]) -> List[str]:
    """Generate review suggestions, ending with the guides to load."""
    suggestions = []

    total_changes = sum(f.additions + f.deletions for f in files)

    if total_changes > 800:
        suggestions.append("Consider splitting this PR into smaller, focused changes")

    if complexity > 0.7:
        suggestions.append("High complexity - allocate extra review time")
        suggestions.append("Consider pair reviewing for critical sections")

    if _has_risk(risks, RISK_NO_TESTS):
        suggestions.append("Request test additions before approval")

    # Language-specific suggestions
    languages = set(f.language for f in files)
    if any(f.language == 'TypeScript'
           or (f.language == LANG_LWC and _suffix(f.filename) == 'ts') for f in files):
        suggestions.append("Check for proper type usage (avoid 'any')")
    if 'SQL' in languages:
        suggestions.append("Review for SQL injection and query performance")

    suggestions.extend(_salesforce_suggestions(files))

    if _has_risk(risks, RISK_APEX_NO_TESTS):
        suggestions.append(
            "Request Apex test updates: bulk (200+ records), negative paths, and "
            "System.runAs() permission cases with meaningful Assert messages"
        )

    if not suggestions:
        suggestions.append("Standard review process should suffice")

    guides = recommend_guides(files)
    if guides:
        suggestions.append("Load guides: " + ", ".join(guides))

    return suggestions


def analyze_pr(diff_content: str) -> PRAnalysis:
    """Perform complete PR analysis."""
    files = parse_diff(diff_content)

    total_additions = sum(f.additions for f in files)
    total_deletions = sum(f.deletions for f in files)
    total_changes = total_additions + total_deletions

    complexity = calculate_complexity(files)
    risks = identify_risk_factors(files)
    suggestions = generate_suggestions(files, complexity, risks)

    return PRAnalysis(
        total_files=len(files),
        total_additions=total_additions,
        total_deletions=total_deletions,
        files=files,
        complexity_score=complexity,
        size_category=categorize_size(total_changes),
        estimated_review_time=estimate_review_time(files, complexity),
        risk_factors=risks,
        suggestions=suggestions,
    )


def print_analysis(analysis: PRAnalysis, show_files: bool = False):
    """Print analysis results."""
    print("\n" + "=" * 60)
    print("PR ANALYSIS REPORT")
    print("=" * 60)

    print(f"\n📊 SUMMARY")
    print(f"   Files changed: {analysis.total_files}")
    print(f"   Additions: +{analysis.total_additions}")
    print(f"   Deletions: -{analysis.total_deletions}")
    print(f"   Total changes: {analysis.total_additions + analysis.total_deletions}")

    print(f"\n📏 SIZE: {analysis.size_category}")
    print(f"   Complexity score: {analysis.complexity_score}/1.0")
    print(f"   Estimated review time: ~{analysis.estimated_review_time} minutes")

    if analysis.risk_factors:
        print(f"\n⚠️  RISK FACTORS:")
        for risk in analysis.risk_factors:
            print(f"   • {risk}")

    print(f"\n💡 SUGGESTIONS:")
    for suggestion in analysis.suggestions:
        print(f"   • {suggestion}")

    if show_files:
        print(f"\n📁 FILES:")
        # Group by language
        by_lang: Dict[str, List[FileStats]] = defaultdict(list)
        for f in analysis.files:
            by_lang[f.language].append(f)

        for lang, lang_files in sorted(by_lang.items()):
            print(f"\n   [{lang}]")
            for f in lang_files:
                prefix = "🧪" if f.is_test else "⚙️" if f.is_config else "📄"
                print(f"   {prefix} {f.filename} (+{f.additions}/-{f.deletions})")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Analyze PR complexity')
    parser.add_argument('--diff-file', '-f', help='Path to diff file')
    parser.add_argument('--stats', '-s', action='store_true', help='Show file details')
    args = parser.parse_args()

    # Read diff from file or stdin
    try:
        if args.diff_file:
            with open(args.diff_file, 'r', encoding='utf-8', errors='replace') as f:
                diff_content = f.read()
        elif not sys.stdin.isatty():
            diff_content = sys.stdin.buffer.read().decode('utf-8', errors='replace')
        else:
            print("Usage: git diff main...HEAD | python3 pr-analyzer.py")
            print("       python3 pr-analyzer.py -f diff.txt")
            sys.exit(1)
    except OSError as e:
        print(f"Error reading diff input: {e}", file=sys.stderr)
        sys.exit(1)

    if not diff_content.strip():
        print("No diff content provided")
        sys.exit(1)

    analysis = analyze_pr(diff_content)
    # Windows pipes default to the ANSI code page, which cannot encode the
    # report's emoji; write UTF-8 whatever the locale.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print_analysis(analysis, show_files=args.stats)


if __name__ == '__main__':
    main()
