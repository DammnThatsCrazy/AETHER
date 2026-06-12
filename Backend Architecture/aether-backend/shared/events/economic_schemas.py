"""
Aether Economic Event Schemas — Agentic Commerce Control Plane (L3b+).

Typed Pydantic payloads for all 29 commerce lifecycle event topics.
Every schema carries: tenant_id, correlation_id, actor_id, actor_type,
schema_version, and domain-specific fields.

Serialized via existing Event.serialize().
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Base ──────────────────────────────────────────────────────────────────────

class CommerceEventBase(BaseModel):
    tenant_id: str
    correlation_id: str
    actor_id: str
    actor_type: str  # "agent" | "operator" | "system" | "user"
    schema_version: str = "1.0"
    occurred_at: Optional[datetime] = None

    class Config:
        extra = "allow"


class ChallengeEventBase(CommerceEventBase):
    challenge_id: str


# ── Challenge & Requirement ───────────────────────────────────────────────────

class ChallengeIssuedPayload(CommerceEventBase):
    challenge_id: str
    resource_id: str
    resource_class: str
    amount: float
    currency: str
    payment_rail: str
    agent_id: Optional[str] = None
    policy_ids: list[str] = Field(default_factory=list)


class RequirementGeneratedPayload(ChallengeEventBase):
    requirement_id: str
    resource_id: str
    amount: float
    currency: str
    payment_rail: str
    ttl_seconds: Optional[int] = None


# ── Approval Lifecycle ────────────────────────────────────────────────────────

class ApprovalRequestedPayload(ChallengeEventBase):
    approval_request_id: str
    resource_id: str
    amount: float
    currency: str
    priority: str  # "low" | "normal" | "high" | "critical"
    reason: Optional[str] = None


class ApprovalAssignedPayload(ChallengeEventBase):
    approval_request_id: str
    assignee_id: str
    assignee_type: str  # "user" | "queue" | "agent"


class ApprovalApprovedPayload(ChallengeEventBase):
    approval_request_id: str
    decision_id: str
    override: bool = False
    notes: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)


class ApprovalRejectedPayload(ChallengeEventBase):
    approval_request_id: str
    decision_id: str
    reason: str
    override: bool = False
    notes: Optional[str] = None


class ApprovalEscalatedPayload(ChallengeEventBase):
    approval_request_id: str
    escalation_level: int
    escalated_to: str
    reason: Optional[str] = None


class ApprovalExpiredPayload(ChallengeEventBase):
    approval_request_id: str
    expired_at: datetime
    last_assignee_id: Optional[str] = None


class ApprovalRevokedPayload(ChallengeEventBase):
    approval_request_id: str
    decision_id: Optional[str] = None
    revoked_by: str
    reason: str


# ── Payment & Verification ────────────────────────────────────────────────────

class PaymentSubmittedPayload(ChallengeEventBase):
    receipt_id: str
    resource_id: str
    amount: float
    currency: str
    payment_rail: str
    facilitator_id: Optional[str] = None
    transaction_hash: Optional[str] = None


class VerificationStartedPayload(ChallengeEventBase):
    receipt_id: str
    verification_id: str
    payment_rail: str
    facilitator_id: Optional[str] = None


class VerificationSucceededPayload(ChallengeEventBase):
    receipt_id: str
    verification_id: str
    amount_verified: float
    currency: str
    confirmed_at: Optional[datetime] = None


class VerificationFailedPayload(ChallengeEventBase):
    receipt_id: str
    verification_id: str
    error_code: str
    error_message: Optional[str] = None
    retryable: bool = False


# ── Settlement ────────────────────────────────────────────────────────────────

class SettlementStartedPayload(ChallengeEventBase):
    settlement_id: str
    receipt_id: str
    resource_id: str
    amount: float
    currency: str
    payment_rail: str


class SettlementPendingPayload(ChallengeEventBase):
    settlement_id: str
    receipt_id: str
    pending_since: datetime
    estimated_completion_at: Optional[datetime] = None


class SettlementCompletedPayload(ChallengeEventBase):
    settlement_id: str
    receipt_id: str
    resource_id: str
    amount_settled: float
    currency: str
    fee_amount: Optional[float] = None
    net_amount: Optional[float] = None
    completed_at: datetime


class SettlementFailedPayload(ChallengeEventBase):
    settlement_id: str
    receipt_id: str
    error_code: str
    error_message: Optional[str] = None
    retryable: bool = False
    failed_at: datetime


# ── Entitlement ───────────────────────────────────────────────────────────────

class EntitlementGrantedPayload(ChallengeEventBase):
    entitlement_id: str
    resource_id: str
    settlement_id: str
    granted_to: str  # agent_id or user_id
    ttl_seconds: Optional[int] = None
    max_reuse: Optional[int] = None
    expires_at: Optional[datetime] = None


class EntitlementReusedPayload(ChallengeEventBase):
    entitlement_id: str
    resource_id: str
    reuse_count: int
    reused_by: str
    reused_at: datetime


class EntitlementRevokedPayload(ChallengeEventBase):
    entitlement_id: str
    resource_id: str
    revoked_by: str
    reason: str
    revoked_at: datetime


class EntitlementExpiredPayload(ChallengeEventBase):
    entitlement_id: str
    resource_id: str
    expired_at: datetime
    reuse_count: int = 0


# ── Access ────────────────────────────────────────────────────────────────────

class AccessGrantedPayload(ChallengeEventBase):
    entitlement_id: str
    resource_id: str
    granted_to: str
    access_token: Optional[str] = None
    expires_at: Optional[datetime] = None


class AccessDeniedPayload(ChallengeEventBase):
    resource_id: str
    denied_reason: str  # "no_entitlement" | "expired" | "policy" | "quota"
    policy_ids: list[str] = Field(default_factory=list)


# ── Policy ────────────────────────────────────────────────────────────────────

class PolicyDeniedPayload(CommerceEventBase):
    challenge_id: Optional[str] = None
    resource_id: str
    policy_id: str
    rule_type: str
    conditions_failed: list[str] = Field(default_factory=list)
    agent_id: Optional[str] = None


# ── Facilitator ───────────────────────────────────────────────────────────────

class FacilitatorRouteSelectedPayload(ChallengeEventBase):
    receipt_id: str
    facilitator_id: str
    payment_rail: str
    selection_reason: Optional[str] = None
    alternative_count: int = 0
    latency_ms: Optional[int] = None


# ── Audit & Operator ──────────────────────────────────────────────────────────

class KyberActionLoggedPayload(CommerceEventBase):
    action: str
    target_type: str
    target_id: str
    page: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperatorActionLoggedPayload(CommerceEventBase):
    action: str
    target_type: str
    target_id: str
    operator_id: str
    justification: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayExecutedPayload(CommerceEventBase):
    replay_id: str
    original_event_id: str
    original_topic: str
    replay_reason: Optional[str] = None
    triggered_by: str


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationTaskCreatedPayload(CommerceEventBase):
    task_id: str
    task_type: str  # "stuck_settlement" | "missing_entitlement" | "duplicate_grant" | "drift"
    resource_id: Optional[str] = None
    settlement_id: Optional[str] = None
    challenge_id: Optional[str] = None
    severity: str = "medium"  # "low" | "medium" | "high" | "critical"
    details: dict[str, Any] = Field(default_factory=dict)


class ReconciliationTaskResolvedPayload(CommerceEventBase):
    task_id: str
    task_type: str
    resolution: str  # "auto_resolved" | "manual_resolved" | "invalidated" | "escalated"
    resolved_by: str
    duration_seconds: Optional[float] = None
    details: dict[str, Any] = Field(default_factory=dict)


# ── Topic → Schema registry ───────────────────────────────────────────────────

COMMERCE_EVENT_SCHEMAS: dict[str, type[CommerceEventBase]] = {
    "aether.commerce.challenge.issued": ChallengeIssuedPayload,
    "aether.commerce.requirement.generated": RequirementGeneratedPayload,
    "aether.commerce.approval.requested": ApprovalRequestedPayload,
    "aether.commerce.approval.assigned": ApprovalAssignedPayload,
    "aether.commerce.approval.approved": ApprovalApprovedPayload,
    "aether.commerce.approval.rejected": ApprovalRejectedPayload,
    "aether.commerce.approval.escalated": ApprovalEscalatedPayload,
    "aether.commerce.approval.expired": ApprovalExpiredPayload,
    "aether.commerce.approval.revoked": ApprovalRevokedPayload,
    "aether.commerce.payment.submitted": PaymentSubmittedPayload,
    "aether.commerce.verification.started": VerificationStartedPayload,
    "aether.commerce.verification.succeeded": VerificationSucceededPayload,
    "aether.commerce.verification.failed": VerificationFailedPayload,
    "aether.commerce.settlement.started": SettlementStartedPayload,
    "aether.commerce.settlement.pending": SettlementPendingPayload,
    "aether.commerce.settlement.completed": SettlementCompletedPayload,
    "aether.commerce.settlement.failed": SettlementFailedPayload,
    "aether.commerce.entitlement.granted": EntitlementGrantedPayload,
    "aether.commerce.entitlement.reused": EntitlementReusedPayload,
    "aether.commerce.entitlement.revoked": EntitlementRevokedPayload,
    "aether.commerce.entitlement.expired": EntitlementExpiredPayload,
    "aether.commerce.access.granted": AccessGrantedPayload,
    "aether.commerce.access.denied": AccessDeniedPayload,
    "aether.commerce.policy.denied": PolicyDeniedPayload,
    "aether.commerce.facilitator.route_selected": FacilitatorRouteSelectedPayload,
    "aether.commerce.kyber.action_logged": KyberActionLoggedPayload,
    "aether.commerce.operator.action_logged": OperatorActionLoggedPayload,
    "aether.commerce.replay.executed": ReplayExecutedPayload,
    "aether.commerce.reconciliation.task_created": ReconciliationTaskCreatedPayload,
    "aether.commerce.reconciliation.task_resolved": ReconciliationTaskResolvedPayload,
}


def get_schema(topic: str) -> type[CommerceEventBase] | None:
    """Return the Pydantic schema class for a given commerce event topic."""
    return COMMERCE_EVENT_SCHEMAS.get(topic)


def validate_payload(topic: str, data: dict[str, Any]) -> CommerceEventBase:
    """Validate and parse a raw payload dict against the topic's schema."""
    schema_cls = get_schema(topic)
    if schema_cls is None:
        raise ValueError(f"No schema registered for topic: {topic!r}")
    return schema_cls.model_validate(data)
