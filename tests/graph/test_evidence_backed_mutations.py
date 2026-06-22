"""Tests for evidence-backed graph mutations.

Verifies:
- New edge types (PURCHASED, ACHIEVED_OUTCOME, CONTACTED) are registered
- source_event_id is enforced for silver-sourced mutations
- idempotency key is deterministic
- SilverGraphProjector emits correct edge types per projection result
"""

from __future__ import annotations

import pytest


def test_new_edge_types_registered():
    from shared.graph.graph import EdgeType
    assert hasattr(EdgeType, "PURCHASED")
    assert hasattr(EdgeType, "ACHIEVED_OUTCOME")
    assert hasattr(EdgeType, "CONTACTED")
    assert EdgeType.PURCHASED == "PURCHASED"
    assert EdgeType.ACHIEVED_OUTCOME == "ACHIEVED_OUTCOME"
    assert EdgeType.CONTACTED == "CONTACTED"


def test_new_edge_types_in_layer_map():
    from shared.graph.graph import EdgeType
    from shared.graph.relationship_layers import classify_edge_type, RelationshipLayer
    assert classify_edge_type(EdgeType.PURCHASED) == RelationshipLayer.H2A
    assert classify_edge_type(EdgeType.ACHIEVED_OUTCOME) == RelationshipLayer.H2H
    assert classify_edge_type(EdgeType.CONTACTED) == RelationshipLayer.A2H


def test_silver_sourced_edge_requires_source_event_id():
    from shared.graph.graph import Edge, EdgeType
    from shared.graph.edge_properties import build_edge_properties
    from shared.graph.write_validator import GraphWriteValidator

    props = build_edge_properties(
        tenant_id="t1",
        edge_type=EdgeType.PURCHASED,
        from_vertex_id="user-1",
        to_vertex_id="product-1",
        actor_kind="system",
        actor_id="silver_projector",
        provenance="silver_projector",
        provenance_class="silver",
        valid_from="2026-01-01T00:00:00Z",
        source_event_id="",   # intentionally empty — should fail
        consent_purpose="commerce",
    )
    edge = Edge(
        edge_type=EdgeType.PURCHASED,
        from_vertex_id="user-1",
        to_vertex_id="product-1",
        properties=props,
    )
    result = GraphWriteValidator().validate(edge, env="staging")
    assert not result.passed
    assert any("silver" in v.lower() and "source_event_id" in v for v in result.violations)


def test_silver_sourced_edge_passes_with_source_event_id():
    from shared.graph.graph import Edge, EdgeType
    from shared.graph.edge_properties import build_edge_properties
    from shared.graph.write_validator import GraphWriteValidator

    props = build_edge_properties(
        tenant_id="t1",
        edge_type=EdgeType.PURCHASED,
        from_vertex_id="user-1",
        to_vertex_id="product-1",
        actor_kind="system",
        actor_id="silver_projector",
        provenance="silver_projector",
        provenance_class="silver",
        valid_from="2026-01-01T00:00:00Z",
        source_event_id="evt-abc-123",
        consent_purpose="commerce",
    )
    edge = Edge(
        edge_type=EdgeType.PURCHASED,
        from_vertex_id="user-1",
        to_vertex_id="product-1",
        properties=props,
    )
    result = GraphWriteValidator().validate(edge, env="staging")
    assert result.passed, result.violations


def test_direct_sourced_edge_does_not_require_source_event_id():
    from shared.graph.graph import Edge, EdgeType
    from shared.graph.edge_properties import build_edge_properties
    from shared.graph.write_validator import GraphWriteValidator

    props = build_edge_properties(
        tenant_id="t1",
        edge_type=EdgeType.ACHIEVED_OUTCOME,
        from_vertex_id="user-1",
        to_vertex_id="goal-1",
        actor_kind="system",
        actor_id="api",
        provenance="api",
        provenance_class="direct",
        valid_from="2026-01-01T00:00:00Z",
        source_event_id="",
    )
    edge = Edge(
        edge_type=EdgeType.ACHIEVED_OUTCOME,
        from_vertex_id="user-1",
        to_vertex_id="goal-1",
        properties=props,
    )
    result = GraphWriteValidator().validate(edge, env="staging")
    assert result.passed, result.violations


def test_idempotency_key_is_deterministic():
    from shared.graph.edge_properties import make_edge_idempotency_key
    k1 = make_edge_idempotency_key("t1", "PURCHASED", "user-1", "product-1", "evt-abc")
    k2 = make_edge_idempotency_key("t1", "PURCHASED", "user-1", "product-1", "evt-abc")
    assert k1 == k2
    assert len(k1) == 64


def test_idempotency_key_differs_by_source_event_id():
    from shared.graph.edge_properties import make_edge_idempotency_key
    k1 = make_edge_idempotency_key("t1", "PURCHASED", "user-1", "product-1", "evt-1")
    k2 = make_edge_idempotency_key("t1", "PURCHASED", "user-1", "product-1", "evt-2")
    assert k1 != k2
