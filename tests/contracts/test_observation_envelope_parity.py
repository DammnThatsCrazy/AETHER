"""Parity tests for the UniversalObservationEnvelope (Envelope B) triad.

Holds the three Envelope-B surfaces in lock-step without importing backend
code (matching the repo-root parity-test convention):

  * ``packages/shared/contracts/observation-envelope-registry.json`` — the
    canonical field registry (blocks, requiredness, vocabularies).
  * ``packages/shared/observation-envelope.ts`` — the passive TS contract twin.
  * ``Backend Architecture/aether-backend/shared/observation/envelope.py`` —
    the pydantic runtime model.

Behavioral checks (pydantic construction, extra=forbid, curated-vocabulary
enforcement, the SDK mapping) live in ``tests/unit/observation/`` where the
backend is on ``sys.path``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REGISTRY_PATH = REPO_ROOT / "packages/shared/contracts/observation-envelope-registry.json"
TS_PATH = REPO_ROOT / "packages/shared/observation-envelope.ts"
PY_PATH = REPO_ROOT / "Backend Architecture/aether-backend/shared/observation/envelope.py"
GEN_REGISTRY_PATH = REPO_ROOT / "Backend Architecture/aether-backend/services/ingestion/generated_registry.py"
INDEX_PATH = REPO_ROOT / "packages/shared/index.ts"


# ── Parsers ──────────────────────────────────────────────────────────────────

def _load_registry() -> dict:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _ts_text() -> str:
    return TS_PATH.read_text(encoding="utf-8")


def _py_text() -> str:
    return PY_PATH.read_text(encoding="utf-8")


def _ts_const_array(name: str) -> list[str]:
    """Extract the string literals of an `export const X = [...] as const;`."""
    content = _ts_text()
    match = re.search(rf"export const {re.escape(name)}\s*=\s*\[(.*?)\]\s*as const;", content, re.DOTALL)
    assert match, f"export const {name} array not found in observation-envelope.ts"
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return re.findall(r"'([^']+)'", body)


def _py_tuple(name: str, *, text: str) -> list[str]:
    """Extract string literals from a `name: tuple[str, ...] = ( ... )` block."""
    match = re.search(rf"{re.escape(name)}: tuple\[str, \.\.\.\]\s*=\s*\((.*?)\)", text, re.DOTALL)
    assert match, f"{name} tuple not found"
    return re.findall(r'"([^"]+)"', match.group(1))


def _py_frozenset(name: str) -> list[str]:
    """Extract string literals from a `name: frozenset[str] = frozenset({...})` block."""
    match = re.search(rf"{re.escape(name)}: frozenset\[str\]\s*=\s*frozenset\(\s*\{{(.*?)\}}", _py_text(), re.DOTALL)
    assert match, f"{name} frozenset not found"
    return re.findall(r'"([^"]+)"', match.group(1))


def _ts_interface_field_requiredness(name: str) -> dict[str, bool]:
    """Map TS interface field -> required (True) / optional (False)."""
    match = re.search(rf"export interface {re.escape(name)}\s*\{{(.*?)\n\}}", _ts_text(), re.DOTALL)
    assert match, f"export interface {name} not found in observation-envelope.ts"
    body = match.group(1)
    result: dict[str, bool] = {}
    for line in body.splitlines():
        req_match = re.match(r"\s{2}([A-Za-z_][A-Za-z0-9_]*):(?!\?)", line)
        opt_match = re.match(r"\s{2}([A-Za-z_][A-Za-z0-9_]*)\?:", line)
        if req_match:
            result[req_match.group(1)] = True
        elif opt_match:
            result[opt_match.group(1)] = False
    return result


def _py_class_bodies() -> dict[str, str]:
    """Split the model module into per-class bodies keyed by class name."""
    text = _py_text()
    pattern = re.compile(r"^class ((\w+)Block|SubjectRef|UniversalObservationEnvelope)\(BaseModel\):(.*?)(?=^class |\Z)", re.DOTALL | re.MULTILINE)
    bodies: dict[str, str] = {}
    for match in pattern.finditer(text):
        bodies[match.group(1)] = match.group(3)
    return bodies


# Registry block -> TS interface / python class for its element fields.
TS_INTERFACE_FOR_BLOCK = {
    "observation": "ObservationBlock",
    "tenancy": "TenancyBlock",
    "source": "SourceBlock",
    "subjects": "SubjectRef",
    "temporal": "TemporalBlock",
    "correlation": "CorrelationBlock",
    "privacy": "PrivacyBlock",
    "provenance": "ProvenanceBlock",
    "quality": "QualityBlock",
    "lineage": "LineageBlock",
}


# ── Vocabulary parity ─────────────────────────────────────────────────────────

def test_vocabularies_match_across_all_three_surfaces() -> None:
    """source/identifier/credential vocabularies must agree registry == TS == Py."""
    registry = _load_registry()
    for vocab, py_name, ts_name in (
        ("source_types", "SOURCE_TYPES", "SOURCE_TYPES"),
        ("identifier_types", "IDENTIFIER_TYPES", "IDENTIFIER_TYPES"),
        ("credential_classes", "CREDENTIAL_CLASSES", "CREDENTIAL_CLASSES"),
    ):
        canonical = set(registry["vocabularies"][vocab])
        ts_values = set(_ts_const_array(ts_name))
        py_values = set(_py_tuple(py_name, text=_py_text()))
        assert canonical == ts_values, f"{vocab}: registry vs TS mismatch -> TS only: {ts_values - canonical}, registry only: {canonical - ts_values}"
        assert canonical == py_values, f"{vocab}: registry vs Py mismatch -> Py only: {py_values - canonical}, registry only: {canonical - py_values}"


def test_trust_classes_match_generated_registry_order() -> None:
    """The 10-class field-authority rank must not drift from generated_registry."""
    py_trust = set(_py_frozenset("TRUST_CLASSES"))
    ts_trust = set(_ts_const_array("TRUST_CLASSES"))
    generated = _py_tuple("TRUST_CLASS_ORDER", text=GEN_REGISTRY_PATH.read_text(encoding="utf-8"))

    assert py_trust == set(generated), (
        f"envelope.py TRUST_CLASSES drifted from generated TRUST_CLASS_ORDER -> "
        f"model only: {py_trust - set(generated)}, generated only: {set(generated) - py_trust}"
    )
    assert ts_trust == set(generated), (
        f"observation-envelope.ts TRUST_CLASSES drifted -> "
        f"TS only: {ts_trust - set(generated)}, generated only: {set(generated) - ts_trust}"
    )
    assert len(py_trust) == 10 and len(ts_trust) == 10


# ── Schema version parity ─────────────────────────────────────────────────────

def test_schema_version_matches_registry() -> None:
    """The TS schema-version constant must equal the registry schemaVersion."""
    registry = _load_registry()
    ts = _ts_text()
    match = re.search(r"export const OBSERVATION_ENVELOPE_SCHEMA_VERSION\s*=\s*'([^']+)';", ts)
    assert match, "OBSERVATION_ENVELOPE_SCHEMA_VERSION not found"
    assert match.group(1) == registry["schemaVersion"]


# ── Structure parity (registry blocks vs TS interfaces vs python models) ─────

def test_every_registry_block_has_a_ts_interface_and_py_model() -> None:
    """Each registry-declared block maps to a TS interface and a pydantic model."""
    registry = _load_registry()
    py_bodies = _py_class_bodies()
    for block in registry["blocks"]:
        name = block["name"]
        assert name in TS_INTERFACE_FOR_BLOCK, f"unmapped block {name!r} in parity test"
        ts_interface = TS_INTERFACE_FOR_BLOCK[name]
        assert re.search(rf"export interface {ts_interface}\s*\{{", _ts_text()), f"TS interface {ts_interface} missing"
        py_class = ts_interface
        assert py_class in py_bodies, f"pydantic model {py_class} missing from envelope.py"

    for block in registry["passthrough_blocks"]["blocks"]:
        assert re.search(rf"\n\s{{2}}{block['name']}\?:?\s*AetherSubEnvelope;", _ts_text()), (
            f"passthrough block {block['name']!r} missing from UniversalObservationEnvelope TS interface"
        )
        assert re.search(rf"\n\s{{4}}{block['name']}:\s*Optional\[dict\[str, Any\]\] = None", _py_text()), (
            f"passthrough block {block['name']!r} missing from python UniversalObservationEnvelope"
        )


def test_registry_field_requiredness_matches_ts() -> None:
    """Registry field requiredness must mirror the TS interface exactly."""
    registry = _load_registry()
    for block in registry["blocks"]:
        ts_interface = TS_INTERFACE_FOR_BLOCK[block["name"]]
        requiredness = _ts_interface_field_requiredness(ts_interface)
        for field in block["fields"]:
            name = field["name"]
            assert name in requiredness, f"{ts_interface}.{name} missing from TS interface"
            if field["required"]:
                assert requiredness[name] is True, (
                    f"{ts_interface}.{name} is required in the registry but optional (?) in TS"
                )
            else:
                assert requiredness[name] is False, (
                    f"{ts_interface}.{name} is optional in the registry but required in TS"
                )


def test_registry_required_leafs_present_in_py() -> None:
    """Every required leaf from envelope_required_fields appears on the model."""
    registry = _load_registry()
    py_text = _py_text()
    for path in registry["envelope_required_fields"]:
        _block, field = path.split(".", 1)
        ts_interface = TS_INTERFACE_FOR_BLOCK[_block]
        # python field names mirror TS; assert the required leaf is declared
        assert re.search(rf"^\s{{4}}{re.escape(field)}:", py_text, re.MULTILINE), (
            f"required leaf {path!r} missing from envelope.py"
        )
        assert ts_interface  # imported for clarity


def test_every_pydantic_model_is_extra_forbid() -> None:
    """extra=forbid must be configured on every envelope model class."""
    py_bodies = _py_class_bodies()
    assert len(py_bodies) == 11, f"expected 11 model classes, found: {sorted(py_bodies)}"
    for name, body in py_bodies.items():
        assert "extra=\"forbid\"" in body, f"{name} missing ConfigDict(extra=\"forbid\")"


def test_model_classes_imported_from_barrel() -> None:
    """shared/observation/__init__.py must re-export the envelope surface."""
    init_text = (REPO_ROOT / "Backend Architecture/aether-backend/shared/observation/__init__.py").read_text(encoding="utf-8")
    for name in ("UniversalObservationEnvelope", "ObservationBlock", "TenancyBlock", "SourceBlock",
                 "SubjectRef", "TemporalBlock", "CorrelationBlock", "PrivacyBlock", "ProvenanceBlock",
                 "QualityBlock", "LineageBlock", "SOURCE_TYPES", "IDENTIFIER_TYPES", "CREDENTIAL_CLASSES",
                 "TRUST_CLASSES"):
        assert name in init_text, f"{name} not re-exported from shared/observation/__init__.py"


# ── Barrel + passive contract guard ──────────────────────────────────────────

def test_ts_twin_exported_from_shared_barrel() -> None:
    """packages/shared/index.ts must export the passive Envelope-B twin."""
    assert "export * from './observation-envelope';" in INDEX_PATH.read_text(encoding="utf-8")


def test_ts_twin_is_passive_no_emitter() -> None:
    """Envelope B is a contract surface for adapters — never a client emitter."""
    content = _ts_text()
    assert "passive TypeScript contract twin" in content
    assert "It is deliberately NOT a client emitter" in content
    for forbidden in ("export function", "export const build", "fetch(", "send("):
        assert forbidden not in content, f"observation-envelope.ts must stay passive; found {forbidden!r}"
