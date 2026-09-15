#!/usr/bin/env python3
"""Validate the first-heartbeat contract between the loader and the verifier.

The install verifier answers one question — did the snippet a tenant pasted
actually come up? — and it answers it from events the loader writes. Those two
halves are written in different languages, shipped as different artifacts, and
linked by nothing at runtime: the loader is a standalone script on a CDN, the
verifier is Python on the backend.

That is the same shape as the snippet/loader split next door, and it fails the
same way. A rename on either side produces a system that looks correct and
reports nothing: every install reads `awaiting_first_signal` forever, no error
is raised anywhere, and the only symptom is a dashboard that never turns green.
An operator seeing that cannot tell a broken deploy from a tenant who has not
pasted the tag yet — which is exactly the ambiguity the verifier exists to
remove.

So this gate holds the two halves to one vocabulary:

  * every signal type the loader can emit is a type the verifier reads, and
    vice versa — an event nobody reads is dead weight, an event nobody writes is
    a state that can never be reached;
  * every property the verifier reads off a signal is a property the loader
    writes, because a silently-absent property degrades to `None` and reports a
    healthy install as `unknown`;
  * the install signals must not be routed through the SDK's own queue, since
    the one that matters most — the failure — is reported by the SDK that just
    failed;
  * the verifier's read endpoints exist on the router the install page
    advertises, so a documented URL is never a 404 at the moment someone is
    trying to find out whether their install worked.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

LOADER_HEARTBEAT = 'packages/web/src/loader/heartbeat.ts'
VERIFIER = 'services/backend/services/sdk_distribution/install_verifier.py'
ROUTES = 'services/backend/services/sdk_distribution/routes.py'
MIDDLEWARE = 'services/backend/middleware/middleware.py'


def fail(msg: str) -> None:
    ERRORS.append(msg)


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        fail(f'{rel} does not exist')
        return ''
    return path.read_text(encoding='utf-8')


# --- 1. The signal vocabulary ------------------------------------------------
loader_src = text(LOADER_HEARTBEAT)
signal_union = re.search(
    r"""export type InstallSignal\s*=\s*([^;]+);""", loader_src
)
if not signal_union:
    fail(f'{LOADER_HEARTBEAT} has no parseable InstallSignal union')
    loader_signals: set[str] = set()
else:
    loader_signals = set(re.findall(r"""['"]([a-z0-9_]+)['"]""", signal_union.group(1)))

verifier_src = text(VERIFIER)
verifier_signals = set(
    re.findall(r"""^SIGNAL_[A-Z]+\s*=\s*['"]([a-z0-9_]+)['"]""", verifier_src, re.MULTILINE)
)
# INSTALL_SIGNAL_TYPES is the set the verifier actually dispatches on. If it
# were narrower than the SIGNAL_* constants, a signal could be declared and
# never read back.
types_block = re.search(
    r'INSTALL_SIGNAL_TYPES[^=]*=\s*frozenset\(\s*\{(.*?)\}\s*\)', verifier_src, re.DOTALL
)
if not types_block:
    fail(f'{VERIFIER} has no parseable INSTALL_SIGNAL_TYPES')
else:
    dispatched = set(re.findall(r'\b(SIGNAL_[A-Z]+)\b', types_block.group(1)))
    declared = set(re.findall(r'^(SIGNAL_[A-Z]+)\s*=', verifier_src, re.MULTILINE))
    unread_constants = declared - dispatched
    if unread_constants:
        fail(
            f'{VERIFIER} declares {", ".join(sorted(unread_constants))} but '
            'INSTALL_SIGNAL_TYPES does not dispatch on it — the verifier would never '
            'see that signal, so the state it names is unreachable.'
        )

if not loader_signals:
    fail(f'{LOADER_HEARTBEAT} declares no install signal types')
if not verifier_signals:
    fail(f'{VERIFIER} declares no install signal types')

unread = loader_signals - verifier_signals
if unread:
    fail(
        f'the loader can emit {", ".join(sorted(unread))} but {VERIFIER} never reads it. '
        'An install producing only that signal reports as awaiting_first_signal forever.'
    )
unwritten = verifier_signals - loader_signals
if unwritten:
    fail(
        f'{VERIFIER} reads {", ".join(sorted(unwritten))} but the loader never emits it, '
        'so that state can never be reached. Remove it or teach the loader to report it.'
    )

# --- 2. The properties the verifier reads must be the ones the loader writes --
props_block = re.search(
    r'const properties:\s*Record<string,\s*unknown>\s*=\s*\{(.*?)\n\s*\};',
    loader_src,
    re.DOTALL,
)
if not props_block:
    fail(f'{LOADER_HEARTBEAT} has no parseable properties literal in buildSignalEvent')
    loader_props: set[str] = set()
else:
    loader_props = set(re.findall(r'^\s*([A-Za-z_]\w*)\s*:', props_block.group(1), re.MULTILINE))
# Optional properties are assigned after the literal.
loader_props |= set(re.findall(r'properties\.([A-Za-z_]\w*)\s*=', loader_src))

verifier_reads = set(re.findall(r'properties\.get\(\s*["\']([A-Za-z_]\w*)["\']', verifier_src))

missing_from_loader = verifier_reads - loader_props
if missing_from_loader:
    noun = 'property' if len(missing_from_loader) == 1 else 'properties'
    fail(
        f'{VERIFIER} reads {noun} {", ".join(sorted(missing_from_loader))} that '
        f'{LOADER_HEARTBEAT} never writes. A missing property reads as absent rather '
        'than as an error, so the install would be classified from nothing rather than '
        'reported as malformed.'
    )

# The site is the one property the verifier refuses to guess at, and the loader
# is the only thing that can supply it.
if 'siteId' not in loader_props:
    fail(
        f'{LOADER_HEARTBEAT} does not stamp siteId on install signals. The verifier '
        'cannot attribute a signal to a site without it, and refuses to guess — every '
        'install would be dropped.'
    )
if 'siteId' not in verifier_reads:
    fail(f'{VERIFIER} never reads siteId off an install signal; signals cannot be attributed')

# --- 3. The failure signal must not depend on the thing that failed ----------
# heartbeat.ts states this in prose; it is also a routing fact worth holding,
# because sending the signal through the SDK's queue is the obvious
# simplification and it silently breaks the only signal that matters.
if 'event-queue' in loader_src or 'EventQueue' in loader_src:
    fail(
        f'{LOADER_HEARTBEAT} routes install signals through the SDK event queue. The '
        'signal that matters most is sdk_init_failed — the one case where the SDK is by '
        'definition not working — so it must be posted directly.'
    )

# --- 4. The read endpoints the install page advertises must exist ------------
routes_src = text(ROUTES)
registered = set(re.findall(r'@router\.(?:get|post|patch|delete)\(\s*["\']([^"\']+)["\']', routes_src))
if not registered:
    fail(f'{ROUTES} declares no routes')

# Decorator paths are declared relative to the router's prefix, but the URLs
# handed to operators are written out in full. Both spellings are checked
# against each other, so a prefix change or a typo'd response URL is caught
# rather than shipped as a 404 in an install page.
prefix_match = re.search(r'APIRouter\(\s*prefix\s*=\s*["\']([^"\']+)["\']', routes_src)
if not prefix_match:
    fail(f'{ROUTES} has no parseable router prefix')
else:
    prefix = prefix_match.group(1)
    full_registered = {f'{prefix}{path}' for path in registered}

    # Absolute paths this module hands back to a caller, e.g. in `verify.endpoint`
    # or in an error message telling an operator where to go next. The mount
    # prefix itself is excluded: it is where the router lives, not a route.
    advertised = set(re.findall(r"""["'`](/v1/[a-z0-9/_{}-]+)["'`]""", routes_src))
    advertised.discard(prefix)
    unregistered = advertised - full_registered
    for endpoint in sorted(unregistered):
        fail(
            f'{ROUTES} hands an operator the URL {endpoint}, which is not a route the '
            'router serves. An install page that points at a 404 fails at the exact '
            'moment someone is trying to find out whether their install worked.'
        )

    for endpoint in (f'{prefix}/sites/{{site_id}}/heartbeat', f'{prefix}/sites/{{site_id}}/live'):
        if endpoint not in full_registered:
            fail(
                f'{endpoint} is the verifier read the install page advertises, but it is '
                'not registered. A site cannot be checked without it.'
            )

# --- 5. The site header the loader sends must be the one enforced ------------
loader_header = re.search(r"""['"]X-Aether-Site['"]""", loader_src)
middleware_src = text(MIDDLEWARE)
enforced_header = re.search(r"""get\(["']X-Aether-Site["']\)""", middleware_src)
if loader_header and not enforced_header:
    fail(
        f'{LOADER_HEARTBEAT} declares a site on every batch but {MIDDLEWARE} never reads '
        'X-Aether-Site, so the publishable key binding is not enforced and a key copied '
        'off one page writes for every site the tenant owns.'
    )

if ERRORS:
    print('SDK first-heartbeat contract validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

noun = 'property' if len(verifier_reads) == 1 else 'properties'
print(
    f'SDK first-heartbeat contract validation passed: loader and verifier agree on '
    f'{len(loader_signals)} install signal(s) ({", ".join(sorted(loader_signals))}) and '
    f'{len(verifier_reads)} signaled {noun}, the failure signal bypasses the SDK queue, '
    'and every advertised read endpoint is registered.'
)
