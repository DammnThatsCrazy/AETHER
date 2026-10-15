"""Notification Intelligence — Durable External Delivery Outbox.

``queue_external_delivery`` writes one durable ``notification_delivery_outbox``
row per requested channel (BaseRepository-shape table created by
alembic/versions/20260713_platform_control_plane.py). The generic outbox
worker (shared/outbox.py) drains rows through ``deliver_outbox_row``, which
dispatches via the EXISTING per-channel delivery path —
DeliveryRouter._deliver_one → vault credential resolution → channel gateway.
No second delivery implementation exists here.

Row lifecycle: queued → processing → delivered, or failed (backoff retry)
→ dead_lettered after MAX_DELIVERY_ATTEMPTS.

Supervisor wiring (orchestrator-owned; this module never touches main.py):
``build_notification_outbox_worker()`` is a zero-arg factory returning a
fresh long-running coroutine, same shape as services/api/workers/jobs factories.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace
from typing import Any, Coroutine, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from shared.outbox import GenericOutboxWorker, STATUS_DELIVERED, STATUS_QUEUED
from journeys.notification_intelligence.inbox import publish_notification_event

logger = get_logger("aether.notification.delivery_outbox")

OUTBOX_WORKER_NAME = "notification_delivery_outbox"
MAX_DELIVERY_ATTEMPTS = 5
BACKOFF_BASE_S = 5.0
POLL_INTERVAL_S = 5.0
ACCESS_INTERACTION_EVENT_TYPES = frozenset({
    "access.interaction.completed",
    "access.interaction.blocked",
    "access.interaction.failed",
})


class NotificationDeliveryOutboxRepository(BaseRepository):
    """Durable external-delivery outbox rows (table: notification_delivery_outbox)."""

    def __init__(self) -> None:
        super().__init__("notification_delivery_outbox")

    async def insert_once(self, record_id: str, data: dict[str, Any]) -> tuple[dict, bool]:
        """Insert an event row once, preserving terminal state across request retries."""
        now = utc_now().isoformat()
        data = {**data, "id": record_id, "created_at": now, "updated_at": now}
        pool = await self._ensure_pool()
        if pool is None:
            existing = self._store.get(record_id)
            if existing:
                return existing, False
            self._store[record_id] = data
            return data, True
        await self._ensure_table()
        row = await pool.fetchrow(
            f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING RETURNING data""",
            record_id, json.dumps(data, default=str), data.get("tenant_id", ""),
        )
        if row:
            return self._decode_row(row), True
        existing = await pool.fetchrow(
            f"SELECT data FROM {self.table_name} WHERE id = $1", record_id,
        )
        if not existing:
            raise RuntimeError("notification outbox row disappeared after idempotent insert")
        return self._decode_row(existing), False

    @staticmethod
    def _decode_row(row: Any) -> dict[str, Any]:
        data = row["data"]
        return json.loads(data) if isinstance(data, str) else dict(data)


_repo: Optional[NotificationDeliveryOutboxRepository] = None


def get_delivery_outbox_repository() -> NotificationDeliveryOutboxRepository:
    """Lazy module-level repository singleton."""
    global _repo
    if _repo is None:
        _repo = NotificationDeliveryOutboxRepository()
    return _repo


# ── enqueue ──────────────────────────────────────────────────────────────────

async def queue_external_delivery(
    tenant_id: str,
    *,
    channels: list[str],
    notification: dict,
    correlation_id: Optional[str] = None,
) -> list[dict]:
    """Queue durable external delivery of a notification, one outbox row per
    channel. ``channels`` entries are registered UserNotificationChannel ids
    or channel types ("slack", "discord", "telegram", "webhook").

    Returns the persisted rows (status queued, attempts 0). Actual dispatch
    happens asynchronously in the outbox worker.
    """
    repo = get_delivery_outbox_repository()
    rows: list[dict] = []
    for channel in channels:
        row_id = str(uuid.uuid4())
        row = {
            "id": row_id,
            "tenant_id": tenant_id,
            "channel": str(channel),
            "notification": dict(notification),
            "correlation_id": correlation_id,
            "status": STATUS_QUEUED,
            "attempts": 0,
            "created_at": utc_now().isoformat(),
        }
        rows.append(await repo.insert(row_id, row))
        metrics.increment(
            "aether_notification_delivery_outbox_queued_total",
            labels={"tenant_id": tenant_id, "channel": str(channel)},
        )
    if rows:
        await publish_notification_event(
            "NOTIFICATION_DELIVERY_QUEUED",
            tenant_id,
            {
                "channels": [str(c) for c in channels],
                "count": len(rows),
                "correlation_id": correlation_id or "",
            },
        )
    return rows


async def queue_access_interaction_event(tenant_id: str, event: dict[str, Any]) -> list[dict]:
    """Queue a minimized Access Kit interaction to subscribed customer hooks."""
    from repositories.repos import WebhookRepository

    event_type = str(event.get("type", ""))
    event_id = str(event.get("id", ""))
    if event_type not in ACCESS_INTERACTION_EVENT_TYPES or not event_id:
        raise ValueError("unsupported or unidentified Access Kit webhook event")

    hooks = await WebhookRepository().find_many(
        filters={"tenant_id": tenant_id}, limit=200,
    )
    repo = get_delivery_outbox_repository()
    rows: list[dict] = []
    for hook in hooks:
        webhook_id = str(hook.get("id", ""))
        if not webhook_id or not hook.get("active"):
            continue
        if event_type not in (hook.get("events") or []):
            continue
        row_id = "access_" + hashlib.sha256(
            f"{tenant_id}:{webhook_id}:{event_id}".encode("utf-8")
        ).hexdigest()
        row = {
            "id": row_id,
            "tenant_id": tenant_id,
            "channel": f"customer_webhook:{webhook_id}",
            "notification": dict(event),
            "correlation_id": event_id,
            "status": STATUS_QUEUED,
            "attempts": 0,
            "created_at": utc_now().isoformat(),
        }
        saved, created = await repo.insert_once(row_id, row)
        if created:
            rows.append(saved)

    if rows:
        metrics.increment(
            "aether_notification_delivery_outbox_queued_total",
            labels={"tenant_id": tenant_id, "channel": "customer_webhook"},
        )
        await publish_notification_event(
            "NOTIFICATION_DELIVERY_QUEUED", tenant_id,
            {"channels": [row["channel"] for row in rows], "count": len(rows), "correlation_id": event_id},
        )
    return rows


# ── sink ─────────────────────────────────────────────────────────────────────

async def _resolve_channel(
    channel_repo: Any, tenant_id: str, channel_spec: str
) -> Optional[dict]:
    """Match an outbox row's channel spec against the tenant's registered
    active channels: by channel id first, then by channel_type."""
    channels = await channel_repo.list_for_tenant(
        tenant_id, active_only=False, limit=200
    )
    active = [ch for ch in channels if ch.get("active")]
    for ch in active:
        if ch.get("id") == channel_spec:
            return ch
    for ch in active:
        if ch.get("channel_type") == channel_spec:
            return ch
    return None


async def deliver_outbox_row(row: dict) -> None:
    """Outbox sink: dispatch one row through the existing delivery path.

    Uses DeliveryRouter._deliver_one — the same per-channel code the
    notification consumer path relies on (vault credential resolution via
    ProvidersRepository + channel gateway dispatch). Raises on failure so
    the generic worker applies retry/backoff/dead-letter; per-attempt
    delivery detail is recorded on the row and persisted with the mark.
    """
    from repositories.repos import ProvidersRepository, UserNotificationChannelRepository
    from journeys.notification_intelligence.delivery_router import DeliveryRouter

    tenant_id = str(row.get("tenant_id", ""))
    channel_spec = str(row.get("channel", ""))
    notification = row.get("notification") or {}

    if channel_spec.startswith("customer_webhook:"):
        await _deliver_customer_webhook_row(row, tenant_id, channel_spec, notification)
        return

    notif_view = SimpleNamespace(**{str(k): v for k, v in dict(notification).items()})

    channel_repo = UserNotificationChannelRepository()
    channel = await _resolve_channel(channel_repo, tenant_id, channel_spec)
    if channel is None:
        row["delivery"] = {
            "channel": channel_spec,
            "success": False,
            "error": "no matching active channel",
            "attempted_at": utc_now().isoformat(),
        }
        raise RuntimeError(
            f"no active channel matching {channel_spec!r} for tenant {tenant_id!r}"
        )

    router = DeliveryRouter(
        channel_repo=channel_repo, providers_repo=ProvidersRepository()
    )
    result = await router._deliver_one(notif_view, channel)

    row["delivery"] = {
        "channel": channel_spec,
        "channel_id": channel.get("id"),
        "channel_type": result.channel_type,
        "success": result.success,
        "message_ref": result.message_ref,
        "error": result.error,
        "latency_ms": result.latency_ms,
        "attempted_at": utc_now().isoformat(),
    }

    if not result.success:
        await publish_notification_event(
            "NOTIFICATION_DELIVERY_FAILED",
            tenant_id,
            {
                "outbox_id": row.get("id", ""),
                "channel": channel_spec,
                "error": result.error or "",
                "correlation_id": row.get("correlation_id") or "",
            },
        )
        raise RuntimeError(
            result.error or f"delivery failed on channel {channel_spec!r}"
        )

    await publish_notification_event(
        "NOTIFICATION_DELIVERED",
        tenant_id,
        {
            "outbox_id": row.get("id", ""),
            "channel": channel_spec,
            "message_ref": result.message_ref or "",
            "correlation_id": row.get("correlation_id") or "",
        },
    )


async def _deliver_customer_webhook_row(
    row: dict, tenant_id: str, channel_spec: str, event: dict[str, Any],
) -> None:
    from repositories.repos import ProvidersRepository, WebhookRepository
    from journeys.notification_intelligence.customer_webhook_delivery import (
        CustomerWebhookDeliveryService,
        CustomerWebhookSecretStore,
    )

    webhook_id = channel_spec.removeprefix("customer_webhook:")
    webhook = await WebhookRepository().find_by_id(webhook_id)
    if not webhook or webhook.get("tenant_id") != tenant_id or not webhook.get("active"):
        row["delivery"] = {"success": False, "error": "no matching active customer webhook"}
        raise RuntimeError("no active customer webhook matches the outbox row")
    event_type = str(event.get("type", ""))
    if event_type not in ACCESS_INTERACTION_EVENT_TYPES or event_type not in (webhook.get("events") or []):
        row["delivery"] = {"success": False, "error": "event is not subscribed"}
        raise RuntimeError("customer webhook is not subscribed to this event")

    secret_ref = webhook.get("secret_ref")
    if not isinstance(secret_ref, str) or not secret_ref:
        row["delivery"] = {"success": False, "error": "signing secret unavailable"}
        raise RuntimeError("customer webhook signing secret unavailable")
    secret_store = CustomerWebhookSecretStore(ProvidersRepository())
    secret = await secret_store.resolve(tenant_id, secret_ref)
    webhook_id = str(webhook.get("id") or webhook_id)
    outcome = await CustomerWebhookDeliveryService().deliver(
        tenant_id=tenant_id,
        webhook_id=webhook_id,
        url=str(webhook.get("url", "")),
        payload=dict(event),
        secret=secret,
        event_id=str(event.get("id", row.get("correlation_id", ""))),
        kind="production",
    )
    row["delivery"] = {
        "channel": channel_spec,
        "success": outcome.success,
        "status": outcome.status,
        "status_code": outcome.status_code,
        "attempts": outcome.attempts,
        "latency_ms": outcome.latency_ms,
        "attempt_id": outcome.attempt_id,
        "error": outcome.error,
        "attempted_at": utc_now().isoformat(),
    }
    if not outcome.success:
        await publish_notification_event(
            "NOTIFICATION_DELIVERY_FAILED", tenant_id,
            {"outbox_id": row.get("id", ""), "channel": channel_spec,
             "error": outcome.error or outcome.status,
             "correlation_id": row.get("correlation_id") or ""},
        )
        raise RuntimeError(outcome.error or f"customer webhook delivery {outcome.status}")
    await publish_notification_event(
        "NOTIFICATION_DELIVERED", tenant_id,
        {"outbox_id": row.get("id", ""), "channel": channel_spec,
         "attempt_id": outcome.attempt_id or "",
         "correlation_id": row.get("correlation_id") or ""},
    )


# ── supervisor factory ───────────────────────────────────────────────────────

def build_notification_outbox_worker() -> Coroutine[Any, Any, None]:
    """Zero-arg supervisor factory: a fresh long-running notification
    delivery outbox worker coroutine. The orchestrator wires this into the
    runtime supervisor — do not start it from this module."""
    worker = GenericOutboxWorker(
        repo=get_delivery_outbox_repository(),
        sink=deliver_outbox_row,
        name=OUTBOX_WORKER_NAME,
        max_attempts=MAX_DELIVERY_ATTEMPTS,
        backoff_base_s=BACKOFF_BASE_S,
        poll_interval_s=POLL_INTERVAL_S,
        success_status=STATUS_DELIVERED,
    )
    return worker.run_forever()
