"""
Intelligence Graph Contract — canonical Python definitions.

Four relationship layers: H2H, H2A, A2H, A2A.
This module is the single backend source of truth for graph layer
classification, vertex/edge canonical sets, and contract enforcement.

Validated in CI by tests/contracts/test_graph_contract_parity.py.
"""

from __future__ import annotations

from shared.graph.relationship_layers import (
    RelationshipLayer,
    _EDGE_LAYER_MAP,
    H2H_VERTEX_TYPES,
    H2A_VERTEX_TYPES,
    A2H_VERTEX_TYPES,
    A2A_VERTEX_TYPES,
)
from shared.graph.graph import EdgeType, VertexType

# ── Canonical layer set ───────────────────────────────────────────────────────

CANONICAL_LAYERS: frozenset[RelationshipLayer] = frozenset({
    RelationshipLayer.H2H,
    RelationshipLayer.H2A,
    RelationshipLayer.A2H,
    RelationshipLayer.A2A,
})

LAYER_COUNT = len(CANONICAL_LAYERS)  # must be 4

LAYER_DESCRIPTIONS: dict[RelationshipLayer, str] = {
    RelationshipLayer.H2H: "Identity graph: merges, referrals, clusters, behavioral similarity",
    RelationshipLayer.H2A: "Delegation, configuration, ownership, supervision of agents by humans",
    RelationshipLayer.A2H: "Agent notifications, recommendations, result delivery, and escalations to humans",
    RelationshipLayer.A2A: "Orchestration, hiring, payments, and trust propagation between agents",
}

# ── Edge classifications by layer ─────────────────────────────────────────────

EDGES_BY_LAYER: dict[RelationshipLayer, frozenset[str]] = {
    layer: frozenset(et for et, l in _EDGE_LAYER_MAP.items() if l == layer)
    for layer in RelationshipLayer
}

# ── Vertex types by layer ─────────────────────────────────────────────────────

VERTEX_TYPES_BY_LAYER: dict[RelationshipLayer, frozenset[str]] = {
    RelationshipLayer.H2H: H2H_VERTEX_TYPES,
    RelationshipLayer.H2A: H2A_VERTEX_TYPES,
    RelationshipLayer.A2H: A2H_VERTEX_TYPES,
    RelationshipLayer.A2A: A2A_VERTEX_TYPES,
}

# ── Contract enforcement ──────────────────────────────────────────────────────

def validate_contract() -> list[str]:
    """Return a list of contract violations. Empty list means contract is valid."""
    violations: list[str] = []

    # 1. All four layers must exist
    for layer in RelationshipLayer:
        if layer not in CANONICAL_LAYERS:
            violations.append(f"Missing canonical layer: {layer}")

    # 2. Every layer must have at least one edge
    for layer in RelationshipLayer:
        if not EDGES_BY_LAYER.get(layer):
            violations.append(f"Layer {layer} has no registered edge types")

    # 3. A2H must be present (historical gap check)
    if RelationshipLayer.A2H not in CANONICAL_LAYERS:
        violations.append("A2H layer is missing from canonical layers — this is a critical gap")

    if not EDGES_BY_LAYER.get(RelationshipLayer.A2H):
        violations.append("A2H layer has no registered edge types")

    # 4. Every edge in _EDGE_LAYER_MAP must map to a known layer
    for edge_type, layer in _EDGE_LAYER_MAP.items():
        if layer not in CANONICAL_LAYERS:
            violations.append(f"Edge {edge_type} maps to unknown layer: {layer}")

    # 5. Every layer must have vertex types
    for layer in RelationshipLayer:
        if not VERTEX_TYPES_BY_LAYER.get(layer):
            violations.append(f"Layer {layer} has no registered vertex types")

    return violations


def assert_contract_valid() -> None:
    """Raise ValueError if the graph contract has violations."""
    violations = validate_contract()
    if violations:
        raise ValueError(
            f"Graph contract violations detected ({len(violations)}):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


def get_layer_for_edge(edge_type: str) -> RelationshipLayer | None:
    """Return the layer for an edge type, or None if unclassified."""
    return _EDGE_LAYER_MAP.get(edge_type)


def is_valid_edge_for_layer(
    edge_type: str,
    from_vertex_type: str,
    to_vertex_type: str,
    layer: RelationshipLayer,
) -> bool:
    """Check whether an edge is valid for its layer given source/target vertex types."""
    if _EDGE_LAYER_MAP.get(edge_type) != layer:
        return False

    allowed_vertices = VERTEX_TYPES_BY_LAYER.get(layer, frozenset())
    return (
        from_vertex_type in allowed_vertices
        and to_vertex_type in allowed_vertices
    )


# ── Overlay status constants ──────────────────────────────────────────────────

OVERLAY_STATUS_COMPUTED = "computed"
OVERLAY_STATUS_NO_DATA = "no_data"
OVERLAY_STATUS_VALUES = frozenset({OVERLAY_STATUS_COMPUTED, OVERLAY_STATUS_NO_DATA})
# "placeholder" is never a valid overlay status in production
OVERLAY_STATUS_FORBIDDEN = frozenset({"placeholder"})
