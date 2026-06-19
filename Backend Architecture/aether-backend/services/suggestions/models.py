"""Pydantic models for the OODA Suggestion Intelligence service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core enumerations
# ---------------------------------------------------------------------------

class OodaPhase(str, Enum):
    OBSERVE = "observe"
    ORIENT  = "orient"
    SUGGEST = "suggest"
    REVIEW  = "review"
    ACT     = "act"
    MEASURE = "measure"
    LEARN   = "learn"
    CLOSED  = "closed"


class SuggestionStatus(str, Enum):
    DETECTED        = "detected"
    ORIENTED        = "oriented"
    SUGGESTED       = "suggested"
    REVIEW_REQUIRED = "review_required"
    APPROVED        = "approved"
    REJECTED        = "rejected"
    SUPPRESSED      = "suppressed"
    EXECUTING       = "executing"
    EXECUTED        = "executed"
    DELIVERED       = "delivered"
    MEASURED        = "measured"
    LEARNED         = "learned"
    CLOSED          = "closed"
    EXPIRED         = "expired"
    FAILED          = "failed"


class SuggestionClass(str, Enum):
    CUSTOMER_SUCCESS    = "customer_success"
    DATA_QUALITY        = "data_quality"
    SDK_HEALTH          = "sdk_health"
    SDK_DRIFT           = "sdk_drift"
    IDENTITY            = "identity"
    GRAPH_HEALTH        = "graph_health"
    PROFILE360          = "profile360"
    CAMPAIGN            = "campaign"
    RETARGETING         = "retargeting"
    REVENUE             = "revenue"
    RELIABILITY         = "reliability"
    SECURITY            = "security"
    GOVERNANCE          = "governance"
    AGENT_OPERATIONS    = "agent_operations"
    NOTIFICATION        = "notification"
    INVESTIGATION       = "investigation"
    GENERAL_INTELLIGENCE = "general_intelligence"


class SuggestionSource(str, Enum):
    NOESIS                    = "noesis"
    MODEL                     = "model"
    RULE                      = "rule"
    AGENT                     = "agent"
    DATA_QUALITY              = "data_quality"
    SDK_HEALTH                = "sdk_health"
    SDK_DRIFT                 = "sdk_drift"
    GRAPH                     = "graph"
    PROFILE360                = "profile360"
    RECOMMENDATION_ENGINE     = "recommendation_engine"
    NOTIFICATION_INTELLIGENCE = "notification_intelligence"
    RELIABILITY               = "reliability"
    GOVERNANCE                = "governance"
    OPERATOR                  = "operator"
    SYSTEM                    = "system"


class SuggestionPriority(str, Enum):
    P0   = "P0"
    P1   = "P1"
    P2   = "P2"
    P3   = "P3"
    INFO = "info"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

SubjectKind = Literal[
    "entity", "tenant", "organization", "graph", "profile", "journey",
    "campaign", "sdk", "provider", "agent", "alert", "investigation", "system",
]


class SuggestionSubject(BaseModel):
    kind: SubjectKind
    id: str
    display_name: Optional[str] = None
    entity_ref: Optional[dict[str, Any]] = None


class SuggestionPolicyDecision(BaseModel):
    decision_id: str
    allowed: bool
    requires_approval: bool
    policies: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    explanation: Optional[str] = None
    evaluated_at: str


class SuggestionOutcome(BaseModel):
    status: Literal[
        "accepted", "rejected", "ignored", "expired",
        "executed", "failed", "helpful", "not_helpful", "unknown",
    ]
    measured_impact: Optional[dict[str, Any]] = None
    operator_notes: Optional[str] = None
    tenant_feedback: Optional[str] = None
    created_at: str
    created_by: Optional[str] = None


class SuggestionAuditEvent(BaseModel):
    id: str
    action: str
    actor_id: Optional[str] = None
    actor_kind: Literal["system", "operator", "tenant_user", "agent"]
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    timestamp: str


# ---------------------------------------------------------------------------
# Canonical Suggestion entity
# ---------------------------------------------------------------------------

class Suggestion(BaseModel):
    id: str
    tenant_id: str
    org_id: Optional[str] = None

    subject: SuggestionSubject
    source: SuggestionSource
    source_ref: Optional[dict[str, Any]] = None

    ooda_phase: OodaPhase = OodaPhase.OBSERVE
    suggestion_class: SuggestionClass
    priority: SuggestionPriority = SuggestionPriority.P3
    status: SuggestionStatus = SuggestionStatus.DETECTED

    title: str = Field(max_length=200)
    summary: str = Field(max_length=500)
    what: str = Field(max_length=2000)
    why: str = Field(max_length=2000)
    impact: str = Field(max_length=2000)
    recommended_action: Optional[str] = Field(None, max_length=2000)
    expected_outcome: Optional[str] = Field(None, max_length=2000)

    confidence_score: float = Field(ge=0.0, le=1.0)
    impact_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    urgency_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    evidence_quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    tenant_value_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    reversibility_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    priority_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    reversible: Optional[bool] = None

    requires_approval: bool = True
    execution_eligible: bool = False
    delivery_eligible: bool = True

    evidence: list[dict[str, Any]] = Field(default_factory=list)
    lineage_event_ids: list[str] = Field(default_factory=list)
    graph_refs: list[dict[str, Any]] = Field(default_factory=list)
    profile_refs: list[dict[str, Any]] = Field(default_factory=list)
    journey_refs: list[dict[str, Any]] = Field(default_factory=list)

    policy_decision: Optional[SuggestionPolicyDecision] = None
    audit_trail: list[SuggestionAuditEvent] = Field(default_factory=list)
    outcome: Optional[SuggestionOutcome] = None

    expires_at: Optional[str] = None
    created_at: str
    updated_at: str
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    closed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Request / input models
# ---------------------------------------------------------------------------

class SuggestionCreate(BaseModel):
    tenant_id: str
    org_id: Optional[str] = None
    subject: SuggestionSubject
    source: SuggestionSource
    source_ref: Optional[dict[str, Any]] = None
    suggestion_class: SuggestionClass
    title: str = Field(max_length=200)
    summary: str = Field(max_length=500)
    what: str = Field(max_length=2000)
    why: str = Field(max_length=2000)
    impact: str = Field(max_length=2000)
    recommended_action: Optional[str] = Field(None, max_length=2000)
    expected_outcome: Optional[str] = Field(None, max_length=2000)
    confidence_score: float = Field(ge=0.0, le=1.0)
    impact_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    urgency_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    reversible: Optional[bool] = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    lineage_event_ids: list[str] = Field(default_factory=list)
    expires_at: Optional[str] = None


class SuggestionQuery(BaseModel):
    tenant_id: str
    org_id: Optional[str] = None
    statuses: Optional[list[SuggestionStatus]] = None
    classes: Optional[list[SuggestionClass]] = None
    priorities: Optional[list[SuggestionPriority]] = None
    sources: Optional[list[SuggestionSource]] = None
    min_priority_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    include_closed: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SuggestionActionRequest(BaseModel):
    actor_id: Optional[str] = None
    notes: Optional[str] = None


class SuggestionRejectRequest(SuggestionActionRequest):
    reason: str


class SuggestionSuppressRequest(SuggestionActionRequest):
    reason: str
    suppress_duration_hours: Optional[int] = None


class SuggestionOutcomeRequest(BaseModel):
    status: str
    measured_impact: Optional[dict[str, Any]] = None
    operator_notes: Optional[str] = None
    tenant_feedback: Optional[str] = None
    created_by: Optional[str] = None


class SuggestionFeedbackRequest(BaseModel):
    status: Literal["helpful", "not_helpful", "ignored"]
    tenant_feedback: Optional[str] = None


# ---------------------------------------------------------------------------
# Summary / aggregate models
# ---------------------------------------------------------------------------

class SuggestionSummary(BaseModel):
    total: int
    open: int
    review_required: int
    approved: int
    executed: int
    failed: int
    closed: int
    by_class: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
