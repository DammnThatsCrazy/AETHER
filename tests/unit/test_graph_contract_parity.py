"""Tests for TypeScript/Python graph contract parity.

Ensures the packages/shared/graph-contract.ts and backend
shared/graph/graph_contract.py agree on edge→layer mappings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]

# ── Parse TypeScript EDGE_LAYER_MAP ──────────────────────────────────────────

def _parse_ts_edge_layer_map() -> dict[str, str]:
    """Extract the EDGE_LAYER_MAP from packages/shared/graph-contract.ts."""
    ts_path = REPO_ROOT / "packages/shared/graph-contract.ts"
    content = ts_path.read_text(encoding="utf-8")

    # Extract the EDGE_LAYER_MAP object body
    match = re.search(
        r"export const EDGE_LAYER_MAP:\s*Record<string,\s*RelationshipLayer>\s*=\s*\{([^}]+)\}",
        content,
        re.DOTALL,
    )
    assert match, "EDGE_LAYER_MAP not found in graph-contract.ts"

    result: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        line = line.strip().rstrip(",")
        if not line or line.startswith("//"):
            continue
        kv_match = re.match(r"(\w+):\s*'([A-Z0-9]+)'", line)
        if kv_match:
            result[kv_match.group(1)] = kv_match.group(2)
    return result


# ── Parse Python _EDGE_LAYER_MAP ─────────────────────────────────────────────

def _parse_py_edge_layer_map() -> dict[str, str]:
    """Extract the _EDGE_LAYER_MAP from shared/graph/relationship_layers.py."""
    py_path = REPO_ROOT / "Backend Architecture/aether-backend/shared/graph/relationship_layers.py"
    content = py_path.read_text(encoding="utf-8")

    result: dict[str, str] = {}
    # Match: EdgeType.XXX: RelationshipLayer.YYY
    for m in re.finditer(r"EdgeType\.(\w+):\s*RelationshipLayer\.(\w+)", content):
        result[m.group(1)] = m.group(2)
    return result


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_ts_edge_layer_map_has_a2h_edges() -> None:
    """TypeScript EDGE_LAYER_MAP must include A2H edge types."""
    ts_map = _parse_ts_edge_layer_map()
    a2h_edges = [k for k, v in ts_map.items() if v == "A2H"]
    assert len(a2h_edges) > 0, f"No A2H edges in TypeScript EDGE_LAYER_MAP. Map: {ts_map}"


def test_py_edge_layer_map_has_a2h_edges() -> None:
    """Python _EDGE_LAYER_MAP must include A2H edge types."""
    py_map = _parse_py_edge_layer_map()
    a2h_edges = [k for k, v in py_map.items() if v == "A2H"]
    assert len(a2h_edges) > 0, f"No A2H edges in Python _EDGE_LAYER_MAP. Map: {py_map}"


def test_ts_and_py_a2h_edges_agree() -> None:
    """TypeScript and Python must agree on which edges are A2H."""
    ts_map = _parse_ts_edge_layer_map()
    py_map = _parse_py_edge_layer_map()

    ts_a2h = {k for k, v in ts_map.items() if v == "A2H"}
    py_a2h = {k for k, v in py_map.items() if v == "A2H"}

    missing_from_ts = py_a2h - ts_a2h
    missing_from_py = ts_a2h - py_a2h

    assert not missing_from_ts, f"A2H edges in Python but not TypeScript: {missing_from_ts}"
    assert not missing_from_py, f"A2H edges in TypeScript but not Python: {missing_from_py}"


def test_all_four_layers_present_in_ts() -> None:
    """TypeScript EDGE_LAYER_MAP must cover all four layers."""
    ts_map = _parse_ts_edge_layer_map()
    layers_present = set(ts_map.values())
    for layer in ("H2H", "H2A", "A2H", "A2A"):
        assert layer in layers_present, f"Layer {layer} has no edges in TypeScript EDGE_LAYER_MAP"


def test_all_four_layers_present_in_py() -> None:
    """Python _EDGE_LAYER_MAP must cover all four layers."""
    py_map = _parse_py_edge_layer_map()
    layers_present = set(py_map.values())
    for layer in ("H2H", "H2A", "A2H", "A2A"):
        assert layer in layers_present, f"Layer {layer} has no edges in Python _EDGE_LAYER_MAP"


def test_ts_relationship_layers_constant_has_four_entries() -> None:
    """RELATIONSHIP_LAYERS in graph-contract.ts must list exactly four layers."""
    ts_path = REPO_ROOT / "packages/shared/graph-contract.ts"
    content = ts_path.read_text(encoding="utf-8")
    layers = re.findall(r"'(H2H|H2A|A2H|A2A)'", content)
    # RELATIONSHIP_LAYERS array has each layer once
    unique_in_constant = set(layers)
    for layer in ("H2H", "H2A", "A2H", "A2A"):
        assert layer in unique_in_constant, f"Layer {layer} missing from graph-contract.ts"


def test_graph_contract_py_exists_and_has_four_layers() -> None:
    """shared/graph/graph_contract.py must exist and export all four layers."""
    py_path = REPO_ROOT / "Backend Architecture/aether-backend/shared/graph/graph_contract.py"
    assert py_path.exists(), "shared/graph/graph_contract.py not found"
    content = py_path.read_text(encoding="utf-8")
    for layer in ("H2H", "H2A", "A2H", "A2A"):
        assert layer in content, f"Layer {layer} missing from graph_contract.py"


# ── Phase 2: Universal envelope parity tests ─────────────────────────────────

def _parse_ts_union_type(type_name: str) -> set[str]:
    """Extract string literal values from a TypeScript union type definition.

    Handles multi-line unions with inline comments:
      export type Foo =
        | 'a'   // comment
        | 'b'
    """
    ts_path = REPO_ROOT / "packages/shared/graph-contract.ts"
    content = ts_path.read_text(encoding="utf-8")
    # Find the block from "export type <name> =" until the next blank line or next "export"
    match = re.search(
        rf"export type {re.escape(type_name)}\s*=(.*?)(?=\n\n|\nexport |\Z)",
        content,
        re.DOTALL,
    )
    assert match, f"{type_name} not found in graph-contract.ts"
    block = match.group(1)
    # Strip inline comments, then extract quoted strings
    block_no_comments = re.sub(r"//[^\n]*", "", block)
    return set(re.findall(r"'([^']+)'", block_no_comments))


def _parse_ts_observation_class() -> set[str]:
    """Extract ObservationClass values from graph-contract.ts."""
    return _parse_ts_union_type("ObservationClass")


def _parse_ts_lifecycle_state() -> set[str]:
    """Extract LifecycleState values from graph-contract.ts."""
    return _parse_ts_union_type("LifecycleState")


def _parse_py_frozenset(name: str) -> set[str]:
    """Extract string values from a named frozenset in graph_contract.py."""
    py_path = REPO_ROOT / "Backend Architecture/aether-backend/shared/graph/graph_contract.py"
    content = py_path.read_text(encoding="utf-8")
    pattern = rf"{name}:\s*frozenset\[str\]\s*=\s*frozenset\({{([^}}]+)}}\)"
    match = re.search(pattern, content, re.DOTALL)
    assert match, f"{name} not found in graph_contract.py"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_observation_class_parity() -> None:
    """TypeScript ObservationClass and Python OBSERVATION_CLASS_VALUES must agree."""
    ts_values = _parse_ts_observation_class()
    py_values = _parse_py_frozenset("OBSERVATION_CLASS_VALUES")
    assert ts_values == py_values, (
        f"ObservationClass mismatch.\n"
        f"  TS only: {ts_values - py_values}\n"
        f"  Py only: {py_values - ts_values}"
    )


def test_observation_class_has_eight_values() -> None:
    """ObservationClass must have exactly 8 values."""
    ts_values = _parse_ts_observation_class()
    assert len(ts_values) == 8, (
        f"ObservationClass must have exactly 8 values, got {len(ts_values)}: {ts_values}"
    )


def test_lifecycle_state_parity() -> None:
    """TypeScript LifecycleState and Python LIFECYCLE_STATE_VALUES must agree."""
    ts_values = _parse_ts_lifecycle_state()
    py_values = _parse_py_frozenset("LIFECYCLE_STATE_VALUES")
    assert ts_values == py_values, (
        f"LifecycleState mismatch.\n"
        f"  TS only: {ts_values - py_values}\n"
        f"  Py only: {py_values - ts_values}"
    )


def test_lifecycle_state_has_eighteen_values() -> None:
    """LifecycleState must have exactly 18 values."""
    ts_values = _parse_ts_lifecycle_state()
    assert len(ts_values) == 18, (
        f"LifecycleState must have exactly 18 values, got {len(ts_values)}: {ts_values}"
    )


def test_phase2_edge_types_in_ts_edge_layer_map() -> None:
    """All Phase 2 new edge types must appear in TypeScript EDGE_LAYER_MAP."""
    ts_map = _parse_ts_edge_layer_map()
    phase2_edges = {
        "PAYS_FOR", "TRANSFERS_TO", "SETTLED_VIA", "REFUNDED_BY", "CHARGED_BACK_BY",
        "LAYERED_THROUGH", "SMURFED_VIA",
        "ACQUIRED_VIA", "CONVERTED_FROM", "ATTRIBUTED_TO_CAMPAIGN", "TOUCHPOINT_IN",
        "NEXT_IN_JOURNEY", "ABANDONED_AT", "CONVERTED_AT",
        "BRIDGES", "MERGED_INTO", "SPLIT_FROM",
    }
    missing = phase2_edges - set(ts_map.keys())
    assert not missing, f"Phase 2 edge types missing from TypeScript EDGE_LAYER_MAP: {missing}"


def test_phase2_edge_types_in_py_edge_layer_map() -> None:
    """All Phase 2 new edge types must appear in Python _EDGE_LAYER_MAP."""
    py_map = _parse_py_edge_layer_map()
    phase2_edges = {
        "TRANSFERS_TO", "REFUNDED_BY", "CHARGED_BACK_BY",
        "LAYERED_THROUGH", "SMURFED_VIA",
        "ACQUIRED_VIA", "CONVERTED_FROM", "ATTRIBUTED_TO_CAMPAIGN", "TOUCHPOINT_IN",
        "NEXT_IN_JOURNEY", "ABANDONED_AT", "CONVERTED_AT",
        "BRIDGES", "MERGED_INTO", "SPLIT_FROM",
    }
    missing = phase2_edges - set(py_map.keys())
    assert not missing, f"Phase 2 edge types missing from Python _EDGE_LAYER_MAP: {missing}"


def test_ts_and_py_agree_on_phase2_edge_layers() -> None:
    """TypeScript and Python must agree on the layer for all Phase 2 edge types."""
    ts_map = _parse_ts_edge_layer_map()
    py_map = _parse_py_edge_layer_map()
    # Edges in both maps
    phase2_common = {
        "TRANSFERS_TO", "REFUNDED_BY", "CHARGED_BACK_BY",
        "LAYERED_THROUGH", "SMURFED_VIA",
        "ACQUIRED_VIA", "CONVERTED_FROM", "ATTRIBUTED_TO_CAMPAIGN", "TOUCHPOINT_IN",
        "NEXT_IN_JOURNEY", "ABANDONED_AT", "CONVERTED_AT",
        "BRIDGES", "MERGED_INTO", "SPLIT_FROM",
    }
    mismatches: list[str] = []
    for edge in phase2_common:
        ts_layer = ts_map.get(edge)
        py_layer = py_map.get(edge)
        if ts_layer and py_layer and ts_layer != py_layer:
            mismatches.append(f"{edge}: TS={ts_layer}, Py={py_layer}")
    assert not mismatches, f"Layer mismatches for Phase 2 edges:\n" + "\n".join(mismatches)
