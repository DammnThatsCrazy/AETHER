"""TS <-> Python parity for the ADR-011 D3 common spine envelope.

`packages/shared/spine-envelope.ts` is the HAND-AUTHORED canonical contract
(never generated) and `Backend Architecture/aether-backend/shared/spine/
spine_envelope.py` is its Python mirror. This test fails on field-set drift
(either side, in either direction), on order drift, on divergence of the
no-producer `@unpopulated` field set, on a Python mirror whose pydantic model
does not match its own declared canonical field tuple, and on the envelope
leaving the shared barrel.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]

TS_PATH = REPO_ROOT / "packages" / "shared" / "spine-envelope.ts"
PY_PATH = (
    REPO_ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "spine"
    / "spine_envelope.py"
)
INDEX_PATH = REPO_ROOT / "packages" / "shared" / "index.ts"


# ── Parse the TypeScript side ────────────────────────────────────────────────

def _ts_interface_fields() -> list[str]:
    """Field names of the SpineEnvelope interface, in declaration order."""
    content = TS_PATH.read_text(encoding="utf-8")
    match = re.search(r"export interface SpineEnvelope\s*\{(.*?)\n\}", content, re.DOTALL)
    assert match, "SpineEnvelope interface not found in spine-envelope.ts"
    return re.findall(r"^\s*([a-z_][a-z0-9_]*)\??:", match.group(1), re.M)


def _ts_unpopulated_fields() -> list[str]:
    """Values of the spineEnvelopeUnpopulatedFields const, in declared order."""
    content = TS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export const spineEnvelopeUnpopulatedFields\s*=\s*\[(.*?)\]\s*as const",
        content,
        re.DOTALL,
    )
    assert match, "spineEnvelopeUnpopulatedFields const not found in spine-envelope.ts"
    return re.findall(r"'([a-z_][a-z0-9_]*)'", match.group(1))


# ── Parse the Python mirror side ─────────────────────────────────────────────

def _py_canonical_fields() -> list[str]:
    """Values of SPINE_ENVELOPE_FIELDS, in declared order."""
    content = PY_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"SPINE_ENVELOPE_FIELDS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\)",
        content,
        re.DOTALL,
    )
    assert match, "SPINE_ENVELOPE_FIELDS tuple not found in spine_envelope.py"
    return re.findall(r'"([a-z_][a-z0-9_]*)"', match.group(1))


def _py_unpopulated_fields() -> list[str]:
    """Values of SPINE_ENVELOPE_UNPOPULATED_FIELDS (frozenset)."""
    content = PY_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"SPINE_ENVELOPE_UNPOPULATED_FIELDS:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)",
        content,
        re.DOTALL,
    )
    assert match, "SPINE_ENVELOPE_UNPOPULATED_FIELDS not found in spine_envelope.py"
    return re.findall(r'"([a-z_][a-z0-9_]*)"', match.group(1))


def _py_model_fields() -> list[str]:
    """Field names declared on the SpineEnvelope pydantic model, in order."""
    content = PY_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"class SpineEnvelope\(BaseModel\):(.*?)(?=\n__all__|\Z)",
        content,
        re.DOTALL,
    )
    assert match, "SpineEnvelope pydantic model not found in spine_envelope.py"
    return re.findall(r"^\s{4}([a-z_][a-z0-9_]*):", match.group(1), re.M)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_ts_and_py_field_sets_agree() -> None:
    """TypeScript and Python must declare exactly the same SpineEnvelope fields."""
    ts_fields = set(_ts_interface_fields())
    py_fields = set(_py_canonical_fields())
    assert ts_fields == py_fields, (
        "SpineEnvelope field drift.\n"
        f"  TS only: {sorted(ts_fields - py_fields)}\n"
        f"  Py only: {sorted(py_fields - ts_fields)}"
    )


def test_ts_and_py_field_order_agree() -> None:
    """Field order must match too — the envelope field set is order-stable."""
    ts_fields = _ts_interface_fields()
    py_fields = _py_canonical_fields()
    assert ts_fields == py_fields, (
        "SpineEnvelope field order drift.\n"
        f"  TS: {ts_fields}\n"
        f"  Py: {py_fields}"
    )


def test_unpopulated_field_sets_agree() -> None:
    """The TS const and the Python frozenset must name the same no-producer fields."""
    ts_unpopulated = set(_ts_unpopulated_fields())
    py_unpopulated = set(_py_unpopulated_fields())
    assert ts_unpopulated == py_unpopulated, (
        "SpineEnvelope @unpopulated set drift.\n"
        f"  TS only: {sorted(ts_unpopulated - py_unpopulated)}\n"
        f"  Py only: {sorted(py_unpopulated - ts_unpopulated)}"
    )


def test_unpopulated_fields_are_declared_in_both_contracts() -> None:
    """Every @unpopulated field must exist on both the TS interface and the Py model."""
    ts_fields = set(_ts_interface_fields())
    py_fields = set(_py_canonical_fields())
    unpopulated = set(_ts_unpopulated_fields())
    assert unpopulated, "spineEnvelopeUnpopulatedFields must not be empty"
    assert unpopulated <= ts_fields, (
        f"Unpopulated fields missing from TS interface: {sorted(unpopulated - ts_fields)}"
    )
    assert unpopulated <= py_fields, (
        f"Unpopulated fields missing from Python mirror: {sorted(unpopulated - py_fields)}"
    )


def test_python_model_matches_python_field_spec() -> None:
    """The pydantic model must match SPINE_ENVELOPE_FIELDS (set and order)."""
    model_fields = _py_model_fields()
    canonical = _py_canonical_fields()
    assert set(model_fields) == set(canonical), (
        "SpineEnvelope pydantic model drifted from SPINE_ENVELOPE_FIELDS.\n"
        f"  Model only: {sorted(set(model_fields) - set(canonical))}\n"
        f"  Spec only: {sorted(set(canonical) - set(model_fields))}"
    )
    assert model_fields == canonical, (
        "SpineEnvelope pydantic model field order drifted from SPINE_ENVELOPE_FIELDS.\n"
        f"  Model: {model_fields}\n"
        f"  Spec:  {canonical}"
    )


def test_spine_envelope_leaves_the_shared_barrel() -> None:
    """index.ts must re-export the hand-authored envelope contract."""
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert "export * from './spine-envelope';" in index


def test_adr_d3_envelope_field_count_is_stable() -> None:
    """Guard against accidental envelope widening beyond the ADR-011 D3 list."""
    ts_fields = _ts_interface_fields()
    assert len(ts_fields) == 16, (
        f"SpineEnvelope has {len(ts_fields)} fields; ADR-011 D3 enumerates 16. "
        f"Changing the envelope field set requires an ADR update first: {ts_fields}"
    )
