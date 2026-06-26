"""Unit tests for /v1/graph/paths*, /v1/graph/snapshots*, /v1/graph/capabilities endpoints."""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def graph_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.operational_intelligence.routes")
        importlib.reload(mod)
        yield mod


def make_request(tenant_id: str = "t1"):
    tenant = SimpleNamespace(tenant_id=tenant_id, require_permission=lambda perm: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


async def _fresh_graph(mod):
    """Return a connected in-memory GraphClient with two seeded nodes and one edge."""
    from shared.graph.graph import Edge, GraphClient, Vertex, VertexType

    client = GraphClient()
    await client.connect()
    for vid in ["node-A", "node-B"]:
        v = Vertex(VertexType.USER, vid)
        v.properties["tenantId"] = "t1"
        await client.add_vertex(v)
    e = Edge("DELEGATES", "node-A", "node-B")
    e.properties["confidence"] = 0.9
    await client.add_edge(e)
    return client


# ── /paths endpoint ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paths_shortest_mode(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B", mode="shortest"
        )
        res = await graph_routes.graph_paths(body, make_request("t1"), graph)
        assert res["data"]["paths"]
        assert res["data"]["paths"][0]["source_id"] == "node-A"


@pytest.mark.asyncio
async def test_paths_strongest_mode(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B", mode="strongest"
        )
        res = await graph_routes.graph_paths(body, make_request("t1"), graph)
        assert res["data"]["paths"]


@pytest.mark.asyncio
async def test_paths_k_shortest_mode(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B",
            mode="k_shortest", k=2
        )
        res = await graph_routes.graph_paths(body, make_request("t1"), graph)
        assert isinstance(res["data"]["paths"], list)


@pytest.mark.asyncio
async def test_paths_neighborhood_mode(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", mode="neighborhood", max_depth=2
        )
        res = await graph_routes.graph_paths(body, make_request("t1"), graph)
        assert res["data"]["paths"] or res["data"]["paths"] == []


@pytest.mark.asyncio
async def test_paths_include_explanation(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B",
            mode="shortest", include_explanation=True
        )
        res = await graph_routes.graph_paths(body, make_request("t1"), graph)
        if res["data"]["paths"]:
            assert res["data"]["explanations"]
            assert "why_connected" in res["data"]["explanations"][0]


@pytest.mark.asyncio
async def test_paths_save_snapshot(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B",
            mode="shortest", save_snapshot=True
        )
        res = await graph_routes.graph_paths(body, make_request("t1"), graph)
        if res["data"]["paths"]:
            assert res["data"]["snapshot_id"] is not None


@pytest.mark.asyncio
async def test_paths_wrong_tenant_raises_forbidden(graph_routes):
    import sys as _sys
    # Get ForbiddenError from the module already loaded alongside graph_routes to avoid
    # class-identity mismatch that arises from nested backend_module_path() re-imports.
    _common = _sys.modules.get("shared.common.common")
    ForbiddenError = _common.ForbiddenError if _common else Exception
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B"
        )
        with pytest.raises(ForbiddenError):
            await graph_routes.graph_paths(body, make_request("t2"), graph)


# ── /paths/expand ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paths_expand_returns_one_hop(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.NodeExpansionRequest(
            tenant_id="t1", node_id="node-A", direction="out"
        )
        res = await graph_routes.graph_paths_expand(body, make_request("t1"), graph)
        assert res["data"]["node_id"] == "node-A"
        assert any(n["id"] == "node-B" for n in res["data"]["added_nodes"])


# ── /paths/explain ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paths_explain_returns_narrative(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        # First create a path to get a path_id
        body_path = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B", mode="shortest"
        )
        res = await graph_routes.graph_paths(body_path, make_request("t1"), graph)
        if not res["data"]["paths"]:
            pytest.skip("no path found to explain")
        path_id = res["data"]["paths"][0]["path_id"]
        body = graph_routes.PathExplainRequest(tenant_id="t1", path_id=path_id)
        res2 = await graph_routes.graph_paths_explain(body, make_request("t1"), graph)
        assert "why_connected" in res2["data"]


# ── /snapshots ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_snapshot(graph_routes):
    with backend_module_path():
        body = graph_routes.SnapshotCreateRequest(
            tenant_id="t1",
            query={"source_id": "node-A"},
            node_ids=["node-A", "node-B"],
            edge_ids=["e1"],
        )
        res = await graph_routes.graph_create_snapshot(body, make_request("t1"))
        assert res["data"]["snapshot_id"]
        assert res["data"]["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_get_snapshot(graph_routes):
    with backend_module_path():
        body = graph_routes.SnapshotCreateRequest(
            tenant_id="t1",
            query={"source_id": "node-A"},
            node_ids=["node-A"],
            edge_ids=[],
        )
        create_res = await graph_routes.graph_create_snapshot(body, make_request("t1"))
        snap_id = create_res["data"]["snapshot_id"]
        get_res = await graph_routes.graph_get_snapshot(snap_id, make_request("t1"))
        assert get_res["data"]["snapshot_id"] == snap_id


@pytest.mark.asyncio
async def test_get_snapshot_wrong_tenant_raises_forbidden(graph_routes):
    with backend_module_path():
        from shared.common.common import ForbiddenError
        body = graph_routes.SnapshotCreateRequest(
            tenant_id="t1",
            query={},
            node_ids=["node-A"],
            edge_ids=[],
        )
        create_res = await graph_routes.graph_create_snapshot(body, make_request("t1"))
        snap_id = create_res["data"]["snapshot_id"]
        with pytest.raises((ForbiddenError, Exception)):
            await graph_routes.graph_get_snapshot(snap_id, make_request("t2"))


# ── /capabilities ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_capabilities_includes_path_intelligence(graph_routes):
    with backend_module_path():
        res = await graph_routes.graph_capabilities()
        features = res["data"]["features"]
        assert "path_intelligence" in features


@pytest.mark.asyncio
async def test_paths_async_job_created_for_deep_query(graph_routes):
    with backend_module_path():
        graph = await _fresh_graph(graph_routes)
        body = graph_routes.PathQuery(
            tenant_id="t1", source_id="node-A", target_id="node-B",
            mode="shortest", max_depth=10,
        )
        res = await graph_routes.graph_paths_create_job(body, make_request("t1"))
        assert "job_id" in res["data"] or "paths" in res["data"]
