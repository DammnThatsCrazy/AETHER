"""SDK Health ↔ Suggestion adapter."""

from __future__ import annotations

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.sdk_health")


def create_suggestion_from_sdk_silence(
    sdk_id: str,
    tenant_id: str,
    hours_silent: float,
    platform: str = "unknown",
    version: str = "",
) -> SuggestionCreate:
    """Create a suggestion when an SDK has gone silent."""
    urgency = min(1.0, hours_silent / 48.0)
    confidence = 0.90 if hours_silent > 24 else 0.75

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="sdk", id=sdk_id, display_name=f"SDK {sdk_id[:16]}"),
        source=SuggestionSource.SDK_HEALTH,
        source_ref={"service": "sdk_health", "id": f"silence:{sdk_id}:{int(hours_silent)}h"},
        suggestion_class=SuggestionClass.SDK_HEALTH,
        title=f"SDK gone silent: {sdk_id[:24]}",
        summary=f"SDK {sdk_id[:24]!r} has not sent events for {hours_silent:.1f} hours.",
        what=f"SDK {sdk_id[:24]!r} ({platform}) has been silent for {hours_silent:.1f} hours.",
        why=(
            "No events received from this SDK suggest it may be offline, "
            "misconfigured, or experiencing an ingestion failure."
        ),
        impact="Missing SDK data creates blind spots in entity intelligence and event tracking.",
        recommended_action="Verify SDK deployment, check network connectivity, and review error logs.",
        confidence_score=confidence,
        urgency_score=urgency,
        risk_score=0.4,
        reversible=True,
        evidence=[
            {
                "id": f"silence:{sdk_id}",
                "type": "entity",
                "source": "sdk_health",
                "observedAt": utc_now().isoformat(),
                "confidence": confidence,
                "uri": f"sdk://{sdk_id}",
            }
        ],
        lineage_event_ids=[],
    )


def create_suggestion_from_ingestion_failure(
    sdk_id: str,
    tenant_id: str,
    error_rate: float,
    platform: str = "unknown",
    version: str = "",
) -> SuggestionCreate:
    """Create a suggestion for a high ingestion error rate."""
    confidence = min(0.95, 0.6 + error_rate * 0.35)

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="sdk", id=sdk_id, display_name=f"SDK {sdk_id[:16]}"),
        source=SuggestionSource.SDK_HEALTH,
        source_ref={"service": "sdk_health", "id": f"error:{sdk_id}:{int(error_rate * 100)}pct"},
        suggestion_class=SuggestionClass.SDK_HEALTH,
        title=f"SDK ingestion failure: {int(error_rate * 100)}% error rate",
        summary=f"SDK {sdk_id[:24]!r} has a {error_rate:.0%} ingestion error rate.",
        what=f"SDK {sdk_id[:24]!r} ({platform}{' v' + version if version else ''}) is producing {error_rate:.0%} errors.",
        why="High ingestion error rates indicate configuration issues or breaking changes.",
        impact="Dropped events cause incomplete entity profiles and missed intelligence signals.",
        recommended_action=f"Review SDK {sdk_id[:16]!r} error logs and update to a stable version.",
        confidence_score=confidence,
        urgency_score=min(1.0, error_rate * 1.2),
        risk_score=0.5,
        reversible=True,
        evidence=[
            {
                "id": f"ingestion_error:{sdk_id}",
                "type": "entity",
                "source": "sdk_health",
                "observedAt": utc_now().isoformat(),
                "confidence": confidence,
            }
        ],
        lineage_event_ids=[],
    )
