"""Tests for AgentLifecycleMapper — agent lifecycle events → graph mutations."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    original = list(sys.path)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


TENANT = "test-tenant"
AGENT = "agent-abc"
PARENT_AGENT = "agent-parent"


def _graph_vertices(mapper):
    """Return in-memory vertex store regardless of backend attribute name."""
    g = mapper._graph
    if hasattr(g, "_vertices"):
        return g._vertices
    if hasattr(g, "_backend") and g._backend is not None:
        return getattr(g._backend, "_vertices", {})
    return {}


def _graph_edges(mapper) -> list:
    g = mapper._graph
    if hasattr(g, "_backend") and g._backend is not None:
        return getattr(g._backend, "_edges", [])
    return []


@pytest.mark.asyncio
async def test_agent_registered_upserts_agent_vertex(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentExecutionRepository, DelegationRepository, reset_in_memory_stores
        from services.agent.lifecycle_mapper import AgentLifecycleMapper
        from shared.graph.graph import GraphClient
        reset_in_memory_stores()
        mapper = AgentLifecycleMapper(GraphClient(), DelegationRepository(), AgentExecutionRepository())
        result = await mapper.handle_event(
            "agent_registered",
            {"agent_id": AGENT, "owner_user_id": "user-001", "name": "TestAgent"},
            TENANT,
        )
        assert result is not None
        vid = f"{TENANT}:agent:{AGENT}"
        verts = _graph_vertices(mapper)
        assert vid in verts, f"Expected vertex {vid!r} in {list(verts.keys())[:5]}"
        assert verts[vid].properties.get("tenant_id") == TENANT
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_agent_task_created_creates_task_vertex(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentExecutionRepository, DelegationRepository, reset_in_memory_stores
        from services.agent.lifecycle_mapper import AgentLifecycleMapper
        from shared.graph.graph import GraphClient
        reset_in_memory_stores()
        mapper = AgentLifecycleMapper(GraphClient(), DelegationRepository(), AgentExecutionRepository())
        await mapper.handle_event(
            "agent_task_created",
            {"agent_id": AGENT, "task_id": "task-001", "description": "Do something"},
            TENANT,
        )
        task_vid = f"{TENANT}:task:task-001"
        verts = _graph_vertices(mapper)
        assert task_vid in verts, f"Expected task vertex, got: {list(verts.keys())[:5]}"
        assert verts[task_vid].properties.get("tenant_id") == TENANT
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_task_decomposed_links_parent_to_children(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentExecutionRepository, DelegationRepository, reset_in_memory_stores
        from services.agent.lifecycle_mapper import AgentLifecycleMapper
        from shared.graph.graph import GraphClient
        reset_in_memory_stores()
        mapper = AgentLifecycleMapper(GraphClient(), DelegationRepository(), AgentExecutionRepository())
        await mapper.handle_event(
            "agent_task_decomposed",
            {"agent_id": AGENT, "task_id": "parent-task", "subtask_ids": ["child-1", "child-2"]},
            TENANT,
        )
        parent_vid = f"{TENANT}:task:parent-task"
        child_vids = {f"{TENANT}:task:child-1", f"{TENANT}:task:child-2"}
        edges = _graph_edges(mapper)
        decompose = [e for e in edges if e.from_vertex_id == parent_vid and e.to_vertex_id in child_vids]
        assert len(decompose) == 2
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_subagent_spawned_links_parent_to_child(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentExecutionRepository, DelegationRepository, reset_in_memory_stores
        from services.agent.lifecycle_mapper import AgentLifecycleMapper
        from shared.graph.graph import GraphClient
        reset_in_memory_stores()
        mapper = AgentLifecycleMapper(GraphClient(), DelegationRepository(), AgentExecutionRepository())
        await mapper.handle_event(
            "agent_subagent_spawned",
            {"agent_id": PARENT_AGENT, "parent_agent_id": AGENT},
            TENANT,
        )
        parent_vid = f"{TENANT}:agent:{PARENT_AGENT}"
        child_vid = f"{TENANT}:agent:{AGENT}"
        edges = _graph_edges(mapper)
        spawn_edges = [e for e in edges if e.from_vertex_id == parent_vid and e.to_vertex_id == child_vid]
        assert spawn_edges, "Expected SPAWNED_SUBAGENT edge"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_agent_lifecycle_graph_writes_are_tenant_scoped(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentExecutionRepository, DelegationRepository, reset_in_memory_stores
        from services.agent.lifecycle_mapper import AgentLifecycleMapper
        from shared.graph.graph import GraphClient
        reset_in_memory_stores()
        mapper = AgentLifecycleMapper(GraphClient(), DelegationRepository(), AgentExecutionRepository())
        await mapper.handle_event("agent_registered", {"agent_id": AGENT, "owner_user_id": "u1"}, TENANT)
        await mapper.handle_event("agent_registered", {"agent_id": AGENT, "owner_user_id": "u2"}, "other-tenant")
        vid_a = f"{TENANT}:agent:{AGENT}"
        vid_b = f"other-tenant:agent:{AGENT}"
        verts = _graph_vertices(mapper)
        assert vid_a in verts and vid_b in verts
        assert verts[vid_a].properties["tenant_id"] == TENANT
        assert verts[vid_b].properties["tenant_id"] == "other-tenant"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_agent_legacy_task_normalizes(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentExecutionRepository, DelegationRepository, reset_in_memory_stores
        from services.agent.lifecycle_mapper import AgentLifecycleMapper
        from shared.graph.graph import GraphClient
        reset_in_memory_stores()
        mapper = AgentLifecycleMapper(GraphClient(), DelegationRepository(), AgentExecutionRepository())
        result = await mapper.handle_event(
            "agent_task",
            {"agent_id": AGENT, "task_id": "legacy-task", "status": "completed"},
            TENANT,
        )
        assert result is not None
        task_vid = f"{TENANT}:task:legacy-task"
        assert task_vid in _graph_vertices(mapper)
        reset_in_memory_stores()
