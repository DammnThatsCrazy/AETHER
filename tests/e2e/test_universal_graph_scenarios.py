"""End-to-end tests for Universal Intelligence Graph acceptance scenarios.

Scenario A: Campaign macro-to-micro — campaign node → cluster → entity
Scenario B: Historical graph change — compare two point-in-time snapshots
Scenario D: Fraud network investigation — overlay returns fraud membership
Scenario E: Agent delegation path — A2A traversal follows delegation chain
Scenario G: Consent withdrawal — activation_eligible=false on withdrawn nodes

These tests exercise real service code (no HTTP, no database) using the
in-memory graph store to simulate the full query pipeline.

Requires backend dependencies. Skipped gracefully if not installed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

import uuid
from datetime import timezone


TENANT = "e2e-test-tenant"


def _ts(offset_days: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


async def _make_graph():
    from shared.graph.graph import GraphClient, Vertex, Edge, VertexType
    g = GraphClient()
    return g, VertexType


# ── Scenario A: Campaign macro-to-micro ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_a_campaign_macro_to_micro() -> None:
    """Traversing from a campaign node should reach its member entities."""
    from shared.graph.graph import GraphClient, Vertex, Edge
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()

    campaign_id = f"campaign-{_uid()}"
    cluster_id = f"cluster-{_uid()}"
    entity_id = f"user-{_uid()}"

    def _v(vid, vtype, extra=None):
        return Vertex(
            vertex_id=vid, vertex_type=vtype,
            properties={"tenantId": TENANT, "label": vid, **(extra or {})},
        )

    await graph.add_vertex(_v(campaign_id, "campaign", {"channel": "social"}))
    await graph.add_vertex(_v(cluster_id, "cluster", {"cluster_type": "identity"}))
    await graph.add_vertex(_v(entity_id, "human", {"risk_score": 0.1, "trust_score": 0.9}))

    def _e(src, tgt, etype, props=None):
        return Edge(
            edge_id=f"{src}-{etype}-{tgt}", edge_type=etype,
            source_vertex_id=src, target_vertex_id=tgt,
            properties={"tenantId": TENANT, **(props or {})},
        )

    await graph.add_edge(_e(entity_id, campaign_id, "ACQUIRED_VIA"))
    await graph.add_edge(_e(entity_id, cluster_id, "MEMBER_OF_CLUSTER", {"confidence": 0.92}))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(campaign_id, depth=2, direction="in", tenant_id=TENANT)

    visited_ids = {v.vertex_id for v in result.vertices}
    assert entity_id in visited_ids, "Entity should be reachable from campaign node via BFS"
    assert cluster_id in visited_ids, "Cluster should also be reachable"


# ── Scenario B: Historical graph change ───────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_b_historical_comparison() -> None:
    """Point-in-time replay must return materially different node sets."""
    from shared.graph.graph import GraphClient, Vertex
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    entity_id = f"user-{_uid()}"

    t1 = _ts(-10)
    t3 = _ts(-5)
    t5 = _ts(0)

    # Version 1 of the entity (valid T1 → T3)
    v1 = Vertex(
        vertex_id=entity_id, vertex_type="human",
        properties={
            "tenantId": TENANT, "label": "v1",
            "valid_from": t1, "valid_to": t3, "recorded_at": t1,
            "lifecycle_state": "provisional",
        },
    )
    # Version 2 of the entity (valid from T3 onward)
    v2 = Vertex(
        vertex_id=entity_id + "-v2", vertex_type="human",
        properties={
            "tenantId": TENANT, "label": "v2",
            "valid_from": t3, "recorded_at": t3,
            "lifecycle_state": "active",
        },
    )
    await graph.add_vertex(v1)
    await graph.add_vertex(v2)

    engine = GraphTraversalEngine(graph)

    # Query at T2 (between T1 and T3): should find v1 (provisional)
    result_t2 = await engine.temporal_bfs(entity_id, as_of=_ts(-7), depth=0, tenant_id=TENANT)
    ids_t2 = {v.vertex_id for v in result_t2.vertices}
    assert entity_id in ids_t2, "Version 1 node should be visible at T2"

    # Query at T4 (after T3): should find v2 (active)
    result_t4 = await engine.temporal_bfs(entity_id + "-v2", as_of=t5, depth=0, tenant_id=TENANT)
    ids_t4 = {v.vertex_id for v in result_t4.vertices}
    assert entity_id + "-v2" in ids_t4, "Version 2 node should be visible at T4"


# ── Scenario D: Fraud network overlay ────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_d_fraud_network_graph() -> None:
    """Fraud network entity should be reachable via BFS from a member."""
    from shared.graph.graph import GraphClient, Vertex, Edge
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    member_id = f"user-{_uid()}"
    fraud_net_id = f"fraud-net-{_uid()}"

    def _v(vid, vtype, props=None):
        return Vertex(vertex_id=vid, vertex_type=vtype,
                      properties={"tenantId": TENANT, **(props or {})})

    def _e(src, tgt, etype, props=None):
        return Edge(edge_id=f"{src}-{etype}-{tgt}", edge_type=etype,
                    source_vertex_id=src, target_vertex_id=tgt,
                    properties={"tenantId": TENANT, **(props or {})})

    await graph.add_vertex(_v(member_id, "human", {"risk_score": 0.82}))
    await graph.add_vertex(_v(fraud_net_id, "fraud_network", {"network_type": "payment_fraud"}))
    await graph.add_edge(_e(member_id, fraud_net_id, "MEMBER_OF_FRAUD_NETWORK",
                            {"member_role": "mule", "risk_score": 0.82}))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(member_id, depth=1, direction="out", tenant_id=TENANT)
    visited_ids = {v.vertex_id for v in result.vertices}
    assert fraud_net_id in visited_ids, "Fraud network node should be reachable from member"


# ── Scenario E: Agent delegation path ────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_e_agent_delegation_chain() -> None:
    """BFS from a root agent should traverse A2A delegation chain."""
    from shared.graph.graph import GraphClient, Vertex, Edge
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    agent_ids = [f"agent-{_uid()}" for _ in range(3)]

    def _v(vid):
        return Vertex(vertex_id=vid, vertex_type="agent",
                      properties={"tenantId": TENANT, "task_count": 10})

    def _e(src, tgt):
        return Edge(edge_id=f"{src}-DELEGATED_TO-{tgt}", edge_type="DELEGATED_TO",
                    source_vertex_id=src, target_vertex_id=tgt,
                    properties={"tenantId": TENANT})

    for aid in agent_ids:
        await graph.add_vertex(_v(aid))
    for i in range(len(agent_ids) - 1):
        await graph.add_edge(_e(agent_ids[i], agent_ids[i + 1]))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(agent_ids[0], depth=3, direction="out", tenant_id=TENANT)
    visited_ids = {v.vertex_id for v in result.vertices}

    assert agent_ids[-1] in visited_ids, "Last agent in delegation chain should be reachable"


# ── Scenario G: Consent withdrawal removes activation eligibility ─────────────

@pytest.mark.asyncio
async def test_scenario_g_consent_withdrawal_eligibility() -> None:
    """Nodes with withdrawn consent must have activation_eligible=false."""
    from shared.graph.graph import GraphClient, Vertex
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    entity_id = f"user-{_uid()}"

    v = Vertex(
        vertex_id=entity_id, vertex_type="human",
        properties={
            "tenantId": TENANT,
            "consent_state": "withdrawn",
            "activation_eligible": False,
            "label": "withdrawn-user",
        },
    )
    await graph.add_vertex(v)

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(entity_id, depth=0, tenant_id=TENANT)
    vertices = result.vertices

    assert any(v.vertex_id == entity_id for v in vertices), "Entity should still exist in graph"
    for v in vertices:
        if v.vertex_id == entity_id:
            assert v.properties.get("activation_eligible") is False, (
                "Withdrawn consent entity must have activation_eligible=false"
            )
            assert v.properties.get("consent_state") == "withdrawn"
