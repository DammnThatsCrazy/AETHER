"""WP2.6 Profile360 fixes.

1. _compose_graph surfaces REAL graph edge types (drops the generic
   RELATED_TO / profile360_inferred synthesis).
2. ProfileComposer readiness adopts the canonical DimensionEnvelope contract
   (per-dimension envelopes rolled up to the single worst state).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.profile.composer import ProfileComposer
from shared.dimension_state import DIMENSION_STATES
from shared.graph.graph import Edge, GraphClient, Vertex, VertexType


def _composer(graph: GraphClient) -> ProfileComposer:
    identity = MagicMock()
    identity.get_profile = AsyncMock(return_value={"user_id": "user-1", "status": "active"})
    analytics = MagicMock()
    consent = MagicMock()
    consent.get_consent = AsyncMock(return_value={"status": "granted"})
    cache = MagicMock()
    resolver = MagicMock()
    resolver.get_all_identifiers = AsyncMock(return_value=[{"type": "email"}])
    return ProfileComposer(identity, analytics, consent, graph, cache, resolver)


@pytest.mark.asyncio
async def test_compose_graph_uses_real_edge_type_not_related_to():
    graph = GraphClient()
    await graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a"}))
    await graph.add_vertex(Vertex(VertexType.WALLET, "wallet-a", {"tenant_id": "tenant-a"}))
    await graph.add_edge(Edge(
        "OWNS_WALLET", "user-1", "wallet-a",
        {"tenant_id": "tenant-a", "confidence": "0.9", "provenance": "identity_resolution"},
    ))

    result = await _composer(graph)._compose_graph("user-1", tenant_id="tenant-a")

    assert len(result["edges"]) == 1
    edge = result["edges"][0]
    assert edge["type"] == "OWNS_WALLET"          # real type, not RELATED_TO
    assert edge["source"] == "user-1" and edge["target"] == "wallet-a"
    assert edge["weight"] == pytest.approx(0.9)   # from the real confidence
    assert edge["label"] == "owns wallet"
    # The synthetic inference marker is gone; real provenance is surfaced.
    assert "profile360_inferred" not in edge["metadata"]
    assert edge["metadata"]["provenance"] == "identity_resolution"


@pytest.mark.asyncio
async def test_compose_graph_excludes_cross_tenant_edge_between_in_tenant_vertices():
    """A relationship whose own tenant_id belongs to another tenant must not be
    surfaced/relabeled as the requesting tenant, even when both endpoints are
    in-tenant vertices (F1 regression)."""
    graph = GraphClient()
    await graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a"}))
    await graph.add_vertex(Vertex(VertexType.WALLET, "wallet-a", {"tenant_id": "tenant-a"}))
    # Edge between two in-tenant vertices, but carrying tenant-b provenance.
    await graph.add_edge(Edge(
        "OWNS_WALLET", "user-1", "wallet-a",
        {"tenant_id": "tenant-b", "provenance": "tenant_b_only_secret"},
    ))

    result = await _composer(graph)._compose_graph("user-1", tenant_id="tenant-a")

    # The other tenant's relationship is not leaked (no relabel to tenant-a).
    assert result["edges"] == []
    assert result["alignment_audit"]["cross_tenant_edges_excluded"] == 1


@pytest.mark.asyncio
async def test_compose_graph_no_synthetic_edge_type_anywhere():
    graph = GraphClient()
    await graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a"}))
    await graph.add_vertex(Vertex(VertexType.DEVICE, "dev-1", {"tenant_id": "tenant-a"}))
    await graph.add_edge(Edge("USED_DEVICE", "user-1", "dev-1", {"tenant_id": "tenant-a"}))

    result = await _composer(graph)._compose_graph("user-1", tenant_id="tenant-a")
    assert [e["type"] for e in result["edges"]] == ["USED_DEVICE"]
    assert all("RELATED_TO" != e["type"] for e in result["edges"])


_LIGHT = dict(
    include_timeline=False, include_graph=False,
    include_intelligence=False, include_lake=False,
)


@pytest.mark.asyncio
async def test_readiness_uses_dimension_envelopes():
    graph = GraphClient()
    result = await _composer(graph).get_full_profile("user-1", "tenant-a", **_LIGHT)

    readiness = result["readiness"]
    assert readiness["state"] == "ready"
    assert readiness["degraded_dimensions"] == []
    # Canonical DimensionEnvelope contract per active dimension.
    dims = readiness["dimensions"]
    assert {d["dimension"] for d in dims} == {"core", "identifiers", "consent"}
    for env in dims:
        assert env["state"] in DIMENSION_STATES
        assert "reason_code" in env
        assert env["state"] == "ready"


@pytest.mark.asyncio
async def test_readiness_degraded_dimension_is_canonical():
    graph = GraphClient()
    composer = _composer(graph)
    composer._resolver.get_all_identifiers = AsyncMock(side_effect=RuntimeError("boom"))

    result = await composer.get_full_profile("user-1", "tenant-a", **_LIGHT)
    readiness = result["readiness"]

    assert readiness["state"] == "degraded"
    degraded = {d["dimension"]: d for d in readiness["degraded_dimensions"]}
    assert "identifiers" in degraded
    assert degraded["identifiers"]["state"] == "degraded"
    assert degraded["identifiers"]["reason_code"] == "dependency_failed"
    assert result["identifiers"] == []  # typed default preserved
