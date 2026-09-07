"""TS <-> Python parity for the connector-taxonomy provider/category mirror.

`packages/shared/connector-taxonomy.ts` is GENERATED (never hand-edited) from
`shared/integration_contracts/catalog.py` (ALL_MANIFESTS four-group union) and
`shared/integration_contracts/experience.py` by
`scripts/generate_connector_taxonomy.py`. This suite is the drift gate:

  1. `python scripts/generate_connector_taxonomy.py --check` must exit 0
     (byte-for-byte parity between the committed TS and a fresh projection).
  2. The semantically important projections (group family membership, entry
     count, readiness states present, experience ordering) are also parsed out
     of the committed TS and compared to the Python single source directly, so
     a failure names the drifted projection even when the generator itself is
     unavailable in a constrained sandbox.

Namespaced (test_integration_catalog_*) so this module never collides with the
backend test tree (the 7b69a028 root-tests basename-collision class).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.integration_contracts.catalog import (  # noqa: E402
    AD_MANIFESTS,
    ALL_MANIFESTS,
    CONNECTOR_MANIFESTS,
    DEFERRED_CREDIT_BUREAU_MANIFESTS,
    PAYMENT_RAIL_MANIFESTS,
)
from shared.integration_contracts.experience import (  # noqa: E402
    EXPERIENCE_CATEGORIES,
    experience_category_for,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "connector-taxonomy.ts"

_GROUP_TO_PY_LIST = {
    "connectors": CONNECTOR_MANIFESTS,
    "ad_platforms": AD_MANIFESTS,
    "payment_rails": PAYMENT_RAIL_MANIFESTS,
    "deferred_credit_bureaus": DEFERRED_CREDIT_BUREAU_MANIFESTS,
}
_GROUP_TO_TS_CONST = {
    "connectors": "CONNECTOR_FAMILIES",
    "ad_platforms": "AD_PLATFORM_FAMILIES",
    "payment_rails": "PAYMENT_RAIL_FAMILIES",
    "deferred_credit_bureaus": "DEFERRED_CREDIT_BUREAU_FAMILIES",
}


def _ts_const_array(name: str) -> list[str]:
    """Parse a ``export const NAME = [ 'a' as const, ... ] as const;`` array."""
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        rf"export const {re.escape(name)} = \[(.*?)\]\s*as const;", text, re.S
    )
    assert m, f"const array {name!r} not found in {TS_PATH.name}"
    return re.findall(r"'([^']+)'", m.group(1))


def _ts_number_const(name: str) -> int:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export const {re.escape(name)} = (\d+) as const;", text)
    assert m, f"number const {name!r} not found in {TS_PATH.name}"
    return int(m.group(1))


def _ts_experience_families() -> dict[str | None, list[str]]:
    """Parse the ``EXPERIENCE_CATEGORY_FAMILIES`` object into bucket -> families."""
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"export const EXPERIENCE_CATEGORY_FAMILIES = \{(.*?)\}\s*as const;",
        text,
        re.S,
    )
    assert m, "EXPERIENCE_CATEGORY_FAMILIES not found in connector-taxonomy.ts"
    body = m.group(1)
    out: dict[str | None, list[str]] = {}
    # Property forms:  'experience': [...],   or   null: [...]
    for prop_match in re.finditer(r"('([a-z_]+)'|null)\s*:\s*\[([^\]]*)\]", body):
        key_lit = prop_match.group(1)
        bucket: str | None = None if key_lit == "null" else prop_match.group(2)
        fams = re.findall(r"'([^']+)'", prop_match.group(3))
        out[bucket] = fams
    return out


def _py_group_families() -> dict[str, list[str]]:
    return {
        group: [m.provider_family for m in manifests]
        for group, manifests in _GROUP_TO_PY_LIST.items()
    }


def _py_experience_families() -> dict[str | None, list[str]]:
    out: dict[str | None, list[str]] = {}
    for manifest in ALL_MANIFESTS:
        exp = experience_category_for(manifest)
        bucket = exp.value if exp is not None else None
        out.setdefault(bucket, []).append(manifest.provider_family)
    return out


def test_generator_check_is_clean():
    """The committed mirror is byte-for-byte what the generator produces."""
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_connector_taxonomy.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"connector-taxonomy.ts out of step with catalog.py:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def test_all_manifest_count_parity():
    assert _ts_number_const("CATALOG_ENTRIES_COUNT") == len(ALL_MANIFESTS) == 36
    assert _ts_number_const("ALL_CATALOG_FAMILIES_COUNT") == len(ALL_MANIFESTS) == 36


def test_group_family_parity():
    """Each group's family array in the TS matches the Python catalog list."""
    py_groups = _py_group_families()
    for group_id, py_families in py_groups.items():
        ts_families = _ts_const_array(_GROUP_TO_TS_CONST[group_id])
        assert ts_families == py_families, (
            f"group {group_id} family drift: "
            f"TS-only={set(ts_families) - set(py_families)}, "
            f"PY-only={set(py_families) - set(ts_families)}"
        )
        assert _ts_number_const(f"{_GROUP_TO_TS_CONST[group_id]}_COUNT") == len(
            py_families
        )


def test_experience_families_parity():
    """The derived experience → families map in the TS matches Python."""
    py_exp = _py_experience_families()
    ts_exp = _ts_experience_families()
    assert set(ts_exp.keys()) == set(py_exp.keys()), (
        f"experience bucket drift: TS-only={set(ts_exp) - set(py_exp)}, "
        f"PY-only={set(py_exp) - set(ts_exp)}"
    )
    for bucket in py_exp:
        assert ts_exp[bucket] == py_exp[bucket], (
            f"experience bucket {bucket!r} drift"
        )


def test_experience_category_order_parity():
    ts_order = _ts_const_array("EXPERIENCE_CATEGORY_ORDER")
    py_order = [c.value for c in EXPERIENCE_CATEGORIES]
    assert ts_order == py_order, (
        f"experience category order drift: TS={ts_order} PY={py_order}"
    )
    assert len(py_order) == 8


def test_readiness_states_present_parity():
    ts_states = _ts_const_array("CATALOG_READINESS_STATES_PRESENT")
    py_states = sorted({m.readiness.state.value for m in ALL_MANIFESTS})
    assert ts_states == py_states, (
        f"readiness states present drift: TS={ts_states} PY={py_states}"
    )


def test_catalog_identity_keys_unique_and_wellformed():
    """identity_key uniqueness is enforced at import; pin the well-formedness."""
    keys = [m.identity_key for m in ALL_MANIFESTS]
    assert len(keys) == len(set(keys))
    for key in keys:
        assert re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", key), (
            f"non-canonical identity_key {key!r}"
        )
