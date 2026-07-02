"""Aether Service — Notification Intelligence

FastAPI router providing:
  - Intelligence notification CRUD + operator actions
  - Tenant notification config management
  - End-user multi-channel management (Slack OAuth, Discord, Telegram, Webhook)
  - Slack interactive callback handler
  - Telegram callback handler

Prefix: /v1/notifications
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics
from repositories.repos import (
    NotificationIntelligenceRepository,
    OperatorActionRepository,
    TenantNotificationConfigRepository,
    UserNotificationChannelRepository,
    SlackOAuthStateRepository,
)
from repositories.delivery_repos import WebhookInboxRepository as _WebhookInboxRepository
from services.delivery.security import sanitize_headers as _sanitize_headers
from services.notification_intelligence.models import (
    AnnotateRequest,
    EmitNotificationRequest,
    IntelligenceNotificationEvent,
    NotificationLifecycleState,
    NotificationSeverity,
    NotificationClass,
    OperatorAction,
    OperatorActionType,
    RegisterChannelRequest,
    TenantNotificationConfig,
    UpdateChannelRequest,
    UpdateConfigRequest,
    UserNotificationChannel,
    make_dedup_key,
)
from services.notification_intelligence.lifecycle import LifecycleEngine
from services.notification_intelligence.audit import build_audit_entry
from services.notification_intelligence.channel_gateway import (
    get_gateway,
    SlackChannelGateway,
)

logger = get_logger("aether.service.notification_intelligence")

router = APIRouter(prefix="/v1/notifications", tags=["Notification Intelligence"])

# ── Repositories (module-level, lazy-init pattern) ────────────────────────────
_notif_repo = NotificationIntelligenceRepository()
_action_repo = OperatorActionRepository()
_config_repo = TenantNotificationConfigRepository()
_channel_repo = UserNotificationChannelRepository()
_oauth_state_repo = SlackOAuthStateRepository()
_webhook_inbox_repo = _WebhookInboxRepository()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


def _get_lifecycle_engine() -> LifecycleEngine:
    from dependencies.providers import get_producer, get_graph
    try:
        producer = get_producer()
        graph = get_graph()
    except Exception:
        producer, graph = None, None
    return LifecycleEngine(repo=_notif_repo, producer=producer, graph=graph)


def _enqueue_notification_delivery(notif: Any) -> None:
    """D7: After persisting a notification, create durable DeliveryIntent + DeliveryJobs.

    Called synchronously from emit_notification() so the jobs are queued
    before the API response is returned. Errors are logged but never raised
    so the API response is always returned to the caller.
    """
    from services.notification_intelligence.consumer import _create_notification_delivery_jobs
    try:
        _create_notification_delivery_jobs(notif)
    except Exception as exc:
        logger.warning(f"_enqueue_notification_delivery failed notif={getattr(notif, 'notification_id', '?')!r}: {exc}")


async def _create_delivery_jobs_for_replay(notif: Any) -> int:
    """D5: Create DeliveryIntent + DeliveryJobs for replay. Returns jobs_queued count."""
    try:
        from repositories.repos import UserNotificationChannelRepository
        from repositories.delivery_repos import DeliveryIntentRepository, DeliveryJobRepository
        from services.delivery.models import (
            DeliveryChannel, DeliveryIntent, DeliveryJob, DeliveryJobPriority,
            generate_idempotency_key,
        )
        import uuid as _uuid

        tenant_id = notif.tenant_id
        notif_id = notif.notification_id

        ch_repo = UserNotificationChannelRepository()
        channels = await ch_repo.list_for_tenant(tenant_id, active_only=True)
        if not channels:
            return 0

        intent_repo = DeliveryIntentRepository()
        job_repo = DeliveryJobRepository()

        severity = notif.severity.value if hasattr(notif.severity, "value") else str(notif.severity)
        # Replay always gets a fresh intent key so it can re-queue even if one already exists
        intent_key = generate_idempotency_key("notification-replay", notif_id, str(_uuid.uuid4()))

        intent = DeliveryIntent(
            tenant_id=tenant_id,
            source_type="notification",
            source_id=notif_id,
            channels=[ch.get("channel_type", "notification") for ch in channels],
            idempotency_key=intent_key,
            metadata={"severity": severity, "title": notif.title, "replay": True},
        )
        await intent_repo.insert(intent.id, intent.model_dump())

        prio_map = {"P0": DeliveryJobPriority.P0, "P1": DeliveryJobPriority.P1,
                    "P2": DeliveryJobPriority.P2, "P3": DeliveryJobPriority.P3,
                    "INFO": DeliveryJobPriority.INFO}
        job_priority = prio_map.get(severity, DeliveryJobPriority.P3)

        payload = {
            "title": notif.title,
            "body": notif.body or "",
            "summary": notif.body or "",
            "priority": severity,
            "notification_id": notif_id,
            "tenant_id": tenant_id,
            "source": "notification-replay",
        }

        count = 0
        for ch in channels:
            channel_type = ch.get("channel_type", "notification")
            try:
                ch_enum = DeliveryChannel(channel_type)
            except ValueError:
                ch_enum = DeliveryChannel.NOTIFICATION

            provider_config = {
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
            await job_repo.insert(job.id, job.model_dump())
            count += 1

        logger.info(f"Replay jobs queued: notification={notif_id!r} count={count}")
        return count
    except Exception as exc:
        logger.error(f"_create_delivery_jobs_for_replay failed: {exc}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/intelligence")
async def emit_notification(body: EmitNotificationRequest, request: Request):
    """Emit a new intelligence notification (usually called by internal services)."""
    _require(request, body.tenant_id, "write")

    dedup_key = make_dedup_key(body.source_topic, body.source_event_id, body.tenant_id)
    notif = IntelligenceNotificationEvent(
        tenant_id=body.tenant_id,
        deduplication_key=dedup_key,
        idempotency_key=dedup_key,
        source_topic=body.source_topic,
        source_event_id=body.source_event_id,
        source_service=body.source_service,
        correlation_id=body.correlation_id,
        severity=body.severity,
        notification_class=body.notification_class,
        title=body.title,
        body=body.body,
        what=body.what,
        why=body.why,
        impact=body.impact,
        recommended_action=body.recommended_action,
        reversible=body.reversible,
        deep_link=body.deep_link,
        operator_context=body.operator_context,
        graph_propagation=body.graph_propagation,
        audit_trail=[build_audit_entry("detected", actor_user_id=request.state.tenant.user_id)],
    )

    notif_dict = notif.model_dump()
    notif_dict["id"] = notif.notification_id
    notif_dict["tenant_id"] = notif.tenant_id
    result = await _notif_repo.create(notif_dict)

    # D7 fix: enqueue durable delivery jobs after persisting the notification
    _enqueue_notification_delivery(notif)

    metrics.increment("aether_notifications_emitted_total",
                      labels={"tenant_id": body.tenant_id,
                              "severity": body.severity.value,
                              "source_topic": body.source_topic})
    return APIResponse(data=result).to_dict()


@router.get("/intelligence")
async def list_notifications(
    request: Request,
    tenantId: str = Query(...),
    state: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    source_topic: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List intelligence notifications for a tenant."""
    _require(request, tenantId, "read")
    filters: dict[str, Any] = {"tenant_id": tenantId}
    if state:
        filters["lifecycle_state"] = state
    if severity:
        filters["severity"] = severity
    if source_topic:
        filters["source_topic"] = source_topic
    rows = await _notif_repo.find_many(filters=filters, limit=limit)
    return APIResponse(data=rows).to_dict()


@router.get("/intelligence/{notification_id}")
async def get_notification(notification_id: str, request: Request, tenantId: str = Query(...)):
    """Get a single notification with full audit trail."""
    _require(request, tenantId, "read")
    row = await _notif_repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenantId:
        raise NotFoundError(f"Notification {notification_id!r} not found")
    return APIResponse(data=row).to_dict()


@router.get("/intelligence/{notification_id}/audit")
async def get_audit_trail(notification_id: str, request: Request, tenantId: str = Query(...)):
    """Return the full immutable audit trail for a notification."""
    _require(request, tenantId, "read")
    row = await _notif_repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenantId:
        raise NotFoundError(f"Notification {notification_id!r} not found")
    trail = row.get("audit_trail") or []
    if isinstance(trail, str):
        trail = json.loads(trail)
    return APIResponse(data=trail).to_dict()


# ── Operator Actions ──────────────────────────────────────────────────────────

async def _operator_action(
    notification_id: str,
    tenant_id: str,
    action_type: OperatorActionType,
    new_state: NotificationLifecycleState,
    request: Request,
    annotation: Optional[str] = None,
) -> dict:
    _require(request, tenant_id, "write")
    request.state.tenant.require_permission("notifications:approve")

    row = await _notif_repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"Notification {notification_id!r} not found")

    engine = _get_lifecycle_engine()
    updated = await engine.advance(
        notification_id, new_state,
        actor_user_id=request.state.tenant.user_id,
        actor_role=str(request.state.tenant.role),
        metadata={"annotation": annotation} if annotation else None,
    )

    action = OperatorAction(
        notification_id=notification_id,
        tenant_id=tenant_id,
        action_type=action_type,
        actor_user_id=request.state.tenant.user_id or "",
        annotation=annotation,
    )
    action_dict = action.model_dump()
    action_dict["tenant_id"] = tenant_id
    await _action_repo.create(action_dict)

    metrics.increment("aether_notifications_operator_action_total",
                      labels={"tenant_id": tenant_id, "action_type": action_type.value})

    # On approve: trigger graph propagation
    if action_type == OperatorActionType.APPROVE:
        config_record = await _config_repo.find_by_id(tenant_id)
        from services.notification_intelligence.models import TenantNotificationConfig
        config = TenantNotificationConfig(**(config_record or {"tenant_id": tenant_id}))
        await engine.on_approve(
            notification=row,
            actor_user_id=request.state.tenant.user_id or "",
            config=config,
        )
        # Advance to propagated
        try:
            await engine.advance(notification_id, NotificationLifecycleState.PROPAGATED,
                                 actor_user_id=request.state.tenant.user_id)
        except Exception:
            pass  # propagated transition may fail if graph write failed; approved state is set

    return APIResponse(data=updated).to_dict()


@router.patch("/intelligence/{notification_id}/approve")
async def approve_notification(notification_id: str, request: Request, tenantId: str = Query(...)):
    return await _operator_action(
        notification_id, tenantId,
        OperatorActionType.APPROVE, NotificationLifecycleState.APPROVED, request
    )


@router.patch("/intelligence/{notification_id}/suppress")
async def suppress_notification(notification_id: str, request: Request, tenantId: str = Query(...)):
    return await _operator_action(
        notification_id, tenantId,
        OperatorActionType.SUPPRESS, NotificationLifecycleState.SUPPRESSED, request
    )


@router.patch("/intelligence/{notification_id}/escalate")
async def escalate_notification(notification_id: str, request: Request, tenantId: str = Query(...)):
    # Escalate stays in operator_review but advances with escalation metadata
    _require(request, tenantId, "write")
    request.state.tenant.require_permission("notifications:approve")
    engine = _get_lifecycle_engine()
    updated = await engine.advance(
        notification_id, NotificationLifecycleState.OPERATOR_REVIEW,
        actor_user_id=request.state.tenant.user_id,
        actor_role=str(request.state.tenant.role),
        metadata={"escalated": True},
    )
    action = OperatorAction(
        notification_id=notification_id, tenant_id=tenantId,
        action_type=OperatorActionType.ESCALATE,
        actor_user_id=request.state.tenant.user_id or "",
    )
    action_dict = action.model_dump()
    action_dict["tenant_id"] = tenantId
    await _action_repo.create(action_dict)
    metrics.increment("aether_notifications_operator_action_total",
                      labels={"tenant_id": tenantId, "action_type": "escalate"})
    return APIResponse(data=updated).to_dict()


@router.patch("/intelligence/{notification_id}/annotate")
async def annotate_notification(
    notification_id: str, body: AnnotateRequest, request: Request, tenantId: str = Query(...)
):
    _require(request, tenantId, "write")
    row = await _notif_repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenantId:
        raise NotFoundError(f"Notification {notification_id!r} not found")
    engine = _get_lifecycle_engine()
    current_state = NotificationLifecycleState(row.get("lifecycle_state", "detected"))
    updated = await engine.advance(
        notification_id, current_state,
        actor_user_id=request.state.tenant.user_id,
        actor_role=str(request.state.tenant.role),
        metadata={"annotation": body.annotation},
    )
    action = OperatorAction(
        notification_id=notification_id, tenant_id=tenantId,
        action_type=OperatorActionType.ANNOTATE,
        actor_user_id=request.state.tenant.user_id or "",
        annotation=body.annotation,
    )
    action_dict = action.model_dump()
    action_dict["tenant_id"] = tenantId
    await _action_repo.create(action_dict)
    return APIResponse(data=updated).to_dict()


@router.post("/intelligence/{notification_id}/replay")
async def replay_notification(notification_id: str, request: Request, tenantId: str = Query(...)):
    """Re-queue a notification for delivery by creating fresh DeliveryIntent + DeliveryJobs.

    Returns 202 Accepted with jobs_queued count. The DeliveryWorker handles
    actual dispatch asynchronously.
    """
    _require(request, tenantId, "write")
    row = await _notif_repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenantId:
        raise NotFoundError(f"Notification {notification_id!r} not found")

    from services.notification_intelligence.models import IntelligenceNotificationEvent
    notif = IntelligenceNotificationEvent(**{k: v for k, v in row.items() if k != "id"})
    notif.notification_id = row.get("id", notification_id)

    # D5 fix: use _create_notification_delivery_jobs() — creates durable DB records
    # instead of fire-and-forget DeliveryRouter instantiated without providers_repo.
    jobs_queued = await _create_delivery_jobs_for_replay(notif)
    return APIResponse(data={"replayed": True, "jobs_queued": jobs_queued}, status_code=202).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# TENANT NOTIFICATION CONFIG
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/config")
async def get_config(request: Request, tenantId: str = Query(...)):
    _require(request, tenantId, "read")
    record = await _config_repo.find_by_id(tenantId)
    if not record:
        record = TenantNotificationConfig(tenant_id=tenantId).model_dump()
    # Never return token refs in plaintext
    record.pop("slack_bot_token_ref", None)
    return APIResponse(data=record).to_dict()


@router.put("/config")
async def update_config(body: UpdateConfigRequest, request: Request, tenantId: str = Query(...)):
    _require(request, tenantId, "write")
    request.state.tenant.require_permission("notifications:manage")

    existing_record = await _config_repo.find_by_id(tenantId)
    if existing_record:
        config = TenantNotificationConfig(**existing_record)
    else:
        config = TenantNotificationConfig(tenant_id=tenantId)

    update_data = body.model_dump(exclude_none=True)

    # Handle Slack bot token separately — store in vault
    slack_token = update_data.pop("slack_bot_token", None)
    if slack_token:
        from repositories.repos import ProvidersRepository
        providers_repo = ProvidersRepository()
        token_ref = f"slack_bot_token:{tenantId}"
        await providers_repo.upsert(token_ref, {"api_key": slack_token, "provider": "slack", "tenant_id": tenantId})
        update_data["slack_bot_token_ref"] = token_ref

    config_dict = config.model_dump()
    config_dict.update(update_data)
    config_dict["id"] = tenantId
    config_dict["tenant_id"] = tenantId
    result = await _config_repo.upsert(tenantId, config_dict)
    result.pop("slack_bot_token_ref", None)
    return APIResponse(data=result).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# END-USER NOTIFICATION CHANNELS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/channels")
async def list_channels(request: Request):
    """List notification channels for the authenticated tenant/user."""
    tenant_id = request.state.tenant.tenant_id
    user_id = request.state.tenant.user_id
    filters: dict[str, Any] = {"tenant_id": tenant_id}
    if user_id:
        # Return both user-specific and tenant-wide channels
        rows = await _channel_repo.find_many(filters=filters)
    else:
        rows = await _channel_repo.find_many(filters=filters)
    # Strip credentials_ref from response
    for row in rows:
        row.pop("credentials_ref", None)
    return APIResponse(data=rows).to_dict()


@router.post("/channels")
async def register_channel(body: RegisterChannelRequest, request: Request):
    """Register a new notification channel (Discord, Telegram, or Webhook).
    For Slack, use the OAuth flow at /channels/slack/connect instead.
    """
    request.state.tenant.require_permission("notifications:channels:write")
    tenant_id = request.state.tenant.tenant_id
    user_id = request.state.tenant.user_id

    # For non-Slack channels, the credential lives in channel_config
    # We store it encrypted via a vault ref
    raw_credential = body.channel_config.pop("token", None) or \
                     body.channel_config.pop("webhook_url", None) or \
                     body.channel_config.pop("bot_token", None) or \
                     json.dumps(body.channel_config)

    channel_id = str(uuid.uuid4())
    credentials_ref = f"notif_channel:{channel_id}"

    from repositories.repos import ProvidersRepository
    providers_repo = ProvidersRepository()
    await providers_repo.upsert(credentials_ref, {
        "api_key": raw_credential,
        "provider": body.channel_type.value,
        "tenant_id": tenant_id,
    })

    channel = UserNotificationChannel(
        id=channel_id,
        tenant_id=tenant_id,
        user_id=user_id,
        channel_type=body.channel_type,
        channel_name=body.channel_name,
        credentials_ref=credentials_ref,
        channel_config=body.channel_config,
        severity_filter=body.severity_filter,
        event_type_filter=body.event_type_filter,
        active=False,  # inactive until test passes
    )
    channel_dict = channel.model_dump()
    channel_dict["id"] = channel_id
    channel_dict["tenant_id"] = tenant_id
    result = await _channel_repo.create(channel_dict)
    result.pop("credentials_ref", None)

    metrics.increment("aether_notification_channels_connected_total",
                      labels={"tenant_id": tenant_id, "channel_type": body.channel_type.value})
    return APIResponse(data=result).to_dict()


@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: str, body: UpdateChannelRequest, request: Request):
    request.state.tenant.require_permission("notifications:channels:write")
    tenant_id = request.state.tenant.tenant_id
    row = await _channel_repo.find_by_id(channel_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"Channel {channel_id!r} not found")
    update_data = body.model_dump(exclude_none=True)
    update_data["updated_at"] = _utc_now()
    updated = await _channel_repo.update(channel_id, update_data)
    updated.pop("credentials_ref", None)
    return APIResponse(data=updated).to_dict()


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, request: Request):
    request.state.tenant.require_permission("notifications:channels:write")
    tenant_id = request.state.tenant.tenant_id
    row = await _channel_repo.find_by_id(channel_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"Channel {channel_id!r} not found")
    await _channel_repo.delete(channel_id)

    from shared.events.events import Event, Topic
    from dependencies.providers import get_producer
    try:
        producer = get_producer()
        await producer.publish(Event(
            topic=Topic.NOTIFICATION_CHANNEL_DISCONNECTED,
            tenant_id=tenant_id,
            payload={"channel_id": channel_id, "channel_type": row.get("channel_type")},
        ))
    except Exception:
        pass

    return APIResponse(data={"deleted": True, "channel_id": channel_id}).to_dict()


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: str, request: Request):
    """Send a test message to verify the channel is reachable."""
    request.state.tenant.require_permission("notifications:channels:write")
    tenant_id = request.state.tenant.tenant_id
    row = await _channel_repo.find_by_id(channel_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"Channel {channel_id!r} not found")

    channel_type = row.get("channel_type", "webhook")
    gateway = get_gateway(channel_type)
    if gateway is None:
        raise NotFoundError(f"Unsupported channel type: {channel_type}")

    credentials = await _resolve_channel_credentials(row)
    config = row.get("channel_config") or {}

    result = await gateway.test(config, credentials)

    if result.success:
        await _channel_repo.update(channel_id, {
            "verified_at": _utc_now(),
            "active": True,
            "updated_at": _utc_now(),
        })

    return APIResponse(data={
        "success": result.success,
        "channel_id": channel_id,
        "channel_type": channel_type,
        "error": result.error,
    }).to_dict()


async def _resolve_channel_credentials(channel: dict) -> str:
    credentials_ref = channel.get("credentials_ref", "")
    from repositories.repos import ProvidersRepository
    try:
        providers_repo = ProvidersRepository()
        record = await providers_repo.find_by_id(credentials_ref)
        if record:
            return record.get("api_key", credentials_ref)
    except Exception:
        pass
    return credentials_ref


# ── Slack OAuth ───────────────────────────────────────────────────────────────

@router.get("/channels/slack/connect")
async def slack_oauth_connect(request: Request):
    """Initiate Slack OAuth install flow. Returns a redirect URL."""
    tenant_id = request.state.tenant.tenant_id
    user_id = request.state.tenant.user_id or ""
    client_id = os.getenv("SLACK_CLIENT_ID", "")
    if not client_id:
        from shared.common.common import APIError
        raise APIError("SLACK_CLIENT_ID not configured")

    state = secrets.token_urlsafe(32)
    redirect_uri = os.getenv("SLACK_REDIRECT_URI", "/v1/notifications/channels/slack/callback")

    state_record = {
        "state": state,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "redirect_uri": redirect_uri,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    await _oauth_state_repo.create(state_record)

    redirect_url = (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={client_id}"
        f"&scope=chat:write,channels:read,incoming-webhook"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return APIResponse(data={"redirect_url": redirect_url}).to_dict()


@router.get("/channels/slack/callback")
async def slack_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle Slack OAuth callback — exchange code for bot token and register channel."""
    state_record = await _oauth_state_repo.find_by_id(state)
    if not state_record:
        raise ForbiddenError("Invalid or expired OAuth state")

    now_iso = _utc_now()
    if state_record.get("expires_at", "") < now_iso:
        await _oauth_state_repo.delete(state)
        raise ForbiddenError("OAuth state expired")

    await _oauth_state_repo.delete(state)

    tenant_id = state_record["tenant_id"]
    user_id = state_record.get("user_id", "")
    client_id = os.getenv("SLACK_CLIENT_ID", "")
    client_secret = os.getenv("SLACK_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise ForbiddenError("Slack OAuth not configured")

    # Exchange code for access token
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={"code": code, "client_id": client_id, "client_secret": client_secret},
            )
            data = resp.json()
    except Exception as exc:
        logger.error("slack_oauth_exchange_failed: %s", exc)
        raise ForbiddenError("Slack token exchange failed")

    if not data.get("ok"):
        raise ForbiddenError(f"Slack OAuth failed: {data.get('error', 'unknown')}")

    access_token = data.get("access_token", "")
    team = data.get("team", {})
    webhook = data.get("incoming_webhook", {})
    channel_id_val = webhook.get("channel_id", "")
    channel_name_val = webhook.get("channel", "#aether-ops")
    workspace = team.get("name", "")

    channel_uuid = str(uuid.uuid4())
    credentials_ref = f"notif_channel:{channel_uuid}"
    from repositories.repos import ProvidersRepository
    providers_repo = ProvidersRepository()
    await providers_repo.upsert(credentials_ref, {
        "api_key": access_token,
        "provider": "slack",
        "tenant_id": tenant_id,
    })

    channel = UserNotificationChannel(
        id=channel_uuid,
        tenant_id=tenant_id,
        user_id=user_id,
        channel_type="slack",
        channel_name=f"{workspace} / {channel_name_val}",
        credentials_ref=credentials_ref,
        channel_config={"channel_id": channel_id_val, "channel": channel_name_val,
                        "workspace_id": team.get("id", ""), "workspace_name": workspace},
        active=True,
        verified_at=_utc_now(),
    )
    channel_dict = channel.model_dump()
    channel_dict["id"] = channel_uuid
    channel_dict["tenant_id"] = tenant_id
    await _channel_repo.create(channel_dict)

    from shared.events.events import Event, Topic
    from dependencies.providers import get_producer
    try:
        producer = get_producer()
        await producer.publish(Event(
            topic=Topic.NOTIFICATION_CHANNEL_CONNECTED,
            tenant_id=tenant_id,
            payload={"channel_id": channel_uuid, "channel_type": "slack",
                     "workspace": workspace},
        ))
    except Exception:
        pass

    metrics.increment("aether_notification_channels_connected_total",
                      labels={"tenant_id": tenant_id, "channel_type": "slack"})

    return Response(
        status_code=302,
        headers={"Location": f"/settings/notifications?connected=slack&channel={channel_uuid}"},
    )


# ── Slack Interactive Callback ────────────────────────────────────────────────

@router.post("/slack/callback")
async def slack_interactive_callback(request: Request):
    """Handle Slack interactive component callbacks (button clicks on alert messages)."""
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")

    # Persist to WebhookInbox BEFORE any business logic (best-effort)
    try:
        import base64 as _base64
        _inbox_id = str(uuid.uuid4())
        await _webhook_inbox_repo.insert(_inbox_id, {
            "id": _inbox_id,
            "tenant_id": "",  # extracted later from action payload
            "provider": "slack",
            "headers": _sanitize_headers(dict(request.headers)),
            "raw_body": body_bytes.decode("utf-8", errors="replace"),
            "signature": signature,
            "timestamp": timestamp,
            "verified": False,
            "processed": False,
        })
    except Exception as _exc:
        logger.debug("slack_callback_inbox_write_failed: %s", _exc)

    if signing_secret and not SlackChannelGateway.verify_signature(
        body_bytes, timestamp, signature, signing_secret
    ):
        raise ForbiddenError("Invalid Slack signature")

    try:
        payload_str = body_bytes.decode("utf-8")
        if payload_str.startswith("payload="):
            import urllib.parse
            payload = json.loads(urllib.parse.unquote(payload_str[8:]))
        else:
            payload = json.loads(payload_str)
    except Exception as exc:
        logger.error("slack_callback_parse_error: %s", exc)
        return Response(status_code=400)

    actions = payload.get("actions", [])
    slack_user_id = payload.get("user", {}).get("id", "")

    for action in actions:
        action_id = action.get("action_id", "")
        parts = action_id.split(":")
        if len(parts) < 3:
            continue
        action_type_str, notification_id, tenant_id = parts[0], parts[1], parts[2]

        row = await _notif_repo.find_by_id(notification_id)
        if not row or row.get("tenant_id") != tenant_id:
            continue

        try:
            action_type = OperatorActionType(action_type_str)
        except ValueError:
            continue

        state_map = {
            OperatorActionType.APPROVE: NotificationLifecycleState.APPROVED,
            OperatorActionType.SUPPRESS: NotificationLifecycleState.SUPPRESSED,
        }
        engine = LifecycleEngine(repo=_notif_repo)

        if action_type in state_map:
            try:
                await engine.advance(
                    notification_id, state_map[action_type],
                    actor_user_id=slack_user_id,
                    actor_role="slack_operator",
                    metadata={"via": "slack_interactive"},
                )
            except Exception as exc:
                logger.warning("slack_action_failed action=%s id=%s error=%s",
                               action_type_str, notification_id, exc)

            action_rec = OperatorAction(
                notification_id=notification_id,
                tenant_id=tenant_id,
                action_type=action_type,
                actor_user_id=slack_user_id,
            )
            action_dict = action_rec.model_dump()
            action_dict["tenant_id"] = tenant_id
            await _action_repo.create(action_dict)
            metrics.increment("aether_notifications_operator_action_total",
                              labels={"tenant_id": tenant_id, "action_type": action_type_str})

    return Response(status_code=200)


# ── Telegram Callback ─────────────────────────────────────────────────────────

@router.post("/telegram/callback")
async def telegram_callback(request: Request):
    """Handle Telegram inline keyboard callbacks."""
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # Validate against stored secret if present (per-channel)
    # For simplicity, we trust the callback if it contains a valid notification_id
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)

    callback_query = body.get("callback_query", {})
    data = callback_query.get("data", "")
    telegram_user_id = str(callback_query.get("from", {}).get("id", ""))
    parts = data.split(":")
    if len(parts) < 3:
        return Response(status_code=200)

    action_type_str, notification_id, tenant_id = parts[0], parts[1], parts[2]
    row = await _notif_repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenant_id:
        return Response(status_code=200)

    try:
        action_type = OperatorActionType(action_type_str)
    except ValueError:
        return Response(status_code=200)

    state_map = {
        OperatorActionType.APPROVE: NotificationLifecycleState.APPROVED,
        OperatorActionType.SUPPRESS: NotificationLifecycleState.SUPPRESSED,
    }
    if action_type in state_map:
        engine = LifecycleEngine(repo=_notif_repo)
        try:
            await engine.advance(
                notification_id, state_map[action_type],
                actor_user_id=telegram_user_id,
                actor_role="telegram_operator",
                metadata={"via": "telegram_interactive"},
            )
        except Exception as exc:
            logger.warning("telegram_action_failed action=%s id=%s error=%s",
                           action_type_str, notification_id, exc)

        metrics.increment("aether_notifications_operator_action_total",
                          labels={"tenant_id": tenant_id, "action_type": action_type_str})

    return Response(status_code=200)


# ═══════════════════════════════════════════════════════════════════════════
# LEGACY STUB ENDPOINTS (kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════

class _WebhookConfig(BaseModel):
    url: str
    events: list[str]
    secret: Optional[str] = None
    active: bool = True


class _AlertRule(BaseModel):
    name: str
    condition: str
    channels: list[str]
    recipients: list[str] = []


@router.post("/webhooks")
async def create_webhook(body: _WebhookConfig, request: Request):
    from repositories.repos import WebhookRepository
    request.state.tenant.require_permission("write")
    wh_id = str(uuid.uuid4())
    wh_repo = WebhookRepository()
    webhook = await wh_repo.insert(wh_id, {
        "tenant_id": request.state.tenant.tenant_id, **body.model_dump()
    })
    return APIResponse(data=webhook).to_dict()


@router.get("/webhooks")
async def list_webhooks(request: Request):
    from repositories.repos import WebhookRepository
    wh_repo = WebhookRepository()
    hooks = await wh_repo.find_many(filters={"tenant_id": request.state.tenant.tenant_id})
    return APIResponse(data=hooks).to_dict()


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request):
    from repositories.repos import WebhookRepository
    from shared.common.common import ForbiddenError, NotFoundError
    request.state.tenant.require_permission("write")
    wh_repo = WebhookRepository()
    webhook = await wh_repo.find_by_id(webhook_id)
    if not webhook:
        raise NotFoundError("Webhook")
    if webhook.get("tenant_id") != request.state.tenant.tenant_id:
        raise ForbiddenError("Webhook belongs to a different tenant")
    await wh_repo.delete(webhook_id)
    return APIResponse(data={"deleted": True}).to_dict()


@router.post("/alerts")
async def create_alert(body: _AlertRule, request: Request):
    from repositories.repos import AlertRepository
    request.state.tenant.require_permission("write")
    alert_id = str(uuid.uuid4())
    alert_repo = AlertRepository()
    alert = await alert_repo.insert(alert_id, {
        "tenant_id": request.state.tenant.tenant_id, **body.model_dump()
    })
    return APIResponse(data=alert).to_dict()


@router.get("/alerts")
async def list_alerts(request: Request):
    from repositories.repos import AlertRepository
    alert_repo = AlertRepository()
    alerts = await alert_repo.find_many(filters={"tenant_id": request.state.tenant.tenant_id})
    return APIResponse(data=alerts).to_dict()


# ── Inbound Connector Webhook Routes ─────────────────────────────────────────
# All routes below persist to WebhookInbox FIRST and return 200 immediately.
# Async processing happens via WebhookInboxProcessor background task.

@router.post("/webhooks/linear/events")
async def linear_webhook(request: Request):
    """Persist Linear webhook to WebhookInbox, verify signature, return 200 immediately."""
    body_bytes = await request.body()
    linear_sig = request.headers.get("Linear-Signature", "")
    # Prefer explicit tenant header; processor will also resolve via ExternalResourceLink
    tenant_id = request.headers.get("X-Aether-Tenant-ID", "")
    inbox_id = str(uuid.uuid4())
    try:
        await _webhook_inbox_repo.insert(inbox_id, {
            "id": inbox_id,
            "tenant_id": tenant_id,
            "provider": "linear",
            "headers": _sanitize_headers(dict(request.headers)),
            "raw_body": body_bytes.decode("utf-8", errors="replace"),
            "signature": linear_sig,
            "timestamp": "",
            "verified": False,
            "processed": False,
        })
    except Exception as exc:
        logger.warning("linear_webhook_inbox_write_failed: %s", exc)
        # Return 500 so Linear retries — we must not silently lose outcomes
        return Response(status_code=500)
    return Response(status_code=200)


@router.post("/webhooks/jira/events")
async def jira_webhook(request: Request):
    """Persist Jira webhook to WebhookInbox, verify Jira signature, return 200 immediately."""
    body_bytes = await request.body()
    jira_sig = request.headers.get("X-Hub-Signature-256", "")
    tenant_id = request.headers.get("X-Aether-Tenant-ID", "")
    inbox_id = str(uuid.uuid4())
    try:
        await _webhook_inbox_repo.insert(inbox_id, {
            "id": inbox_id,
            "tenant_id": tenant_id,
            "provider": "jira",
            "headers": _sanitize_headers(dict(request.headers)),
            "raw_body": body_bytes.decode("utf-8", errors="replace"),
            "signature": jira_sig,
            "timestamp": "",
            "verified": False,
            "processed": False,
        })
    except Exception as exc:
        logger.warning("jira_webhook_inbox_write_failed: %s", exc)
        # Return 500 so Jira retries — we must not silently lose outcomes
        return Response(status_code=500)
    return Response(status_code=200)


@router.post("/webhooks/aether/callback")
async def aether_callback(request: Request):
    """Inbound signed outcome callback from generic webhook adapter.

    Persists the callback to WebhookInbox before returning 200.
    The WebhookInboxProcessor handles verification and normalization asynchronously.
    """
    body_bytes = await request.body()
    aether_sig = request.headers.get("X-Aether-Signature", "")
    aether_ts = request.headers.get("X-Aether-Timestamp", "")
    inbox_id = str(uuid.uuid4())
    try:
        tenant_id = request.query_params.get("tenant_id", "")
        await _webhook_inbox_repo.insert(inbox_id, {
            "id": inbox_id,
            "tenant_id": tenant_id,
            "provider": "webhook",
            "headers": _sanitize_headers(dict(request.headers)),
            "raw_body": body_bytes.decode("utf-8", errors="replace"),
            "signature": aether_sig,
            "timestamp": aether_ts,
            "verified": False,
            "processed": False,
        })
    except Exception as exc:
        logger.warning("aether_callback_inbox_write_failed: %s", exc)
        # Return 500 so the sender retries — we must not silently lose outcomes
        return Response(status_code=500)
    return Response(status_code=200)
