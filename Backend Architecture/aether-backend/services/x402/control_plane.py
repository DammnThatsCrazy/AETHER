"""
Aether Service — x402 Commerce Control Plane
Orchestrates the full lifecycle:
  request → challenge → policy → approval → verify → settle → entitle → grant → fulfill

This is the central backend that Kyber actions and SDK calls route through.
Every lifecycle stage is persisted, emits events, and writes graph state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger, metrics

from .approvals import get_approval_service
from .commerce_models import (
    AccessGrant,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalStatus,
    EntitlementStatus,
    Fulfillment,
    LifecycleTrace,
    PaymentAuthorization,
    PaymentRequirement,
    PolicyOutcome,
    PreflightResult,
)
from .commerce_store import get_commerce_store
from .economic_mutations import EconomicGraphMutations
from .entitlements import get_entitlement_service
from .facilitators import get_facilitator_registry
from .idempotency import get_idempotency_store
from .policies import get_policy_engine
from .pricing import PricingEngine
from .resources import get_resource_registry
from .settlement import get_settlement_tracker
from .verification import get_verification_engine

logger = get_logger("aether.service.x402.control_plane")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class ControlPlaneError(Exception):
    def __init__(self, message: str, code: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class X402ControlPlane:
    """Orchestrates the full x402 v2 lifecycle."""

    def __init__(self, graph_client: Optional[GraphClient] = None, event_producer: Optional[EventProducer] = None):
        self._store = get_commerce_store()
        self._resources = get_resource_registry()
        self._facilitators = get_facilitator_registry()
        self._policy = get_policy_engine()
        self._approvals = get_approval_service()
        self._verify = get_verification_engine()
        self._settle = get_settlement_tracker()
        self._entitlements = get_entitlement_service()
        self._idempotency = get_idempotency_store()
        self._pricing = PricingEngine()
        self._mutations = EconomicGraphMutations(graph_client)
        self._producer = event_producer or EventProducer()

    # ─── Preflight ────────────────────────────────────────────────────

    async def preflight(
        self, tenant_id: str, holder_id: str, resource_id: str
    ) -> PreflightResult:
        resource = await self._resources.get(tenant_id, resource_id)
        if not resource:
            return PreflightResult(
                can_access=False,
                reason="resource_not_found",
                resource_id=resource_id,
                holder_id=holder_id,
            )
        existing = await self._entitlements.lookup(tenant_id, holder_id, resource_id)
        if existing:
            return PreflightResult(
                can_access=True,
                reason="active_entitlement",
                resource_id=resource_id,
                holder_id=holder_id,
                existing_entitlement_id=existing.entitlement_id,
                price_quote_usd=resource.price_usd,
                accepted_assets=resource.accepted_assets,
                accepted_chains=resource.accepted_chains,
                approval_required=resource.approval_required,
            )
        return PreflightResult(
            can_access=False,
            reason="payment_required",
            resource_id=resource_id,
            holder_id=holder_id,
            price_quote_usd=resource.price_usd,
            accepted_assets=resource.accepted_assets,
            accepted_chains=resource.accepted_chains,
            approval_required=resource.approval_required,
            challenge_url=f"/v1/x402/challenge?resource_id={resource_id}",
        )

    # ─── 1. Issue Challenge ───────────────────────────────────────────

    async def issue_challenge(
        self,
        tenant_id: str,
        resource_id: str,
        requester_id: str,
        requester_type: str = "agent",
        chain: str = "eip155:8453",
        asset_symbol: str = "USDC",
        recipient: Optional[str] = None,
    ) -> PaymentRequirement:
        resource = await self._resources.get(tenant_id, resource_id)
        if not resource:
            raise ControlPlaneError(
                f"Unknown resource: {resource_id}", "RESOURCE_NOT_FOUND", 404
            )
        if not resource.active:
            raise ControlPlaneError("Resource inactive", "RESOURCE_INACTIVE", 410)

        # Compatibility check upfront
        if resource.accepted_assets and asset_symbol not in resource.accepted_assets:
            raise ControlPlaneError(
                f"Asset {asset_symbol} not accepted", "UNSUPPORTED_ASSET", 400
            )
        if resource.accepted_chains and chain not in resource.accepted_chains:
            raise ControlPlaneError(
                f"Chain {chain} not accepted", "UNSUPPORTED_NETWORK", 400
            )

        price = await self._pricing.quote_for(tenant_id, resource)
        treasury = await self._store.get_treasury(tenant_id)
        treasury_recipient = (
            f"treasury:{tenant_id}"
            if treasury
            else f"aether:{tenant_id}"
        )

        requirement = PaymentRequirement(
            tenant_id=tenant_id,
            resource_id=resource_id,
            amount_usd=price,
            asset_symbol=asset_symbol,
            chain=chain,
            recipient=recipient or treasury_recipient,
            protocol_version="v2",
            expires_at=_iso(_now() + timedelta(minutes=10)),
            requester_id=requester_id,
            requester_type=requester_type,
        )
        await self._store.put_requirement(requirement)
        await self._mutations.write_resource(resource)
        await self._mutations.write_challenge(requirement, resource)

        await self._producer.publish(
            Event(
                topic=Topic.COMMERCE_CHALLENGE_ISSUED,
                payload={
                    "challenge_id": requirement.challenge_id,
                    "resource_id": resource_id,
                    "amount_usd": price,
                    "asset": asset_symbol,
                    "chain": chain,
                    "requester_id": requester_id,
                    "payment_identifier": requirement.payment_identifier,
                },
                tenant_id=tenant_id,
                source_service="x402.control_plane",
            )
        )
        metrics.increment(
            "commerce_challenges_issued",
            labels={"resource": resource_id, "asset": asset_symbol, "chain": chain},
        )
        logger.info(
            f"challenge issued: {requirement.challenge_id} resource={resource_id} "
            f"amount=${price} {asset_symbol} on {chain}"
        )
        return requirement

    # ─── 2. Request Approval ──────────────────────────────────────────

    async def request_approval(
        self,
        tenant_id: str,
        challenge_id: str,
        priority: ApprovalPriority = ApprovalPriority.NORMAL,
        reason: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[ApprovalRequest, "PolicyDecisionLike"]:
        requirement = await self._store.get_requirement(tenant_id, challenge_id)
        if not requirement:
            raise ControlPlaneError("Challenge not found", "CHALLENGE_NOT_FOUND", 404)
        resource = await self._resources.get(tenant_id, requirement.resource_id)
        if not resource:
            raise ControlPlaneError("Resource not found", "RESOURCE_NOT_FOUND", 404)

        decision = await self._policy.evaluate(
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            resource=resource,
            requester_id=requirement.requester_id,
            amount_usd=requirement.amount_usd,
            asset_symbol=requirement.asset_symbol,
            chain=requirement.chain,
        )
        await self._mutations.write_policy_decision(decision)

        if decision.outcome == PolicyOutcome.DENY:
            await self._producer.publish(
                Event(
                    topic=Topic.COMMERCE_POLICY_DENIED,
                    payload={
                        "challenge_id": challenge_id,
                        "decision_id": decision.decision_id,
                        "reason": decision.denial_reason,
                    },
                    tenant_id=tenant_id,
                    source_service="x402.control_plane",
                )
            )
            raise ControlPlaneError(
                decision.denial_reason or "policy denied", "POLICY_DENIED", 403
            )

        approval = await self._approvals.request(
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            resource_id=requirement.resource_id,
            requester_id=requirement.requester_id,
            requester_type=requirement.requester_type,
            amount_usd=requirement.amount_usd,
            asset_symbol=requirement.asset_symbol,
            chain=requirement.chain,
            policy_decision=decision,
            priority=priority,
            reason=reason,
            context=context or {},
        )
        await self._mutations.write_approval_request(approval)
        return approval, decision

    # ─── 3. Apply Decision + Authorize Payment ────────────────────────

    async def apply_decision(
        self,
        tenant_id: str,
        approval_id: str,
        action: str,
        decided_by: str,
        reason: str,
        is_override: bool = False,
    ) -> ApprovalRequest:
        """Apply an approval decision. On approve, create PaymentAuthorization."""
        from .commerce_models import ApprovalDecision

        approval = await self._approvals.decide(
            tenant_id=tenant_id,
            approval_id=approval_id,
            action=action,
            decided_by=decided_by,
            reason=reason,
            is_override=is_override,
        )
        decision_obj = ApprovalDecision(
            approval_id=approval_id,
            tenant_id=tenant_id,
            action=action,
            decided_by=decided_by,
            reason=reason,
            is_override=is_override,
        )
        await self._mutations.write_approval_decision(approval, decision_obj)
        return approval

    async def authorize_payment(
        self,
        tenant_id: str,
        approval_id: str,
        payer: str,
    ) -> PaymentAuthorization:
        """Create a PaymentAuthorization for an approved request."""
        approval = await self._approvals.get(tenant_id, approval_id)
        if not approval:
            raise ControlPlaneError("Approval not found", "APPROVAL_NOT_FOUND", 404)
        if approval.status != ApprovalStatus.APPROVED:
            raise ControlPlaneError(
                f"Cannot authorize: approval status is {approval.status}",
                "APPROVAL_NOT_APPROVED",
                403,
            )
        requirement = await self._store.get_requirement(tenant_id, approval.challenge_id)
        if not requirement:
            raise ControlPlaneError("Challenge not found", "CHALLENGE_NOT_FOUND", 404)

        facilitator = await self._facilitators.select_for(
            tenant_id, requirement.asset_symbol, requirement.chain
        )
        if not facilitator:
            raise ControlPlaneError(
                "No facilitator for asset/chain", "FACILITATOR_UNAVAILABLE", 503
            )

        auth = PaymentAuthorization(
            tenant_id=tenant_id,
            challenge_id=approval.challenge_id,
            approval_id=approval_id,
            payment_identifier=requirement.payment_identifier,
            amount_usd=requirement.amount_usd,
            asset_symbol=requirement.asset_symbol,
            chain=requirement.chain,
            recipient=requirement.recipient,
            payer=payer,
            facilitator_id=facilitator.facilitator_id,
        )
        await self._store.put_authorization(auth)
        await self._mutations.write_authorization(auth)

        await self._producer.publish(
            Event(
                topic=Topic.COMMERCE_FACILITATOR_ROUTE_SELECTED,
                payload={
                    "authorization_id": auth.authorization_id,
                    "facilitator_id": facilitator.facilitator_id,
                },
                tenant_id=tenant_id,
                source_service="x402.control_plane",
            )
        )
        return auth

    # ─── 4. Verify + Settle + Mint Entitlement + Grant Access ─────────

    async def verify_and_settle(
        self, tenant_id: str, authorization_id: str, tx_hash: str
    ) -> dict[str, Any]:
        auth = await self._store.get_authorization(tenant_id, authorization_id)
        if not auth:
            raise ControlPlaneError("Authorization not found", "AUTH_NOT_FOUND", 404)

        # Idempotency check by payment_identifier
        existing = self._idempotency.lookup(tenant_id, auth.payment_identifier)
        if existing:
            logger.info(f"idempotent replay: {auth.payment_identifier}")
            return existing

        await self._producer.publish(
            Event(
                topic=Topic.COMMERCE_PAYMENT_SUBMITTED,
                payload={
                    "authorization_id": authorization_id,
                    "tx_hash": tx_hash,
                    "payment_identifier": auth.payment_identifier,
                },
                tenant_id=tenant_id,
                source_service="x402.control_plane",
            )
        )

        receipt = await self._verify.verify(tenant_id, auth, tx_hash)
        if not receipt.verified:
            result = {
                "verified": False,
                "receipt_id": receipt.receipt_id,
                "error": receipt.verification_error,
            }
            self._idempotency.record(tenant_id, auth.payment_identifier, result)
            return result

        settlement = await self._settle.start(tenant_id, receipt, auth.facilitator_id)
        await self._mutations.write_receipt_and_settlement(receipt, settlement)

        # Mint entitlement
        approval = await self._approvals.get(tenant_id, auth.approval_id)
        requirement = await self._store.get_requirement(tenant_id, auth.challenge_id)
        entitlement = await self._entitlements.mint(
            tenant_id=tenant_id,
            holder_id=approval.requester_id if approval else auth.payer,
            holder_type=requirement.requester_type if requirement else "agent",
            resource_id=requirement.resource_id if requirement else "",
            settlement=settlement,
        )
        await self._mutations.write_entitlement(entitlement)

        result = {
            "verified": True,
            "receipt_id": receipt.receipt_id,
            "settlement_id": settlement.settlement_id,
            "settlement_state": settlement.state.value,
            "entitlement_id": entitlement.entitlement_id,
            "expires_at": entitlement.expires_at,
        }
        self._idempotency.record(tenant_id, auth.payment_identifier, result)
        return result

    async def grant_access(
        self,
        tenant_id: str,
        entitlement_id: str,
        request_url: str = "",
        request_method: str = "GET",
    ) -> dict[str, Any]:
        entitlement = await self._store.get_entitlement(tenant_id, entitlement_id)
        if not entitlement or entitlement.status != EntitlementStatus.ACTIVE:
            await self._producer.publish(
                Event(
                    topic=Topic.COMMERCE_ACCESS_DENIED,
                    payload={"entitlement_id": entitlement_id, "reason": "inactive"},
                    tenant_id=tenant_id,
                    source_service="x402.control_plane",
                )
            )
            raise ControlPlaneError(
                "Entitlement not active", "ENTITLEMENT_INACTIVE", 401
            )

        grant = AccessGrant(
            tenant_id=tenant_id,
            entitlement_id=entitlement_id,
            resource_id=entitlement.resource_id,
            holder_id=entitlement.holder_id,
            request_url=request_url,
            request_method=request_method,
        )
        await self._store.put_grant(grant)

        fulfillment = Fulfillment(
            tenant_id=tenant_id,
            grant_id=grant.grant_id,
            resource_id=entitlement.resource_id,
            status="completed",
            latency_ms=1,
            status_code=200,
        )
        await self._store.put_fulfillment(fulfillment)
        await self._mutations.write_grant_and_fulfillment(grant, fulfillment)

        await self._producer.publish(
            Event(
                topic=Topic.COMMERCE_ACCESS_GRANTED,
                payload={
                    "grant_id": grant.grant_id,
                    "entitlement_id": entitlement_id,
                    "resource_id": entitlement.resource_id,
                },
                tenant_id=tenant_id,
                source_service="x402.control_plane",
            )
        )
        metrics.increment("commerce_access_granted")
        return {
            "grant_id": grant.grant_id,
            "fulfillment_id": fulfillment.fulfillment_id,
            "resource_id": entitlement.resource_id,
            "status": "granted",
        }

    # ─── Explainability ───────────────────────────────────────────────

    async def explain(self, tenant_id: str, challenge_id: str) -> LifecycleTrace:
        """Full lifecycle trace for explainability / support / audit."""
        req = await self._store.get_requirement(tenant_id, challenge_id)
        trace = LifecycleTrace(
            challenge_id=challenge_id,
            tenant_id=tenant_id,
            requirement=req,
            graph_writes=self._mutations.get_trace(),
        )
        if not req:
            return trace

        # find policy decision for this challenge
        for d in list(self._store.policy_decisions._data.get(tenant_id, {}).values()):
            if d.challenge_id == challenge_id:
                trace.policy_decision = d
                break

        # find approval for this challenge
        for a in list(self._store.approvals._data.get(tenant_id, {}).values()):
            if a.challenge_id == challenge_id:
                trace.approval = a
                break

        # find authorization for this challenge
        for a in list(self._store.authorizations._data.get(tenant_id, {}).values()):
            if a.challenge_id == challenge_id:
                trace.authorization = a
                break

        # find receipt for this challenge
        for r in list(self._store.receipts._data.get(tenant_id, {}).values()):
            if r.challenge_id == challenge_id:
                trace.receipt = r
                break

        # find settlement
        for s in list(self._store.settlements._data.get(tenant_id, {}).values()):
            if s.challenge_id == challenge_id:
                trace.settlement = s
                break

        # find entitlement (by settlement_id)
        if trace.settlement:
            for e in list(self._store.entitlements._data.get(tenant_id, {}).values()):
                if e.settlement_id == trace.settlement.settlement_id:
                    trace.entitlement = e
                    break

        # find grant + fulfillment
        if trace.entitlement:
            for g in list(self._store.grants._data.get(tenant_id, {}).values()):
                if g.entitlement_id == trace.entitlement.entitlement_id:
                    trace.grant = g
                    break
        if trace.grant:
            for f in list(self._store.fulfillments._data.get(tenant_id, {}).values()):
                if f.grant_id == trace.grant.grant_id:
                    trace.fulfillment = f
                    break

        return trace


# Module-level singleton
_plane: Optional[X402ControlPlane] = None


def get_control_plane() -> X402ControlPlane:
    global _plane
    if _plane is None:
        _plane = X402ControlPlane()
    return _plane


def reset_control_plane() -> None:
    global _plane
    _plane = None


# For type hints above
class PolicyDecisionLike:  # noqa
    pass
