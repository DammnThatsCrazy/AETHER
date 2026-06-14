"""Profile360 tenant alignment tests."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.profile.composer import ProfileComposer
from shared.graph.graph import Edge, GraphClient, Vertex, VertexType


def _run(coro):
    return asyncio.run(coro)


class _IdentityRepo:
    async def get_profile(self, tenant_id: str, user_id: str):
        return {"user_id": user_id, "tenant_id": tenant_id, "display_name": "Tenant User"}


class _AnalyticsRepo:
    async def query_events(self, tenant_id: str, filters: dict, limit: int = 50):
        return [{"event_id": "evt-1", "event_type": "login", "created_at": "2026-05-10T00:00:00Z", "properties": {"tenant_id": tenant_id}}]


class _ConsentRepo:
    async def get_consent(self, tenant_id: str, user_id: str):
        return {"status": "granted", "tenant_id": tenant_id}


class _Resolver:
    async def get_all_identifiers(self, user_id: str, tenant_id: str):
        return {"wallets": [], "emails": [], "phones": [], "devices": [], "sessions": [], "social": []}


class _Cache:
    pass


def _composer(graph: GraphClient) -> ProfileComposer:
    return ProfileComposer(
        identity_repo=_IdentityRepo(),
        analytics_repo=_AnalyticsRepo(),
        consent_repo=_ConsentRepo(),
        graph=graph,
        cache=_Cache(),
        resolver=_Resolver(),
    )


def test_profile360_graph_excludes_cross_tenant_neighbors_and_audits_legacy():
    graph = GraphClient()
    _run(graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a", "display_name": "Alice"})))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "wallet-a", {"tenant_id": "tenant-a"})))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "wallet-b", {"tenant_id": "tenant-b"})))
    _run(graph.add_vertex(Vertex(VertexType.DEVICE, "legacy-device", {})))
    _run(graph.add_edge(Edge("OWNS_WALLET", "user-1", "wallet-a")))
    _run(graph.add_edge(Edge("OWNS_WALLET", "user-1", "wallet-b")))
    _run(graph.add_edge(Edge("USED_DEVICE", "user-1", "legacy-device")))

    result = _run(_composer(graph)._compose_graph("user-1", tenant_id="tenant-a"))

    node_ids = {node["id"] for node in result["nodes"]}
    assert "wallet-a" in node_ids
    assert "legacy-device" in node_ids
    assert "wallet-b" not in node_ids
    assert result["alignment_audit"]["cross_tenant_neighbors_excluded"] == 1
    assert result["alignment_audit"]["legacy_unscoped_neighbors"] == 1


def test_profile360_surface_marks_kyber_internal_and_tenant_scoped():
    graph = GraphClient()
    _run(graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a"})))

    result = _run(_composer(graph).get_profile360_surface("human", "user-1", "tenant-a", include=["identity", "graph", "timeline", "debug"]))

    assert result["surface"] == "kyber_internal"
    assert result["visibility"] == "internal_full"
    assert result["tenant_id"] == "tenant-a"
    assert result["alignment_audit"]["end_user_surface_requires_redaction"] is True


def test_graph_nodes_include_profile_links():
    """Graph nodes returned by _compose_graph include profile_id and profile_links."""
    graph = GraphClient()
    _run(graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a", "display_name": "Alice"})))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "wallet-a", {"tenant_id": "tenant-a"})))
    _run(graph.add_edge(Edge("OWNS_WALLET", "user-1", "wallet-a")))

    result = _run(_composer(graph)._compose_graph("user-1", tenant_id="tenant-a"))

    nodes = result["nodes"]
    assert len(nodes) >= 2

    for node in nodes:
        assert "profile_id" in node, f"Node {node.get('id')} missing profile_id"
        assert "profile_links" in node, f"Node {node.get('id')} missing profile_links"
        assert node["profile_links"]["summary"].startswith("/v1/profile/")
        assert node["profile_links"]["full"].startswith("/v1/profile360/")
        assert "entity_type" in node
        assert "display_label" in node


def test_graph_root_node_fallback_includes_profile_links():
    """Root node fallback (when vertex not found) still includes profile_links."""
    graph = GraphClient()

    result = _run(_composer(graph)._compose_graph("ghost-user", tenant_id="tenant-a"))

    assert result["nodes"] == []
    assert result["neighbor_count"] == 0


def test_graph_nodes_profile_links_use_correct_entity_type():
    """Graph node profile_links.full uses the actual vertex_type, not a hardcoded fallback."""
    graph = GraphClient()
    _run(graph.add_vertex(Vertex(VertexType.USER, "user-1", {"tenant_id": "tenant-a"})))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "wallet-a", {"tenant_id": "tenant-a"})))
    _run(graph.add_edge(Edge("OWNS_WALLET", "user-1", "wallet-a")))

    result = _run(_composer(graph)._compose_graph("user-1", tenant_id="tenant-a"))

    nodes_by_id = {n["id"]: n for n in result["nodes"]}
    wallet_node = nodes_by_id.get("wallet-a")
    assert wallet_node is not None
    assert "/wallet-a" in wallet_node["profile_links"]["full"]
    assert wallet_node["profile_links"]["summary"] == "/v1/profile/wallet-a/summary"
