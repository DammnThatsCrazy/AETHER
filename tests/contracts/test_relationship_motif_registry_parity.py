"""TS <-> Python parity for the relationship-motif registry.

`packages/shared/relationship-motif-registry.ts` and
`shared/relationship_spine/generated_relationship_motif_registry.py` are
generated twins of `packages/shared/contracts/relationship-motif-registry.json`.
This test fails on drift in the version, vocabulary arrays, motif catalog
(per-index scalar/nested parity), duplicate/invalid motif ids, and barrel export
presence. The registry is also held honest against its neighbors: every edge
predicate a motif references must resolve either to a predicate id in
`relationship-predicate-registry.json` OR to a real member of
`shared.graph.graph.EdgeType`, and every RELATIONSHIP_PREDICATE-output motif must
emit an outputPredicate that exists in the predicate registry.
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
from shared.relationship_spine.generated_relationship_motif_registry import (  # noqa: E402
    RELATIONSHIP_MOTIF_CLAIM_CEILINGS,
    RELATIONSHIP_MOTIF_EDGE_ROLES,
    RELATIONSHIP_MOTIF_EVIDENCE_INDEPENDENCE_POLICIES,
    RELATIONSHIP_MOTIF_INCENTIVE_POLICIES,
    RELATIONSHIP_MOTIF_OUTPUT_KINDS,
    RELATIONSHIP_MOTIF_REGISTRY_VERSION,
    RELATIONSHIP_MOTIFS,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "relationship-motif-registry.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "relationship-motif-registry.json"
PREDICATE_REGISTRY_PATH = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "relationship-predicate-registry.json"
)
INDEX_PATH = REPO_ROOT / "packages" / "shared" / "index.ts"

# json vocab key -> (TS const array name, Python vocab constant)
_VOCAB = {
    "outputKinds": ("relationshipMotifOutputKinds", RELATIONSHIP_MOTIF_OUTPUT_KINDS),
    "claimCeilings": ("relationshipMotifClaimCeilings", RELATIONSHIP_MOTIF_CLAIM_CEILINGS),
    "evidenceIndependencePolicies": (
        "relationshipMotifEvidenceIndependencePolicies",
        RELATIONSHIP_MOTIF_EVIDENCE_INDEPENDENCE_POLICIES,
    ),
    "incentivePolicies": ("relationshipMotifIncentivePolicies", RELATIONSHIP_MOTIF_INCENTIVE_POLICIES),
    "edgeRoles": ("relationshipMotifEdgeRoles", RELATIONSHIP_MOTIF_EDGE_ROLES),
}

_MOTIF_KEYS = frozenset(
    {
        "motifId",
        "version",
        "name",
        "description",
        "requiredNodes",
        "requiredEdges",
        "optionalEdges",
        "temporalConstraints",
        "entityKindConstraints",
        "evidenceIndependencePolicy",
        "incentivePolicy",
        "outputPredicate",
        "outputState",
        "outputKind",
        "outputClaimCeiling",
        "promotionPolicyRef",
        "owner",
        "tests",
    }
)


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in relationship-motif-registry.ts"
    return re.findall(r"'([A-Za-z0-9_]+)'", m.group(1))


def _const_version() -> str:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"relationshipMotifRegistryVersion\s*=\s*'([^']+)'", text)
    assert m, "relationshipMotifRegistryVersion not found in relationship-motif-registry.ts"
    return m.group(1)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _ts_object_texts(array_name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{array_name}\s*=\s*\[(.*)\]\s*as const;", text, re.S)
    assert m, f"{array_name} block not found in relationship-motif-registry.ts"
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


def _normalize_motif(motif: dict) -> dict:
    """Every motif twin carries both outputPredicate and outputState (one null)."""
    normalized = dict(motif)
    normalized.setdefault("outputPredicate", None)
    normalized.setdefault("outputState", None)
    assert set(normalized) == _MOTIF_KEYS
    return normalized


def _ts_motifs() -> dict[str, dict]:
    return {
        obj["motifId"]: obj
        for obj in (_ts_object_to_dict(t) for t in _ts_object_texts("relationshipMotifs"))
    }


def _py_motifs() -> dict[str, dict]:
    return {m["motifId"]: dict(m) for m in RELATIONSHIP_MOTIFS}


def _json_motifs() -> dict[str, dict]:
    return {m["motifId"]: _normalize_motif(m) for m in _registry()["motifs"]}


def _edge_type_values() -> set[str]:
    return {v for k, v in vars(EdgeType).items() if not k.startswith("_") and isinstance(v, str)}


def test_relationship_motif_registry_version_parity():
    assert _const_version() == RELATIONSHIP_MOTIF_REGISTRY_VERSION
    assert RELATIONSHIP_MOTIF_REGISTRY_VERSION == _registry()["contractVersion"]


def test_relationship_motif_vocab_parity():
    registry = _registry()
    for key, (ts_name, py_value) in _VOCAB.items():
        ts_value = _const_array(ts_name)
        assert list(py_value) == registry[key], f"PY vocab {key!r} drifts from JSON"
        assert ts_value == registry[key], f"TS vocab {key!r} drifts from JSON"
        assert set(ts_value) == set(py_value)


def test_relationship_motif_ids_parity():
    json_ids = list(_json_motifs())
    py_ids = [m["motifId"] for m in RELATIONSHIP_MOTIFS]
    ts_ids = list(_ts_motifs())
    assert json_ids == py_ids == ts_ids
    assert len(py_ids) == len(set(py_ids)), "duplicate motifId in RELATIONSHIP_MOTIFS"


def test_relationship_motif_catalog_parity():
    """Per-id: TS object literal, PY dict and JSON entry agree on every field."""
    ts_motifs = _ts_motifs()
    py_motifs = _py_motifs()
    json_motifs = _json_motifs()
    assert set(ts_motifs) == set(py_motifs) == set(json_motifs)
    for mid in json_motifs:
        assert _canon(ts_motifs[mid]) == _canon(json_motifs[mid]), f"TS/{JSON} drift for {mid!r}"
        assert _canon(py_motifs[mid]) == _canon(json_motifs[mid]), f"PY/{JSON} drift for {mid!r}"


def test_relationship_motif_output_predicates_resolve():
    """Every RELATIONSHIP_PREDICATE-output motif emits an outputPredicate that is
    a real predicate id in the relationship-predicate registry."""
    predicate_reg = json.loads(PREDICATE_REGISTRY_PATH.read_text(encoding="utf-8"))
    predicate_ids = {p["predicate"] for p in predicate_reg["predicates"]}
    for motif in _registry()["motifs"]:
        if motif["outputKind"] == "RELATIONSHIP_PREDICATE":
            output = motif.get("outputPredicate")
            assert isinstance(output, str) and output in predicate_ids, (
                f"motif {motif['motifId']!r} outputs relationship predicate {output!r} "
                "which is not in relationship-predicate-registry.json"
            )


def test_relationship_motif_edge_references_resolve():
    """Every predicate referenced across required/optional edges resolves to a
    predicate id in the predicate registry OR a real EdgeType member (so graph
    references like DELEGATES_TO / ACTED_FOR resolve while staying honest)."""
    predicate_reg = json.loads(PREDICATE_REGISTRY_PATH.read_text(encoding="utf-8"))
    predicate_ids = {p["predicate"] for p in predicate_reg["predicates"]}
    edge_values = _edge_type_values()
    referenced: set[str] = set()
    for motif in _registry()["motifs"]:
        for edge_key in ("requiredEdges", "optionalEdges"):
            for edge in motif.get(edge_key, []):
                predicate = edge.get("predicate")
                if predicate is not None:
                    assert isinstance(predicate, str) and predicate, (
                        f"motif {motif['motifId']!r} {edge_key} has a non-string predicate"
                    )
                    referenced.add(predicate)
    unresolved = referenced - predicate_ids - edge_values
    assert not unresolved, (
        f"motif edge predicates do not resolve to the predicate registry or EdgeType: "
        f"{sorted(unresolved)}"
    )


def test_barrel_exports_relationship_motif_registry():
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert "export * from './relationship-motif-registry';" in index
