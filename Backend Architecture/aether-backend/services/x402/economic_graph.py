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
        self._nodes: dict[str, X402Node] = {}
        self._payments: list[CapturedX402Transaction] = []
        self._snapshot_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._recent_payments: dict[str, deque] = {}

    async def add_payment(self, tx: CapturedX402Transaction, tenant_id: str = "") -> None:
        """Add a captured x402 payment to the economic graph."""
        async with self._lock:
            # Use tenant-prefixed keys for tenant isolation
            payer_key = f"{tenant_id}:{tx.payer_agent_id}" if tenant_id else tx.payer_agent_id
            payee_key = f"{tenant_id}:{tx.payee_service_id}" if tenant_id else tx.payee_service_id

            # Update payer node
            payer = self._nodes.setdefault(
                payer_key,
                X402Node(node_id=tx.payer_agent_id, node_type="agent"),
            )
            payer.total_paid_usd += tx.amount_usd
            payer.transaction_count += 1
            payer.fee_eliminated_usd += tx.fee_eliminated_usd

            # Track unique services on the node
            if not hasattr(payer, '_seen_services') or not isinstance(payer._seen_services, set):
                payer._seen_services = set()
            if tx.payee_service_id not in payer._seen_services:
                payer._seen_services.add(tx.payee_service_id)
                payer.unique_services = len(payer._seen_services)

            # Update payee node
            payee = self._nodes.setdefault(
                payee_key,
                X402Node(node_id=tx.payee_service_id, node_type="service"),
            )
            payee.total_received_usd += tx.amount_usd
            payee.transaction_count += 1

            # Append to pending-flush buffer
            self._payments.append(tx)

            # Maintain per-agent bounded deque of last 20 payments
            if payer_key not in self._recent_payments:
                self._recent_payments[payer_key] = deque(maxlen=20)
            self._recent_payments[payer_key].append(tx)

        metrics.increment("x402_graph_payments_added")

    async def snapshot_to_graph(self) -> int:
        """Flush in-memory economic graph to the persistent graph database."""
        # Copy-and-swap: take a snapshot of pending payments under the lock
        async with self._lock:
            payments_to_flush = list(self._payments)
            self._payments.clear()

        edges_created = 0
        last_processed_idx = 0

        try:
            for idx, tx in enumerate(payments_to_flush):
                try:
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
                    last_processed_idx = idx + 1
                except Exception as e:
                    logger.error(f"Graph mutation failed for payment {tx.capture_id}: {e}")
                    # Continue processing remaining payments
                    continue
        except Exception as e:
            logger.error(
                f"Snapshot batch error after {last_processed_idx} of {len(payments_to_flush)} payments: {e}"
            )
            # Re-enqueue unprocessed items
            unprocessed = payments_to_flush[last_processed_idx:]
            if unprocessed:
                async with self._lock:
                    self._payments = unprocessed + self._payments

        snapshot_count = last_processed_idx
        logger.info(f"Economic graph snapshot: {snapshot_count} payments -> {edges_created} edges")
        metrics.increment("x402_graph_snapshots", labels={"edges": str(edges_created)})
        return edges_created

    def get_spending_patterns(self, agent_id: str, tenant_id: str = "") -> SpendingSummary:
        """Get spending patterns for an agent using node-level cumulative data."""
        node_key = f"{tenant_id}:{agent_id}" if tenant_id else agent_id
        node = self._nodes.get(node_key)
        total_spent = node.total_paid_usd if node else 0.0
        total_tx = node.transaction_count if node else 0
        unique_services = node.unique_services if node else 0
        fee_eliminated = node.fee_eliminated_usd if node else 0.0

        # Get last 20 payments from bounded deque
        recent = self._recent_payments.get(node_key, deque(maxlen=20))

        return SpendingSummary(
            agent_id=agent_id,
            total_spent_usd=round(total_spent, 4),
            total_transactions=total_tx,
            unique_services=unique_services,
            avg_payment_usd=round(total_spent / total_tx, 4) if total_tx > 0 else 0.0,
            fee_eliminated_usd=round(fee_eliminated, 4),
            payments=[p.model_dump() for p in recent],
        )

    def get_graph_snapshot(self, tenant_id: str = "") -> dict:
        """Get current state of the economic graph."""
        if tenant_id:
            prefix = f"{tenant_id}:"
            filtered_nodes = {
                nid: n for nid, n in self._nodes.items() if nid.startswith(prefix)
            }
        else:
            filtered_nodes = self._nodes

        return {
            "nodes": {nid: n.model_dump() for nid, n in filtered_nodes.items()},
            "node_count": len(filtered_nodes),
            "pending_payments": len(self._payments),
            "total_volume_usd": round(
                sum(n.total_paid_usd for n in filtered_nodes.values() if n.node_type == "agent"),
                2,
            ),
        }
