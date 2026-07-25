"""Pydantic contracts for Data Quality, Drift Detection & Intelligence Reliability.

These mirror the shared TypeScript contracts in
``frontend/shared/src/types/data-quality.ts``. Field names are kept identical
across both layers so payloads round-trip cleanly between backend and frontend.

Scores are normalized 0..1 (1.0 = best). Drift events are graph-native signals
about degradation in the intelligence pipeline; critical ``tenant_data_contamination``
drift is escalated into the Security/Governance audit ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Enums (string literals so they serialize transparently)
# ─────────────────────────────────────────────────────────────────────────────

QualityStatus = Literal["healthy", "watch", "degraded", "critical", "unknown"]

DriftType = Literal[
    "event_volume_drift",
    "schema_drift",
    "identity_resolution_drift",
    "graph_mutation_drift",
    "profile_freshness_drift",
    "recommendation_quality_drift",
    "outcome_feedback_drift",
    "playbook_performance_drift",
    "tenant_data_contamination",
    "scoring_model_drift",
]

DriftSeverity = Literal["low", "medium", "high", "critical"]
DriftStatus = Literal["open", "acknowledged", "resolved", "expired"]

# Quality dimensions that roll up into the overall intelligence quality score.
QUALITY_DIMENSIONS: tuple[str, ...] = (
    "event_quality_score",
    "schema_stability_score",
    "identity_resolution_score",
    "graph_quality_score",
    "profile_quality_score",
    "recommendation_quality_score",
    "outcome_feedback_quality_score",
    "playbook_quality_score",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def status_for_score(score: float) -> QualityStatus:
    """Map a normalized 0..1 quality score onto a status band."""
    if score >= 0.9:
        return "healthy"
    if score >= 0.8:
        return "watch"
    if score >= 0.6:
        return "degraded"
    return "critical"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Intelligence Quality Score
# ─────────────────────────────────────────────────────────────────────────────

class IntelligenceQualityScore(BaseModel):
    tenant_id: str | None = None
    scope: str = "tenant"  # "tenant" | "platform"
    event_quality_score: float | None = None
    schema_stability_score: float | None = None
    identity_resolution_score: float | None = None
    graph_quality_score: float | None = None
    profile_quality_score: float | None = None
    recommendation_quality_score: float | None = None
    outcome_feedback_quality_score: float | None = None
    playbook_quality_score: float | None = None
    overall_intelligence_quality_score: float | None = None
    status: QualityStatus = "unknown"
    calculated_at: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Drift Event
# ─────────────────────────────────────────────────────────────────────────────

class DriftEvent(BaseModel):
    drift_event_id: str
    tenant_id: str | None = None
    drift_type: DriftType
    severity: DriftSeverity = "low"
    source: str = "data_quality_monitor"
    affected_resource_type: str | None = None
    affected_resource_id: str | None = None
    affected_recommendation_family: str | None = None
    affected_playbook_id: str | None = None
    affected_entity_count: int | None = None
    confidence_impact: float | None = None
    reason: str = ""
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str = ""
    status: DriftStatus = "open"
    detected_at: str = Field(default_factory=now_iso)
    acknowledged_at: str | None = None
    resolved_at: str | None = None
    # Internal-only audit linkage (never exposed on tenant-facing routes).
    escalated_audit_event_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
