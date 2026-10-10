"""
Aether Service — Approval Workflow
Mandatory approval workflow for every spend class at Day-1 GA.

States: pending → assigned → (approved | rejected | escalated | expired | revoked)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import (
    ApprovalDecision,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalStatus,
    PolicyDecision,
)
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.approvals")


# Day-1 SLA defaults (seconds)
SLA_SECONDS: dict[ApprovalPriority, int] = {
    ApprovalPriority.CRITICAL: 5 * 60,
    ApprovalPriority.HIGH: 15 * 60,
    ApprovalPriority.NORMAL: 60 * 60,
    ApprovalPriority.LOW: 4 * 60 * 60,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class ApprovalService:
    """Manages the approval workflow. Mandatory for all spend classes at GA."""

    def __init__(self, event_producer: Optional[EventProducer] = None):
        self._store = get_commerce_store()
        self._producer = event_producer or EventProducer()

    async def request(
        self,
        tenant_id: str,
        challenge_id: str,
        resource_id: str,
        requester_id: str,
        requester_type: str,
        amount_usd: float,
        asset_symbol: str,
        chain: str,
        policy_decision: Optional[PolicyDecision] = None,
        priority: ApprovalPriority = ApprovalPriority.NORMAL,
        reason: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """Create an approval request. Required for every spend class at GA."""
        expires = _now() + timedelta(seconds=SLA_SECONDS[priority])
        approval = ApprovalRequest(
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            resource_id=resource_id,
            requester_id=requester_id,
            requester_type=requester_type,
            amount_usd=amount_usd,
            asset_symbol=asset_symbol,
            chain=chain,
            priority=priority,
            reason=reason or "Mandatory approval (Day-1 GA: all spend classes)",
            context=context or {},
            policy_decision_id=policy_decision.decision_id if policy_decision else None,
            status=ApprovalStatus.PENDING,
            expires_at=_iso(expires),
        )
        await self._store.put_approval(approval)
        await self._emit(
            Topic.COMMERCE_APPROVAL_REQUESTED,
            tenant_id,
            {
                "approval_id": approval.approval_id,
                "challenge_id": challenge_id,
                "resource_id": resource_id,
                "requester_id": requester_id,
                "amount_usd": amount_usd,
                "priority": priority.value,
                "expires_at": approval.expires_at,
            },
        )
        metrics.increment("commerce_approvals_requested", labels={"priority": priority.value})
        logger.info(
            f"approval requested: {approval.approval_id} challenge={challenge_id} "
            f"amount=${amount_usd} priority={priority.value} expires={approval.expires_at}"
        )
        return approval

    async def assign(
        self, tenant_id: str, approval_id: str, assignee_id: str, assigned_by: str
    ) -> ApprovalRequest:
        approval = await self._require(tenant_id, approval_id)
        if approval.status not in (ApprovalStatus.PENDING, ApprovalStatus.ESCALATED):
            raise ValueError(f"Cannot assign approval in status {approval.status}")
        approval.assigned_to = assignee_id
        approval.status = ApprovalStatus.ASSIGNED
        await self._store.put_approval(approval)
        await self._emit(
            Topic.COMMERCE_APPROVAL_ASSIGNED,
            tenant_id,
            {"approval_id": approval_id, "assignee_id": assignee_id, "assigned_by": assigned_by},
        )
        return approval

    async def decide(
        self,
        tenant_id: str,
        approval_id: str,
        action: str,
        decided_by: str,
        reason: str,
        is_override: bool = False,
    ) -> ApprovalRequest:
        """action: approve|reject|escalate"""
        approval = await self._require(tenant_id, approval_id)
        if approval.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.REVOKED,
        ):
            raise ValueError(f"Approval already finalized: {approval.status}")

        if self._is_expired(approval):
            approval.status = ApprovalStatus.EXPIRED
            await self._store.put_approval(approval)
            await self._emit(
                Topic.COMMERCE_APPROVAL_EXPIRED,
                tenant_id,
                {"approval_id": approval_id},
            )
            raise ValueError("Approval has expired")

        if action == "approve":
            approval.status = ApprovalStatus.APPROVED
            topic = Topic.COMMERCE_APPROVAL_APPROVED
        elif action == "reject":
            approval.status = ApprovalStatus.REJECTED
            topic = Topic.COMMERCE_APPROVAL_REJECTED
        elif action == "escalate":
            approval.status = ApprovalStatus.ESCALATED
            approval.escalation_chain.append(decided_by)
            topic = Topic.COMMERCE_APPROVAL_ESCALATED
        else:
            raise ValueError(f"Unknown action: {action}")

        approval.decided_at = _iso(_now())
        approval.decided_by = decided_by
        approval.decision_reason = reason
        approval.is_override = is_override
        await self._store.put_approval(approval)

        decision = ApprovalDecision(
            approval_id=approval_id,
            tenant_id=tenant_id,
            action=action,
            decided_by=decided_by,
            reason=reason,
            is_override=is_override,
        )

        await self._emit(
            topic,
            tenant_id,
            {
                "approval_id": approval_id,
                "challenge_id": approval.challenge_id,
                "action": action,
                "decided_by": decided_by,
                "reason": reason,
                "is_override": is_override,
            },
        )
        metrics.increment(
            "commerce_approvals_decided", labels={"decision": action, "override": str(is_override)}
        )
        logger.info(
            f"approval {action}: {approval_id} by={decided_by} override={is_override} reason={reason}"
        )
        return approval

    async def revoke(
        self, tenant_id: str, approval_id: str, revoked_by: str, reason: str
    ) -> ApprovalRequest:
        approval = await self._require(tenant_id, approval_id)
        if approval.status == ApprovalStatus.REVOKED:
            return approval
        approval.status = ApprovalStatus.REVOKED
        approval.decided_at = _iso(_now())
        approval.decided_by = revoked_by
        approval.decision_reason = reason
        await self._store.put_approval(approval)
        await self._emit(
            Topic.COMMERCE_APPROVAL_REVOKED,
            tenant_id,
            {"approval_id": approval_id, "revoked_by": revoked_by, "reason": reason},
        )
        return approval

    async def list_queue(
        self,
        tenant_id: str,
        status: Optional[ApprovalStatus] = None,
        assigned_to: Optional[str] = None,
    ) -> list[ApprovalRequest]:
        items = await self._store.list_approvals(tenant_id, status=status, assigned_to=assigned_to)
        # Sort: critical first, then oldest first
        priority_order = {
            ApprovalPriority.CRITICAL: 0,
            ApprovalPriority.HIGH: 1,
            ApprovalPriority.NORMAL: 2,
            ApprovalPriority.LOW: 3,
        }
        items.sort(key=lambda a: (priority_order[a.priority], a.created_at))
        return items

    async def get(self, tenant_id: str, approval_id: str) -> Optional[ApprovalRequest]:
        return await self._store.get_approval(tenant_id, approval_id)

    async def evidence_bundle(self, tenant_id: str, approval_id: str) -> dict[str, Any]:
        approval = await self._require(tenant_id, approval_id)
        policy = None
        if approval.policy_decision_id:
            policy = await self._store.get_policy_decision(tenant_id, approval.policy_decision_id)
        requirement = await self._store.get_requirement(tenant_id, approval.challenge_id)
        return {
            "approval": approval.model_dump(),
            "policy_decision": policy.model_dump() if policy else None,
            "requirement": requirement.model_dump() if requirement else None,
        }

    async def sweep_expired(self, tenant_id: str) -> int:
        """Mark past-SLA approvals as expired. Called by diagnostic sweeper."""
        count = 0
        for a in await self._store.list_approvals(tenant_id):
            if a.status in (ApprovalStatus.PENDING, ApprovalStatus.ASSIGNED, ApprovalStatus.ESCALATED):
                if self._is_expired(a):
                    a.status = ApprovalStatus.EXPIRED
                    await self._store.put_approval(a)
                    await self._emit(
                        Topic.COMMERCE_APPROVAL_EXPIRED,
                        tenant_id,
                        {"approval_id": a.approval_id},
                    )
                    count += 1
        return count

    def _is_expired(self, a: ApprovalRequest) -> bool:
        if not a.expires_at:
            return False
        try:
            return _now() > datetime.fromisoformat(a.expires_at)
        except Exception:
            return False

    async def _require(self, tenant_id: str, approval_id: str) -> ApprovalRequest:
        approval = await self._store.get_approval(tenant_id, approval_id)
        if not approval:
            raise ValueError(f"Approval not found: {approval_id}")
        return approval

    async def _emit(self, topic: Topic, tenant_id: str, payload: dict[str, Any]) -> None:
        try:
            await self._producer.publish(
                Event(
                    topic=topic,
                    payload=payload,
                    tenant_id=tenant_id,
                    source_service="x402.approvals",
                )
            )
        except Exception as e:
            logger.error(f"failed to emit {topic}: {e}")


_service: Optional[ApprovalService] = None


def get_approval_service() -> ApprovalService:
    global _service
    if _service is None:
        _service = ApprovalService()
    return _service
