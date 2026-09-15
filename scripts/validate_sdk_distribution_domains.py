#!/usr/bin/env python3
"""Validate the SDK's two origins and the install URL customers actually paste.

Aether serves the SDK from a different origin than its API, deliberately: the
loader is fetched by browsers on customers' pages, while the API is a credential
-bearing surface. Collapsing them into one host would put the ingestion endpoint
behind the same DNS name every page in the world loads, and make the CDN's cache
policy and the API's auth policy one decision instead of two.

Two things follow, and both are checked here.

**The split has to stay a split.** One origin is the default API endpoint the
SDK and the loader send events to; the other is where the loader itself is
served from. They are compared against their real sources rather than a literal
list, so a rename has to happen in the code that uses the value.

**The URL customers paste has one spelling.** Documentation is where an install
actually starts, and a `<script src>` in a guide is copied verbatim. A guide that
names a host that does not serve the loader, or a versioned path that stops
existing at the next release, produces an install that fails silently — the page
loads, nothing throws, and no events arrive. That is the failure this gate
exists for, and it is not hypothetical: every web quickstart in this repo once
pointed at `cdn.aether.io/sdk/v8/aether.min.js`, a host, path, and version that
were all wrong.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

#: The server module that renders the snippet. It owns the install URL: what it
#: emits is what a customer pastes, so it is the authority here.
SERVER_SNIPPET = 'services/backend/services/sdk_distribution/snippet.py'
#: The SDK's own default endpoint.
SDK_ENTRY = 'packages/web/src/index.ts'
#: The loader's default endpoint, resolved for the one-tag install.
LOADER_AUTO_INIT = 'packages/web/src/loader/auto-init.ts'

#: Surfaces a developer copies an install from. Archives and the changelog are
#: excluded on purpose: they are records of what was true when written, and
#: rewriting history to satisfy a gate would destroy the only evidence of it.
SCANNED_GLOBS = (
    'docs/**/*.md',
    'packages/web/README.md',
    'packages/*/README.md',
    'frontend/*/src/pages/*.tsx',
    'frontend/*/src/components/*.tsx',
)
EXCLUDED_PARTS = ('docs/archive/', 'docs/_generated/')


def fail(msg: str) -> None:
    ERRORS.append(msg)


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        fail(f'{rel} does not exist')
        return ''
    return path.read_text(encoding='utf-8')


# --- 1. The two origins, read from the code that uses them -------------------

loader_match = re.search(
    r"""^LOADER_URL\s*=\s*['"]([^'"]+)['"]""", text(SERVER_SNIPPET), re.MULTILINE
)
if not loader_match:
    fail(f'{SERVER_SNIPPET} has no parseable LOADER_URL')
    sys.exit(1)
loader_url = loader_match.group(1)

api_match = re.search(
    r"""^const DEFAULT_ENDPOINT\s*=\s*['"]([^'"]+)['"]""", text(SDK_ENTRY), re.MULTILINE
)
if not api_match:
    fail(f'{SDK_ENTRY} has no parseable DEFAULT_ENDPOINT')
    sys.exit(1)
api_endpoint = api_match.group(1)

loader_origin = urlparse(loader_url)
api_origin = urlparse(api_endpoint)

for label, url in (('LOADER_URL', loader_url), ('DEFAULT_ENDPOINT', api_endpoint)):
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        fail(f'{label} ({url}) is not https; browser clients must not fetch it in the clear')
    if not parsed.netloc:
        fail(f'{label} ({url}) has no host')

# The install URL must be unversioned. A version in the loader path is the
# mistake that broke every quickstart in this repo: it pins customer HTML to a
# release, so the tag 404s the moment the next one ships.
if re.search(r'/v?\d+(\.\d+)*/', loader_origin.path + '/'):
    fail(
        f'LOADER_URL ({loader_url}) carries a version in its path. The loader URL is the '
        'one install URL that must not move when the SDK does, so that customer HTML '
        'never needs re-editing. Serve it from an unversioned path.'
    )

if loader_origin.netloc == api_origin.netloc:
    fail(
        f'LOADER_URL ({loader_url}) and DEFAULT_ENDPOINT ({api_endpoint}) share the host '
        f'{api_origin.netloc}. The split is deliberate: the loader origin is fetched by '
        'every customer page, the API origin is a credential-bearing surface with its '
        'own auth and audit policy. Keep them separable.'
    )

# --- 2. The loader must send install signals where the SDK sends events ------
# The loader is bundled standalone and repeats this literal rather than importing
# it. If the two diverged, the SDK's events and the install signals that verify
# the install would land on different hosts, and the verifier would report every
# working install as `awaiting_first_signal`.

auto_init_src = text(LOADER_AUTO_INIT)
auto_init_match = re.search(
    r"""endpoint:\s*['"]([^'"]+)['"]""", auto_init_src
)
if not auto_init_match:
    fail(f'{LOADER_AUTO_INIT} declares no default endpoint')
elif auto_init_match.group(1) != api_endpoint:
    fail(
        f'{LOADER_AUTO_INIT} defaults to {auto_init_match.group(1)} but {SDK_ENTRY} '
        f'defaults to {api_endpoint}. Install signals would be posted to a different '
        'host than the events they verify.'
    )

# --- 3. Every install example a developer copies must name the loader --------
# A <script src> in a guide is pasted verbatim, so it is checked as a URL rather
# than as prose: whatever it points at is what a customer's page will fetch.
SCRIPT_SRC = re.compile(r"""<script\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

scanned: set[Path] = set()
for pattern in SCANNED_GLOBS:
    for path in ROOT.glob(pattern):
        rel = path.relative_to(ROOT).as_posix()
        if any(part in rel for part in EXCLUDED_PARTS):
            continue
        scanned.add(path)

checked = 0
for path in sorted(scanned):
    rel = path.relative_to(ROOT).as_posix()
    body = path.read_text(encoding='utf-8')
    for src in SCRIPT_SRC.findall(body):
        # Relative and module sources are the frontends' own entry points.
        if not src.startswith(('http://', 'https://')):
            continue
        checked += 1
        if src != loader_url:
            fail(
                f'{rel} installs the SDK from {src}, not the canonical loader URL '
                f'({loader_url}). A developer copies this tag verbatim, so a wrong host '
                'or a versioned path here becomes an install that fails silently.'
            )

if not checked:
    fail(
        'no install <script src> was found in any scanned surface. Either the install '
        'examples were removed or the scan patterns no longer match them, and this gate '
        'is checking nothing.'
    )

if ERRORS:
    print('SDK distribution domain validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

print(
    f'SDK distribution domain validation passed: {checked} install tag(s) across '
    f'{len(scanned)} surface(s) name the canonical loader ({loader_url}), which stays '
    f'separate from the API origin ({api_origin.netloc}) and is unversioned.'
)
