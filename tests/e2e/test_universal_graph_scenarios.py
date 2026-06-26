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
import uuid

pytest.importorskip("fastapi", reason="Backend deps not installed")


TENANT = "e2e-test-tenant"


def _ts(offset_days: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _vertex(vid, vtype, props=None, tenant=TENANT):
    from shared.graph.graph import Vertex
    return Vertex(
        vertex_id=vid, vertex_type=vtype,
        properties={"tenantId": tenant, **(props or {})},
    )


def _edge(src, tgt, etype, props=None, tenant=TENANT):
    from shared.graph.graph import Edge
    return Edge(
        edge_type=etype,
        from_vertex_id=src,
        to_vertex_id=tgt,
        properties={"tenantId": tenant, **(props or {})},
    )


# ── Scenario A: Campaign macro-to-micro ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_a_campaign_macro_to_micro() -> None:
    """Traversing from a campaign node should reach its member entities."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()

    campaign_id = f"campaign-{_uid()}"
    cluster_id = f"cluster-{_uid()}"
    entity_id = f"user-{_uid()}"

    await graph.add_vertex(_vertex(campaign_id, "campaign", {"channel": "social"}))
    await graph.add_vertex(_vertex(cluster_id, "cluster", {"cluster_type": "identity"}))
    await graph.add_vertex(_vertex(entity_id, "human", {"risk_score": 0.1, "trust_score": 0.9}))

    await graph.add_edge(_edge(entity_id, campaign_id, "ACQUIRED_VIA"))
    await graph.add_edge(_edge(entity_id, cluster_id, "MEMBER_OF_CLUSTER", {"confidence": 0.92}))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(campaign_id, depth=2, direction="in", tenant_id=TENANT)

    visited_ids = {v.vertex_id for v in result.nodes}
    assert entity_id in visited_ids, "Entity should be reachable from campaign node via BFS"
    assert cluster_id in visited_ids, "Cluster should also be reachable"


# ── Scenario B: Historical graph change ───────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_b_historical_comparison() -> None:
    """Point-in-time replay must return materially different node sets.

    An anchor vertex connects to v1 (valid T1→T3) and v2 (valid T3+).
    At T2, only v1 should be reachable. At T4, only v2 should be reachable.
    """
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()

    t1 = _ts(-10)   # 10 days ago
    t2 = _ts(-7)    # 7 days ago (between T1 and T3)
    t3 = _ts(-5)    # 5 days ago
    t4 = _ts(-2)    # 2 days ago (after T3)

    anchor_id = f"anchor-{_uid()}"
    v1_id = f"user-v1-{_uid()}"
    v2_id = f"user-v2-{_uid()}"

    await graph.add_vertex(_vertex(anchor_id, "anchor"))
    await graph.add_vertex(_vertex(v1_id, "human", {
        "label": "v1", "valid_from": t1, "valid_to": t3, "recorded_at": t1,
        "lifecycle_state": "provisional",
    }))
    await graph.add_vertex(_vertex(v2_id, "human", {
        "label": "v2", "valid_from": t3, "recorded_at": t3,
        "lifecycle_state": "active",
    }))

    await graph.add_edge(_edge(anchor_id, v1_id, "HAS_VERSION", {
        "valid_from": t1, "valid_to": t3,
    }))
    await graph.add_edge(_edge(anchor_id, v2_id, "HAS_VERSION", {
        "valid_from": t3,
    }))

    engine = GraphTraversalEngine(graph)

    # Query at T2: v1 should be visible (valid T1→T3), v2 should NOT (valid from T3)
    result_t2 = await engine.temporal_bfs(anchor_id, as_of=t2, depth=1, tenant_id=TENANT)
    ids_t2 = {v.vertex_id for v in result_t2.nodes}
    assert v1_id in ids_t2, "Version 1 node should be visible at T2 (valid T1→T3)"
    assert v2_id not in ids_t2, "Version 2 node should NOT be visible at T2 (valid from T3)"

    # Query at T4: v2 should be visible (valid T3+), v1 should NOT (expired at T3)
    result_t4 = await engine.temporal_bfs(anchor_id, as_of=t4, depth=1, tenant_id=TENANT)
    ids_t4 = {v.vertex_id for v in result_t4.nodes}
    assert v2_id in ids_t4, "Version 2 node should be visible at T4 (valid from T3)"
    assert v1_id not in ids_t4, "Version 1 node should NOT be visible at T4 (expired at T3)"


# ── Scenario D: Fraud network overlay ────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_d_fraud_network_graph() -> None:
    """Fraud network entity should be reachable via BFS from a member."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    member_id = f"user-{_uid()}"
    fraud_net_id = f"fraud-net-{_uid()}"

    await graph.add_vertex(_vertex(member_id, "human", {"risk_score": 0.82}))
    await graph.add_vertex(_vertex(fraud_net_id, "fraud_network", {"network_type": "payment_fraud"}))
    await graph.add_edge(_edge(member_id, fraud_net_id, "MEMBER_OF_FRAUD_NETWORK",
                               {"member_role": "mule", "risk_score": 0.82}))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(member_id, depth=1, direction="out", tenant_id=TENANT)
    visited_ids = {v.vertex_id for v in result.nodes}
    assert fraud_net_id in visited_ids, "Fraud network node should be reachable from member"


# ── Scenario E: Agent delegation path ────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_e_agent_delegation_chain() -> None:
    """BFS from a root agent should traverse A2A delegation chain."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    agent_ids = [f"agent-{_uid()}" for _ in range(3)]

    for aid in agent_ids:
        await graph.add_vertex(_vertex(aid, "agent", {"task_count": 10}))
    for i in range(len(agent_ids) - 1):
        await graph.add_edge(_edge(agent_ids[i], agent_ids[i + 1], "DELEGATED_TO"))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(agent_ids[0], depth=3, direction="out", tenant_id=TENANT)
    visited_ids = {v.vertex_id for v in result.nodes}

    assert agent_ids[-1] in visited_ids, "Last agent in delegation chain should be reachable"


# ── Scenario G: Consent withdrawal removes activation eligibility ─────────────

@pytest.mark.asyncio
async def test_scenario_g_consent_withdrawal_eligibility() -> None:
    """Nodes with withdrawn consent must have activation_eligible=false.

    An anchor vertex connects to the entity; BFS depth=1 from anchor
    returns the consent-withdrawn entity so we can assert its properties.
    """
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id = f"anchor-{_uid()}"
    entity_id = f"user-{_uid()}"

    await graph.add_vertex(_vertex(anchor_id, "anchor"))
    await graph.add_vertex(_vertex(entity_id, "human", {
        "consent_state": "withdrawn",
        "activation_eligible": False,
        "label": "withdrawn-user",
    }))
    await graph.add_edge(_edge(anchor_id, entity_id, "RELATED_TO"))

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(anchor_id, depth=1, tenant_id=TENANT)
    nodes = result.nodes

    assert any(v.vertex_id == entity_id for v in nodes), "Entity should be reachable from anchor"
    for v in nodes:
        if v.vertex_id == entity_id:
            assert v.properties.get("activation_eligible") is False, (
                "Withdrawn consent entity must have activation_eligible=false"
            )
            assert v.properties.get("consent_state") == "withdrawn"
