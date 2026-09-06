"""TS <-> Python parity for the relationship-predicate registry.

`packages/shared/relationship-predicate-registry.ts` and
`shared/relationship_spine/generated_relationship_predicate_registry.py` are
generated twins of `packages/shared/contracts/relationship-predicate-registry.json`.
This test fails on drift in the version, vocabulary arrays, predicate catalog
(per-index scalar/nested parity), duplicate/invalid predicate ids, barrel export
presence, and the honest graph cross-check: every predicate that claims
``graphRegistrationState == "REGISTERED"`` must reference a graphEdgeType that is
a real member of ``shared.graph.graph.EdgeType``.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.graph.graph import EdgeType  # noqa: E402
from shared.relationship_spine.generated_relationship_predicate_registry import (  # noqa: E402
    RELATIONSHIP_PREDICATE_ACTOR_KINDS,
    RELATIONSHIP_PREDICATE_CLAIM_TYPES,
    RELATIONSHIP_PREDICATE_DIRECTIONALITY,
    RELATIONSHIP_PREDICATE_FAMILIES,
    RELATIONSHIP_PREDICATE_GRAPH_REGISTRATION_STATES,
    RELATIONSHIP_PREDICATE_PROOF_LEVELS,
    RELATIONSHIP_PREDICATE_RECIPROCITY_SEMANTICS,
    RELATIONSHIP_PREDICATE_REGISTRY_VERSION,
    RELATIONSHIP_PREDICATE_SENSITIVE_INFERENCE_POLICIES,
    RELATIONSHIP_PREDICATE_SENSITIVE_RELATIONSHIP_LABELS,
    RELATIONSHIP_PREDICATE_STRENGTH_SEMANTICS,
    RELATIONSHIP_PREDICATES,
    RELATIONSHIP_PREDICATE_TRANSITIVITY_CLASSES,
    RELATIONSHIP_PREDICATE_VALIDITY_SEMANTICS,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "relationship-predicate-registry.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "relationship-predicate-registry.json"
INDEX_PATH = REPO_ROOT / "packages" / "shared" / "index.ts"

# json vocab key -> (TS const array name, Python vocab constant)
_VOCAB = {
    "families": ("relationshipPredicateFamilies", RELATIONSHIP_PREDICATE_FAMILIES),
    "directionality": ("relationshipPredicateDirectionality", RELATIONSHIP_PREDICATE_DIRECTIONALITY),
    "reciprocitySemantics": ("relationshipPredicateReciprocitySemantics", RELATIONSHIP_PREDICATE_RECIPROCITY_SEMANTICS),
    "transitivityClasses": ("relationshipPredicateTransitivityClasses", RELATIONSHIP_PREDICATE_TRANSITIVITY_CLASSES),
    "proofLevels": ("relationshipPredicateProofLevels", RELATIONSHIP_PREDICATE_PROOF_LEVELS),
    "graphRegistrationStates": ("relationshipPredicateGraphRegistrationStates", RELATIONSHIP_PREDICATE_GRAPH_REGISTRATION_STATES),
    "validitySemantics": ("relationshipPredicateValiditySemantics", RELATIONSHIP_PREDICATE_VALIDITY_SEMANTICS),
    "claimTypes": ("relationshipPredicateClaimTypes", RELATIONSHIP_PREDICATE_CLAIM_TYPES),
    "strengthSemantics": ("relationshipPredicateStrengthSemantics", RELATIONSHIP_PREDICATE_STRENGTH_SEMANTICS),
    "sensitiveInferencePolicies": ("relationshipPredicateSensitiveInferencePolicies", RELATIONSHIP_PREDICATE_SENSITIVE_INFERENCE_POLICIES),
    "actorKinds": ("relationshipPredicateActorKinds", RELATIONSHIP_PREDICATE_ACTOR_KINDS),
    "sensitiveRelationshipLabels": ("relationshipPredicateSensitiveRelationshipLabels", RELATIONSHIP_PREDICATE_SENSITIVE_RELATIONSHIP_LABELS),
}


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in relationship-predicate-registry.ts"
    return re.findall(r"'([A-Za-z0-9_]+)'", m.group(1))


def _const_version() -> str:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"relationshipPredicateRegistryVersion\s*=\s*'([^']+)'", text)
    assert m, "relationshipPredicateRegistryVersion not found in relationship-predicate-registry.ts"
    return m.group(1)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _ts_object_texts(array_name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{array_name}\s*=\s*\[(.*)\]\s*as const;", text, re.S)
    assert m, f"{array_name} block not found in relationship-predicate-registry.ts"
    body = m.group(1)
    texts: list[str] = []
    depth = 0
    start: int | None = None
    for i, ch in enumerate(body):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                assert start is not None
                texts.append(body[start : i + 1])
    assert texts, f"no object literals found under {array_name}"
    return texts


def _replace_literal(match: re.Match[str]) -> str:
    mapping = {"true": "True", "false": "False", "null": "None"}
    return match.group(1) + mapping[match.group(2)] + match.group(3)


def _ts_object_to_dict(text: str) -> dict:
    # _ts_literal emits dict keys as bare identifiers at the start of a line and
    # string values in single quotes (escaped like Python). Quote the keys and
    # translate true/false/null so ast.literal_eval can parse the object.
    text = re.sub(r'(?m)^(\s*)([A-Za-z_$][A-Za-z0-9_$]*)(?=\s*:)', r'\1"\2"', text)
    text = re.sub(r"(?m)(:\s*)(true|false|null)(\s*,?)$", _replace_literal, text)
    parsed = ast.literal_eval(text)
    assert isinstance(parsed, dict), f"expected a dict literal, got {type(parsed)}"
    return parsed


def _canon(value: object) -> object:
    """Recursive list/tuple-insensitive canonical form for parity comparison."""
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_canon(v) for v in value)
    return value


def _ts_predicates() -> dict[str, dict]:
    return {
        obj["predicate"]: obj
        for obj in (_ts_object_to_dict(t) for t in _ts_object_texts("relationshipPredicates"))
    }


def _py_predicates() -> dict[str, dict]:
    return {p["predicate"]: dict(p) for p in RELATIONSHIP_PREDICATES}


def _json_predicates() -> dict[str, dict]:
    return {p["predicate"]: dict(p) for p in _registry()["predicates"]}


def _edge_type_values() -> set[str]:
    return {v for k, v in vars(EdgeType).items() if not k.startswith("_") and isinstance(v, str)}


def test_relationship_predicate_registry_version_parity():
    assert _const_version() == RELATIONSHIP_PREDICATE_REGISTRY_VERSION
    assert RELATIONSHIP_PREDICATE_REGISTRY_VERSION == _registry()["contractVersion"]


def test_relationship_predicate_vocab_parity():
    registry = _registry()
    for key, (ts_name, py_value) in _VOCAB.items():
        ts_value = _const_array(ts_name)
        assert list(py_value) == registry[key], f"PY vocab {key!r} drifts from JSON"
        assert ts_value == registry[key], f"TS vocab {key!r} drifts from JSON"
        assert set(ts_value) == set(py_value)


def test_relationship_predicate_ids_parity():
    json_ids = list(_json_predicates())
    py_ids = [p["predicate"] for p in RELATIONSHIP_PREDICATES]
    ts_ids = list(_ts_predicates())
    assert json_ids == py_ids == ts_ids
    assert len(py_ids) == len(set(py_ids)), "duplicate predicate id in RELATIONSHIP_PREDICATES"


def test_relationship_predicate_catalog_parity():
    """Per-id: TS object literal, PY dict and JSON entry agree on every field."""
    ts_predicates = _ts_predicates()
    py_predicates = _py_predicates()
    json_predicates = _json_predicates()
    assert set(ts_predicates) == set(py_predicates) == set(json_predicates)
    for pid in json_predicates:
        assert _canon(ts_predicates[pid]) == _canon(json_predicates[pid]), f"TS/JSON drift for {pid!r}"
        assert _canon(py_predicates[pid]) == _canon(json_predicates[pid]), f"PY/JSON drift for {pid!r}"


def test_relationship_predicate_registered_edges_resolve():
    """Fail-closed graph honesty check: REGISTERED predicates must reference a
    real EdgeType member; a graphEdgeType that is not an EdgeType member can
    never claim REGISTERED."""
    edge_values = _edge_type_values()
    for pred in _registry()["predicates"]:
        edge = pred.get("graphEdgeType")
        if pred["graphRegistrationState"] == "REGISTERED":
            assert isinstance(edge, str) and edge in edge_values, (
                f"predicate {pred['predicate']!r} claims REGISTERED but graphEdgeType "
                f"{edge!r} is not a shared.graph.graph.EdgeType member"
            )
        elif edge is not None and isinstance(edge, str) and edge not in edge_values:
            assert pred["graphRegistrationState"] != "REGISTERED", (
                f"predicate {pred['predicate']!r} has non-EdgeType graphEdgeType "
                f"{edge!r} yet claims REGISTERED"
            )


def test_barrel_exports_relationship_predicate_registry():
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert "export * from './relationship-predicate-registry';" in index
