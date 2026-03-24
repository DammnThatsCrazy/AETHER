"""
Aether — Lake-to-Graph Mutation Jobs

Reads from Silver/Gold lake tiers and creates graph edges for:
- Wallet ↔ Protocol interactions
- Wallet ↔ Wallet transfers
- Wallet ↔ Social identity links
- Entity ↔ Risk labels
- Entity ↔ Governance activity

All mutations are deterministic and replayable from lake state.
"""

from __future__ import annotations

from typing import Optional

from shared.graph.graph import GraphClient, Vertex, Edge, VertexType, EdgeType
from shared.logger.logger import get_logger, metrics
from shared.common.common import utc_now
from repositories.lake import (
    silver_onchain, silver_social, silver_identity, silver_governance,
    gold_identity,
)

logger = get_logger("aether.lake.graph_mutations")


async def build_wallet_protocol_edges(
    graph: GraphClient,
    wallet_address: str,
) -> int:
    """Create INTERACTS_WITH edges from wallet to protocols based on Silver on-chain data."""
    records = await silver_onchain.get_entity(wallet_address, "wallet")
    count = 0
    for rec in records:
        protocol = rec.get("protocol")
        if not protocol:
            continue

        # Ensure vertices exist
        await graph.upsert_vertex(Vertex(
            vertex_type=VertexType.WALLET,
            vertex_id=wallet_address,
            properties={"entity_type": "wallet"},
        ))
        await graph.upsert_vertex(Vertex(
            vertex_type=VertexType.PROTOCOL,
            vertex_id=protocol,
            properties={"entity_type": "protocol"},
        ))

        # Create edge
        await graph.add_edge(Edge(
            edge_type=EdgeType.INTERACTS_WITH,
            from_vertex_id=wallet_address,
            to_vertex_id=protocol,
            properties={
                "source": rec.get("source", "onchain"),
                "last_interaction": rec.get("updated_at", ""),
            },
        ))
        count += 1

    if count:
        metrics.increment("graph_edges_created", labels={"type": "wallet_protocol"})
        logger.info(f"Created {count} wallet→protocol edges for {wallet_address}")
    return count


async def build_wallet_social_edges(
    graph: GraphClient,
    wallet_address: str,
) -> int:
    """Create identity edges from wallet to social profiles based on Silver identity data."""
    records = await silver_identity.get_entity(wallet_address, "wallet")
    count = 0
    for rec in records:
        social_id = rec.get("social_id") or rec.get("entity_id")
        if not social_id or social_id == wallet_address:
            continue

        await graph.upsert_vertex(Vertex(
            vertex_type=VertexType.WALLET,
            vertex_id=wallet_address,
            properties={"entity_type": "wallet"},
        ))
        await graph.upsert_vertex(Vertex(
            vertex_type=VertexType.USER,
            vertex_id=social_id,
            properties={"entity_type": "social", "source": rec.get("source", "")},
        ))
        await graph.add_edge(Edge(
            edge_type=EdgeType.RESOLVED_AS,
            from_vertex_id=wallet_address,
            to_vertex_id=social_id,
            properties={"source": rec.get("source", "identity"), "confidence": str(rec.get("confidence", 0.5))},
        ))
        count += 1

    if count:
        metrics.increment("graph_edges_created", labels={"type": "wallet_social"})
    return count


async def build_governance_edges(
    graph: GraphClient,
    entity_id: str,
) -> int:
    """Create governance participation edges from Silver governance data."""
    records = await silver_governance.get_entity(entity_id, "voter")
    count = 0
    for rec in records:
        proposal_id = rec.get("proposal_id")
        if not proposal_id:
            continue

        await graph.upsert_vertex(Vertex(
            vertex_type=VertexType.USER,
            vertex_id=entity_id,
            properties={"entity_type": "voter"},
        ))
        await graph.add_edge(Edge(
            edge_type=EdgeType.INTERACTS_WITH,
            from_vertex_id=entity_id,
            to_vertex_id=proposal_id,
            properties={"type": "governance_vote", "source": rec.get("source", "snapshot")},
        ))
        count += 1

    if count:
        metrics.increment("graph_edges_created", labels={"type": "governance"})
    return count


async def run_full_graph_build(graph: GraphClient, wallet_address: str) -> dict:
    """Run all edge builders for a wallet. Returns counts per type."""
    results = {
        "wallet_protocol": await build_wallet_protocol_edges(graph, wallet_address),
        "wallet_social": await build_wallet_social_edges(graph, wallet_address),
        "governance": await build_governance_edges(graph, wallet_address),
    }
    logger.info(f"Full graph build for {wallet_address}: {results}")
    return results
