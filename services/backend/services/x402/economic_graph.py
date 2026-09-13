"""
Aether Service — x402 Economic Graph
In-memory economic subgraph built from x402 payments.
Snapshots to Neptune (GraphClient) periodically.
"""

from __future__ import annotations

import asyncio
from collections import deque
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.logger.logger import get_logger, metrics

from services.value.models import to_decimal, to_decimal_string

from .models import CapturedX402Transaction, SpendingSummary, X402Node

logger = get_logger("aether.service.x402.economic_graph")

SNAPSHOT_INTERVAL_S = 30


def _round_usd(value: Decimal, dp: int) -> Decimal:
    """Round a money Decimal to `dp` decimal places (half-even)."""
    quantum = Decimal(1).scaleb(-dp)
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def _money_add(current: object, increment: object) -> float:
    """Exact-Decimal running sum converted to float only at the model boundary.

    The X402Node money fields are float-typed (in-memory graph metrics), but
    summing floats directly produces binary-float artifacts (e.g. 0.10 + 0.10 +
    0.10 -> 0.30000000000000004). Each step is therefore summed in Decimal and
    only the result is converted to the float the model carries.
    """
    left = to_decimal(current)
    right = to_decimal(increment)
    if left is None or right is None:
        # Unparseable money is never coerced to 0; fall back to the raw value
        # rather than inventing a number (callers validate amounts upstream).
        return float(current) + float(increment)
    return float(left + right)


class X402EconomicGraph:
    """
    Builds an in-memory economic subgraph from x402 payments.
    Snapshots to Neptune via GraphClient every 30 seconds.
    """

    def __init__(self, graph_client: Optional[GraphClient] = None):
        self._graph = graph_client or GraphClient()
        self._nodes: dict[str, X402Node] = {}
        self._payments: list[tuple[CapturedX402Transaction, str]] = []
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
            payer.total_paid_usd = _money_add(payer.total_paid_usd, tx.amount_usd)
            payer.transaction_count += 1
            payer.fee_eliminated_usd = _money_add(
                payer.fee_eliminated_usd, tx.fee_eliminated_usd
            )

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
            payee.total_received_usd = _money_add(payee.total_received_usd, tx.amount_usd)
            payee.transaction_count += 1

            # Append to pending-flush buffer (store with tenant_id for scoped graph writes)
            self._payments.append((tx, tenant_id))

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
        gateway = GraphMutationGateway(graph_client=self._graph)

        try:
            for idx, (tx, tenant_id) in enumerate(payments_to_flush):
                try:
                    # Build tenant-scoped vertex IDs for isolation
                    payer_vid = f"{tenant_id}:{tx.payer_agent_id}" if tenant_id else tx.payer_agent_id
                    payee_vid = f"{tenant_id}:{tx.payee_service_id}" if tenant_id else tx.payee_service_id

                    # Ensure payer (Agent) vertex exists
                    await gateway.apply(vertex_intent(
                        Vertex(
                            vertex_type=VertexType.AGENT,
                            vertex_id=payer_vid,
                            properties={
                                "node_role": "x402_payer",
                                "agent_id": tx.payer_agent_id,
                                "tenant_id": tenant_id,
                            },
                        ),
                        operation="node_versioned", tenant_id=tenant_id,
                        actor_kind="agent", actor_id=tx.payer_agent_id,
                    ))

                    # Ensure payee (Service) vertex exists
                    await gateway.apply(vertex_intent(
                        Vertex(
                            vertex_type=VertexType.SERVICE,
                            vertex_id=payee_vid,
                            properties={
                                "node_role": "x402_payee",
                                "service_id": tx.payee_service_id,
                                "tenant_id": tenant_id,
                            },
                        ),
                        operation="node_versioned", tenant_id=tenant_id,
                        actor_id="x402_economic_graph",
                    ))

                    # Create PAYS edge with deterministic ID for idempotency
                    await gateway.apply(edge_intent(
                        Edge(
                            edge_type=EdgeType.PAYS,
                            from_vertex_id=payer_vid,
                            to_vertex_id=payee_vid,
                            properties={
                                "edge_id": f"{tenant_id}:{tx.capture_id}:pays",
                                # Economic-graph money is a decimal-string amount —
                                # never a JSON number that carries binary-float drift.
                                # (amount_usd is a validated float, so the
                                # decimal-string form always parses.)
                                "amount": to_decimal_string(tx.amount_usd),
                                "token": tx.terms.token,
                                "chain": tx.terms.chain,
                                "capture_id": tx.capture_id,
                                "method": "x402",
                                "tenant_id": tenant_id,
                            },
                        ),
                        operation="edge_created", tenant_id=tenant_id,
                        actor_kind="agent", actor_id=tx.payer_agent_id,
                        subject_kind="agent", subject_id=payer_vid,
                        source_event_id=tx.capture_id,
                    ))

                    # Create CONSUMES edge (agent -> service) with deterministic ID
                    await gateway.apply(edge_intent(
                        Edge(
                            edge_type=EdgeType.CONSUMES,
                            from_vertex_id=payer_vid,
                            to_vertex_id=payee_vid,
                            properties={
                                "edge_id": f"{tenant_id}:{tx.capture_id}:consumes",
                                "api_call_url": tx.request_url,
                                "method": tx.request_method,
                                "tenant_id": tenant_id,
                            },
                        ),
                        operation="edge_created", tenant_id=tenant_id,
                        actor_kind="agent", actor_id=tx.payer_agent_id,
                        subject_kind="agent", subject_id=payer_vid,
                        source_event_id=tx.capture_id,
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
        """Get spending patterns for an agent using node-level cumulative data.

        Aggregates are computed in Decimal (spending total, per-tx average,
        fee elimination) and rounded at the reporting boundary, so a series of
        fractional payments never sums to a binary-float artifact.
        """
        node_key = f"{tenant_id}:{agent_id}" if tenant_id else agent_id
        node = self._nodes.get(node_key)
        total_tx = node.transaction_count if node else 0
        if node is None:
            return SpendingSummary(
                agent_id=agent_id,
                total_spent_usd=0.0,
                total_transactions=0,
                unique_services=0,
                avg_payment_usd=0.0,
                fee_eliminated_usd=0.0,
                payments=[],
            )

        total_dec = to_decimal(node.total_paid_usd)
        fee_dec = to_decimal(node.fee_eliminated_usd)
        total_dec = Decimal(0) if total_dec is None else total_dec
        fee_dec = Decimal(0) if fee_dec is None else fee_dec
        avg_dec = (
            total_dec / Decimal(total_tx) if total_tx > 0 else Decimal(0)
        )

        # Get last 20 payments from bounded deque
        recent = self._recent_payments.get(node_key, deque(maxlen=20))

        return SpendingSummary(
            agent_id=agent_id,
            total_spent_usd=float(_round_usd(total_dec, 4)),
            total_transactions=total_tx,
            unique_services=node.unique_services,
            avg_payment_usd=float(_round_usd(avg_dec, 4)),
            fee_eliminated_usd=float(_round_usd(fee_dec, 4)),
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

        # Total volume is a money rollup — summed in Decimal (never float
        # accumulation), rounded half-even at 2 dp at the reporting boundary.
        volume_dec = Decimal(0)
        for n in filtered_nodes.values():
            if n.node_type != "agent":
                continue
            node_total = to_decimal(n.total_paid_usd)
            if node_total is not None:
                volume_dec += node_total

        return {
            "nodes": {nid: n.model_dump() for nid, n in filtered_nodes.items()},
            "node_count": len(filtered_nodes),
            "pending_payments": len(self._payments),
            "total_volume_usd": float(_round_usd(volume_dec, 2)),
        }
