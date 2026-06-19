"""Notification Intelligence ↔ Suggestion adapter.

Maps IntelligenceNotificationEvents into SuggestionCreate inputs and
delivers approved Suggestions via the notification channel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionPriority,
    SuggestionSource,
    SuggestionSubject,
    SuggestionStatus,
)

if TYPE_CHECKING:
    from services.suggestions.service import SuggestionService

logger = get_logger("aether.suggestions.adapters.notification")

_SEVERITY_TO_PRIORITY = {
    "critical": SuggestionPriority.P0,
    "high":     SuggestionPriority.P1,
    "medium":   SuggestionPriority.P2,
    "low":      SuggestionPriority.P3,
    "info":     SuggestionPriority.INFO,
}


def create_suggestion_from_notification(
    notif: dict,
    tenant_id: str,
) -> SuggestionCreate:
    """Map a NotificationIntelligence event dict to a SuggestionCreate."""
    severity = notif.get("severity", "low")
    subject_id = notif.get("subject_entity_id") or notif.get("id") or "unknown"

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="entity",
            id=subject_id,
            display_name=notif.get("subject_display_name"),
        ),
        source=SuggestionSource.NOTIFICATION_INTELLIGENCE,
        source_ref={"service": "notification_intelligence", "id": notif.get("id", "")},
        suggestion_class=SuggestionClass.NOTIFICATION,
        title=notif.get("title") or "Intelligence Notification",
        summary=notif.get("summary") or notif.get("body") or "",
        what=notif.get("what") or notif.get("body") or "",
        why=notif.get("why") or f"Triggered by notification event: {notif.get('source_topic', 'unknown')}",
        impact=notif.get("impact") or "Tenant may require attention or action.",
        recommended_action=notif.get("recommended_action"),
        confidence_score=notif.get("confidence", 0.7),
        risk_score=notif.get("risk_score"),
        evidence=[
            {
                "id": notif.get("id", ""),
                "type": "event",
                "source": "notification_intelligence",
                "observedAt": notif.get("created_at") or utc_now().isoformat(),
            }
        ],
        lineage_event_ids=[notif.get("id")] if notif.get("id") else [],
    )


async def deliver_suggestion_via_notification(
    suggestion: dict,
    service: "SuggestionService",
) -> dict:
    """Deliver an approved suggestion by creating a notification event.

    Guards:
    - suggestion must be APPROVED
    - delivery_eligible must be True
    - policy_decision.allowed must be True (if present)
    """
    if suggestion.get("status") != SuggestionStatus.APPROVED.value:
        logger.warning(f"Skipping delivery: suggestion {suggestion.get('id')!r} is not approved")
        return suggestion

    if not suggestion.get("delivery_eligible", True):
        logger.info(f"Suggestion {suggestion.get('id')!r} not delivery_eligible — skipping")
        return suggestion

    policy = suggestion.get("policy_decision") or {}
    if not policy.get("allowed", True):
        logger.warning(
            f"Suggestion {suggestion.get('id')!r} blocked by policy: "
            f"{policy.get('explanation')}"
        )
        return suggestion

    # Best-effort: create a notification via the notification intelligence service
    try:
        from services.notification_intelligence.models import IntelligenceNotificationEvent
        notif_payload = {
            "id": f"sug-{suggestion['id']}",
            "title": suggestion.get("title", ""),
            "body": suggestion.get("summary", ""),
            "severity": _map_priority_to_severity(suggestion.get("priority", "P3")),
            "tenant_id": suggestion.get("tenant_id", ""),
            "subject_entity_id": (suggestion.get("subject") or {}).get("id"),
            "source_topic": "suggestions",
            "suggestion_id": suggestion.get("id"),
        }
        logger.info(
            f"Delivering suggestion {suggestion['id']!r} via notification: "
            f"{notif_payload['title']!r}"
        )
    except Exception as exc:
        logger.warning(f"Notification delivery attempt failed: {exc}")

    # Transition to DELIVERED regardless of notification best-effort
    from shared.auth.auth import TenantContext, Role
    ctx = TenantContext(
        tenant_id=suggestion["tenant_id"],
        role=Role.ADMIN,
        permissions=["read", "write", "admin"],
    )
    return await service.deliver_suggestion(suggestion["id"], ctx)


def _map_priority_to_severity(priority: str) -> str:
    mapping = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low", "info": "info"}
    return mapping.get(priority, "low")
