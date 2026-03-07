"""
Aether Service — Commerce Business Logic
Records payments, creates graph edges, computes fee elimination.
"""

from __future__ import annotations

import uuid
from typing import Optional

from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics

from .models import AgentHireRecord, FeeEliminationReport, PaymentRecord

logger = get_logger("aether.service.commerce")

# Card processing fee rate (used for fee elimination calculation)
CARD_FEE_RATE = 0.029  # 2.9% typical card processing fee


class CommerceService:
    """Handles payment recording, agent hiring, and fee elimination tracking."""

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        event_producer: Optional[EventProducer] = None,
    ):
        self._graph = graph_client or GraphClient()
        self._producer = event_producer or EventProducer()
        self._payments: list[PaymentRecord] = []
        self._hires: list[AgentHireRecord] = []

    async def record_payment(self, payment: PaymentRecord, tenant_id: str = "") -> PaymentRecord:
        """Record a payment and create a PAYS edge in the graph."""
        if not payment.payment_id:
            payment.payment_id = str(uuid.uuid4())

        # Calculate fee elimination if using crypto/x402 instead of card
        if payment.method in ("x402", "usdc", "eth", "sol", "sponge"):
            payment.fee_eliminated_usd = round(payment.amount * CARD_FEE_RATE, 4)

        # Create Payment vertex
        vertex = Vertex(
            vertex_type=VertexType.PAYMENT,
            vertex_id=payment.payment_id,
            properties={
                "amount": str(payment.amount),
                "currency": payment.currency,
                "method": payment.method,
                "chain_id": payment.chain_id or "",
                "tx_hash": payment.tx_hash or "",
                "fee_eliminated_usd": str(payment.fee_eliminated_usd),
                "tenant_id": tenant_id,
            },
        )
        await self._graph.add_vertex(vertex)

        # Create PAYS edge: payer -> payee
        edge = Edge(
            edge_type=EdgeType.PAYS,
            from_vertex_id=payment.payer_id,
            to_vertex_id=payment.payee_id,
            properties={
                "payment_id": payment.payment_id,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "method": payment.method,
            },
        )
        await self._graph.add_edge(edge)

        # Publish event
        await self._producer.publish(Event(
            topic=Topic.PAYMENT_SENT,
            payload=payment.model_dump(),
            source_service="commerce",
        ))

        self._payments.append(payment)
        metrics.increment("commerce_payments_recorded", labels={"method": payment.method})
        logger.info(f"Payment recorded: {payment.payment_id} ({payment.payer_type}->{payment.payee_type})")
        return payment

    async def record_hire(self, hire: AgentHireRecord, tenant_id: str = "") -> AgentHireRecord:
        """Record an agent hiring another agent and create a HIRED edge."""
        if not hire.hire_id:
            hire.hire_id = str(uuid.uuid4())

        # Create HIRED edge: hiring_agent -> hired_agent
        edge = Edge(
            edge_type=EdgeType.HIRED,
            from_vertex_id=hire.hiring_agent_id,
            to_vertex_id=hire.hired_agent_id,
            properties={
                "hire_id": hire.hire_id,
                "task_type": hire.task_type,
                "agreed_amount": str(hire.agreed_amount),
                "status": hire.status,
                "tenant_id": tenant_id,
            },
        )
        await self._graph.add_edge(edge)

        # Publish event
        await self._producer.publish(Event(
            topic=Topic.AGENT_HIRED,
            payload=hire.model_dump(),
            source_service="commerce",
        ))

        self._hires.append(hire)
        metrics.increment("commerce_hires_recorded")
        logger.info(f"Agent hire recorded: {hire.hiring_agent_id} hired {hire.hired_agent_id}")
        return hire

    async def get_fee_elimination_report(self, period: str = "all", tenant_id: str = "") -> FeeEliminationReport:
        """Generate fee elimination report for a period."""
        payments = self._payments
        if tenant_id:
            payments = [p for p in payments if getattr(p, 'tenant_id', '') == tenant_id]

        total_volume = sum(p.amount for p in payments)
        total_eliminated = sum(p.fee_eliminated_usd for p in payments)
        card_fees_would_be = round(total_volume * CARD_FEE_RATE, 2)

        return FeeEliminationReport(
            period=period,
            total_transactions=len(payments),
            total_volume_usd=round(total_volume, 2),
            card_fees_would_be_usd=card_fees_would_be,
            actual_fees_usd=round(card_fees_would_be - total_eliminated, 2),
            eliminated_usd=round(total_eliminated, 2),
        )

    async def get_agent_spend(self, agent_id: str, tenant_id: str = "") -> dict:
        """Get spending history for an agent."""
        agent_payments = [
            p for p in self._payments
            if p.payer_id == agent_id and p.payer_type == "agent"
        ]
        if tenant_id:
            agent_payments = [p for p in agent_payments if getattr(p, 'tenant_id', '') == tenant_id]

        return {
            "agent_id": agent_id,
            "total_spent_usd": sum(p.amount for p in agent_payments),
            "total_fees_eliminated_usd": sum(p.fee_eliminated_usd for p in agent_payments),
            "transaction_count": len(agent_payments),
            "payments": [p.model_dump() for p in agent_payments],
        }
