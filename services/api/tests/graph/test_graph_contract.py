"""Tests for the Intelligence Graph contract — four-layer parity enforcement."""

from __future__ import annotations

import pytest
from shared.graph.graph_contract import (
    CANONICAL_LAYERS,
    EDGES_BY_LAYER,
    LAYER_COUNT,
    VERTEX_TYPES_BY_LAYER,
    assert_contract_valid,
    get_layer_for_edge,
    is_valid_edge_for_layer,
    validate_contract,
    OVERLAY_STATUS_VALUES,
    OVERLAY_STATUS_FORBIDDEN,
)
from shared.graph.relationship_layers import RelationshipLayer, _EDGE_LAYER_MAP


def test_exactly_four_layers() -> None:
    """The canonical layer set must have exactly four layers."""
    assert LAYER_COUNT == 4
    assert len(CANONICAL_LAYERS) == 4


def test_all_four_layers_present() -> None:
    """H2H, H2A, A2H, and A2A must all be in the canonical layer set."""
    assert RelationshipLayer.H2H in CANONICAL_LAYERS
    assert RelationshipLayer.H2A in CANONICAL_LAYERS
    assert RelationshipLayer.A2H in CANONICAL_LAYERS
    assert RelationshipLayer.A2A in CANONICAL_LAYERS


def test_a2h_layer_not_missing() -> None:
    """A2H is the historically omitted layer — verify it is present and has edges."""
    assert RelationshipLayer.A2H in CANONICAL_LAYERS
    a2h_edges = EDGES_BY_LAYER[RelationshipLayer.A2H]
    assert len(a2h_edges) > 0, "A2H layer must have at least one registered edge type"


def test_every_layer_has_edges() -> None:
    """Every relationship layer must have at least one edge type."""
    for layer in RelationshipLayer:
        edges = EDGES_BY_LAYER.get(layer, frozenset())
        assert len(edges) > 0, f"Layer {layer} has no registered edge types"


def test_every_canonical_layer_has_vertex_types() -> None:
    """Every CANONICAL relationship layer must have registered vertex types.

    EXCLUDED is a non-canonical classification for edges intentionally
    outside the four operational layers; it has no vertex-type registry.
    """
    for layer in CANONICAL_LAYERS:
        vtypes = VERTEX_TYPES_BY_LAYER.get(layer, frozenset())
        assert len(vtypes) > 0, f"Layer {layer} has no registered vertex types"


def test_every_edge_maps_to_known_layer() -> None:
    """Every edge type maps to a canonical layer or the explicit EXCLUDED
    classification — never to an unknown value."""
    known = set(CANONICAL_LAYERS) | {RelationshipLayer.EXCLUDED}
    for edge_type, layer in _EDGE_LAYER_MAP.items():
        assert layer in known, (
            f"Edge {edge_type} maps to unknown layer {layer}"
        )


def test_a2h_edges_are_classified() -> None:
    """A2H-specific edges must be classified as A2H."""
    a2h_edge_types = ["NOTIFIES", "RECOMMENDS", "DELIVERS_TO", "ESCALATES_TO"]
    for edge_type in a2h_edge_types:
        layer = get_layer_for_edge(edge_type)
        assert layer == RelationshipLayer.A2H, (
            f"Edge {edge_type} should be A2H but got {layer}"
        )


def test_h2a_edges_are_classified() -> None:
    """H2A-specific edges must be classified as H2A."""
    h2a_edge_types = ["LAUNCHED_BY", "DELEGATES", "INTERACTS_WITH"]
    for edge_type in h2a_edge_types:
        layer = get_layer_for_edge(edge_type)
        assert layer == RelationshipLayer.H2A, (
            f"Edge {edge_type} should be H2A but got {layer}"
        )


def test_a2a_edges_are_classified() -> None:
    """A2A-specific edges must be classified as A2A."""
    a2a_edge_types = ["PAYS", "CONSUMES", "HIRED", "DEPLOYED", "CALLED"]
    for edge_type in a2a_edge_types:
        layer = get_layer_for_edge(edge_type)
        assert layer == RelationshipLayer.A2A, (
            f"Edge {edge_type} should be A2A but got {layer}"
        )


def test_h2h_edges_are_classified() -> None:
    """H2H-specific edges must be classified as H2H."""
    h2h_edge_types = ["HAS_SESSION", "VIEWED_PAGE", "HAS_EMAIL", "OWNS_WALLET"]
    for edge_type in h2h_edge_types:
        layer = get_layer_for_edge(edge_type)
        assert layer == RelationshipLayer.H2H, (
            f"Edge {edge_type} should be H2H but got {layer}"
        )


def test_contract_validates_without_violations() -> None:
    """The full graph contract must have zero violations."""
    violations = validate_contract()
    assert violations == [], f"Contract violations: {violations}"


def test_assert_contract_valid_does_not_raise() -> None:
    """assert_contract_valid() must not raise when contract is valid."""
    assert_contract_valid()  # should not raise


def test_overlay_status_never_includes_placeholder() -> None:
    """The forbidden overlay status set must contain 'placeholder'."""
    assert "placeholder" in OVERLAY_STATUS_FORBIDDEN
    assert "placeholder" not in OVERLAY_STATUS_VALUES


def test_edges_by_layer_covers_all_registered_edges() -> None:
    """Union of all layer edges must equal _EDGE_LAYER_MAP keys."""
    all_classified = set()
    for edge_set in EDGES_BY_LAYER.values():
        all_classified.update(edge_set)
    registered = set(_EDGE_LAYER_MAP.keys())
    assert all_classified == registered, (
        f"Edge classification gap: unclassified={registered - all_classified}, "
        f"over-classified={all_classified - registered}"
    )
