"""
Intelligence Graph Contract — canonical Python definitions.

Four relationship layers: H2H, H2A, A2H, A2A.
This module is the single backend source of truth for graph layer
classification, vertex/edge canonical sets, and contract enforcement.

Validated in CI by tests/contracts/test_graph_contract_parity.py.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

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
# EXCLUDED is a non-canonical classification for edges intentionally outside
# the four operational layers. It is not counted in LAYER_COUNT.

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

    # 1. All four canonical layers must exist (EXCLUDED is intentionally non-canonical)
    for layer in CANONICAL_LAYERS:
        if layer not in CANONICAL_LAYERS:
            violations.append(f"Missing canonical layer: {layer}")

    # 2. Every canonical layer must have at least one edge
    for layer in CANONICAL_LAYERS:
        if not EDGES_BY_LAYER.get(layer):
            violations.append(f"Layer {layer} has no registered edge types")

    # 3. A2H must be present (historical gap check)
    if RelationshipLayer.A2H not in CANONICAL_LAYERS:
        violations.append("A2H layer is missing from canonical layers — this is a critical gap")

    if not EDGES_BY_LAYER.get(RelationshipLayer.A2H):
        violations.append("A2H layer has no registered edge types")

    # 4. Every edge in _EDGE_LAYER_MAP must map to a canonical or EXCLUDED layer
    for edge_type, layer in _EDGE_LAYER_MAP.items():
        if layer not in CANONICAL_LAYERS and layer is not RelationshipLayer.EXCLUDED:
            violations.append(f"Edge {edge_type} maps to unknown layer: {layer}")

    # 5a. Every EdgeType class attribute must be mapped (exhaustiveness check)
    all_edge_type_values = {
        v for k, v in vars(EdgeType).items()
        if not k.startswith("_") and isinstance(v, str)
    }
    unmapped = all_edge_type_values - set(_EDGE_LAYER_MAP.keys())
    for et in sorted(unmapped):
        violations.append(f"EdgeType {et!r} is not mapped in _EDGE_LAYER_MAP")

    # 5. Every canonical layer must have vertex types (EXCLUDED is non-canonical)
    for layer in CANONICAL_LAYERS:
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

# ── Universal Envelopes — Python mirrors (Phase 2) ────────────────────────────

# ObservationClass: how a data point was produced.
# Mirrors ObservationClass in packages/shared/graph-contract.ts.
OBSERVATION_CLASS_VALUES: frozenset[str] = frozenset({
    "observed",
    "deterministic",
    "probabilistic",
    "derived",
    "predicted",
    "simulated",
    "manually_asserted",
    "externally_enriched",
})

# LifecycleState: lifecycle state of a graph node or cluster.
# Mirrors LifecycleState in packages/shared/graph-contract.ts.
LIFECYCLE_STATE_VALUES: frozenset[str] = frozenset({
    "provisional",
    "unresolved",
    "active",
    "growing",
    "stable",
    "shrinking",
    "dormant",
    "decaying",
    "reactivated",
    "merged",
    "split",
    "suppressed",
    "disputed",
    "expired",
    "revoked",
    "invalidated",
    "deleted",
    "tombstoned",
})

# ClusterType: all supported cluster classification types.
# Mirrors ClusterType in packages/shared/graph-contract.ts.
CLUSTER_TYPE_VALUES: frozenset[str] = frozenset({
    "identity",
    "household",
    "org",
    "device",
    "wallet",
    "behavioral",
    "geographic",
    "economic_segment",
    "campaign_cohort",
    "journey",
    "fraud_network",
    "risk",
    "dormant",
    "reactivated",
    "unresolved",
})

# FilterOperator: comparison operators for graph filter expressions.
# Mirrors FilterOperator in packages/shared/graph-contract.ts.
FILTER_OPERATOR_VALUES: frozenset[str] = frozenset({
    "eq", "neq",
    "gt", "gte", "lt", "lte",
    "in", "not_in",
    "exists", "not_exists",
    "contains", "starts_with",
    "between", "relative_time", "threshold",
})

# Phase 2 new edge types added to EDGE_LAYER_MAP (TypeScript side).
# These must also be present in relationship_layers.py when added there.
PHASE2_NEW_EDGE_TYPES: frozenset[str] = frozenset({
    # Economic flow
    "PAYS_FOR", "TRANSFERS_TO", "SETTLED_VIA", "REFUNDED_BY", "CHARGED_BACK_BY",
    # Fraud ring
    "LAYERED_THROUGH", "SMURFED_VIA",
    # Campaign attribution
    "ACQUIRED_VIA", "CONVERTED_FROM", "ATTRIBUTED_TO_CAMPAIGN", "TOUCHPOINT_IN",
    # Journey
    "NEXT_IN_JOURNEY", "ABANDONED_AT", "CONVERTED_AT",
    # Cluster lifecycle
    "BRIDGES", "MERGED_INTO", "SPLIT_FROM",
})
