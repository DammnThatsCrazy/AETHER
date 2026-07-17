"""TS <-> Python parity for the context-capsule contract.

`packages/shared/context-capsule.ts` and
`shared/context_capsule/generated_taxonomy.py` are generated twins of
`packages/shared/contracts/context-capsule-registry.json`;
`shared/context_capsule/models.py` is the hand-authored twin of the generated
`LocationObservation` / `ContextCapsule` interfaces. This test fails on
vocabulary or field drift, if the TS module leaves the barrel, if a raw-IP or
lat/lon field sneaks into the contract, and if `capsule_hash` loses its
determinism guarantees.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.context_capsule.generated_taxonomy import (  # noqa: E402
    CAPSULE_TRANSITION_TYPES,
    CONTEXT_CAPSULE_CONTRACT_VERSION,
    CONTEXT_RETENTION_CLASS_NAMES,
    CONTEXT_RETENTION_CLASSES,
    CONTEXT_STATES,
    LOCATION_CONFLICT_STATES,
    LOCATION_PRECISION_CLASSES,
    LOCATION_SEMANTICS,
    LOCATION_SOURCES,
)
from shared.context_capsule.models import (  # noqa: E402
    CAPSULE_HASH_FIELDS,
    ContextCapsule,
    LocationObservation,
    capsule_hash,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "context-capsule.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "context-capsule-registry.json"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in context-capsule.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in context-capsule.ts"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_location_sources_parity():
    assert set(_const_array("locationSources")) == set(LOCATION_SOURCES)


def test_location_semantics_parity():
    assert set(_const_array("locationSemantics")) == set(LOCATION_SEMANTICS)


def test_precision_classes_parity():
    assert set(_const_array("locationPrecisionClasses")) == set(LOCATION_PRECISION_CLASSES)


def test_conflict_states_parity():
    assert set(_const_array("locationConflictStates")) == set(LOCATION_CONFLICT_STATES)


def test_context_states_parity():
    assert set(_const_array("contextStates")) == set(CONTEXT_STATES)


def test_retention_class_names_parity():
    assert set(_const_array("contextRetentionClassNames")) == set(CONTEXT_RETENTION_CLASS_NAMES)
    assert set(CONTEXT_RETENTION_CLASS_NAMES) == set(CONTEXT_RETENTION_CLASSES)


def test_capsule_transition_types_parity():
    assert set(_const_array("capsuleTransitionTypes")) == set(CAPSULE_TRANSITION_TYPES)


def test_location_observation_field_parity():
    ts_fields = _interface_fields("LocationObservation")
    py_fields = set(LocationObservation.model_fields.keys())
    assert ts_fields == py_fields, (
        f"LocationObservation drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_context_capsule_field_parity():
    ts_fields = _interface_fields("ContextCapsule")
    py_fields = set(ContextCapsule.model_fields.keys())
    assert ts_fields == py_fields, (
        f"ContextCapsule drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_no_raw_ip_or_latlon_fields():
    """The privacy shape of the contract: no raw IP, no precise coordinates."""
    for model in (LocationObservation, ContextCapsule):
        fields = set(model.model_fields.keys())
        assert not {"ip", "ip_address", "raw_ip"} & fields, f"raw IP field in {model.__name__}"
        assert not {"lat", "latitude", "lon", "lng", "longitude"} & fields, (
            f"precise coordinate field in {model.__name__}"
        )


def test_generated_taxonomy_matches_registry():
    """Generated Python taxonomy mirrors the JSON registry (regen if this fails)."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert CONTEXT_CAPSULE_CONTRACT_VERSION == registry["contractVersion"]
    assert list(LOCATION_SOURCES) == registry["locationSources"]
    assert list(LOCATION_SEMANTICS) == registry["locationSemantics"]
    assert list(LOCATION_PRECISION_CLASSES) == registry["precisionClasses"]
    assert list(LOCATION_CONFLICT_STATES) == registry["conflictStates"]
    assert list(CONTEXT_STATES) == registry["contextStates"]
    assert list(CAPSULE_TRANSITION_TYPES) == registry["capsuleTransitionTypes"]
    assert CONTEXT_RETENTION_CLASSES == registry["retentionClasses"]


def test_barrel_exports_context_capsule():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './context-capsule';" in index


# ---------------------------------------------------------------------------
# capsule_hash determinism
# ---------------------------------------------------------------------------

_BASE_FIELDS = {
    "tenant_id": "t1",
    "session_id": "s1",
    "capsule_version": 1,
    "valid_from": datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
    "actor_id": "actor-1",
    "actor_kind": "human",
    "device_id": "dev-1",
    "device_platform": "ios",
    "network_connection_type": "wifi",
    "network_vpn_likelihood": 0.1,
    "geo_country_code": "US",
    "geo_city": "Portland",
    "campaign_id": "camp-1",
    "journey_stage": "activation",
    "consent_snapshot_id": "consent-1",
    "schema_version": "1.0.0",
}


def test_capsule_hash_ignores_construction_order():
    """Same logical capsule built in a different field order hashes identically."""
    forward = dict(_BASE_FIELDS)
    backward = dict(reversed(list(_BASE_FIELDS.items())))
    a = ContextCapsule(capsule_id="cap-a", **forward)
    b = ContextCapsule(capsule_id="cap-a", **backward)
    assert capsule_hash(a) == capsule_hash(b)


def test_capsule_hash_ignores_lineage_fields():
    """capsule_id/version/validity/prior/source/context_hash never affect the hash."""
    a = ContextCapsule(capsule_id="cap-a", **_BASE_FIELDS)
    changed = dict(
        _BASE_FIELDS,
        capsule_version=7,
        valid_from=datetime(2026, 7, 2, 9, 30, 0, tzinfo=timezone.utc),
        valid_to=datetime(2026, 7, 3, 9, 30, 0, tzinfo=timezone.utc),
    )
    b = ContextCapsule(
        capsule_id="cap-b",
        prior_capsule_id="cap-a",
        source_event_id="evt-9",
        context_hash="stale",
        **changed,
    )
    assert capsule_hash(a) == capsule_hash(b)


def test_capsule_hash_changes_with_device():
    a = ContextCapsule(capsule_id="cap-a", **_BASE_FIELDS)
    b = ContextCapsule(capsule_id="cap-a", **{**_BASE_FIELDS, "device_id": "dev-2"})
    assert capsule_hash(a) != capsule_hash(b)


def test_capsule_hash_allowlist_excludes_lineage():
    excluded = {
        "capsule_id",
        "capsule_version",
        "valid_from",
        "valid_to",
        "prior_capsule_id",
        "source_event_id",
        "context_hash",
    }
    assert not excluded & set(CAPSULE_HASH_FIELDS)
    assert set(CAPSULE_HASH_FIELDS) <= set(ContextCapsule.model_fields.keys())
