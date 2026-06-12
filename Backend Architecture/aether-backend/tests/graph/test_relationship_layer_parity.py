"""Tests for four-layer parity across the relationship layer module."""

from __future__ import annotations

import pytest
from shared.graph.graph import Edge, EdgeType
from shared.graph.relationship_layers import (
    RelationshipLayer,
    classify_edge,
    classify_edge_type,
    get_layer_stats,
    _EDGE_LAYER_MAP,
    H2H_VERTEX_TYPES,
    H2A_VERTEX_TYPES,
    A2H_VERTEX_TYPES,
    A2A_VERTEX_TYPES,
)


def _make_edge(from_id: str, to_id: str, edge_type: str) -> Edge:
    return Edge(
        edge_type=edge_type,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        created_at="2024-01-01T00:00:00+00:00",
    )


# ── Layer enum parity ──────────────────────────────────────────────────────────

def test_relationship_layer_enum_has_four_values() -> None:
    layers = list(RelationshipLayer)
    assert len(layers) == 4
    assert RelationshipLayer.H2H in layers
    assert RelationshipLayer.H2A in layers
    assert RelationshipLayer.A2H in layers
    assert RelationshipLayer.A2A in layers


def test_a2h_layer_value() -> None:
    assert RelationshipLayer.A2H.value == "A2H"


def test_all_four_layers_have_string_values() -> None:
    expected = {"H2H", "H2A", "A2H", "A2A"}
    actual = {layer.value for layer in RelationshipLayer}
    assert actual == expected


# ── Edge classification ────────────────────────────────────────────────────────

def test_classify_a2h_edge_notifies() -> None:
    edge = _make_edge("agent_1", "user_1", EdgeType.NOTIFIES)
    assert classify_edge(edge) == RelationshipLayer.A2H


def test_classify_a2h_edge_recommends() -> None:
    edge = _make_edge("agent_1", "user_1", EdgeType.RECOMMENDS)
    assert classify_edge(edge) == RelationshipLayer.A2H


def test_classify_a2h_edge_delivers_to() -> None:
    edge = _make_edge("agent_1", "user_1", EdgeType.DELIVERS_TO)
    assert classify_edge(edge) == RelationshipLayer.A2H


def test_classify_a2h_edge_escalates_to() -> None:
    edge = _make_edge("agent_1", "user_1", EdgeType.ESCALATES_TO)
    assert classify_edge(edge) == RelationshipLayer.A2H


def test_classify_h2a_edge_delegates() -> None:
    edge = _make_edge("user_1", "agent_1", EdgeType.DELEGATES)
    assert classify_edge(edge) == RelationshipLayer.H2A


def test_classify_a2a_edge_pays() -> None:
    edge = _make_edge("agent_1", "agent_2", EdgeType.PAYS)
    assert classify_edge(edge) == RelationshipLayer.A2A


def test_classify_h2h_edge_has_session() -> None:
    edge = _make_edge("user_1", "session_1", EdgeType.HAS_SESSION)
    assert classify_edge(edge) == RelationshipLayer.H2H


def test_classify_edge_type_string_a2h() -> None:
    assert classify_edge_type("NOTIFIES") == RelationshipLayer.A2H
    assert classify_edge_type("RECOMMENDS") == RelationshipLayer.A2H
    assert classify_edge_type("DELIVERS_TO") == RelationshipLayer.A2H
    assert classify_edge_type("ESCALATES_TO") == RelationshipLayer.A2H


def test_classify_edge_type_string_h2a() -> None:
    assert classify_edge_type("DELEGATES") == RelationshipLayer.H2A
    assert classify_edge_type("LAUNCHED_BY") == RelationshipLayer.H2A


def test_classify_edge_type_string_a2a() -> None:
    assert classify_edge_type("PAYS") == RelationshipLayer.A2A
    assert classify_edge_type("HIRED") == RelationshipLayer.A2A


def test_classify_edge_type_string_h2h() -> None:
    assert classify_edge_type("HAS_SESSION") == RelationshipLayer.H2H
    assert classify_edge_type("OWNS_WALLET") == RelationshipLayer.H2H


# ── Layer stats ────────────────────────────────────────────────────────────────

def test_get_layer_stats_returns_all_four_layers() -> None:
    edges = [
        _make_edge("u", "s", EdgeType.HAS_SESSION),
        _make_edge("u", "a", EdgeType.DELEGATES),
        _make_edge("a", "u", EdgeType.NOTIFIES),
        _make_edge("a", "b", EdgeType.PAYS),
    ]
    stats = get_layer_stats(edges)
    assert stats["H2H"] == 1
    assert stats["H2A"] == 1
    assert stats["A2H"] == 1
    assert stats["A2A"] == 1


def test_get_layer_stats_empty_edges() -> None:
    stats = get_layer_stats([])
    assert stats == {"H2H": 0, "H2A": 0, "A2H": 0, "A2A": 0}


def test_get_layer_stats_keys_are_exactly_four_layers() -> None:
    stats = get_layer_stats([])
    assert set(stats.keys()) == {"H2H", "H2A", "A2H", "A2A"}


# ── Edge map completeness ──────────────────────────────────────────────────────

def test_edge_layer_map_has_entries_for_all_four_layers() -> None:
    layers_with_edges = {layer for layer in _EDGE_LAYER_MAP.values()}
    for layer in RelationshipLayer:
        assert layer in layers_with_edges, f"No edges registered for layer {layer}"


def test_a2h_vertex_types_include_agent_and_user() -> None:
    from shared.graph.graph import VertexType
    assert VertexType.AGENT in A2H_VERTEX_TYPES
    assert VertexType.USER in A2H_VERTEX_TYPES


def test_h2a_vertex_types_include_user_and_agent() -> None:
    from shared.graph.graph import VertexType
    assert VertexType.USER in H2A_VERTEX_TYPES
    assert VertexType.AGENT in H2A_VERTEX_TYPES
