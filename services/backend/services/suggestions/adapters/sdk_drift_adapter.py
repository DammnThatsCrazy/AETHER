"""SDK Drift ↔ Suggestion adapter."""

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

logger = get_logger("aether.suggestions.adapters.sdk_drift")

# Drift incident type → (confidence, risk, urgency)
_DRIFT_TYPE_PARAMS: dict[str, tuple[float, float, float]] = {
    "REPLAY_STORM":  (0.90, 0.70, 0.85),
    "SCHEMA_DRIFT":  (0.80, 0.50, 0.65),
    "STALENESS":     (0.70, 0.30, 0.45),
}


def create_suggestion_from_drift_incident(
    incident: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map a SDK drift incident dict to a SuggestionCreate."""
    incident_type = (incident.get("incident_type") or incident.get("drift_type", "STALENESS")).upper()
    sdk_id = incident.get("sdk_id") or incident.get("source_id", "unknown")
    incident_id = incident.get("id") or incident.get("incident_id", "")

    confidence, risk, urgency = _DRIFT_TYPE_PARAMS.get(
        incident_type, (0.65, 0.35, 0.50)
    )

    title_map = {
        "REPLAY_STORM": "Replay storm detected",
        "SCHEMA_DRIFT": "Schema drift detected",
        "STALENESS": "SDK data staleness detected",
    }

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="sdk", id=sdk_id, display_name=f"SDK {sdk_id[:16]}"),
        source=SuggestionSource.SDK_DRIFT,
        source_ref={"service": "sdk_drift", "id": incident_id},
        suggestion_class=SuggestionClass.SDK_DRIFT,
        title=f"{title_map.get(incident_type, 'SDK drift detected')}: {sdk_id[:16]}",
        summary=incident.get("summary") or f"{incident_type} detected for SDK {sdk_id[:16]!r}.",
        what=incident.get("description") or f"SDK {sdk_id[:16]!r} is exhibiting {incident_type.lower()}.",
        why=incident.get("root_cause") or "Drift patterns suggest configuration or deployment issues.",
        impact="SDK drift may corrupt entity timelines and degrade intelligence accuracy.",
        recommended_action=incident.get("recommended_action") or "Investigate SDK deployment and resolve the drift.",
        confidence_score=confidence,
        urgency_score=urgency,
        risk_score=risk,
        reversible=True,
        evidence=[
            {
                "id": incident_id,
                "type": "event",
                "source": "sdk_drift",
                "observedAt": incident.get("detected_at") or utc_now().isoformat(),
                "confidence": confidence,
            }
        ],
        lineage_event_ids=[incident_id] if incident_id else [],
    )
