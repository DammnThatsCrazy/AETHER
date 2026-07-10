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
fresh long-running coroutine, same shape as services/jobs factories.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Coroutine, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from shared.outbox import GenericOutboxWorker, STATUS_DELIVERED, STATUS_QUEUED
from services.notification_intelligence.inbox import publish_notification_event

logger = get_logger("aether.notification.delivery_outbox")

OUTBOX_WORKER_NAME = "notification_delivery_outbox"
MAX_DELIVERY_ATTEMPTS = 5
BACKOFF_BASE_S = 5.0
POLL_INTERVAL_S = 5.0


class NotificationDeliveryOutboxRepository(BaseRepository):
    """Durable external-delivery outbox rows (table: notification_delivery_outbox)."""

    def __init__(self) -> None:
        super().__init__("notification_delivery_outbox")


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
    from services.notification_intelligence.delivery_router import DeliveryRouter

    tenant_id = str(row.get("tenant_id", ""))
    channel_spec = str(row.get("channel", ""))
    notification = row.get("notification") or {}
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
