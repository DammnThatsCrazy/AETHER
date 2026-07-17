"""TS <-> Python parity for the canonical interaction vocabulary.

`packages/shared/interaction-contract.ts` and
`shared/product/generated_vocabulary.py` are generated twins of
`packages/shared/contracts/interaction-vocabulary.json`;
`shared/product/models.py` is the hand-authored payload twin of the generated
`InteractionPayload` interface. This test fails on drift in any vocabulary,
on payload field drift, and if the TS module is not exported from the barrel.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.product.generated_vocabulary import (  # noqa: E402
    INTERACTION_ACTOR_KINDS,
    INTERACTION_CUSTOM_NAMESPACES,
    INTERACTION_EVIDENCE_BASIS,
    INTERACTION_RESULT_STATES,
    INTERACTION_TYPES,
    INTERACTION_VOCABULARY_VERSION,
)
from shared.product.models import InteractionPayload  # noqa: E402

TS_PATH = REPO_ROOT / "packages" / "shared" / "interaction-contract.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "interaction-vocabulary.json"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in interaction-contract.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in interaction-contract.ts"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_interaction_types_parity():
    assert set(_const_array("interactionTypes")) == set(INTERACTION_TYPES)


def test_custom_namespaces_parity():
    assert set(_const_array("interactionCustomNamespaces")) == set(INTERACTION_CUSTOM_NAMESPACES)


def test_result_states_parity():
    assert set(_const_array("interactionResultStates")) == set(INTERACTION_RESULT_STATES)


def test_evidence_basis_parity():
    assert set(_const_array("interactionEvidenceBasis")) == set(INTERACTION_EVIDENCE_BASIS)


def test_actor_kinds_parity():
    assert set(_const_array("interactionActorKinds")) == set(INTERACTION_ACTOR_KINDS)


def test_payload_field_parity():
    ts_fields = _interface_fields("InteractionPayload")
    py_fields = set(InteractionPayload.model_fields.keys())
    assert ts_fields == py_fields, (
        f"InteractionPayload drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_payload_required_fields():
    required = {
        name for name, field in InteractionPayload.model_fields.items() if field.is_required()
    }
    assert required == {"tenant_id", "event_id", "occurred_at"}


def test_payload_forbids_unknown_fields():
    assert InteractionPayload.model_config.get("extra") == "forbid"


def test_generated_vocabulary_matches_registry():
    """Generated Python vocabulary mirrors the JSON registry (regen if this fails)."""
    registry = _registry()
    assert INTERACTION_VOCABULARY_VERSION == registry["contractVersion"]
    assert list(INTERACTION_TYPES) == registry["interactionTypes"]
    assert list(INTERACTION_CUSTOM_NAMESPACES) == registry["customNamespaces"]
    assert list(INTERACTION_RESULT_STATES) == registry["resultStates"]
    assert list(INTERACTION_EVIDENCE_BASIS) == registry["evidenceBasis"]
    assert list(INTERACTION_ACTOR_KINDS) == registry["actorKinds"]


def test_barrel_exports_interaction_contract():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './interaction-contract';" in index
