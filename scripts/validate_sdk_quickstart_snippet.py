#!/usr/bin/env python3
"""Validate that the install snippet is one language, spoken in two places.

The snippet is written twice: the server renders it
(``services/backend/services/sdk_distribution/snippet.py``) and the loader
interprets it (``packages/web/src/loader/auto-init.ts``). Nothing links the two
at runtime — the loader is a standalone script on a CDN and the server is
Python — so a rename on one side produces a snippet that looks right, installs
nothing, and reports no error, because a loader attribute it does not recognise
is silently ignored.

This gate is that link. It fails when:
  * the server can emit an attribute the loader does not read;
  * the server's loader URL disagrees with the URL the shipping bundle
    advertises;
  * the snippet cannot name the two attributes it cannot work without.

It checks the *contract*, not the prose: both sides are parsed for the literal
attribute names they use, so this keeps holding when either is refactored as
long as the vocabulary stays shared.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

LOADER_TS = 'packages/web/src/loader/auto-init.ts'
LOADER_BUNDLE = 'packages/web/rollup.loader.mjs'
SERVER_SNIPPET = 'services/backend/services/sdk_distribution/snippet.py'


def fail(msg: str) -> None:
    ERRORS.append(msg)


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        fail(f'{rel} does not exist')
        return ''
    return path.read_text(encoding='utf-8')


# --- What the loader reads ---------------------------------------------------
# ATTRIBUTE_MAP is the loader's single interpretation point: every attribute it
# understands is a key there, and anything not listed is ignored.
loader_src = text(LOADER_TS)
attr_block = re.search(r'const ATTRIBUTE_MAP = \{(.*?)\} as const;', loader_src, re.DOTALL)
if not attr_block:
    fail(f'{LOADER_TS} has no parseable ATTRIBUTE_MAP — the loader/snippet contract cannot be checked')
    loader_attributes: set[str] = set()
else:
    loader_attributes = set(re.findall(r"""['"](data-[a-z-]+)['"]\s*:""", attr_block.group(1)))
    if not loader_attributes:
        fail(f'{LOADER_TS} ATTRIBUTE_MAP declares no data-* attributes')

# --- What the server can emit ------------------------------------------------
# The snippet builder writes some attributes literally and some through module
# constants. Both spellings count, so collect the literals it renders and the
# values of the constants it references.
server_src = text(SERVER_SNIPPET)
server_literals = set(re.findall(r"""['"](data-[a-z-]+)['"]""", server_src))
server_constants = {
    name: value
    for name, value in re.findall(r"""^(ATTR_[A-Z_]+)\s*=\s*['"](data-[a-z-]+)['"]""",
                                  server_src, re.MULTILINE)
}
server_attributes = server_literals | set(server_constants.values())
if not server_attributes:
    fail(f'{SERVER_SNIPPET} declares no data-* attributes — the builder emits nothing')

# --- 1. The server must not emit an attribute the loader ignores -------------
unknown = server_attributes - loader_attributes
if unknown:
    fail(
        f'{SERVER_SNIPPET} can emit attribute(s) the loader does not read: '
        f'{", ".join(sorted(unknown))}. The loader ignores unknown attributes '
        'silently, so a snippet naming one installs nothing and reports no error. '
        f'Add them to ATTRIBUTE_MAP in {LOADER_TS}, or stop emitting them.'
    )

# --- 2. The two attributes a snippet cannot work without ---------------------
required = {'data-key', 'data-site'}
for attribute in sorted(required):
    if attribute not in server_attributes:
        fail(f'{SERVER_SNIPPET} never emits {attribute}; a snippet without it cannot install')
    if attribute not in loader_attributes:
        fail(f'{LOADER_TS} does not read {attribute}; a snippet carrying it cannot install')

# --- 3. The loader URL must be the one the shipping bundle advertises --------
bundle_src = text(LOADER_BUNDLE)
bundle_urls = set(re.findall(r'https://cdn\.aether\.network/[A-Za-z0-9._/-]*\.js', bundle_src))
if not bundle_urls:
    fail(f'{LOADER_BUNDLE} advertises no cdn.aether.network loader URL')

server_url_match = re.search(r"""^LOADER_URL\s*=\s*['"]([^'"]+)['"]""", server_src, re.MULTILINE)
if not server_url_match:
    fail(f'{SERVER_SNIPPET} has no parseable LOADER_URL')
else:
    server_url = server_url_match.group(1)
    if bundle_urls and server_url not in bundle_urls:
        fail(
            f'{SERVER_SNIPPET} LOADER_URL is {server_url}, which is not a URL the '
            f'shipping bundle advertises ({", ".join(sorted(bundle_urls))}). Every '
            'snippet the platform renders would 404.'
        )

# --- 4. The snippet must be installed on a site, not on anything -------------
# The site id is what binds a publishable key to one property. A snippet that
# omitted it would mint a key that the loader cannot scope.
if 'data-site' in server_attributes and 'site_id' not in server_src:
    fail(f'{SERVER_SNIPPET} emits data-site but never takes a site_id')

if ERRORS:
    print('SDK quickstart snippet validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

print(
    'SDK quickstart snippet validation passed: the server emits only attributes the '
    f'loader reads ({", ".join(sorted(server_attributes))}), the snippet carries the '
    'key and site it cannot install without, and its loader URL matches the shipping bundle.'
)
