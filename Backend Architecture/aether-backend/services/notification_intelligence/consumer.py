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
    Topic.SUGGESTION_APPROVED.value: (
        "P2", "action-request",
        "Suggestion Approved",
        "An Aether suggestion has been approved and is ready for delivery",
    ),
    Topic.SUGGESTION_CREATED.value: (
        "P3", "operational",
        "New Suggestion Available",
        "A new Aether suggestion has been created for tenant review",
    ),
    Topic.STABLECOIN_DEPEG_DETECTED.value: (
        "P1", "alert",
        "Stablecoin Depeg Detected",
        "A tracked stablecoin's observed price crossed its depeg threshold",
    ),
    Topic.DERIVATIVES_VARIANCE_DETECTED.value: (
        "P2", "alert",
        "Derivatives Reconciliation Variance",
        "Venue-reported derivatives state diverged from Aether's projected state",
    ),
    Topic.DERIVATIVES_STREAM_GAP_STALLED.value: (
        "P2", "alert",
        "Derivatives Stream Gap Unrecovered",
        "A market-data stream gap has remained open beyond the recovery window",
    ),
    Topic.INTEROP_MESSAGE_STUCK.value: (
        "P2", "alert",
        "Cross-Chain Message Stuck",
        "A cross-chain message exceeded its lifecycle-phase SLA without new evidence",
    ),
    Topic.INTEROP_SECURITY_POLICY_CHANGED.value: (
        "P1", "alert",
        "Interop Security Policy Changed",
        "The verification/security configuration of a cross-chain path has changed",
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


def _channel_passes_filters(ch: dict, severity: str, notification_class: str) -> bool:
    """Return True if a channel should receive this notification based on its filters."""
    severity_filter = ch.get("severity_filter")
    if severity_filter and severity not in severity_filter:
        return False
    event_type_filter = ch.get("event_type_filter")
    if event_type_filter and notification_class not in event_type_filter:
        return False
    return True


async def _create_notification_delivery_jobs(notif: Any, intent_repo: Any = None, job_repo: Any = None) -> None:
    """Create durable DeliveryIntent + DeliveryJob records for a notification.

    Awaited directly — not scheduled as a background task — so records are
    committed before the caller returns. The DeliveryWorker executes dispatch.
    """
    try:
        from repositories.repos import UserNotificationChannelRepository
        from repositories.delivery_repos import DeliveryIntentRepository, DeliveryJobRepository
        from services.delivery.models import (
            DeliveryChannel, DeliveryIntent, DeliveryJob, DeliveryJobPriority,
            generate_idempotency_key,
        )

        _ch_repo = UserNotificationChannelRepository()
        _intent_repo = intent_repo or DeliveryIntentRepository()
        _job_repo = job_repo or DeliveryJobRepository()

        tenant_id = notif.tenant_id
        notif_id = notif.notification_id
        severity = notif.severity.value if hasattr(notif.severity, "value") else str(notif.severity)

        channels = await _ch_repo.list_for_tenant(tenant_id, active_only=True)
        if not channels:
            logger.info("no_active_channels tenant=%s notification=%s", tenant_id, notif_id)
            return

        # Apply per-channel filters (severity_filter, event_type_filter)
        notification_class = (
            notif.notification_class.value
            if hasattr(notif.notification_class, "value")
            else str(getattr(notif, "notification_class", ""))
        )
        channels = [ch for ch in channels if _channel_passes_filters(ch, severity, notification_class)]
        if not channels:
            logger.info(
                "all_channels_filtered tenant=%s notification=%s severity=%s",
                tenant_id, notif_id, severity,
            )
            return

        intent_key = generate_idempotency_key("notification", notif_id, tenant_id)
        existing = await _intent_repo.find_by_idempotency_key(intent_key)
        if existing:
            logger.info("delivery_intent_exists notification=%s", notif_id)
            return

        intent = DeliveryIntent(
            tenant_id=tenant_id,
            source_type="notification",
            source_id=notif_id,
            channels=[ch.get("channel_type", "notification") for ch in channels],
            idempotency_key=intent_key,
            metadata={"severity": severity, "title": notif.title},
        )
        await _intent_repo.insert(intent.id, intent.model_dump())

        prio_map = {"P0": DeliveryJobPriority.P0, "P1": DeliveryJobPriority.P1,
                    "P2": DeliveryJobPriority.P2, "P3": DeliveryJobPriority.P3,
                    "INFO": DeliveryJobPriority.INFO}
        job_priority = prio_map.get(severity, DeliveryJobPriority.P3)

        payload = {
            "title": notif.title,
            "body": notif.body or notif.why or "",
            "summary": notif.body or "",
            "priority": severity,
            "notification_id": notif_id,
            "tenant_id": tenant_id,
            "source": "notification",
        }

        for ch in channels:
            channel_type = ch.get("channel_type", "notification")
            try:
                ch_enum = DeliveryChannel(channel_type)
            except ValueError:
                ch_enum = DeliveryChannel.NOTIFICATION

            # channel_config holds per-channel settings (e.g. Slack's channel_id, webhook URL)
            provider_config = {
                **(ch.get("channel_config") or {}),
                "secret_ref": ch.get("credentials_ref"),
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

        logger.info(
            "delivery_jobs_created notification=%s intent=%s jobs=%d",
            notif_id, intent.id, len(channels),
        )
    except Exception as exc:
        logger.error(
            "delivery_job_creation_failed notification=%s error=%s",
            getattr(notif, "notification_id", "?"), exc,
        )


def attach_notification_consumers(
    consumer,
    repo=None,
    policy_engine=None,
    delivery_router=None,
    producer=None,
    cache=None,
    intent_repo=None,
    job_repo=None,
) -> None:
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

        # Create durable DeliveryIntent + DeliveryJobs — synchronous DB write,
        # picked up by DeliveryWorker. Replaces fire-and-forget create_task.
        await _create_notification_delivery_jobs(notif, intent_repo=intent_repo, job_repo=job_repo)

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
        Topic.SUGGESTION_APPROVED,
        Topic.SUGGESTION_CREATED,
        Topic.STABLECOIN_DEPEG_DETECTED,
        Topic.DERIVATIVES_VARIANCE_DETECTED,
        Topic.DERIVATIVES_STREAM_GAP_STALLED,
        Topic.INTEROP_MESSAGE_STUCK,
        Topic.INTEROP_SECURITY_POLICY_CHANGED,
    ]:
        consumer.subscribe(topic, _handle)

    logger.info("notification_intelligence_consumers_attached")
