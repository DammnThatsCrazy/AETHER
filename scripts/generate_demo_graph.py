"""Generate synthetic demo graph data for local development and demos.

Creates realistic (but clearly synthetic) data in the in-memory graph:
  - 1 synthetic tenant
  - 50 human entities across various lifecycle states
  - 10 clusters (identity, fraud-network, behavioral, economic)
  - 3 campaigns with attribution chains
  - 2 fraud networks with member roles and risk scores
  - 5 AI agent entities with delegation chains
  - 30 days of temporal events with valid_from/valid_to timestamps

Usage:
    AETHER_ENV=local python scripts/generate_demo_graph.py

All generated data is tagged synthetic=true and should NEVER be used in
production environments. It is cleared when the in-memory graph is reset.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Backend Architecture", "aether-backend"))

os.environ.setdefault("AETHER_ENV", "local")

from shared.graph.graph import GraphClient, VertexType, EdgeType, Vertex, Edge  # noqa: E402

TENANT_ID = "demo-tenant-001"
NOW = datetime.now(timezone.utc)


def _ts(offset_days: float = 0) -> str:
    return (NOW + timedelta(days=offset_days)).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _human(
    i: int,
    lifecycle: str = "active",
    risk: float = 0.1,
    trust: float = 0.8,
    campaign_id: str | None = None,
) -> Vertex:
    vt = VertexType.HUMAN if hasattr(VertexType, "HUMAN") else "human"
    props: dict = {
        "tenantId": TENANT_ID,
        "label": f"User-{i:04d}",
        "lifecycle_state": lifecycle,
        "risk_score": round(risk, 3),
        "trust_score": round(trust, 3),
        "first_seen": _ts(-random.uniform(10, 90)),
        "last_seen": _ts(-random.uniform(0, 5)),
        "valid_from": _ts(-30),
        "recorded_at": _ts(-30),
        "observation_class": "observed",
        "synthetic": True,
    }
    if campaign_id:
        props["acquisition_campaign_id"] = campaign_id
    return Vertex(vertex_id=f"user-{i:04d}", vertex_type=vt, properties=props)


def _agent(i: int, spawn_depth: int = 0) -> Vertex:
    vt = VertexType.AGENT if hasattr(VertexType, "AGENT") else "agent"
    return Vertex(
        vertex_id=f"agent-{i:04d}",
        vertex_type=vt,
        properties={
            "tenantId": TENANT_ID,
            "label": f"Agent-{i:04d}",
            "lifecycle_state": "active",
            "spawn_depth": spawn_depth,
            "task_count": random.randint(10, 500),
            "total_spend_usd": round(random.uniform(0.5, 50.0), 4),
            "total_revenue_produced_usd": round(random.uniform(5.0, 200.0), 2),
            "observation_class": "observed",
            "synthetic": True,
            "valid_from": _ts(-14),
            "recorded_at": _ts(-14),
        },
    )


def _cluster(i: int, cluster_type: str, member_ids: list[str], risk: float = 0.2) -> Vertex:
    vt = VertexType.CLUSTER if hasattr(VertexType, "CLUSTER") else "cluster"
    return Vertex(
        vertex_id=f"cluster-{i:04d}",
        vertex_type=vt,
        properties={
            "tenantId": TENANT_ID,
            "label": f"{cluster_type.title()} Cluster {i}",
            "cluster_type": cluster_type,
            "member_count": len(member_ids),
            "risk_score": round(risk, 3),
            "lifecycle_state": "active" if risk < 0.5 else "growing",
            "observation_class": "derived",
            "synthetic": True,
            "valid_from": _ts(-20),
            "recorded_at": _ts(-20),
        },
    )


def _fraud_network(i: int, network_type: str, member_ids: list[str]) -> Vertex:
    vt = VertexType.FRAUD_NETWORK if hasattr(VertexType, "FRAUD_NETWORK") else "fraud_network"
    return Vertex(
        vertex_id=f"fraud-net-{i:04d}",
        vertex_type=vt,
        properties={
            "tenantId": TENANT_ID,
            "label": f"Fraud Network {i} ({network_type})",
            "network_type": network_type,
            "member_count": len(member_ids),
            "risk_score": round(random.uniform(0.65, 0.95), 3),
            "alert_state": "open",
            "observation_class": "probabilistic",
            "synthetic": True,
            "valid_from": _ts(-15),
            "recorded_at": _ts(-15),
        },
    )


def _campaign(i: int, channel: str) -> Vertex:
    vt = VertexType.CAMPAIGN if hasattr(VertexType, "CAMPAIGN") else "campaign"
    return Vertex(
        vertex_id=f"campaign-{i:04d}",
        vertex_type=vt,
        properties={
            "tenantId": TENANT_ID,
            "label": f"Campaign-{i:04d} ({channel})",
            "channel": channel,
            "budget_usd": round(random.uniform(1000, 50000), 2),
            "attributed_revenue_usd": round(random.uniform(2000, 120000), 2),
            "conversion_count": random.randint(10, 500),
            "observation_class": "observed",
            "synthetic": True,
            "valid_from": _ts(-25),
            "recorded_at": _ts(-25),
        },
    )


def _edge(
    source: str,
    target: str,
    edge_type: str,
    props: dict | None = None,
) -> Edge:
    return Edge(
        edge_id=f"{source}-{edge_type}-{target}",
        edge_type=edge_type,
        source_vertex_id=source,
        target_vertex_id=target,
        properties={
            "tenantId": TENANT_ID,
            "valid_from": _ts(-30),
            "recorded_at": _ts(-30),
            "synthetic": True,
            **(props or {}),
        },
    )


async def generate(graph: GraphClient) -> None:
    print(f"[demo] Generating synthetic graph data for tenant {TENANT_ID}...")

    # ── Campaigns ─────────────────────────────────────────────────────────────
    campaigns = [
        _campaign(1, "social"),
        _campaign(2, "search"),
        _campaign(3, "email"),
    ]
    for c in campaigns:
        await graph.add_vertex(c)

    # ── Human entities ────────────────────────────────────────────────────────
    users: list[Vertex] = []
    for i in range(1, 51):
        campaign_id = campaigns[i % 3].vertex_id if i % 5 != 0 else None
        risk = round(random.uniform(0.0, 0.3), 3) if i % 7 != 0 else round(random.uniform(0.65, 0.95), 3)
        trust = round(1.0 - risk * 0.6, 3)
        lifecycle = random.choice(["active", "active", "active", "dormant", "reactivated"])
        u = _human(i, lifecycle=lifecycle, risk=risk, trust=trust, campaign_id=campaign_id)
        await graph.add_vertex(u)
        users.append(u)

    # ── AI agents ─────────────────────────────────────────────────────────────
    agents: list[Vertex] = []
    for i in range(1, 6):
        a = _agent(i, spawn_depth=i - 1)
        await graph.add_vertex(a)
        agents.append(a)

    # ── Identity clusters ─────────────────────────────────────────────────────
    clusters: list[Vertex] = []
    for ci in range(1, 8):
        group = users[(ci - 1) * 6 : ci * 6]
        c = _cluster(ci, "identity", [u.vertex_id for u in group], risk=round(random.uniform(0.05, 0.25), 3))
        await graph.add_vertex(c)
        clusters.append(c)
        for u in group:
            await graph.add_edge(_edge(u.vertex_id, c.vertex_id, "MEMBER_OF_CLUSTER", {"confidence": 0.9}))

    # ── Fraud networks ────────────────────────────────────────────────────────
    fraud_targets = users[40:46]
    fn1 = _fraud_network(1, "payment_fraud", [u.vertex_id for u in fraud_targets[:3]])
    fn2 = _fraud_network(2, "account_takeover", [u.vertex_id for u in fraud_targets[3:]])
    for fn in [fn1, fn2]:
        await graph.add_vertex(fn)
    for role, u in zip(["organizer", "mule", "beneficiary"], fraud_targets[:3]):
        await graph.add_edge(_edge(u.vertex_id, fn1.vertex_id, "MEMBER_OF_FRAUD_NETWORK", {"member_role": role, "risk_score": 0.82}))
    for role, u in zip(["organizer", "mule", "beneficiary"], fraud_targets[3:]):
        await graph.add_edge(_edge(u.vertex_id, fn2.vertex_id, "MEMBER_OF_FRAUD_NETWORK", {"member_role": role, "risk_score": 0.71}))

    # ── Economic clusters ─────────────────────────────────────────────────────
    econ_group = users[20:25]
    ec = _cluster(8, "economic", [u.vertex_id for u in econ_group], risk=0.12)
    await graph.add_vertex(ec)
    clusters.append(ec)
    for u in econ_group:
        await graph.add_edge(_edge(u.vertex_id, ec.vertex_id, "MEMBER_OF_CLUSTER", {"confidence": 0.85}))

    # ── Behavioral clusters ───────────────────────────────────────────────────
    behav_group = users[10:15]
    bc = _cluster(9, "behavioral", [u.vertex_id for u in behav_group], risk=0.18)
    await graph.add_vertex(bc)
    clusters.append(bc)
    for u in behav_group:
        await graph.add_edge(_edge(u.vertex_id, bc.vertex_id, "MEMBER_OF_CLUSTER", {"confidence": 0.78}))

    # ── Fraud network cluster ─────────────────────────────────────────────────
    fnc = _cluster(10, "fraud_network", [u.vertex_id for u in fraud_targets], risk=0.85)
    await graph.add_vertex(fnc)
    clusters.append(fnc)
    for u in fraud_targets:
        await graph.add_edge(_edge(u.vertex_id, fnc.vertex_id, "MEMBER_OF_CLUSTER", {"confidence": 0.91}))

    # ── Campaign attribution edges ─────────────────────────────────────────────
    for u in users[:15]:
        c = campaigns[0]
        await graph.add_edge(_edge(u.vertex_id, c.vertex_id, "ACQUIRED_VIA", {"attribution_share": round(random.uniform(0.3, 1.0), 2)}))
    for u in users[15:30]:
        c = campaigns[1]
        await graph.add_edge(_edge(u.vertex_id, c.vertex_id, "ACQUIRED_VIA", {"attribution_share": round(random.uniform(0.3, 1.0), 2)}))
    for u in users[30:40]:
        c = campaigns[2]
        await graph.add_edge(_edge(u.vertex_id, c.vertex_id, "ACQUIRED_VIA", {"attribution_share": round(random.uniform(0.3, 1.0), 2)}))

    # ── H2H relationship edges ─────────────────────────────────────────────────
    for i in range(20):
        src = users[i]
        tgt = users[(i + 3) % 50]
        await graph.add_edge(_edge(src.vertex_id, tgt.vertex_id, "REFERRED", {"weight": round(random.uniform(0.5, 1.0), 2)}))

    # ── Agent delegation chain (A2A) ──────────────────────────────────────────
    for i in range(len(agents) - 1):
        await graph.add_edge(_edge(agents[i].vertex_id, agents[i + 1].vertex_id, "DELEGATED_TO", {"task_type": "data_enrichment"}))

    # ── H2A edges (users who hired agents) ───────────────────────────────────
    for i, u in enumerate(users[:5]):
        await graph.add_edge(_edge(u.vertex_id, agents[i].vertex_id, "HIRED", {"contract_type": "task_based"}))

    # ── Economic flow edges ───────────────────────────────────────────────────
    for i in range(5):
        src = users[i]
        tgt = users[(i + 10) % 50]
        await graph.add_edge(_edge(src.vertex_id, tgt.vertex_id, "PAYS_FOR", {
            "amount": round(random.uniform(10, 500), 2),
            "currency": "USD",
            "rail": "card",
        }))

    print(f"[demo] Done. Generated:")
    print(f"  - {len(users)} human entities")
    print(f"  - {len(agents)} AI agents")
    print(f"  - {len(campaigns)} campaigns")
    print(f"  - {len(clusters)} clusters")
    print(f"  - 2 fraud networks")
    print(f"  - Multiple H2H, H2A, A2A, and economic edges")
    print(f"  Tenant: {TENANT_ID}")
    print(f"  All data tagged synthetic=true")


async def main() -> None:
    graph = GraphClient()
    await generate(graph)


if __name__ == "__main__":
    asyncio.run(main())
