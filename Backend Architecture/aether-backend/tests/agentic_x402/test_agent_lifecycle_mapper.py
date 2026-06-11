"""Tests for AgentLifecycleMapper — agent lifecycle events → graph mutations."""

from __future__ import annotations

import pytest

from repositories.repos import (
    AgentExecutionRepository,
    DelegationRepository,
    reset_in_memory_stores,
)
from services.agent.lifecycle_mapper import AgentLifecycleMapper
from shared.graph.graph import GraphClient, VertexType


@pytest.fixture(autouse=True)
def isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


TENANT = "test-tenant"
AGENT = "agent-abc"
PARENT_AGENT = "agent-parent"


def _make_mapper():
    return AgentLifecycleMapper(
        graph_client=GraphClient(),
        delegations=DelegationRepository(),
        executions=AgentExecutionRepository(),
    )


def _vertices(mapper: AgentLifecycleMapper) -> dict:
    """Return the in-memory vertex store from the graph backend."""
    backend = mapper._graph._backend
    if backend is None:
        return {}
    return getattr(backend, "_vertices", {})


def _edges(mapper: AgentLifecycleMapper) -> list:
    """Return the in-memory edge list from the graph backend."""
    backend = mapper._graph._backend
    if backend is None:
        return []
    return getattr(backend, "_edges", [])


@pytest.mark.asyncio
async def test_agent_registered_upserts_agent_vertex():
    mapper = _make_mapper()
    result = await mapper.handle_event(
        "agent_registered",
        {
            "agent_id": AGENT,
            "owner_user_id": "user-001",
            "name": "TestAgent",
        },
        TENANT,
    )
    assert result is not None
    expected_vid = f"{TENANT}:agent:{AGENT}"
    # Verify in the in-memory graph store
    vertex = _vertices(mapper).get(expected_vid)
    assert vertex is not None, f"Expected vertex {expected_vid!r} not found"
    assert vertex.properties.get("tenant_id") == TENANT


@pytest.mark.asyncio
async def test_agent_registered_links_owner():
    mapper = _make_mapper()
    await mapper.handle_event(
        "agent_registered",
        {"agent_id": AGENT, "owner_user_id": "user-owner"},
        TENANT,
    )
    agent_vid = f"{TENANT}:agent:{AGENT}"
    edges = [
        e for e in _edges(mapper)
        if e.to_vertex_id == agent_vid
    ]
    assert any("agent" in e.edge_type.lower() or "owns" in e.edge_type.lower() for e in edges), \
        f"Expected ownership edge to {agent_vid!r}, found: {[e.edge_type for e in edges]}"


@pytest.mark.asyncio
async def test_agent_task_created_creates_task_vertex():
    mapper = _make_mapper()
    await mapper.handle_event(
        "agent_task_created",
        {"agent_id": AGENT, "task_id": "task-001", "description": "Do something"},
        TENANT,
    )
    task_vid = f"{TENANT}:task:task-001"
    vertex = _vertices(mapper).get(task_vid)
    assert vertex is not None, f"Expected task vertex {task_vid!r}"
    assert vertex.properties.get("tenant_id") == TENANT


@pytest.mark.asyncio
async def test_task_decomposed_links_parent_to_children():
    mapper = _make_mapper()
    await mapper.handle_event(
        "agent_task_decomposed",
        {
            "agent_id": AGENT,
            "task_id": "parent-task",
            "subtask_ids": ["child-1", "child-2"],
        },
        TENANT,
    )
    parent_vid = f"{TENANT}:task:parent-task"
    child1_vid = f"{TENANT}:task:child-1"
    child2_vid = f"{TENANT}:task:child-2"
    edges = list(_edges(mapper))
    decompose_edges = [
        e for e in edges
        if e.from_vertex_id == parent_vid and e.to_vertex_id in (child1_vid, child2_vid)
    ]
    assert len(decompose_edges) == 2, f"Expected 2 decompose edges, got {len(decompose_edges)}"


@pytest.mark.asyncio
async def test_subagent_spawned_links_parent_to_child():
    mapper = _make_mapper()
    await mapper.handle_event(
        "agent_subagent_spawned",
        {
            "agent_id": PARENT_AGENT,
            "parent_agent_id": AGENT,  # field name the mapper actually reads
        },
        TENANT,
    )
    parent_vid = f"{TENANT}:agent:{PARENT_AGENT}"
    child_vid = f"{TENANT}:agent:{AGENT}"
    edges = [
        e for e in _edges(mapper)
        if e.from_vertex_id == parent_vid and e.to_vertex_id == child_vid
    ]
    assert len(edges) >= 1, "Expected SPAWNED_SUBAGENT edge"


@pytest.mark.asyncio
async def test_agent_lifecycle_graph_writes_are_tenant_scoped():
    mapper = _make_mapper()
    await mapper.handle_event(
        "agent_registered",
        {"agent_id": AGENT, "owner_user_id": "u1"},
        TENANT,
    )
    await mapper.handle_event(
        "agent_registered",
        {"agent_id": AGENT, "owner_user_id": "u2"},
        "other-tenant",
    )
    vid_a = f"{TENANT}:agent:{AGENT}"
    vid_b = f"other-tenant:agent:{AGENT}"
    verts = _vertices(mapper)
    assert vid_a in verts
    assert vid_b in verts
    assert verts[vid_a].properties["tenant_id"] == TENANT
    assert verts[vid_b].properties["tenant_id"] == "other-tenant"


@pytest.mark.asyncio
async def test_agent_legacy_task_normalizes():
    mapper = _make_mapper()
    result = await mapper.handle_event(
        "agent_task",
        {
            "agent_id": AGENT,
            "task_id": "legacy-task",
            "status": "completed",
        },
        TENANT,
    )
    assert result is not None
    task_vid = f"{TENANT}:task:legacy-task"
    assert task_vid in _vertices(mapper)
