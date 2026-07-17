"""TS <-> Python parity for the graph-mutation contract.

`packages/shared/graph-mutation.ts` and
`shared/graph/generated_mutation_taxonomy.py` are generated twins of
`packages/shared/contracts/graph-mutation-registry.json`;
`shared/graph/mutation_models.py` is the hand-authored twin of the generated
`MutationRecord` / `GraphDecisionRecord` / `ChangeSet` interfaces. This test
fails on vocabulary or field drift, if the TS module leaves the barrel, and if
`MutationRecord` stops using the exact bitemporal field names owned by
`shared/graph/edge_properties.py::BITEMPORAL_EDGE_PROPERTIES`.
"""
from __future__ import annotations

import json
import re
import sys
import typing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.graph.edge_properties import BITEMPORAL_EDGE_PROPERTIES  # noqa: E402
from shared.graph.generated_mutation_taxonomy import (  # noqa: E402
    GRAPH_MUTATION_CONTRACT_VERSION,
    GRAPH_MUTATION_TYPES,
    MUTATION_ACTOR_KINDS,
    MUTATION_CAUSALITY_CLASSES,
    MUTATION_EXPLANATION_TYPES,
)
from shared.graph.mutation_models import (  # noqa: E402
    ChangeSet,
    DecisionRecord,
    MutationRecord,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "graph-mutation.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "graph-mutation-registry.json"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in graph-mutation.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in graph-mutation.ts"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_mutation_types_parity():
    assert set(_const_array("graphMutationTypes")) == set(GRAPH_MUTATION_TYPES)


def test_actor_kinds_parity():
    assert set(_const_array("mutationActorKinds")) == set(MUTATION_ACTOR_KINDS)


def test_causality_classes_parity():
    assert set(_const_array("mutationCausalityClasses")) == set(MUTATION_CAUSALITY_CLASSES)


def test_explanation_types_parity():
    assert set(_const_array("mutationExplanationTypes")) == set(MUTATION_EXPLANATION_TYPES)


def test_mutation_record_field_parity():
    ts_fields = _interface_fields("MutationRecord")
    py_fields = set(MutationRecord.model_fields.keys())
    assert ts_fields == py_fields, (
        f"MutationRecord drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_decision_record_field_parity():
    ts_fields = _interface_fields("GraphDecisionRecord")
    py_fields = set(DecisionRecord.model_fields.keys())
    assert ts_fields == py_fields, (
        f"GraphDecisionRecord drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_change_set_field_parity():
    ts_fields = _interface_fields("ChangeSet")
    py_fields = set(ChangeSet.model_fields.keys())
    assert ts_fields == py_fields, (
        f"ChangeSet drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_mutation_record_uses_bitemporal_edge_property_names():
    """The ledger's bitemporal fields are exactly the canonical edge-property names."""
    py_fields = set(MutationRecord.model_fields.keys())
    assert BITEMPORAL_EDGE_PROPERTIES <= py_fields, (
        f"MutationRecord missing bitemporal fields: {BITEMPORAL_EDGE_PROPERTIES - py_fields}"
    )
    # No near-miss aliases (e.g. validFrom, valid_start, system_time) allowed.
    aliases = {"valid_start", "valid_end", "system_time", "transaction_time", "recorded_time"}
    assert not aliases & py_fields


def test_mutation_record_aggregate_types():
    annotation = MutationRecord.model_fields["aggregate_type"].annotation
    assert set(typing.get_args(annotation)) == {"node", "edge", "cluster", "score"}


def test_generated_taxonomy_matches_registry():
    """Generated Python taxonomy mirrors the JSON registry (regen if this fails)."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert GRAPH_MUTATION_CONTRACT_VERSION == registry["contractVersion"]
    assert list(GRAPH_MUTATION_TYPES) == registry["mutationTypes"]
    assert list(MUTATION_ACTOR_KINDS) == registry["actorKinds"]
    assert list(MUTATION_CAUSALITY_CLASSES) == registry["causalityClasses"]
    assert list(MUTATION_EXPLANATION_TYPES) == registry["explanationTypes"]


def test_barrel_exports_graph_mutation():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './graph-mutation';" in index
