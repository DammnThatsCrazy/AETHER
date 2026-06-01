"""Decision and outcome intelligence schemas for graph-native OODA loops."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ApprovalLevel = Literal["none", "standard", "elevated", "critical"]
DecisionStatus = Literal["approved", "rejected", "deferred", "escalated"]
OutcomeLabel = Literal["success", "failure", "neutral"]


class RecommendationEvidence(BaseModel):
    evidence_id: str
    source_type: Literal[
        "event", "entity", "edge", "profile_signal", "ml_prediction",
        "attribution_path", "economic_state", "policy",
    ]
    source_id: str
    summary: str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: str | None = None
    tenant_id: str | None = None


class RecommendationConfidence(BaseModel):
    overall: float = Field(ge=0.0, le=1.0)
    deterministic_rule_score: float = Field(default=0.0, ge=0.0, le=1.0)
    ml_probability_score: float | None = Field(default=None, ge=0.0, le=1.0)
    graph_relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    attribution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    economic_expected_value: float | None = None
    risk_penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    governance_policy_penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    model_version: str | None = None


class CandidateAction(BaseModel):
    action_key: str
    action_type: str
    label: str
    description: str | None = None
    system: str | None = None
    integration: str | None = None
    expected_outcome: str | None = None
    expected_value: float | None = None
    currency: str | None = None
    downside_risk: str | None = None
    confidence: RecommendationConfidence | None = None
    requires_approval_level: ApprovalLevel = "standard"
    policy_flags: list[str] = Field(default_factory=list)


class DataFreshness(BaseModel):
    status: Literal["fresh", "stale", "unknown"] = "unknown"
    max_age_seconds: int | None = None
    oldest_evidence_at: str | None = None


class Recommendation(BaseModel):
    recommendation_id: str
    tenant_id: str
    entity_id: str | None = None
    population_id: str | None = None
    recommendation_type: str
    recommended_action: CandidateAction
    candidate_actions: list[CandidateAction]
    confidence: RecommendationConfidence
    expected_outcome: str
    expected_value: float | None = None
    downside_risk: str | None = None
    evidence: list[RecommendationEvidence]
    graph_snapshot_id: str | None = None
    computed_at: str
    required_approval_level: ApprovalLevel
    policy_governance_flags: list[str] = Field(default_factory=list)
    data_freshness: DataFreshness = Field(default_factory=DataFreshness)
    status: Literal["generated", "viewed", "decided", "expired", "suppressed"] = "generated"

    @model_validator(mode="after")
    def require_entity_or_population(self) -> "Recommendation":
        if not self.entity_id and not self.population_id:
            raise ValueError("Recommendation requires entity_id or population_id")
        return self


class DecisionRecord(BaseModel):
    decision_id: str
    recommendation_id: str
    actor_id: str
    selected_action: CandidateAction | None = None
    rejected_actions: list[CandidateAction] = Field(default_factory=list)
    decision_status: DecisionStatus
    reason: str | None = None
    comment: str | None = None
    created_at: str
    tenant_id: str


class ActionFeedback(BaseModel):
    action_id: str
    decision_id: str
    action_type: str
    system: str | None = None
    integration: str | None = None
    status: Literal["planned", "queued", "executed", "failed", "cancelled"] = "planned"
    actor_type: Literal["human", "system", "agent"] = "human"
    economic_payload: dict[str, Any] | None = None
    authorization_metadata: dict[str, Any] | None = None
    created_at: str
    tenant_id: str


class ObservedWindow(BaseModel):
    start: str
    end: str


class OutcomeObservation(BaseModel):
    outcome_id: str
    action_id: str
    recommendation_id: str
    entity_id: str | None = None
    population_id: str | None = None
    outcome_type: str
    value: float | None = None
    currency: str | None = None
    label: OutcomeLabel
    observed_window: ObservedWindow
    computed_at: str
    confidence_delta: float = Field(ge=-1.0, le=1.0)
    tenant_id: str


class PlaybookDefinition(BaseModel):
    playbook_id: str
    tenant_id: str
    name: str
    description: str | None = None
    trigger: str
    recommendation_types: list[str] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    approval_level: ApprovalLevel = "standard"
    enabled: bool = True
    created_at: str
    updated_at: str | None = None


class PlaybookRun(BaseModel):
    run_id: str
    playbook_id: str
    tenant_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    recommendation_ids: list[str] = Field(default_factory=list)
    started_at: str
    completed_at: str | None = None
    summary: dict[str, Any] | None = None
