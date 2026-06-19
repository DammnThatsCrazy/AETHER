"""Reliability ↔ Suggestion adapter."""

from __future__ import annotations

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.reliability")

# SLO thresholds that elevate to P0
_P0_SLO_BREACHES = frozenset({"availability", "latency_p99", "error_rate"})


def create_suggestion_from_slo_breach(
    metric: str,
    value: float,
    tenant_id: str,
    target: float = 0.0,
    service_name: str = "aether",
    breach_id: str = "",
) -> SuggestionCreate:
    """Create a reliability suggestion from an SLO breach event."""
    breach_pct = abs(value - target) / max(target, 0.001) * 100 if target else 0
    is_critical = metric in _P0_SLO_BREACHES or breach_pct > 20

    confidence = 0.95 if is_critical else 0.85
    risk = 0.85 if is_critical else 0.60
    urgency = 0.95 if is_critical else 0.75

    effective_id = breach_id or f"slo:{metric}:{int(value * 1000)}"

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="system",
            id=service_name,
            display_name=f"Service: {service_name}",
        ),
        source=SuggestionSource.RELIABILITY,
        source_ref={"service": "reliability", "id": effective_id},
        suggestion_class=SuggestionClass.RELIABILITY,
        title=f"SLO breach: {metric} ({value:.2f} vs target {target:.2f})",
        summary=f"Service {service_name!r} breached SLO for {metric}: {value:.4f} (target {target:.4f}).",
        what=f"Metric '{metric}' is at {value:.4f}, violating the SLO target of {target:.4f}.",
        why=(
            f"SLO breach detected. {'Critical' if is_critical else 'High'} severity: "
            f"breach of {breach_pct:.1f}% from target."
        ),
        impact="SLO breaches directly affect service reliability, tenant trust, and contractual obligations.",
        recommended_action=f"Investigate {service_name!r} for the root cause of the {metric} SLO breach.",
        confidence_score=confidence,
        urgency_score=urgency,
        risk_score=risk,
        reversible=False,
        evidence=[
            {
                "id": effective_id,
                "type": "event",
                "source": "reliability",
                "observedAt": utc_now().isoformat(),
                "confidence": confidence,
            }
        ],
        lineage_event_ids=[effective_id],
    )
