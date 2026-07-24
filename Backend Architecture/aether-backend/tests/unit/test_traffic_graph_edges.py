"""Source/attribution graph edges projected from touchpoint facts (spec §13.6)."""

from __future__ import annotations

import pytest

from services.silver.projectors import silver_graph_projector as sgp
from services.silver.projectors.base import ProjectionResult
from shared.graph.graph import EdgeType
from shared.graph.relationship_layers import classify_edge_type, RelationshipLayer


def _touchpoint_row(**over):
    row = {
        "tenant_id": "tenant-a",
        "source_event_id": "evt-1",
        "occurred_at": "2026-07-10T00:00:00+00:00",
        "profile_id": "profile-1",
        "session_id": "session-1",
        "source_class": "organic_search",
        "source": "google",
    }
    row.update(over)
    return row


@pytest.fixture
def captured(monkeypatch):
    edges: list = []

    async def _fake_emit(edge, *, subject_id: str = ""):
        edges.append(edge)

    monkeypatch.setattr(sgp, "_emit", _fake_emit)
    return edges


async def _run(rows):
    projector = sgp.SilverGraphProjector()
    result = ProjectionResult(table="silver_campaign_touchpoint_facts", rows=rows)
    await projector.maybe_emit(result, {})


@pytest.mark.asyncio
async def test_arrived_through_source_edge(captured) -> None:
    await _run([_touchpoint_row()])
    arrived = [e for e in captured if e.edge_type == EdgeType.ARRIVED_THROUGH_SOURCE]
    assert len(arrived) == 1
    edge = arrived[0]
    assert edge.from_vertex_id == "profile-1"
    assert edge.to_vertex_id == "source:tenant-a:organic_search:google"
    assert edge.properties["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_placement_link_platform_and_referral_edges(captured) -> None:
    rows = [
        _touchpoint_row(
            placement_id="plc-9",
            verified_referral_link_id="link-7",
            entry_method="ios_universal_link",
            proof_level="platform_verified",
            source_class="ai_referral",
            actor_type="ai",
            ai_provider="openai",
        )
    ]
    await _run(rows)
    kinds = {e.edge_type for e in captured}
    assert EdgeType.USED_PLACEMENT in kinds
    assert EdgeType.ORIGINATED_FROM_LINK in kinds
    assert EdgeType.ATTRIBUTED_TO_PLATFORM_EVIDENCE in kinds
    assert EdgeType.REFERRED_ENTITY in kinds

    referred = next(e for e in captured if e.edge_type == EdgeType.REFERRED_ENTITY)
    assert referred.from_vertex_id == "ai:tenant-a:openai"
    assert referred.to_vertex_id == "profile-1"

    platform = next(e for e in captured if e.edge_type == EdgeType.ATTRIBUTED_TO_PLATFORM_EVIDENCE)
    assert platform.to_vertex_id == "platform_evidence:tenant-a:ios_universal_link"


@pytest.mark.asyncio
async def test_platform_evidence_requires_platform_verified_proof(captured) -> None:
    # Same install entry method but only declared proof — no platform-evidence edge.
    await _run([_touchpoint_row(entry_method="ios_universal_link", proof_level="declared")])
    kinds = {e.edge_type for e in captured}
    assert EdgeType.ATTRIBUTED_TO_PLATFORM_EVIDENCE not in kinds


@pytest.mark.asyncio
async def test_edges_are_tenant_scoped(captured) -> None:
    await _run([
        _touchpoint_row(tenant_id="tenant-a", source_event_id="a1", profile_id="p-a"),
        _touchpoint_row(tenant_id="tenant-b", source_event_id="b1", profile_id="p-b"),
    ])
    arrived = [e for e in captured if e.edge_type == EdgeType.ARRIVED_THROUGH_SOURCE]
    by_tenant = {e.properties["tenant_id"]: e for e in arrived}
    assert set(by_tenant) == {"tenant-a", "tenant-b"}
    assert by_tenant["tenant-a"].to_vertex_id.startswith("source:tenant-a:")
    assert by_tenant["tenant-b"].to_vertex_id.startswith("source:tenant-b:")


@pytest.mark.asyncio
async def test_edge_identity_is_idempotent_on_replay(captured) -> None:
    row = _touchpoint_row()
    await _run([row])
    await _run([dict(row)])  # replay same event
    arrived = [e for e in captured if e.edge_type == EdgeType.ARRIVED_THROUGH_SOURCE]
    # Two emissions, but identical (from, to, edge_type) identity — idempotent upsert.
    assert len(arrived) == 2
    a, b = arrived
    assert (a.from_vertex_id, a.to_vertex_id, a.edge_type) == (
        b.from_vertex_id, b.to_vertex_id, b.edge_type
    )


@pytest.mark.asyncio
async def test_rows_without_source_event_id_emit_nothing(captured) -> None:
    await _run([_touchpoint_row(source_event_id="")])
    assert captured == []


def test_new_edge_types_are_registered_in_layer_map() -> None:
    # classify_edge_type raises for unregistered edges in staging/prod.
    assert classify_edge_type(EdgeType.ARRIVED_THROUGH_SOURCE) == RelationshipLayer.EXCLUDED
    assert classify_edge_type(EdgeType.USED_PLACEMENT) == RelationshipLayer.EXCLUDED
    assert classify_edge_type(EdgeType.ORIGINATED_FROM_LINK) == RelationshipLayer.EXCLUDED
    assert classify_edge_type(EdgeType.ATTRIBUTED_TO_PLATFORM_EVIDENCE) == RelationshipLayer.EXCLUDED
    assert classify_edge_type(EdgeType.REFERRED_ENTITY) == RelationshipLayer.A2H
