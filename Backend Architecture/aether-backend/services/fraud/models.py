"""Fraud Decision — durable, versioned, tenant-isolated decision models."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

SubjectType = Literal[
    "entity", "activity", "journey", "wallet", "agent", "cluster", "profile"
]

FraudDecisionOutcome = Literal[
    "clear", "allow", "monitor", "review", "hold", "block", "suppress", "escalate"
]

RiskTier = Literal["low", "medium", "high", "critical"]

EvaluationState = Literal[
    "not_evaluated", "pending", "evaluated", "stale", "superseded", "failed"
]

ReviewState = Literal[
    "not_required", "required", "in_review", "approved", "rejected", "suppressed"
]

DecisionStatus = Literal["active", "superseded", "expired", "voided"]


class EvidenceRef(BaseModel):
    ref_id: str = Field(default_factory=lambda: str(uuid4()))
    ref_type: str  # "session", "transfer", "wallet_link", "reward_event", "delegation", "order"
    ref_source: str  # service that produced this evidence
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudDecision(BaseModel):
    """Complete, durable fraud decision record."""

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str

    # Subject
    subject_type: SubjectType
    subject_id: str

    # Cross-rail links (all optional)
    entity_id: Optional[str] = None
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    wallet_id: Optional[str] = None
    agent_id: Optional[str] = None
    activity_id: Optional[str] = None
    journey_id: Optional[str] = None
    journey_version_id: Optional[str] = None

    # Related fraud constructs
    fraud_network_ids: list[str] = Field(default_factory=list)
    flow_trace_ids: list[str] = Field(default_factory=list)

    # Outcome
    decision: FraudDecisionOutcome
    risk_score: float = Field(ge=0.0, le=100.0)
    risk_tier: RiskTier
    signal_types: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    human_explanation: Optional[str] = None
    machine_explanation: Optional[str] = None

    # Versioning
    detector_versions: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    policy_version: str = "v1"

    # Lifecycle
    evaluation_state: EvaluationState = "evaluated"
    evaluated_at: str
    valid_from: str
    valid_until: Optional[str] = None
    status: DecisionStatus = "active"

    # Supersession chain
    supersedes_decision_id: Optional[str] = None
    superseded_by_decision_id: Optional[str] = None

    # Human review
    review_state: ReviewState = "not_required"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    suppression_reason: Optional[str] = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class FraudDecisionCreateRequest(BaseModel):
    """Input for creating a new fraud decision."""
    tenant_id: str
    subject_type: SubjectType
    subject_id: str
    entity_id: Optional[str] = None
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    wallet_id: Optional[str] = None
    agent_id: Optional[str] = None
    activity_id: Optional[str] = None
    journey_id: Optional[str] = None
    journey_version_id: Optional[str] = None
    fraud_network_ids: list[str] = Field(default_factory=list)
    flow_trace_ids: list[str] = Field(default_factory=list)
    decision: FraudDecisionOutcome
    risk_score: float = Field(ge=0.0, le=100.0)
    risk_tier: RiskTier
    signal_types: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    human_explanation: Optional[str] = None
    machine_explanation: Optional[str] = None
    detector_versions: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    policy_version: str = "v1"
    valid_until: Optional[str] = None
    supersedes_decision_id: Optional[str] = None
    review_state: ReviewState = "not_required"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FraudDecisionSupersessionRequest(BaseModel):
    tenant_id: str
    new_decision: FraudDecisionOutcome
    new_risk_score: float = Field(ge=0.0, le=100.0)
    new_risk_tier: RiskTier
    reason: str
    reviewed_by: Optional[str] = None


class FraudDecisionReviewRequest(BaseModel):
    tenant_id: str
    review_state: ReviewState
    reviewed_by: str
    suppression_reason: Optional[str] = None


class RiskAnnotation(BaseModel):
    """Risk annotation snapshot for writing back to canonical_activity or journey_steps."""
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None
    fraud_status: Optional[str] = None
    fraud_disposition: Optional[str] = None
    fraud_decision_id: Optional[str] = None
    fraud_network_ids: list[str] = Field(default_factory=list)
    fraud_signal_types: list[str] = Field(default_factory=list)
    fraud_evidence_refs: list[dict] = Field(default_factory=list)
    risk_evaluated_at: Optional[str] = None
    risk_model_version: Optional[str] = None
    risk_policy_version: Optional[str] = None
    risk_explanation: Optional[str] = None
    risk_evaluation_state: str = "not_evaluated"


def risk_tier_from_score(score: float) -> RiskTier:
    """Convert numeric risk score to tier."""
    if score >= 75:
        return "critical"
    elif score >= 50:
        return "high"
    elif score >= 25:
        return "medium"
    return "low"


def decision_from_score(score: float, *, block_threshold: float = 75.0, review_threshold: float = 50.0, monitor_threshold: float = 25.0) -> FraudDecisionOutcome:
    """Map risk score to decision outcome."""
    if score >= block_threshold:
        return "block"
    elif score >= review_threshold:
        return "review"
    elif score >= monitor_threshold:
        return "monitor"
    return "allow"
