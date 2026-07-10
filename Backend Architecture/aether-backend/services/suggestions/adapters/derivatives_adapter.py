"""Derivatives Intelligence ↔ Suggestion adapter.

Maps reconciliation variances and unrecovered stream gaps to OODA
suggestions. Suggestions only — Aether never places, modifies, or cancels
orders. Gated by settings.suggestions.derivatives_adapter_enabled.
"""

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

logger = get_logger("aether.suggestions.adapters.derivatives")

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


def create_suggestion_from_reconciliation_variance(
    variance: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map a derivatives reconciliation variance to a SuggestionCreate.

    Returns None for variances already resolved or below 'medium' severity.
    Idempotency basis: the variance id (source_ref + lineage).
    """
    if variance.get("status") not in (None, "variance_detected"):
        return None
    severity = str(variance.get("severity", "low")).lower()
    if severity == "low":
        return None

    variance_id = variance.get("reconciliation_variance_id") or variance.get("id", "")
    account_id = variance.get("trading_account_id") or "unknown"
    variance_type = variance.get("variance_type") or "unknown"

    confidence = _SEVERITY_TO_CONFIDENCE.get(severity, 0.6)

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id=account_id),
        source=SuggestionSource.RULE,
        source_ref={"service": "derivatives_intelligence", "id": variance_id},
        suggestion_class=SuggestionClass.DERIVATIVES_RECONCILIATION,
        title=f"Derivatives reconciliation variance: {variance_type}",
        summary=(
            f"{severity.capitalize()} variance between venue-reported and "
            f"projected state on account {account_id}"
        ),
        what=(
            f"Reconciliation compared venue snapshots against projected state "
            f"for account {account_id} and found a '{variance_type}' variance "
            f"(expected {variance.get('expected_value')}, observed "
            f"{variance.get('observed_value')})."
        ),
        why=(
            "Venue-reported state diverged from Aether's event-derived "
            "projection, which may indicate missed events, a stream gap, or "
            "a venue-side correction."
        ),
        impact="Exposure and P&L figures derived from projected state may be inaccurate until reviewed.",
        recommended_action=(
            "Review the variance record, replay the adapter's checkpoint "
            "window, and mark the variance reviewed once explained."
        ),
        confidence_score=confidence,
        risk_score=_SEVERITY_TO_RISK.get(severity, 0.3),
        reversible=True,
        evidence=[
            {
                "id": variance_id,
                "type": "reconciliation_variance",
                "source": "derivatives_intelligence",
                "observedAt": variance.get("detected_at") or utc_now().isoformat(),
                "confidence": confidence,
            }
        ],
        lineage_event_ids=[variance_id] if variance_id else [],
    )


def create_suggestion_from_stream_gap(
    gap: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map an unrecovered market-stream gap to a SuggestionCreate.

    Returns None for gaps that already recovered. Idempotency basis: the
    gap id (source_ref + lineage).
    """
    if str(gap.get("status", "open")).lower() != "open":
        return None

    gap_id = gap.get("stream_gap_id") or gap.get("id", "")
    market_id = gap.get("canonical_market_id") or gap.get("market_id") or "unknown"
    expected = gap.get("expected_sequence")
    received = gap.get("received_sequence")

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id=market_id),
        source=SuggestionSource.RULE,
        source_ref={"service": "derivatives_intelligence", "id": gap_id},
        suggestion_class=SuggestionClass.DERIVATIVES_RISK,
        title=f"Unrecovered derivatives stream gap on {market_id}",
        summary=(
            f"Market stream sequence jumped from {expected} to {received} "
            f"and has not recovered"
        ),
        what=(
            f"The sequence tracker for {market_id} detected a gap (expected "
            f"{expected}, received {received}) that remains open."
        ),
        why=(
            "Messages inside the gap window were never observed, so any "
            "state derived from this stream is provisionally stale."
        ),
        impact="Positions, prices, and exposure for the affected market may lag venue reality.",
        recommended_action=(
            "Trigger a checkpointed backfill for the gap window and verify "
            "the gap closes; escalate to the venue adapter owner if it recurs."
        ),
        confidence_score=0.85,
        risk_score=0.6,
        reversible=True,
        evidence=[
            {
                "id": gap_id,
                "type": "stream_gap",
                "source": "derivatives_intelligence",
                "observedAt": gap.get("detected_at") or utc_now().isoformat(),
                "confidence": 0.85,
            }
        ],
        lineage_event_ids=[gap_id] if gap_id else [],
    )
