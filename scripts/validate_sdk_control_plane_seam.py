#!/usr/bin/env python3
"""Validate the seam between the SDK distribution layer and the control plane.

Two layers meet here and neither can see the other's vocabulary at runtime:

  * the SDK distribution layer writes a site's install handshake and publishes
    its read view (``services/sdk_distribution/install_verifier.py``);
  * the Reconciled Control Plane reads that view into an observed-state
    snapshot and reconciles it (``services/managed_integrations/sensors.py``).

The dependency runs one way on purpose — the plane owns the observed-state
vocabulary and knows nothing about SDK installs — which means every name that
crosses the seam is written down twice. That is the same hazard as the
loader/verifier seam next door and it fails more quietly: a renamed field does
not raise, it degrades to ``None``, and the plane classifies the integration
from nothing. A site whose install failed would reconcile as ``match``.

So this gate holds the two halves to one vocabulary:

  * every field the plane reads off a described install is a field the
    distribution layer emits, and the install state it dispatches on is one the
    distribution layer declares — both spellings, held together;
  * the version the plane diffs against the desired version is the same field
    the distribution layer derives its own ``drift_status`` and
    ``compatibility_tier`` from, so the install page and the reconcile verdict
    cannot disagree about which side of the desired version a site is on;
  * the health status a failed install produces is one the reconciler treats as
    drift, so the most actionable install state there is cannot reconcile as
    ``match``;
  * the layering itself: the plane never imports the distribution layer, and the
    distribution layer never reaches into the plane's mutation path — it
    observes and registers, it does not reconcile, plan or execute (CP-08).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

VERIFIER = 'services/backend/services/sdk_distribution/install_verifier.py'
SENSORS = 'services/backend/services/managed_integrations/sensors.py'
RECONCILER = 'services/backend/services/managed_integrations/reconciler.py'
CONTROL_PLANE = 'services/backend/services/sdk_distribution/control_plane.py'
VERSIONS = 'services/backend/services/sdk_distribution/versions.py'
TIERS = 'services/backend/services/ingestion/sdk_version_tiers.py'
DESIRED_POLICY = 'services/backend/services/managed_integrations/desired_policy.py'


def fail(msg: str) -> None:
    ERRORS.append(msg)


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        fail(f'{rel} does not exist')
        return ''
    return path.read_text(encoding='utf-8')


verifier_src = text(VERIFIER)
sensors_src = text(SENSORS)
reconciler_src = text(RECONCILER)
control_src = text(CONTROL_PLANE)
versions_src = text(VERSIONS)
tiers_src = text(TIERS)
policy_src = text(DESIRED_POLICY)


def block(src: str, start: str, end: str = r'\n\n\ndef |\n\ndef ') -> str:
    """The text of one top-level function, from its ``def`` to the next one."""
    idx = src.find(start)
    if idx < 0:
        return ''
    rest = src[idx:]
    match = re.search(end, rest[len(start):])
    return rest[: len(start) + match.start()] if match else rest


# --- 1. The install state vocabulary -----------------------------------------
# The distribution layer's state tokens are its STATE_* constants; the plane
# spells them out again because it cannot import them. Both sides must name the
# same set — a state only one side knows is either unreachable or misread.
verifier_states = set(
    re.findall(r"""^STATE_[A-Z]+\s*=\s*['"]([a-z0-9_]+)['"]""", verifier_src, re.MULTILINE)
)
sensor_states = set(
    re.findall(r"""^SITE_STATE_[A-Z]+\s*=\s*['"]([a-z0-9_]+)['"]""", sensors_src, re.MULTILINE)
)

if not verifier_states:
    fail(f'{VERIFIER} declares no STATE_* install states')
if not sensor_states:
    fail(f'{SENSORS} declares no SITE_STATE_* install states')

unread_states = verifier_states - sensor_states
if unread_states:
    fail(
        f'the install verifier can report {", ".join(sorted(unread_states))} but '
        f'{SENSORS} does not recognize it. An unrecognized state resolves to CP-12 '
        'availability `unknown`, so every site in it reads as unclassifiable.'
    )
unknown_states = sensor_states - verifier_states
if unknown_states:
    fail(
        f'{SENSORS} dispatches on {", ".join(sorted(unknown_states))}, which the install '
        f'verifier never reports — that branch is unreachable, and the state it was added '
        'for is silently unhandled.'
    )

# A state in the vocabulary but absent from the availability map resolves to
# CP-12 `unknown` — the install would be visible and unclassifiable at once.
unobserved_block = re.search(
    r'SITE_STATES_UNOBSERVED[^=]*=\s*frozenset\(\s*\{(.*?)\}\s*\)', sensors_src, re.DOTALL
)
availability_block = re.search(
    r'_SITE_STATE_AVAILABILITY[^=]*=\s*\{(.*?)\n\}', sensors_src, re.DOTALL
)
if not unobserved_block or not availability_block:
    fail(f'{SENSORS} has no parseable SITE_STATES_UNOBSERVED / _SITE_STATE_AVAILABILITY')
else:
    by_name = {
        name: value
        for name, value in re.findall(
            r"""^(SITE_STATE_[A-Z]+)\s*=\s*['"]([a-z0-9_]+)['"]""", sensors_src, re.MULTILINE
        )
    }
    unobserved = {
        by_name[name]
        for name in re.findall(r'\b(SITE_STATE_[A-Z]+)\b', unobserved_block.group(1))
        if name in by_name
    }
    mapped = {
        by_name[name]
        for name in re.findall(r'^\s*(SITE_STATE_[A-Z]+)\s*:', availability_block.group(1), re.MULTILINE)
        if name in by_name
    }
    should_map = sensor_states - unobserved
    unmapped = should_map - mapped
    if unmapped:
        fail(
            f'{SENSORS} recognizes {", ".join(sorted(unmapped))} but maps '
            f'{("it" if len(unmapped) == 1 else "them")} to no CP-12 availability, so the '
            'install resolves to `unknown` while looking handled.'
        )
    extra = mapped - should_map
    if extra:
        fail(
            f'{SENSORS} maps {", ".join(sorted(extra))} to an availability but does not '
            'list it as unobserved or recognize it as an install state.'
        )

# The status the distribution layer stores is separate from the state a reader
# sees (a site with no record has a state but no status). The plane reports the
# status as health, so the health-drift set has to know the failure token: a
# failed install reported under a health status the reconciler ignores would
# reconcile as `match`, which is the worst possible answer for a broken install.
verifier_statuses = set(
    re.findall(r"""^STATUS_[A-Z]+\s*=\s*['"]([a-z0-9_]+)['"]""", verifier_src, re.MULTILINE)
)
health_block = re.search(
    r'_UNHEALTHY_STATUSES\s*=\s*frozenset\(\s*\{(.*?)\}\s*\)', reconciler_src, re.DOTALL
)
if not health_block:
    fail(f'{RECONCILER} has no parseable _UNHEALTHY_STATUSES set')
else:
    unhealthy = set(re.findall(r"""['"]([a-z0-9_]+)['"]""", health_block.group(1)))
    if 'failed' not in unhealthy:
        fail(
            f'{RECONCILER} does not treat `failed` as an unhealthy status, but '
            f'{VERIFIER} reports a site install as `failed` when the loader emitted '
            'sdk_init_failed. The install is present and broken — the most actionable '
            'state a managed integration has — and it would reconcile as `match`.'
        )
    if not unhealthy & verifier_statuses:
        fail(
            f'{RECONCILER} treats none of {VERIFIER}\'s statuses '
            f'({", ".join(sorted(verifier_statuses)) or "none declared"}) as unhealthy, so a '
            'broken site install can never produce health drift.'
        )

# --- 2. The fields the plane reads must be the fields the layer emits --------
# ``describe_site_install`` is the read view; its returned dict literal is the
# contract the sensor consumes.
described = block(verifier_src, 'def describe_site_install(')
if not described:
    fail(f'{VERIFIER} has no parseable describe_site_install')
    described_fields: set[str] = set()
else:
    described_fields = set(
        re.findall(r'^\s*"([a-z_]+)":', described, re.MULTILINE)
    )
if not described_fields:
    fail(f'{VERIFIER}.describe_site_install returns no parseable fields')

sensor_src_fn = block(sensors_src, 'def observed_from_site_install(')
if not sensor_src_fn:
    fail(f'{SENSORS} has no parseable observed_from_site_install')
    reads: set[str] = set()
else:
    reads = set(re.findall(r'record\.get\(\s*"([a-z_]+)"', sensor_src_fn))

if not reads:
    fail(f'{SENSORS}.observed_from_site_install reads no fields off the install record')

missing = reads - described_fields
if missing:
    fail(
        f'{SENSORS} reads {", ".join(sorted(missing))} off a site install, but '
        f'{VERIFIER}.describe_site_install does not publish {("it" if len(missing) == 1 else "them")}. '
        'An absent field degrades to None rather than raising, so the plane would '
        'classify the integration from nothing and report it as unobserved.'
    )

# A description that stopped carrying the site identity would leave every
# observation unattributable — the plane's fleet-identity dimension compares the
# reported identity against the registered one, and skips the comparison
# entirely when there is nothing reported.
if 'reported_source_identity' not in sensor_src_fn:
    fail(
        f'{SENSORS}.observed_from_site_install does not report the site as the '
        'observation\'s source identity, so the plane cannot tell a site reporting for '
        'itself from a record filed under the wrong site.'
    )

# --- 3. One version authority, read through one field ------------------------
# The plane diffs `runtime_version` against the desired version. The
# distribution layer derives its own drift verdict. Both must read the same
# field, or the install page and the reconcile verdict disagree.
if 'loader_version' not in reads:
    fail(
        f'{SENSORS}.observed_from_site_install does not read `loader_version`. It is the '
        'field the distribution layer derives drift_status and compatibility_tier from; '
        'reconciling any other field would let the install page and the reconcile verdict '
        'disagree about which side of the desired version a site is on.'
    )

drift_src = block(versions_src, 'def describe_install_version(')
if not drift_src:
    fail(f'{VERSIONS} has no parseable describe_install_version')
else:
    if 'loader_version' not in drift_src:
        fail(
            f'{VERSIONS}.describe_install_version no longer derives drift from '
            '`loader_version`, but the control plane reads that field as the observed '
            'runtime. One of the two has to move.'
        )
    for token in ('compatibility_tier', 'desired_version', 'drift_status'):
        if f'"{token}"' not in drift_src:
            fail(f'{VERSIONS}.describe_install_version no longer publishes {token}')

# Both sides must classify through the same band authority. A second classifier
# would agree until the day it silently did not, and the disagreement would show
# up as the control plane calling an install out of support that the install page
# calls supported.
if 'classify_sdk_version' not in drift_src:
    fail(
        f'{VERSIONS}.describe_install_version does not classify through '
        'sdk_version_tiers.classify_sdk_version.'
    )
policy_fn = block(policy_src, 'def classify_observed_runtime(')
if not policy_fn:
    fail(f'{DESIRED_POLICY} has no parseable classify_observed_runtime')
elif 'classify_sdk_version' not in policy_fn:
    fail(
        f'{DESIRED_POLICY}.classify_observed_runtime no longer classifies through '
        'sdk_version_tiers.classify_sdk_version, so the plane and the SDK distribution '
        'layer would band the same install differently.'
    )
if not re.search(r'^def compare_sdk_versions\(', tiers_src, re.MULTILINE):
    fail(
        f'{TIERS} no longer exposes compare_sdk_versions — the one version parser the '
        'distribution layer\'s drift ordering delegates to.'
    )

# --- 4. The layering --------------------------------------------------------
# The plane is the lower layer and must not know the SDK distribution layer
# exists; if it ever imports it, the two become mutually dependent and neither
# can ship alone.
plane_imports = set(
    re.findall(
        r'^from services\.sdk_distribution|^import services\.sdk_distribution',
        sensors_src + reconciler_src,
        re.MULTILINE,
    )
)
if plane_imports:
    fail(
        f'{SENSORS} / {RECONCILER} import the SDK distribution layer. The plane owns the '
        'observed-state vocabulary and the distribution layer depends on it, not the '
        'reverse — the reverse edge makes each layer unable to ship without the other.'
    )

# CP-08: the distribution layer registers and observes. It must not reach into
# the plane's mutation path — actuators, the executor, the planner, the rollout
# engine or the scheduler. Those run behind the plane's own flags and approval
# gates, and a CDN-adjacent module driving them is the boundary CP-08 draws.
#
# Both import spellings are checked. `from P import m` is the more likely one to
# be written here, and a check that only understands `P.m` would pass while the
# dependency it forbids is sitting in the file.
MUTATION_MODULES = (
    'actuators',
    'executor',
    'change_planning',
    'rollout',
    'scheduler',
    'simulation',
)


def _imports_module(src: str, module: str) -> bool:
    """True when ``src`` imports ``module`` from the plane, in any spelling."""
    if re.search(rf'managed_integrations\.{module}\b', src):
        # `from services.managed_integrations.executor import ...`, `import ...executor`
        return True
    # `from services.managed_integrations import a, b` — every such line, since a
    # file can carry several and the module may be named on any of them.
    for names in re.findall(r'from services\.managed_integrations import ([^\n]+)', src):
        if re.search(rf'\b{module}\b', names):
            return True
    return False


reached = sorted(name for name in MUTATION_MODULES if _imports_module(control_src, name))
if reached:
    fail(
        f'{CONTROL_PLANE} imports the control plane\'s mutation path '
        f'({", ".join(reached)}). The SDK distribution layer registers a site and '
        'reports its install state; reconciling, planning and executing stay behind the '
        "plane's own flags and approvals (CP-08)."
    )

# Registration writes into the plane's stores, so it must be gated on the plane's
# master switch — a deploy that does not run the plane must not accumulate
# control-plane rows from tenants installing the SDK.
if not re.search(r'flags\.enabled\(\)', control_src):
    fail(
        f'{CONTROL_PLANE} does not gate registration on the plane master switch. With '
        'the plane off (the default) a site install would still write control-plane '
        'rows into a plane nobody is running.'
    )

# Registration rides ingestion-adjacent request paths, so it must not be able to
# fail one: the events are already durable, and a plane write is recoverable in a
# way a 5xx on /v1/batch is not.
if not re.search(r'except Exception', control_src):
    fail(
        f'{CONTROL_PLANE} does not swallow its own failures. It is called from the site '
        "creation path, where a control-plane write must not become a failed request."
    )

if ERRORS:
    print('SDK control-plane seam validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)

print(
    f'SDK control-plane seam validation passed: {len(verifier_states)} install '
    f'state(s) in one vocabulary, {len(reads)} field(s) read off the described install, '
    'one version authority on both sides, and the plane\'s mutation path unreached.'
)
