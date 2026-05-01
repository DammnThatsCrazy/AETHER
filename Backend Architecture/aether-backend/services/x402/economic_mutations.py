"""
Aether Service — Economic Graph Mutations
Deterministic graph builders that persist commerce lifecycle objects into
the Intelligence Graph. Each mutation is idempotent and tenant-isolated.

Downstream: these writes are consumed by Noesis (graph UI), Entities (economic
profile), Review (evidence panel), and the explainability endpoint.
"""

from __future__ import annotations

from typing import Optional

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger

from .commerce_models import (
    AccessGrant,
    ApprovalDecision,
    ApprovalRequest,
    Entitlement,
    Fulfillment,
    PaymentAuthorization,
    PaymentReceipt,
    PaymentRequirement,
    PolicyDecision,
    ProtectedResource,
    Settlement,
)

logger = get_logger("aether.service.x402.economic_mutations")


def _tkey(tenant_id: str, vid: str) -> str:
    return f"{tenant_id}:{vid}"


class EconomicGraphMutations:
    """All commerce graph writes. Each method is idempotent."""

    def __init__(self, graph_client: Optional[GraphClient] = None):
        self._graph = graph_client or GraphClient()
        self._writes: list[dict] = []  # trace log for explainability

    def _trace(self, kind: str, label: str, props: dict) -> None:
        self._writes.append({"kind": kind, "label": label, "properties": props})

    def get_trace(self) -> list[dict]:
        return list(self._writes)

    async def write_resource(self, resource: ProtectedResource) -> None:
        v = Vertex(
            vertex_type=VertexType.PROTECTED_RESOURCE,
            vertex_id=_tkey(resource.tenant_id, resource.resource_id),
            properties={
                "resource_id": resource.resource_id,
                "name": resource.name,
                "resource_class": resource.resource_class.value,
                "price_usd": str(resource.price_usd),
                "owner_service": resource.owner_service,
                "tenant_id": resource.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.PROTECTED_RESOURCE, v.properties)

    async def write_challenge(self, req: PaymentRequirement, resource: ProtectedResource) -> None:
        v = Vertex(
            vertex_type=VertexType.PAYMENT_REQUIREMENT,
            vertex_id=_tkey(req.tenant_id, req.challenge_id),
            properties={
                "challenge_id": req.challenge_id,
                "amount_usd": str(req.amount_usd),
                "asset": req.asset_symbol,
                "chain": req.chain,
                "protocol_version": req.protocol_version,
                "requester_id": req.requester_id,
                "tenant_id": req.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.PAYMENT_REQUIREMENT, v.properties)

        edge = Edge(
            edge_type=EdgeType.REQUIRES_PAYMENT,
            from_vertex_id=_tkey(req.tenant_id, resource.resource_id),
            to_vertex_id=_tkey(req.tenant_id, req.challenge_id),
            properties={"amount_usd": str(req.amount_usd)},
        )
        await self._graph.add_edge(edge)
        self._trace("edge", EdgeType.REQUIRES_PAYMENT, edge.properties)

    async def write_policy_decision(self, decision: PolicyDecision) -> None:
        v = Vertex(
            vertex_type=VertexType.POLICY_DECISION,
            vertex_id=_tkey(decision.tenant_id, decision.decision_id),
            properties={
                "decision_id": decision.decision_id,
                "outcome": decision.outcome.value,
                "requires_approval": str(decision.requires_approval),
                "tenant_id": decision.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.POLICY_DECISION, v.properties)

        e = Edge(
            edge_type=EdgeType.GOVERNED_BY_POLICY,
            from_vertex_id=_tkey(decision.tenant_id, decision.challenge_id),
            to_vertex_id=_tkey(decision.tenant_id, decision.decision_id),
            properties={"outcome": decision.outcome.value},
        )
        await self._graph.add_edge(e)
        self._trace("edge", EdgeType.GOVERNED_BY_POLICY, e.properties)

    async def write_approval_request(self, approval: ApprovalRequest) -> None:
        v = Vertex(
            vertex_type=VertexType.APPROVAL_REQUEST,
            vertex_id=_tkey(approval.tenant_id, approval.approval_id),
            properties={
                "approval_id": approval.approval_id,
                "status": approval.status.value,
                "priority": approval.priority.value,
                "amount_usd": str(approval.amount_usd),
                "requester_id": approval.requester_id,
                "tenant_id": approval.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.APPROVAL_REQUEST, v.properties)

    async def write_approval_decision(self, approval: ApprovalRequest, decision: ApprovalDecision) -> None:
        v = Vertex(
            vertex_type=VertexType.APPROVAL_DECISION,
            vertex_id=_tkey(decision.tenant_id, decision.decision_id),
            properties={
                "decision_id": decision.decision_id,
                "action": decision.action,
                "decided_by": decision.decided_by,
                "is_override": str(decision.is_override),
                "tenant_id": decision.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.APPROVAL_DECISION, v.properties)

        edge_type = EdgeType.APPROVED_BY if decision.action == "approve" else EdgeType.REJECTED_BY
        edge = Edge(
            edge_type=edge_type,
            from_vertex_id=_tkey(decision.tenant_id, decision.decision_id),
            to_vertex_id=decision.decided_by,
            properties={"reason": decision.reason},
        )
        await self._graph.add_edge(edge)
        self._trace("edge", edge_type, edge.properties)

        # Link approval -> decision via AUTHORIZED_BY
        approved_edge = Edge(
            edge_type=EdgeType.AUTHORIZED_BY,
            from_vertex_id=_tkey(approval.tenant_id, approval.challenge_id),
            to_vertex_id=_tkey(approval.tenant_id, approval.approval_id),
            properties={"status": approval.status.value},
        )
        await self._graph.add_edge(approved_edge)
        self._trace("edge", EdgeType.AUTHORIZED_BY, approved_edge.properties)

    async def write_authorization(self, auth: PaymentAuthorization) -> None:
        v = Vertex(
            vertex_type=VertexType.PAYMENT_AUTHORIZATION,
            vertex_id=_tkey(auth.tenant_id, auth.authorization_id),
            properties={
                "authorization_id": auth.authorization_id,
                "amount_usd": str(auth.amount_usd),
                "facilitator_id": auth.facilitator_id,
                "tenant_id": auth.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.PAYMENT_AUTHORIZATION, v.properties)

    async def write_receipt_and_settlement(self, receipt: PaymentReceipt, settlement: Settlement) -> None:
        rv = Vertex(
            vertex_type=VertexType.PAYMENT_RECEIPT,
            vertex_id=_tkey(receipt.tenant_id, receipt.receipt_id),
            properties={
                "receipt_id": receipt.receipt_id,
                "verified": str(receipt.verified),
                "tx_hash": receipt.tx_hash,
                "amount_usd": str(receipt.amount_usd),
                "tenant_id": receipt.tenant_id,
            },
        )
        await self._graph.upsert_vertex(rv)
        self._trace("vertex", VertexType.PAYMENT_RECEIPT, rv.properties)

        sv = Vertex(
            vertex_type=VertexType.SETTLEMENT,
            vertex_id=_tkey(settlement.tenant_id, settlement.settlement_id),
            properties={
                "settlement_id": settlement.settlement_id,
                "state": settlement.state.value,
                "chain": settlement.chain,
                "amount_usd": str(settlement.amount_usd),
                "tenant_id": settlement.tenant_id,
            },
        )
        await self._graph.upsert_vertex(sv)
        self._trace("vertex", VertexType.SETTLEMENT, sv.properties)

        e = Edge(
            edge_type=EdgeType.SETTLED_BY,
            from_vertex_id=_tkey(receipt.tenant_id, receipt.receipt_id),
            to_vertex_id=_tkey(settlement.tenant_id, settlement.settlement_id),
            properties={"state": settlement.state.value},
        )
        await self._graph.add_edge(e)
        self._trace("edge", EdgeType.SETTLED_BY, e.properties)

    async def write_entitlement(self, entitlement: Entitlement) -> None:
        v = Vertex(
            vertex_type=VertexType.ENTITLEMENT,
            vertex_id=_tkey(entitlement.tenant_id, entitlement.entitlement_id),
            properties={
                "entitlement_id": entitlement.entitlement_id,
                "status": entitlement.status.value,
                "holder_id": entitlement.holder_id,
                "resource_id": entitlement.resource_id,
                "expires_at": entitlement.expires_at,
                "tenant_id": entitlement.tenant_id,
            },
        )
        await self._graph.upsert_vertex(v)
        self._trace("vertex", VertexType.ENTITLEMENT, v.properties)

        e = Edge(
            edge_type=EdgeType.GRANTS_ACCESS_TO,
            from_vertex_id=_tkey(entitlement.tenant_id, entitlement.entitlement_id),
            to_vertex_id=_tkey(entitlement.tenant_id, entitlement.resource_id),
            properties={"scope": entitlement.scope},
        )
        await self._graph.add_edge(e)
        self._trace("edge", EdgeType.GRANTS_ACCESS_TO, e.properties)

    async def write_grant_and_fulfillment(self, grant: AccessGrant, fulfillment: Fulfillment) -> None:
        gv = Vertex(
            vertex_type=VertexType.ACCESS_GRANT,
            vertex_id=_tkey(grant.tenant_id, grant.grant_id),
            properties={
                "grant_id": grant.grant_id,
                "entitlement_id": grant.entitlement_id,
                "resource_id": grant.resource_id,
                "tenant_id": grant.tenant_id,
            },
        )
        await self._graph.upsert_vertex(gv)
        self._trace("vertex", VertexType.ACCESS_GRANT, gv.properties)

        fv = Vertex(
            vertex_type=VertexType.FULFILLMENT,
            vertex_id=_tkey(fulfillment.tenant_id, fulfillment.fulfillment_id),
            properties={
                "fulfillment_id": fulfillment.fulfillment_id,
                "status": fulfillment.status,
                "latency_ms": str(fulfillment.latency_ms),
                "tenant_id": fulfillment.tenant_id,
            },
        )
        await self._graph.upsert_vertex(fv)
        self._trace("vertex", VertexType.FULFILLMENT, fv.properties)

        e = Edge(
            edge_type=EdgeType.FULFILLED_BY,
            from_vertex_id=_tkey(grant.tenant_id, grant.grant_id),
            to_vertex_id=_tkey(fulfillment.tenant_id, fulfillment.fulfillment_id),
            properties={"status": fulfillment.status},
        )
        await self._graph.add_edge(e)
        self._trace("edge", EdgeType.FULFILLED_BY, e.properties)
