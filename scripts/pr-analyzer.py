#!/usr/bin/env python3
"""
PR Analyzer - Analyze PR complexity and suggest a review approach.

The analysis is name-based: it parses only the diff text it is given and
never reads repository files. It recognizes JavaScript/TypeScript, Node.js,
NestJS, and Python code, and Salesforce DX projects (Apex, triggers, SOQL,
LWC, Aura, Visualforce, flows, and metadata, in source format or the legacy
MDAPI layout). Salesforce changes get platform-specific risk factors, and the
suggestions end with the reference guides to load for the diff. Lockfiles,
snapshots, and minified files don't count toward size or test risks.

Usage:
    python3 pr-analyzer.py [--diff-file FILE] [--stats]

    Or pipe a diff directly (--no-color and --default-prefix undo user settings
    such as color.ui=always and diff.mnemonicPrefix; the parser copes with them
    anyway):
    git diff --no-color --default-prefix main...HEAD | python3 pr-analyzer.py
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

NO_FILES_MESSAGE = (
    "No files found in the input. Pass unified git diff output, for example: "
    "git diff --no-color --default-prefix main...HEAD | python3 pr-analyzer.py"
)

# Apex saved at this API version or later is secure by default: a class with
# no sharing keyword runs 'with sharing' (unless a parent class declares a
# mode), database operations run in user mode (in trigger bodies too), and
# WITH SECURITY_ENFORCED no longer compiles.
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
    'flowtest': LANG_FLOW,
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
    'flowtests': 'flowtest',
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

# Diff headers. The default prefixes are a/ and b/; diff.mnemonicPrefix uses
# a pair of different letters (i/ w/ c/ o/, or 1/ 2/ for --no-index), and
# diff.noprefix drops them. Renames and copies also name the new path, without
# a prefix, on their "rename to" / "copy to" line.
_STANDARD_HEADER_RE = re.compile(r'diff --git a/(.+?) b/\1$')
_MNEMONIC_HEADER_RE = re.compile(r'diff --git ([icwo12])/(.+?) ([icwo12])/\2$')
_SAME_PATH_HEADER_RE = re.compile(r'diff --git (.+?) \1$')
_QUOTED_PAIR_HEADER_RE = re.compile(r'diff --git ("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*")$')
_NEW_PATH_LINES = ('rename to ', 'copy to ')

# Git C-quotes a diff header path that has special characters, including
# non-ASCII names under the default core.quotePath: "b/caf\303\251.md"
_QUOTED_B_PATH_RE = re.compile(r' ("b/(?:[^"\\]|\\.)*")$')
_C_QUOTED_PART_RE = re.compile(r'\\([0-3][0-7]{2}|.)|([^\\]+)')
_C_ESCAPES = {'a': '\a', 'b': '\b', 't': '\t', 'n': '\n', 'v': '\v', 'f': '\f', 'r': '\r'}

# color.ui=always keeps SGR escape codes in piped output
_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# Generated files: reviewed by their source, so they count toward neither size
# nor test risks
_LOCKFILE_NAMES = frozenset({
    'package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock', 'pnpm-lock.yaml',
    'bun.lock', 'bun.lockb', 'poetry.lock', 'Pipfile.lock', 'uv.lock', 'pdm.lock',
})
_GENERATED_PATH_RE = re.compile(
    r'(?:^|/)__snapshots__/|\.snap$|\.min\.(?:js|css)$|\.(?:js|css)\.map$')

# Security-sensitive names, matched as whole words of the path (camelCase and
# snake_case split), so Author, Authority, or Tokenizer don't match
_SECURITY_WORDS = frozenset({
    'auth', 'authn', 'authz', 'oauth', 'oauth2', 'authenticate', 'authentication',
    'authenticator', 'authorization', 'authorize', 'authorizer', 'security',
    'password', 'passwords', 'passwd', 'secret', 'secrets', 'token', 'tokens',
    'credential', 'credentials', 'jwt', 'saml', 'sso', 'csrf', 'crypto', 'encrypt',
    'decrypt', 'encryption',
})
_CAMEL_BOUNDARY_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
# Docs and Aura design-token bundles (*.tokens) are not sensitive by name
_NOT_SECURITY_SENSITIVE = ('.md', '.tokens', '.tokens-meta.xml')

# Meta files that only accompany a code file (Foo.cls + Foo.cls-meta.xml)
_CODE_COMPANION_META_RE = re.compile(r'\.(?:cls|trigger|page|component)-meta\.xml$')

_JEST_TESTS_DIRECTORY_RE = re.compile(r'(?:^|/)__tests__/')

# Content hints read from diff lines (the diff is already in memory;
# repository files are never read). SOQL/SOSL in Apex adds soql-sosl.md;
# Node.js imports or process usage in JS/TS adds nodejs.md; NestJS imports or
# decorators add nestjs.md; @isTest marks an Apex test class whatever its name.
_SOQL_HINT_RE = re.compile(
    r'\[\s*(?:SELECT|FIND)\b'
    r'|\bDatabase\.(?:query|countQuery|getQueryLocator|getCursor|getPaginationCursor)\w*\s*\('
    r'|\bSearch\.(?:query|find)\s*\('
    # Dynamic query strings: 'SELECT Id FROM …', 'SELECT COUNT() FROM …', 'FIND {…}'
    r"|'\s*SELECT\s+[\w.()]+\s*(?:,|FROM\b)"
    r"|'\s*FIND\s*\{",
    re.IGNORECASE,
)
# The second line of a query split after its bracket (Prettier Apex style)
_SOQL_CONTINUATION_RE = re.compile(r'\s*(?:SELECT|FIND)\b', re.IGNORECASE)
_APEX_TEST_ANNOTATION_RE = re.compile(r'@istest\b', re.IGNORECASE)
_NODE_MODULES = (
    r'node:[\w/]+|express|fastify|koa|pg|mysql2|mongodb|mongoose'
    r'|fs|fs/promises|path|child_process|http|https|net|stream|stream/promises|worker_threads|cluster'
)
_NODE_HINT_RE = re.compile(
    r"(?:\brequire\(\s*|\bfrom\s+|\bimport\s*\(\s*)['\"](?:" + _NODE_MODULES + r")['\"]"
    r'|\bprocess\.(?:env|on|once|exit|exitCode|argv|cwd)\b'
)

# NestJS naming conventions that Angular doesn't share; module, service, guard,
# interceptor, pipe, and resolver files need a content hint instead
# (nest-cli.json is matched by name)
_NEST_FILE_RE = re.compile(
    r'\.(?:controller|dto|entity|gateway|filter|strategy)'
    r'(?:\.(?:spec|e2e-spec|test))?\.ts$'
)
_NEST_HINT_RE = re.compile(
    r"""(?:\bfrom\s+|\brequire\(\s*|\bimport\s*\(\s*)['"]@nestjs/"""
    r'|@(?:Module|Controller)\('
)


@dataclass
class FileStats:
    """Statistics for a single file."""
    filename: str
    additions: int = 0
    deletions: int = 0
    is_test: bool = False
    is_config: bool = False
    is_generated: bool = False  # lockfiles, snapshots, minified files
    language: str = "unknown"
    change_type: str = CHANGE_MODIFIED  # 'added' | 'deleted' | 'renamed' | 'modified'
    api_version_before: Optional[float] = None  # Apex meta files only
    api_version_after: Optional[float] = None  # Apex meta files only
    has_soql: bool = False  # Apex source with SOQL/SOSL in an added line
    uses_node: bool = False  # JS/TS with a Node.js import or process usage in an added line
    uses_nest: bool = False  # JS/TS with a NestJS import or decorator in an added line


@dataclass
class PRAnalysis:
    """Complete PR analysis results."""
    total_files: int
    total_additions: int
    total_deletions: int
    files: List[FileStats]
    complexity_score: float
    size_category: str
    risk_factors: List[str]
    suggestions: List[str]
    generated_changes: int = 0  # lines in generated files, not counted toward size


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
        r'(?:^|/)flowtests/',        # Salesforce flow tests
    ]
    if any(re.search(p, path) for p in test_patterns):
        return True
    return any(p.search(path) for p in _APEX_TEST_CLASS_PATTERNS)


def is_generated_file(filename: str) -> bool:
    """Lockfiles, test snapshots, minified bundles, and source maps."""
    path = _normalize_path(filename)
    return _basename(path) in _LOCKFILE_NAMES or bool(_GENERATED_PATH_RE.search(path))


def _path_words(path: str) -> List[str]:
    """Lowercase words of a path, split at separators and camelCase boundaries."""
    words = []
    for part in re.split(r'[^A-Za-z0-9]+', path):
        words.extend(word.lower() for word in _CAMEL_BOUNDARY_RE.split(part) if word)
    return words


def is_security_sensitive(filename: str) -> bool:
    """Env files, and paths with a security word such as auth, token, or secret."""
    path = _normalize_path(filename)
    name = _basename(path)
    if name in ('.env', '.envrc') or name.startswith('.env.'):
        return True
    if name.lower().endswith(_NOT_SECURITY_SENSITIVE):
        return False
    if _metadata_type(path) in _INTEGRATION_TYPES:
        return False  # Salesforce credentials and endpoints get their own risk line
    return any(word in _SECURITY_WORDS for word in _path_words(path))


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


def _path_from_sides(a_side: str, b_side: str) -> str:
    """The file path from the two unquoted sides of a header ('' if unknown)."""
    if a_side.startswith('a/') and b_side.startswith('b/'):
        return b_side[2:]
    if (a_side[1:2] == b_side[1:2] == '/' and a_side[:1] != b_side[:1]
            and a_side[2:] == b_side[2:]):
        return b_side[2:]  # mnemonic prefixes
    return b_side if a_side == b_side else ''  # no prefixes


def _diff_header_path(line: str) -> Optional[str]:
    """The file path named by a "diff --git <a-side> <b-side>" header, else None.

    Paths are matched with a backreference, so a literal "b/" inside paths like
    lib/, web/ or db/ can't be mistaken for the prefix. Mnemonic prefixes (a
    pair of different letters, e.g. c/ and w/) and no prefixes at all are read
    from headers whose two sides name the same path. Renames and copies have
    differing paths, so fall back to the b/ side after the separating space,
    which git C-quotes when the path has special characters; parse_diff then
    takes the path from the "rename to" / "copy to" line.
    """
    header = line.rstrip('\r')  # a diff saved with CRLF line endings
    match = _STANDARD_HEADER_RE.match(header)
    if match:
        return match.group(1)
    match = _MNEMONIC_HEADER_RE.match(header)
    if match and match.group(1) != match.group(3):
        return match.group(2)
    match = _SAME_PATH_HEADER_RE.match(header)
    if match and not match.group(1).startswith('"'):
        return match.group(1)
    match = _QUOTED_PAIR_HEADER_RE.match(header)
    if match:
        path = _path_from_sides(*(_unquote_c_style(side) for side in match.groups()))
        if path:
            return path
    match = _QUOTED_B_PATH_RE.search(header)
    if match:
        return _unquote_c_style(match.group(1))[len('b/'):]
    match = re.search(r' b/(.+)$', header)
    return match.group(1) if match else None


def _new_path(line: str) -> str:
    """The path of a "rename to <path>" or "copy to <path>" line."""
    path = line.rstrip('\r').split(' ', 2)[2]
    return _unquote_c_style(path) if path.startswith('"') else path


def _classify(stats: FileStats, filename: str) -> FileStats:
    """Set the file name and everything derived from it."""
    stats.filename = filename
    stats.language = detect_language(filename)
    stats.is_test = is_test_file(filename)
    stats.is_config = is_config_file(filename)
    stats.is_generated = is_generated_file(filename)
    return stats


def _scan_modes(stats: FileStats):
    """(track apiVersion, scan Apex source, scan JS/TS) for a file."""
    name = stats.filename.lower()
    return (name.endswith(_APEX_META_SUFFIXES),
            stats.language == LANG_APEX and not name.endswith(_META_XML),
            stats.language in ('JavaScript', 'TypeScript'))


def parse_diff(diff_content: str) -> List[FileStats]:
    """Parse git diff output and extract file statistics.

    Besides line counts, records each file's change type from the extended
    header lines (new, deleted, renamed, or copied file) and, for Apex class
    and trigger meta files, the <apiVersion> before and after the change.
    Diff lines also feed guide hints: SOQL/SOSL in Apex source (has_soql, also
    for a query split after its bracket), @isTest (is_test), and Node.js or
    NestJS usage in JS/TS (uses_node, uses_nest). Color codes are ignored.
    """
    files = []
    current_file = None
    awaiting_path = False  # a header without a readable path; "rename to" may name it
    in_hunk = False
    track_api_version = scan_apex = scan_script = False
    bracket_open = False  # the last new-side Apex line ended with '['

    for line in diff_content.split('\n'):
        if '\x1b' in line:
            line = _ANSI_ESCAPE_RE.sub('', line)
        # New file header
        if line.startswith('diff --git'):
            if current_file:
                files.append(current_file)
            in_hunk = bracket_open = False
            filename = _diff_header_path(line)
            current_file = _classify(FileStats(filename=''), filename) if filename else None
            awaiting_path = current_file is None
            if current_file:
                track_api_version, scan_apex, scan_script = _scan_modes(current_file)
            continue
        # Extended header lines come before the first hunk and never start
        # with '+' or '-'. Inside a hunk, "+++"/"---" are content.
        if not in_hunk and (current_file or awaiting_path) and line.startswith(_NEW_PATH_LINES):
            current_file = _classify(current_file or FileStats(filename=''), _new_path(line))
            awaiting_path = False
            # A copy creates the destination file
            current_file.change_type = (CHANGE_RENAMED if line.startswith('rename')
                                        else CHANGE_ADDED)
            track_api_version, scan_apex, scan_script = _scan_modes(current_file)
            continue
        if not current_file:
            continue
        if line.startswith('@@'):
            in_hunk = True
        elif not in_hunk and line.startswith('new file mode'):
            current_file.change_type = CHANGE_ADDED
        elif not in_hunk and line.startswith('deleted file mode'):
            current_file.change_type = CHANGE_DELETED
        elif not in_hunk and line.startswith('rename from '):
            current_file.change_type = CHANGE_RENAMED
        elif not in_hunk and line.startswith('copy from '):
            current_file.change_type = CHANGE_ADDED
        elif line.startswith('+') and (in_hunk or not line.startswith('+++')):
            current_file.additions += 1
            content = line[1:]
            if track_api_version:
                _record_api_version(current_file, line)
            if scan_apex:
                if not current_file.has_soql and (
                        _SOQL_HINT_RE.search(content)
                        or (bracket_open and _SOQL_CONTINUATION_RE.match(content))):
                    current_file.has_soql = True
                bracket_open = _update_bracket(bracket_open, content)
                _mark_apex_test(current_file, content)
            if scan_script:
                if not current_file.uses_node and _NODE_HINT_RE.search(content):
                    current_file.uses_node = True
                if not current_file.uses_nest and _NEST_HINT_RE.search(content):
                    current_file.uses_nest = True
        elif line.startswith('-') and (in_hunk or not line.startswith('---')):
            current_file.deletions += 1
            if track_api_version:
                _record_api_version(current_file, line)
        elif in_hunk and scan_apex and line.startswith(' '):
            # Unchanged context: part of the new file too
            bracket_open = _update_bracket(bracket_open, line[1:])
            _mark_apex_test(current_file, line[1:])

    if current_file:
        files.append(current_file)

    return files


def _update_bracket(bracket_open: bool, content: str) -> bool:
    """Whether a query may start on the next line; blank lines keep the state."""
    stripped = content.rstrip()
    return stripped.endswith('[') if stripped else bracket_open


def _mark_apex_test(stats: FileStats, content: str) -> None:
    """An @isTest annotation makes the class a test class, whatever its name."""
    if not stats.is_test and _APEX_TEST_ANNOTATION_RE.search(content):
        stats.is_test = True


def reviewable_changes(files: List[FileStats]) -> int:
    """Changed lines outside generated files (lockfiles, snapshots, minified)."""
    return sum(f.additions + f.deletions for f in files if not f.is_generated)


def calculate_complexity(files: List[FileStats]) -> float:
    """Calculate complexity score (0-1 scale); generated files don't count."""
    files = [f for f in files if not f.is_generated]
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
        return "XL (Extra Large)"


def _is_testable_code(f: FileStats) -> bool:
    """Present, non-test source that unit tests cover: Python, JS/TS, LWC and
    Aura scripts, and Apex classes and triggers (not docs, config, metadata,
    or generated files)."""
    if f.is_test or f.is_config or f.is_generated or f.change_type == CHANGE_DELETED:
        return False
    if f.language in ('Python', 'JavaScript', 'TypeScript'):
        return True
    if f.language in (LANG_LWC, LANG_AURA):
        return _suffix(f.filename) in ('js', 'ts')
    return _is_apex_source(f)


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

    flows = [f for f in present if f.language == LANG_FLOW and not f.is_test]
    if flows:
        risks.append(
            f"Flow changed ({len(flows)} file(s)) - check active status, entry conditions, "
            "fault paths, data elements inside loops, and run-as context"
        )

    flow_definitions = [f for f in present if _metadata_type(f.filename) == 'flowdefinition']
    if flow_definitions:
        risks.append(
            f"FlowDefinition in source ({len(flow_definitions)} file(s)) - its "
            "activeVersionNumber overrides each flow's <status> on every deploy; commit one "
            "only for a one-off deactivation (activeVersionNumber 0)"
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

    # A rename deploys a new component; the old one stays in the org. A code
    # file and its companion meta file count once.
    renamed = [f for f in files
               if f.change_type == CHANGE_RENAMED and _is_deployable_metadata(f)]
    renamed_names = {f.filename for f in renamed}
    renamed = [f for f in renamed
               if not (_CODE_COMPANION_META_RE.search(f.filename)
                       and f.filename[:-len(_META_XML)] in renamed_names)]
    if renamed:
        risks.append(
            f"Salesforce metadata renamed in source ({len(renamed)} file(s)) - the old API "
            "name stays in orgs until destructiveChanges removes it, and references to it break"
        )

    # Both change at 67.0: classes get sharing and user-mode defaults; database
    # operations in trigger bodies run in user mode (the trigger context itself
    # stays without sharing).
    raised = [f for f in files
              if f.filename.lower().endswith('.cls-meta.xml') and _crosses_secure_by_default(f)]
    if raised:
        risks.append(
            f"Apex class apiVersion raised to {SECURE_BY_DEFAULT_API_VERSION}+ on {len(raised)} "
            "file(s) - classes without a sharing keyword run 'with sharing' unless a parent "
            "class declares one (undeclared subclasses saved at older versions switch too), "
            "database operations run in user mode, and WITH SECURITY_ENFORCED no longer compiles"
        )
    raised_triggers = [f for f in files if f.filename.lower().endswith('.trigger-meta.xml')
                       and _crosses_secure_by_default(f)]
    if raised_triggers:
        risks.append(
            f"Apex trigger apiVersion raised to {SECURE_BY_DEFAULT_API_VERSION}+ on "
            f"{len(raised_triggers)} file(s) - SOQL, SOSL, and DML in the trigger body run in "
            "user mode (sharing, CRUD, and FLS) unless they specify system mode; the trigger "
            "context itself stays without sharing"
        )

    return risks


def identify_risk_factors(files: List[FileStats]) -> List[str]:
    """Identify potential risk factors in the PR (Salesforce risks last)."""
    risks = []

    if reviewable_changes(files) > 400:
        risks.append("Large PR (>400 lines) - harder to review thoroughly")

    # Test risks weigh only code that unit tests cover: docs, config, metadata,
    # and generated files don't need tests, and deleted code needs none.
    code_changes = sum(f.additions + f.deletions for f in files if _is_testable_code(f))
    test_changes = sum(f.additions + f.deletions for f in files
                       if f.is_test and not f.is_generated)

    if test_changes == 0 and code_changes > 50:
        risks.append(f"{RISK_NO_TESTS}: No test changes - verify test coverage")

    if code_changes > 100 and test_changes / (code_changes + test_changes) < 0.2:
        risks.append("Low test ratio (<20%) - consider adding more tests")

    # Security-sensitive files
    for f in files:
        if is_security_sensitive(f.filename):
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

    Mostly name-based, plus the content hints set by parse_diff (SOQL/SOSL in
    Apex, Node.js and NestJS usage in JS/TS). NestJS adds only nestjs.md;
    nodejs.md comes from Node.js usage. Deterministic: returns guide paths
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

        if (basename == 'nest-cli.json' or f.uses_nest
                or (language == 'TypeScript' and _NEST_FILE_RE.search(path))):
            selected.add(GUIDE_NESTJS)
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

    if reviewable_changes(files) > 800:
        suggestions.append("Very large diff: review the riskiest files first, and list "
                           "anything not reviewed under Scope in the review")

    if complexity > 0.7:
        suggestions.append("High complexity: split the review by area (for example one pass "
                           "per stack), each with only its guides")

    if _has_risk(risks, RISK_NO_TESTS):
        suggestions.append("No tests changed: check that the changed code paths are covered, "
                           "and ask for tests where behavior changed")

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
            "Request Apex test updates: bulk (201+ records, so a second trigger chunk runs), "
            "negative paths, and System.runAs() permission cases with meaningful Assert messages"
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
    reviewable = reviewable_changes(files)

    complexity = calculate_complexity(files)
    risks = identify_risk_factors(files)
    suggestions = generate_suggestions(files, complexity, risks)

    return PRAnalysis(
        total_files=len(files),
        total_additions=total_additions,
        total_deletions=total_deletions,
        files=files,
        complexity_score=complexity,
        size_category=categorize_size(reviewable),
        risk_factors=risks,
        suggestions=suggestions,
        generated_changes=total_additions + total_deletions - reviewable,
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
    if analysis.generated_changes:
        print(f"   Generated (lockfiles, snapshots, minified): {analysis.generated_changes} "
              "lines, not counted toward size")

    print(f"\n📏 SIZE: {analysis.size_category}")
    print(f"   Complexity score: {analysis.complexity_score}/1.0")

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
            print("Usage: git diff --no-color --default-prefix main...HEAD | python3 pr-analyzer.py")
            print("       python3 pr-analyzer.py -f diff.txt")
            sys.exit(1)
    except OSError as e:
        print(f"Error reading diff input: {e}", file=sys.stderr)
        sys.exit(1)

    if not diff_content.strip():
        print("No diff content provided")
        sys.exit(1)

    analysis = analyze_pr(diff_content)
    if not analysis.files:
        # Not git diff output: an empty report would read as "nothing to review"
        print(NO_FILES_MESSAGE, file=sys.stderr)
        sys.exit(1)
    # Windows pipes default to the ANSI code page, which cannot encode the
    # report's emoji; write UTF-8 whatever the locale.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print_analysis(analysis, show_files=args.stats)


if __name__ == '__main__':
    main()
