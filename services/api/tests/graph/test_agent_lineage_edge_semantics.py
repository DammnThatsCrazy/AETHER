"""AO-6: agent lineage graph semantics.

Durable semantic edges only, evidence on every lineage edge, and tool
invocations are never graph-projected per call.
"""

from __future__ import annotations

import pytest

from ingestion.silver.projectors.silver_graph_projector import (
    _bounded_edge,
    build_external_agent_run_mutations,
)
from shared.agent_lineage import vocabulary as V
from shared.graph.edge_properties import (
    LINEAGE_EDGE_PROPERTIES,
    LINEAGE_RESOLUTION_METHODS,
    OPTIONAL_EDGE_PROPERTIES,
    build_edge_properties,
    build_lineage_edge_properties,
)
from shared.graph.graph import EdgeType, VertexType
from shared.graph.graph_contract import (
    LINEAGE_EXECUTION_PLANE_ONLY,
    LINEAGE_INVERSE_RELATIONSHIPS,
    LINEAGE_RELATIONSHIP_EDGE_TYPES,
    validate_contract,
)
from shared.graph.relationship_layers import RelationshipLayer, _EDGE_LAYER_MAP

_EDGE_VALUES = {
    v for k, v in vars(EdgeType).items() if not k.startswith("_") and isinstance(v, str)
}


def test_every_lineage_relationship_is_mapped_or_execution_plane_only():
    declared = set(V.LINEAGE_RELATIONSHIP_TYPES)
    mapped = set(LINEAGE_RELATIONSHIP_EDGE_TYPES)
    assert mapped | LINEAGE_EXECUTION_PLANE_ONLY == declared
    assert not mapped & LINEAGE_EXECUTION_PLANE_ONLY
    # Per-call invocation is the execution plane, never a graph edge.
    assert "INVOKED" in LINEAGE_EXECUTION_PLANE_ONLY
    assert "INVOKED" not in LINEAGE_RELATIONSHIP_EDGE_TYPES


def test_lineage_edge_types_exist_and_are_layer_classified():
    for relationship, edge_type in LINEAGE_RELATIONSHIP_EDGE_TYPES.items():
        assert edge_type in _EDGE_VALUES, relationship
        assert _EDGE_LAYER_MAP[edge_type] in {
            RelationshipLayer.H2H, RelationshipLayer.H2A, RelationshipLayer.A2A,
            RelationshipLayer.A2H,
        }, relationship
    assert validate_contract() == []


def test_inverse_relationships_share_the_forward_edge_not_a_second_edge():
    for inverse, forward in LINEAGE_INVERSE_RELATIONSHIPS.items():
        assert LINEAGE_RELATIONSHIP_EDGE_TYPES[inverse] == LINEAGE_RELATIONSHIP_EDGE_TYPES[forward]


def test_identity_hierarchy_edges_are_new_and_agent_internal():
    assert _EDGE_LAYER_MAP[EdgeType.DEPLOYED_AS] == RelationshipLayer.A2A
    assert _EDGE_LAYER_MAP[EdgeType.INSTANTIATED_AS] == RelationshipLayer.A2A
    assert _EDGE_LAYER_MAP[EdgeType.PRINCIPAL_OF] == RelationshipLayer.H2A


def test_lineage_edge_properties_are_the_work_order_set_and_declared_optional():
    assert set(LINEAGE_EDGE_PROPERTIES) == {
        "evidence_refs", "relationship_confidence", "authority_ref", "valid_from",
        "valid_to", "observed_at", "source_namespace", "relationship_status",
        "resolution_method",
    }
    assert set(LINEAGE_EDGE_PROPERTIES) <= OPTIONAL_EDGE_PROPERTIES | {"valid_from"}


def test_lineage_edge_properties_require_evidence_and_known_vocabulary():
    props = build_lineage_edge_properties(
        evidence_refs=["evt-1"], resolution_method="authority_record",
        relationship_status="active", relationship_confidence=0.75,
        authority_ref="deleg-1", observed_at="2026-10-30T10:00:00Z",
        source_namespace="vendor.runtime",
    )
    assert props["evidence_refs"] == ["evt-1"]
    assert props["relationship_confidence"] == "0.75"
    assert props["authority_ref"] == "deleg-1"
    with pytest.raises(ValueError):
        build_lineage_edge_properties(evidence_refs=[], resolution_method="deterministic")
    with pytest.raises(ValueError):
        build_lineage_edge_properties(evidence_refs=["  "], resolution_method="deterministic")
    with pytest.raises(ValueError):
        build_lineage_edge_properties(evidence_refs=["e"], resolution_method="vibes")
    with pytest.raises(ValueError):
        build_lineage_edge_properties(evidence_refs=["e"], resolution_method="manual", relationship_status="maybe")
    with pytest.raises(ValueError):
        build_lineage_edge_properties(evidence_refs=["e"], resolution_method="manual", relationship_confidence=1.5)
    assert set(LINEAGE_RESOLUTION_METHODS) >= {"deterministic", "source_reported", "probabilistic"}


def test_unknown_confidence_is_omitted_not_zeroed():
    props = build_lineage_edge_properties(evidence_refs=["e"], resolution_method="source_reported")
    assert "relationship_confidence" not in props


def test_lineage_properties_merge_through_the_canonical_edge_builder():
    props = build_edge_properties(
        tenant_id="t", edge_type=EdgeType.DELEGATED_TO, from_vertex_id="a", to_vertex_id="b",
        actor_kind="system", actor_id="x", provenance="p", valid_from="2026-10-30T00:00:00Z",
        **build_lineage_edge_properties(evidence_refs=["e1"], resolution_method="deterministic"),
    )
    assert props["evidence_refs"] == ["e1"] and props["resolution_method"] == "deterministic"


def test_bounded_silver_edges_carry_evidence_and_claim_status():
    edge = _bounded_edge(
        EdgeType.AGENT_USED_TOOL_OBS, "agent-1", "tool:t:x", "t", "evt-9", "2026-10-30T10:00:00Z",
    )
    assert edge.properties["evidence_refs"] == ["evt-9"]
    assert edge.properties["resolution_method"] == "source_reported"
    assert edge.properties["relationship_status"] == "unknown"
    assert edge.properties["observed_at"] == "2026-10-30T10:00:00Z"


def _row(**changes) -> dict:
    row = {
        "tenant_id": "tenant-a", "deployment_id": "dep-a", "run_id": "run-1",
        "run_correlation_source": "run_id", "source_event_id": "evt-1",
        "event_name": "agent_task_started", "occurred_at": "2026-10-30T10:00:00+00:00",
    }
    row.update(changes)
    return row


def _action_vertices(mutations):
    return [m for m in mutations if getattr(m, "vertex_type", None) == VertexType.ACTION_RECORD]


@pytest.mark.parametrize("event_name", [
    "agent_tool_invocation_observed", "agent_tool_called", "agent_tool_observed",
    "agent_step_observed",
])
def test_tool_invocations_are_not_graph_projected_per_call(event_name):
    # Seventeen thousand identical calls would otherwise be seventeen thousand
    # ActionRecord vertices; they remain Silver facts only.
    mutations = []
    for i in range(5):
        mutations += build_external_agent_run_mutations(_row(
            event_name=event_name, source_event_id=f"evt-{i}",
            tool_name="get_balance", action_ref=f"act-{i}", trigger_ref="trig",
        ))
    assert _action_vertices(mutations) == []


def test_tool_invocation_with_durable_semantic_evidence_is_still_graphed():
    mutations = build_external_agent_run_mutations(_row(
        event_name="agent_tool_invocation_observed", tool_name="transfer",
        policy_id="policy-1", policy_decision="deny",
    ))
    assert len(_action_vertices(mutations)) == 1


def test_run_action_vertices_carry_source_reported_lineage_not_canonical_principal():
    mutations = build_external_agent_run_mutations(_row(
        event_name="agent_subagent_spawned", child_agent_ref="worker-1",
        parent_agent_ref="orch-1", root_agent_ref="orch-1",
        source_run_id="run-1", root_run_id="run-0", agent_instance_id="inst-7",
        reported_principal_ref="human-claimed", control_mode="AGENT_DELEGATED_TO_AGENT",
        canonical_principal_entity_id="entity-should-never-appear",
    ))
    (action,) = _action_vertices(mutations)
    assert action.properties["agent_instance_id"] == "inst-7"
    assert action.properties["control_mode"] == "AGENT_DELEGATED_TO_AGENT"
    assert action.properties["reported_principal_ref"] == "human-claimed"
    assert action.properties["evidence_status"] == "source_reported"
    assert "canonical_principal_entity_id" not in action.properties
