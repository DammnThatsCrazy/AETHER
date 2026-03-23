"""
Aether Service — x402 Economic Graph
In-memory economic subgraph built from x402 payments.
Snapshots to Neptune (GraphClient) periodically.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Optional

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics
from repositories.repos import BaseRepository

from .models import CapturedX402Transaction, SpendingSummary, X402Node

logger = get_logger("aether.service.x402.economic_graph")

SNAPSHOT_INTERVAL_S = 30


class X402EconomicGraph:
    """
    Builds an in-memory economic subgraph from x402 payments.
    Snapshots to Neptune via GraphClient every 30 seconds.
    """

    def __init__(self, graph_client: Optional[GraphClient] = None):
        self._graph = graph_client or GraphClient()
        self._payments = BaseRepository("x402_payments")
        self._snapshot_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def add_payment(self, tx: CapturedX402Transaction, tenant_id: str = "") -> None:
        """Add a captured x402 payment to the economic graph."""
        async with self._lock:
            await self._payments.insert(
                tx.capture_id,
                {
                    **tx.model_dump(),
                    "tenant_id": tenant_id,
                    "snapshot_status": "pending",
                },
            )

        metrics.increment("x402_graph_payments_added")

    async def snapshot_to_graph(self) -> int:
        """Flush in-memory economic graph to the persistent graph database."""
        async with self._lock:
            payments_to_flush = await self._payments.find_many(filters={"snapshot_status": "pending"}, limit=10_000, sort_by="created_at", sort_order="asc")

        edges_created = 0
        processed_ids: list[str] = []

        try:
            for raw in payments_to_flush:
                try:
                    tx = CapturedX402Transaction.model_validate(raw)
                    # Ensure payer (Agent) vertex exists
                    await self._graph.upsert_vertex(Vertex(
                        vertex_type=VertexType.AGENT,
                        vertex_id=tx.payer_agent_id,
                        properties={"node_role": "x402_payer"},
                    ))

                    # Ensure payee (Service) vertex exists
                    await self._graph.upsert_vertex(Vertex(
                        vertex_type=VertexType.SERVICE,
                        vertex_id=tx.payee_service_id,
                        properties={"node_role": "x402_payee"},
                    ))

                    # Create PAYS edge
                    await self._graph.add_edge(Edge(
                        edge_type=EdgeType.PAYS,
                        from_vertex_id=tx.payer_agent_id,
                        to_vertex_id=tx.payee_service_id,
                        properties={
                            "amount": str(tx.amount_usd),
                            "token": tx.terms.token,
                            "chain": tx.terms.chain,
                            "capture_id": tx.capture_id,
                            "method": "x402",
                        },
                    ))

                    # Create CONSUMES edge (agent -> service)
                    await self._graph.add_edge(Edge(
                        edge_type=EdgeType.CONSUMES,
                        from_vertex_id=tx.payer_agent_id,
                        to_vertex_id=tx.payee_service_id,
                        properties={
                            "api_call_url": tx.request_url,
                            "method": tx.request_method,
                        },
                    ))

                    edges_created += 2
                    processed_ids.append(tx.capture_id)
                except Exception as e:
                    logger.error(f"Graph mutation failed for payment {tx.capture_id}: {e}")
                    # Continue processing remaining payments
                    continue
        except Exception as e:
            logger.error(
                f"Snapshot batch error after {len(processed_ids)} of {len(payments_to_flush)} payments: {e}"
            )
        for capture_id in processed_ids:
            await self._payments.update(capture_id, {"snapshot_status": "snapshotted"})
        snapshot_count = len(processed_ids)
        logger.info(f"Economic graph snapshot: {snapshot_count} payments -> {edges_created} edges")
        metrics.increment("x402_graph_snapshots", labels={"edges": str(edges_created)})
        return edges_created

    async def get_spending_patterns(self, agent_id: str, tenant_id: str = "") -> SpendingSummary:
        """Get spending patterns for an agent using node-level cumulative data."""
        filters = {"payer_agent_id": agent_id}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        recent = await self._payments.find_many(filters=filters, limit=20, sort_by="created_at", sort_order="desc")
        total_spent = sum(p.get("amount_usd", 0.0) for p in recent)
        total_tx = await self._payments.count(**filters)
        unique_services = len({p.get("payee_service_id") for p in recent if p.get("payee_service_id")})
        fee_eliminated = sum(p.get("fee_eliminated_usd", 0.0) for p in recent)

        return SpendingSummary(
            agent_id=agent_id,
            total_spent_usd=round(total_spent, 4),
            total_transactions=total_tx,
            unique_services=unique_services,
            avg_payment_usd=round(total_spent / len(recent), 4) if recent else 0.0,
            fee_eliminated_usd=round(fee_eliminated, 4),
            payments=recent,
        )

    async def get_graph_snapshot(self, tenant_id: str = "") -> dict:
        """Get current state of the economic graph."""
        filters = {"tenant_id": tenant_id} if tenant_id else None
        payments = await self._payments.find_many(filters=filters, limit=100_000)
        payer_totals: dict[str, float] = {}
        service_totals: dict[str, float] = {}
        for payment in payments:
            payer_totals[payment["payer_agent_id"]] = payer_totals.get(payment["payer_agent_id"], 0.0) + payment["amount_usd"]
            service_totals[payment["payee_service_id"]] = service_totals.get(payment["payee_service_id"], 0.0) + payment["amount_usd"]
        return {
            "nodes": {
                **{f"agent:{nid}": {"node_id": nid, "node_type": "agent", "total_paid_usd": round(total, 4)} for nid, total in payer_totals.items()},
                **{f"service:{nid}": {"node_id": nid, "node_type": "service", "total_received_usd": round(total, 4)} for nid, total in service_totals.items()},
            },
            "node_count": len(payer_totals) + len(service_totals),
            "pending_payments": len([p for p in payments if p.get("snapshot_status") == "pending"]),
            "total_volume_usd": round(sum(p.get("amount_usd", 0.0) for p in payments), 2),
        }
