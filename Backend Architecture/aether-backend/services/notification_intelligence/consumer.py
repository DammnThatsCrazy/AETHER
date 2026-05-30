"""Notification Intelligence — Kafka Consumer

Subscribes to source intelligence topics, normalises each into an
IntelligenceNotificationEvent, runs the policy engine, persists, and
dispatches to the DeliveryRouter.

Called from main.py lifespan via attach_notification_consumers().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger, metrics
from services.notification_intelligence.models import (
    IntelligenceNotificationEvent,
    NotificationLifecycleState,
    NotificationSeverity,
    NotificationClass,
    make_dedup_key,
)
from services.notification_intelligence.audit import build_audit_entry

logger = get_logger("aether.notification.consumer")

# Per-topic normalisation config: (severity, notification_class, title_template, why_template)
_TOPIC_MAP: dict[str, tuple[str, str, str, str]] = {
    Topic.ANOMALY_DETECTED.value: (
        "P1", "alert",
        "Anomaly Detected",
        "Session scoring flagged an anomaly in observed behaviour",
    ),
    Topic.CIS_QUARANTINE_ESCALATED.value: (
        "P0", "action-request",
        "CIS Quarantine Escalated",
        "A graph mutation quarantine has been escalated and requires immediate review",
    ),
    Topic.AGENT_ESCALATION_RAISED.value: (
        "P1", "action-request",
        "Agent Escalation Raised",
        "An agent has escalated a task that requires human operator review",
    ),
    Topic.ML_EXTRACTION_ALERT_OPENED.value: (
        "P1", "alert",
        "Model Extraction Alert",
        "Potential model extraction attempt detected",
    ),
    Topic.ML_EXTRACTION_CLUSTER_ESCALATED.value: (
        "P0", "alert",
        "Extraction Cluster Escalated",
        "A coordinated model extraction cluster has been identified",
    ),
    Topic.GOVERNANCE_DECISION_EVALUATED.value: (
        "P2", "operational",
        "Governance Decision Evaluated",
        "A governance decision has been evaluated and is available for review",
    ),
    Topic.COMMERCE_APPROVAL_REQUESTED.value: (
        "P1", "action-request",
        "Commerce Approval Required",
        "An agentic commerce transaction requires operator approval",
    ),
    Topic.CIS_REASONING_CONTRADICTION_DETECTED.value: (
        "P1", "alert",
        "Reasoning Contradiction Detected",
        "CIS detected a logical contradiction in a reasoning chain",
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise(event: Event) -> IntelligenceNotificationEvent | None:
    """Build an IntelligenceNotificationEvent from a source Kafka event."""
    topic_val = event.topic.value if hasattr(event.topic, "value") else str(event.topic)
    mapping = _TOPIC_MAP.get(topic_val)
    if not mapping:
        logger.warning("no_mapping_for_topic topic=%s", topic_val)
        return None

    severity_str, class_str, default_title, default_why = mapping
    payload = event.payload or {}

    title = payload.get("title") or payload.get("alert_title") or default_title
    what = payload.get("what") or payload.get("description") or title
    why = payload.get("why") or payload.get("reason") or default_why
    impact = payload.get("impact") or payload.get("affected") or "Review required"
    recommended = payload.get("recommended_action") or payload.get("action")
    entity_ids = payload.get("entity_ids") or ([payload["entity_id"]] if payload.get("entity_id") else [])

    dedup_key = make_dedup_key(topic_val, event.event_id, event.tenant_id)

    notif = IntelligenceNotificationEvent(
        tenant_id=event.tenant_id,
        deduplication_key=dedup_key,
        idempotency_key=dedup_key,
        source_topic=topic_val,
        source_event_id=event.event_id,
        source_service=event.source_service,
        correlation_id=event.correlation_id,
        severity=NotificationSeverity(severity_str),
        notification_class=NotificationClass(class_str),
        title=title,
        body=why,
        what=what,
        why=why,
        impact=impact,
        recommended_action=recommended,
        deep_link=payload.get("deep_link", "/mission"),
        operator_context=payload.get("operator_context", {}),
        graph_propagation={"entity_ids": entity_ids} if entity_ids else None,
    )
    notif.audit_trail.append(build_audit_entry("detected", actor_user_id="system"))
    return notif


def attach_notification_consumers(consumer, repo=None, policy_engine=None, delivery_router=None, producer=None, cache=None) -> None:
    """Wire notification handlers onto the shared EventConsumer.

    Called from main.py lifespan after attach_profile360_workers().
    """
    from repositories.repos import (
        NotificationIntelligenceRepository,
        TenantNotificationConfigRepository,
        UserNotificationChannelRepository,
    )
    from services.notification_intelligence.policy_engine import PolicyEngine
    from services.notification_intelligence.delivery_router import DeliveryRouter
    from services.notification_intelligence.lifecycle import LifecycleEngine

    _repo = repo or NotificationIntelligenceRepository()
    _config_repo = TenantNotificationConfigRepository()
    _channel_repo = UserNotificationChannelRepository()
    _policy = policy_engine or PolicyEngine(cache=cache)
    _router = delivery_router or DeliveryRouter(channel_repo=_channel_repo)
    _lifecycle = LifecycleEngine(repo=_repo, producer=producer)

    async def _handle(event: Event) -> None:
        notif = _normalise(event)
        if notif is None:
            return

        # Load tenant config
        config_record = await _config_repo.find_by_id(notif.tenant_id)
        from services.notification_intelligence.models import TenantNotificationConfig
        config = TenantNotificationConfig(
            **(config_record or {"tenant_id": notif.tenant_id})
        )

        # Policy evaluation
        policy_result = await _policy.evaluate(
            dedup_key=notif.deduplication_key,
            tenant_id=notif.tenant_id,
            severity=notif.severity.value,
            config=config,
        )
        if not policy_result.allowed:
            logger.info("notification_rejected id=%s reason=%s", notif.notification_id, policy_result.reject_reason)
            return

        notif.routing_policy = {
            "channels": policy_result.channels,
            "requires_operator_review": policy_result.requires_operator_review,
        }
        notif.expires_at = policy_result.expires_at

        # Persist
        notif_dict = notif.model_dump()
        notif_dict["id"] = notif.notification_id
        notif_dict["tenant_id"] = notif.tenant_id
        await _repo.create(notif_dict)

        metrics.increment("aether_notifications_emitted_total",
                          labels={"tenant_id": notif.tenant_id,
                                  "severity": notif.severity.value,
                                  "source_topic": notif.source_topic})

        # Advance lifecycle
        await _lifecycle.advance(notif.notification_id, NotificationLifecycleState.VALIDATED,
                                 actor_user_id="system")
        await _lifecycle.advance(notif.notification_id, NotificationLifecycleState.QUEUED,
                                 actor_user_id="system")

        # Deliver to all configured channels
        import asyncio
        asyncio.create_task(_router.route(notif))

        # If operator review required, advance to that state after delivery
        if policy_result.requires_operator_review:
            await _lifecycle.advance(
                notif.notification_id,
                NotificationLifecycleState.OPERATOR_REVIEW,
                actor_user_id="system",
                metadata={"sla_deadline": notif.expires_at},
            )

        if producer:
            from shared.events.events import Topic as T
            await producer.publish(Event(
                topic=T.INTEL_NOTIFICATION_QUEUED,
                tenant_id=notif.tenant_id,
                payload={"notification_id": notif.notification_id, "severity": notif.severity.value},
            ))

        logger.info("notification_processed id=%s topic=%s tenant=%s",
                    notif.notification_id, notif.source_topic, notif.tenant_id)

    # Register handler for every watched topic
    for topic in [
        Topic.ANOMALY_DETECTED,
        Topic.CIS_QUARANTINE_ESCALATED,
        Topic.AGENT_ESCALATION_RAISED,
        Topic.ML_EXTRACTION_ALERT_OPENED,
        Topic.ML_EXTRACTION_CLUSTER_ESCALATED,
        Topic.GOVERNANCE_DECISION_EVALUATED,
        Topic.COMMERCE_APPROVAL_REQUESTED,
        Topic.CIS_REASONING_CONTRADICTION_DETECTED,
    ]:
        consumer.subscribe(topic, _handle)

    logger.info("notification_intelligence_consumers_attached")
