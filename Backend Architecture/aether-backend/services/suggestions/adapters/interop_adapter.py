"""Interoperability Intelligence ↔ Suggestion adapter.

Maps stuck cross-chain messages and security-policy changes to OODA
suggestions. Suggestions only — Aether never relays, retries, or recovers
messages. Gated by settings.suggestions.interop_adapter_enabled.
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

logger = get_logger("aether.suggestions.adapters.interop")

# Non-terminal statuses where prolonged residence indicates a stuck message.
_STUCK_ELIGIBLE_STATUSES = frozenset({
    "source_confirmed", "verification_in_progress", "partially_verified",
    "verified", "delivery_pending", "delivery_attempted",
})


def create_suggestion_from_stuck_message(
    message: dict,
    tenant_id: str,
    stuck_minutes: int,
) -> Optional[SuggestionCreate]:
    """Map a message that exceeded its phase SLA to a SuggestionCreate.

    Returns None unless the message sits in a non-terminal in-flight status.
    Idempotency basis: message id + current status (so a message that
    progresses and stalls again yields a distinct suggestion).
    """
    status = str(message.get("status", "")).lower()
    if status not in _STUCK_ELIGIBLE_STATUSES:
        return None

    message_id = message.get("interop_message_id") or message.get("id", "")
    path_id = message.get("path_id") or "unknown"
    correlation_key = message.get("correlation_key") or ""
    ref = f"{message_id}:{status}"

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id=message_id),
        source=SuggestionSource.RULE,
        source_ref={"service": "interop_intelligence", "id": ref},
        suggestion_class=SuggestionClass.INTEROP_DELIVERY_HEALTH,
        title=f"Cross-chain message stuck in '{status}'",
        summary=(
            f"Message {message_id} on path {path_id} has been in "
            f"'{status}' for over {stuck_minutes} minutes"
        ),
        what=(
            f"No lifecycle progression has been observed for message "
            f"{message_id} (correlation {correlation_key}) beyond "
            f"'{status}' within the expected window."
        ),
        why=(
            "The provider has not produced the next lifecycle evidence "
            "(verification or delivery) within the configured SLA. This is "
            "an observation of provider/network state — Aether takes no "
            "recovery action."
        ),
        impact=(
            "Assets or messages in flight on this path may be delayed; "
            "repeated stalls indicate degraded path reliability."
        ),
        recommended_action=(
            "Inspect the message trace and the path's security-policy "
            "snapshot, and check the provider's status page for the "
            "affected lane."
        ),
        confidence_score=0.8,
        risk_score=0.5,
        reversible=True,
        evidence=[
            {
                "id": message_id,
                "type": "interop_message",
                "source": "interop_intelligence",
                "observedAt": message.get("source_observed_at") or utc_now().isoformat(),
                "confidence": 0.8,
            }
        ],
        lineage_event_ids=[message_id] if message_id else [],
    )


def create_suggestion_from_policy_change(
    previous_snapshot: dict,
    current_snapshot: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map a security-policy snapshot content change to a SuggestionCreate.

    Returns None when the content hashes match (no change). Idempotency
    basis: the new snapshot id.
    """
    if previous_snapshot.get("content_hash") == current_snapshot.get("content_hash"):
        return None

    snapshot_id = current_snapshot.get("security_snapshot_id") or current_snapshot.get("id", "")
    path_id = current_snapshot.get("path_id") or "unknown"

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id=path_id),
        source=SuggestionSource.RULE,
        source_ref={"service": "interop_intelligence", "id": snapshot_id},
        suggestion_class=SuggestionClass.INTEROP_DELIVERY_HEALTH,
        title=f"Security policy changed on path {path_id}",
        summary="The verification/security configuration for a cross-chain path has changed",
        what=(
            f"The security-policy snapshot for path {path_id} produced a new "
            f"content hash (previous {previous_snapshot.get('content_hash')}, "
            f"current {current_snapshot.get('content_hash')})."
        ),
        why=(
            "Changes to verifier sets, thresholds, or libraries alter the "
            "trust assumptions of every message on this path."
        ),
        impact="Messages verified under the new policy carry different security guarantees than earlier traffic.",
        recommended_action=(
            "Review the policy diff and confirm the change matches the "
            "provider's announced configuration."
        ),
        confidence_score=0.9,
        risk_score=0.6,
        reversible=True,
        evidence=[
            {
                "id": snapshot_id,
                "type": "security_policy_snapshot",
                "source": "interop_intelligence",
                "observedAt": current_snapshot.get("captured_at") or utc_now().isoformat(),
                "confidence": 0.9,
            }
        ],
        lineage_event_ids=[snapshot_id] if snapshot_id else [],
    )
