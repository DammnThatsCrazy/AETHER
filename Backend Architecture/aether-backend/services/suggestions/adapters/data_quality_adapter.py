"""Data Quality ↔ Suggestion adapter."""

from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.data_quality")

_SEVERITY_TO_CONFIDENCE = {
    "critical": 0.95,
    "high":     0.85,
    "medium":   0.70,
    "low":      0.55,
}

_SEVERITY_TO_RISK = {
    "critical": 0.8,
    "high":     0.6,
    "medium":   0.4,
    "low":      0.2,
}


def create_suggestion_from_drift_event(
    drift: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map a data quality drift event to a SuggestionCreate.

    Returns None if the drift event is below the suggestion threshold.
    Idempotency key: f"dq:{drift['drift_event_id']}"
    """
    event_id = drift.get("drift_event_id") or drift.get("id", "")
    severity = drift.get("severity", "low").lower()
    dimension = drift.get("dimension") or drift.get("field") or "unknown"
    entity_id = drift.get("entity_id") or drift.get("dataset_id") or "unknown"
    drift_score = float(drift.get("drift_score", 0.0))

    if drift_score < 0.1 and severity == "low":
        return None

    confidence = _SEVERITY_TO_CONFIDENCE.get(severity, 0.6)
    risk = _SEVERITY_TO_RISK.get(severity, 0.3)

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="entity",
            id=entity_id,
            display_name=drift.get("entity_display_name"),
        ),
        source=SuggestionSource.DATA_QUALITY,
        source_ref={"service": "data_quality", "id": event_id},
        suggestion_class=SuggestionClass.DATA_QUALITY,
        title=f"Data quality drift detected: {dimension}",
        summary=f"{severity.capitalize()} drift detected on {dimension} (score {drift_score:.2f})",
        what=f"Data quality degraded on dimension '{dimension}' with drift score {drift_score:.2f}.",
        why=(
            f"A {severity} severity drift event was detected. "
            f"This may indicate schema changes, missing values, or upstream data issues."
        ),
        impact="Degraded data quality may affect downstream intelligence, scores, and decisions.",
        recommended_action="Investigate the upstream data source and resolve the drift.",
        confidence_score=confidence,
        risk_score=risk,
        reversible=True,
        evidence=[
            {
                "id": event_id,
                "type": "event",
                "source": "data_quality",
                "observedAt": drift.get("detected_at") or utc_now().isoformat(),
                "confidence": confidence,
            }
        ],
        lineage_event_ids=[event_id] if event_id else [],
    )
