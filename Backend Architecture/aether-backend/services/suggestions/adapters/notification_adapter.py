"""Notification Intelligence ↔ Suggestion adapter.

Maps IntelligenceNotificationEvents into SuggestionCreate inputs and
delivers approved Suggestions by creating durable DeliveryIntent + DeliveryJob
records. Never calls service.deliver_suggestion() directly — that is only
called by DeliveryWorker after ProviderReceipt confirms real delivery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

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
    channel_repo: Any = None,
    intent_repo: Any = None,
    job_repo: Any = None,
) -> dict:
    """Deliver an approved suggestion by creating durable DeliveryIntent + DeliveryJob records.

    Guards:
    - suggestion must be APPROVED
    - delivery_eligible must be True
    - policy_decision.allowed must be True (if present)

    This function never calls service.deliver_suggestion() directly.
    The suggestion transitions to DELIVERED only after DeliveryWorker
    confirms ProviderReceipt with a real external_id.
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

    suggestion_id = suggestion["id"]
    tenant_id = suggestion.get("tenant_id", "")

    # Resolve active delivery channels for this tenant
    from repositories.repos import UserNotificationChannelRepository
    _channel_repo = channel_repo or UserNotificationChannelRepository()
    channels: list[dict] = []
    try:
        channels = await _channel_repo.list_for_tenant(tenant_id, active_only=True)
    except Exception as exc:
        logger.warning(f"Channel lookup failed for tenant={tenant_id!r}: {exc}")

    if not channels:
        logger.info(
            f"No active channels for tenant={tenant_id!r} — "
            f"suggestion {suggestion_id!r} will not be delivered"
        )
        return suggestion

    # Lazy-import repos to avoid circular at module load
    from repositories.delivery_repos import DeliveryIntentRepository, DeliveryJobRepository
    from services.delivery.models import (
        DeliveryChannel, DeliveryIntent, DeliveryJob, DeliveryJobPriority,
        generate_idempotency_key,
    )

    _intent_repo = intent_repo or DeliveryIntentRepository()
    _job_repo = job_repo or DeliveryJobRepository()

    priority_str = suggestion.get("priority", "P3")
    try:
        job_priority = DeliveryJobPriority[priority_str]
    except KeyError:
        job_priority = DeliveryJobPriority.P3

    payload: dict[str, Any] = {
        "title": suggestion.get("title", "Aether Suggestion"),
        "body": suggestion.get("summary", ""),
        "summary": suggestion.get("summary", ""),
        "what": suggestion.get("what", ""),
        "why": suggestion.get("why", ""),
        "recommended_action": suggestion.get("recommended_action"),
        "priority": priority_str,
        "suggestion_id": suggestion_id,
        "tenant_id": tenant_id,
        "source": "suggestion",
    }

    channel_names = [ch.get("channel_type", "notification") for ch in channels]
    intent_key = generate_idempotency_key("suggestion", suggestion_id, tenant_id)

    # Idempotent — skip if intent already exists
    existing = await _intent_repo.find_by_idempotency_key(intent_key)
    if existing:
        logger.info(
            f"DeliveryIntent already exists for suggestion={suggestion_id!r}: "
            f"intent_id={existing['id']!r}"
        )
        return suggestion

    intent = DeliveryIntent(
        tenant_id=tenant_id,
        source_type="suggestion",
        source_id=suggestion_id,
        channels=channel_names,
        idempotency_key=intent_key,
        metadata={"suggestion_title": suggestion.get("title", ""), "priority": priority_str},
    )
    await _intent_repo.insert(intent.id, intent.model_dump())

    jobs_created = 0
    for ch in channels:
        channel_type = ch.get("channel_type", "notification")
        try:
            ch_enum = DeliveryChannel(channel_type)
        except ValueError:
            ch_enum = DeliveryChannel.NOTIFICATION

        provider_config: dict[str, Any] = {
            **(ch.get("config") or {}),
            "secret_ref": ch.get("credentials_ref"),
            "channel_id": ch.get("destination") or ch.get("channel_id"),
            "tenant_id": tenant_id,
        }

        job = DeliveryJob(
            intent_id=intent.id,
            tenant_id=tenant_id,
            channel=ch_enum,
            provider_adapter=channel_type,
            priority=job_priority,
            payload=payload,
            provider_config=provider_config,
        )
        await _job_repo.insert(job.id, job.model_dump())
        jobs_created += 1

    logger.info(
        f"Suggestion {suggestion_id!r} enqueued for delivery: "
        f"intent_id={intent.id!r} jobs_created={jobs_created}"
    )
    return suggestion


def _map_priority_to_severity(priority: str) -> str:
    mapping = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low", "info": "info"}
    return mapping.get(priority, "low")
