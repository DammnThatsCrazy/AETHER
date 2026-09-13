"""Tenant-bound graph reads for the typed Entity Intelligence endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.graph.graph import Edge, GraphClient, Vertex
from services.entity_intelligence.routes import (
    EntityProfileRequest,
    RelationshipsQuery,
    TimelineQuery,
    entity_profile,
    entity_relationships,
    entity_timeline,
)
from services.operational_intelligence.models import EntityRef


class _Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, permission: str) -> None:
        assert permission == "read"


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


def _vertex(vertex_id: str, tenant: str, **properties: object) -> Vertex:
    return Vertex(
        vertex_type="User",
        vertex_id=vertex_id,
        properties={"tenantId": tenant, **properties},
        created_at="2025-01-01T00:00:00+00:00",
    )


async def _graph(*vertices: Vertex, edges: list[Edge]) -> GraphClient:
    graph = GraphClient()
    await graph.connect()
    for vertex in vertices:
        await graph.add_vertex(vertex)
    for edge in edges:
        await graph.add_edge(edge)
    return graph


@pytest.mark.asyncio
async def test_profile_and_timeline_filter_foreign_neighbors_before_projection():
    graph = await _graph(
        _vertex("anchor", "tenant-a", name="Anchor"),
        _vertex("same", "tenant-a", name="Same"),
        _vertex("foreign", "tenant-b", name="Foreign"),
        edges=[
            Edge("RELATED", "anchor", "same"),
            Edge("RELATED", "anchor", "foreign"),
            Edge("TRIGGERED_EVENT", "anchor", "foreign"),
        ],
    )
    request = _request()

    profile = await entity_profile(
        EntityProfileRequest(
            tenantId="tenant-a", entity=EntityRef(kind="user", id="anchor")
        ),
        request,
        graph,
    )
    assert profile.dimensions["relationship"]["total_edges"] == 1

    timeline = await entity_timeline(
        TimelineQuery(
            tenantId="tenant-a", entity=EntityRef(kind="user", id="anchor")
        ),
        request,
        graph,
    )
    assert timeline.items == []


@pytest.mark.asyncio
async def test_relationships_reject_foreign_anchor_and_accept_legacy_tenant_alias():
    graph = await _graph(
        _vertex("anchor", "tenant-a"),
        _vertex("same", "tenant-a"),
        _vertex("legacy", "tenant-a"),
        _vertex("foreign", "tenant-b"),
        edges=[
            Edge("RELATED", "anchor", "same"),
            Edge("RELATED", "anchor", "foreign"),
            Edge("RELATED", "same", "legacy"),
        ],
    )
    result = await entity_relationships(
        RelationshipsQuery(
            tenantId="tenant-a", entity=EntityRef(kind="user", id="anchor"), limit=10
        ),
        _request(),
        graph,
    )
    ids = {relationship.to_entity.id for relationship in result.relationships}
    assert ids == {"same"}

    foreign_anchor = await _graph(
        _vertex("anchor", "tenant-b"),
        _vertex("same", "tenant-a"),
        edges=[Edge("RELATED", "anchor", "same")],
    )
    denied = await entity_relationships(
        RelationshipsQuery(
            tenantId="tenant-a", entity=EntityRef(kind="user", id="anchor"), limit=10
        ),
        _request(),
        foreign_anchor,
    )
    assert denied.relationships == []


@pytest.mark.asyncio
async def test_bfs_tenant_filter_supports_snake_case_and_validates_start():
    graph = await _graph(
        Vertex("User", "anchor", {"tenant_id": "tenant-a"}),
        Vertex("User", "same", {"tenant_id": "tenant-a"}),
        Vertex("User", "foreign", {"tenant_id": "tenant-b"}),
        edges=[Edge("RELATED", "anchor", "same"), Edge("RELATED", "anchor", "foreign")],
    )
    result = await entity_relationships(
        RelationshipsQuery(
            tenantId="tenant-a", entity=EntityRef(kind="user", id="anchor"), limit=10
        ),
        _request(),
        graph,
    )
    assert {relationship.to_entity.id for relationship in result.relationships} == {"same"}
