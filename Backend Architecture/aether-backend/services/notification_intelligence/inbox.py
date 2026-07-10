"""Notification Intelligence — Tenant In-App Notification Inbox.

Persists tenant-facing in-app notifications in the ``notification_inbox``
BaseRepository-shape table (created by
alembic/versions/20260713_platform_control_plane.py; auto-created at runtime
by BaseRepository._ensure_table in exact parity).

``create_inbox_notification`` is the stable module-level entry point that
other services lazily import — keep its signature backward compatible.

Dedupe contract: a create carrying a ``dedupe_key`` that matches an UNREAD,
non-archived row for the same tenant created within the last 24 hours
increments that row's ``count`` instead of inserting a new row.

Event publishing is best-effort and defensive: topics are resolved with
``getattr(Topic, name, None)`` (topics may be added concurrently) and any
publish failure is swallowed — the inbox write is the source of truth.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics
from services.notification_intelligence.models import NotificationSeverity

logger = get_logger("aether.notification.inbox")

DEDUPE_WINDOW_HOURS = 24

# Bounded scan window for Python-side read/archived filtering. Boolean JSONB
# fields can't be pushed into BaseRepository.find_many filters portably
# (str(True) != jsonb 'true' on the Postgres backend), so list/count fetch a
# bounded window and filter in Python.
_SCAN_LIMIT = 1000


class NotificationInboxRepository(BaseRepository):
    """Tenant-scoped in-app inbox rows (table: notification_inbox)."""

    def __init__(self) -> None:
        super().__init__("notification_inbox")


_repo: Optional[NotificationInboxRepository] = None


def get_inbox_repository() -> NotificationInboxRepository:
    """Lazy module-level repository singleton."""
    global _repo
    if _repo is None:
        _repo = NotificationInboxRepository()
    return _repo


# ── helpers ──────────────────────────────────────────────────────────────────

def _coerce_severity(severity: Any) -> str:
    """Normalise to a NotificationSeverity value; unknown values degrade to
    'info' (with a warning) so producer bugs never lose a notification."""
    value = severity.value if hasattr(severity, "value") else str(severity)
    try:
        return NotificationSeverity(value).value
    except ValueError:
        logger.warning("unknown inbox severity %r — defaulting to 'info'", value)
        return NotificationSeverity.INFO.value


def _coerce_category(category: Any) -> str:
    """Categories align with NotificationClass values for delivery-facing
    notifications but are intentionally open (platform surfaces emit
    categories like 'jobs' or 'billing'). Coerce enums to their value."""
    return category.value if hasattr(category, "value") else str(category)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def publish_notification_event(
    topic_attr: str, tenant_id: str, payload: dict[str, Any]
) -> None:
    """Best-effort publish. Resolves the Topic defensively (it may not exist
    yet while topics land concurrently) and never raises."""
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_attr, None)
        if topic is None:
            return
        from dependencies.providers import get_producer

        producer = get_producer()
        await producer.publish(
            Event(topic=topic, tenant_id=tenant_id, payload=payload)
        )
    except Exception as exc:
        logger.debug(
            "notification event publish skipped topic=%s error=%s", topic_attr, exc
        )


async def _find_dedupe_target(
    repo: NotificationInboxRepository,
    tenant_id: str,
    dedupe_key: str,
    now: datetime,
) -> Optional[dict]:
    """Unread, non-archived row for (tenant, dedupe_key) created within the
    dedupe window — or None."""
    candidates = await repo.find_many(
        filters={"tenant_id": tenant_id, "dedupe_key": dedupe_key}, limit=50
    )
    window_start = now - timedelta(hours=DEDUPE_WINDOW_HOURS)
    for row in candidates:
        if row.get("read") or row.get("archived"):
            continue
        created = _parse_ts(row.get("created_at"))
        if created is not None and created >= window_start:
            return row
    return None


# ── public API ───────────────────────────────────────────────────────────────

async def create_inbox_notification(
    tenant_id: str,
    *,
    category: Any,
    severity: Any,
    title: str,
    body: str,
    link: Optional[str] = None,
    correlation_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
) -> dict:
    """Create (or dedupe-increment) a tenant in-app inbox notification.

    Returns the persisted row dict. Stable entry point — other services
    lazily import this function.
    """
    repo = get_inbox_repository()
    now = utc_now()

    if dedupe_key:
        existing = await _find_dedupe_target(repo, tenant_id, dedupe_key, now)
        if existing is not None:
            existing["count"] = int(existing.get("count", 1) or 1) + 1
            existing["last_seen_at"] = now.isoformat()
            updated = await repo.update(existing["id"], existing)
            metrics.increment(
                "aether_notification_inbox_total",
                labels={"tenant_id": tenant_id, "outcome": "deduplicated"},
            )
            return updated

    notification_id = str(uuid.uuid4())
    row = {
        "id": notification_id,
        "tenant_id": tenant_id,
        "category": _coerce_category(category),
        "severity": _coerce_severity(severity),
        "title": title,
        "body": body,
        "link": link,
        "correlation_id": correlation_id,
        "dedupe_key": dedupe_key,
        "read": False,
        "read_at": None,
        "archived": False,
        "count": 1,
        "created_at": now.isoformat(),
    }
    created = await repo.insert(notification_id, row)
    metrics.increment(
        "aether_notification_inbox_total",
        labels={"tenant_id": tenant_id, "outcome": "created"},
    )
    await publish_notification_event(
        "NOTIFICATION_CREATED",
        tenant_id,
        {
            "notification_id": notification_id,
            "category": row["category"],
            "severity": row["severity"],
            "title": title,
            "correlation_id": correlation_id or "",
        },
    )
    return created


async def list_inbox_notifications(
    tenant_id: str,
    *,
    unread_only: bool = False,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Newest-first inbox listing for a tenant with unread filtering and
    offset/limit pagination (applied after read/archived filtering)."""
    repo = get_inbox_repository()
    rows = await repo.find_many(
        filters={"tenant_id": tenant_id},
        limit=_SCAN_LIMIT,
        sort_by="created_at",
        sort_order="desc",
    )
    filtered = [
        r for r in rows
        if (include_archived or not r.get("archived"))
        and (not unread_only or not r.get("read"))
    ]
    return filtered[offset: offset + limit]


async def unread_notification_count(tenant_id: str) -> int:
    """Count of unread, non-archived inbox rows for a tenant."""
    repo = get_inbox_repository()
    rows = await repo.find_many(filters={"tenant_id": tenant_id}, limit=_SCAN_LIMIT)
    return sum(1 for r in rows if not r.get("read") and not r.get("archived"))


async def mark_notification_read(tenant_id: str, notification_id: str) -> dict:
    """Mark one notification read (tenant-scoped). Idempotent."""
    repo = get_inbox_repository()
    row = await repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"Inbox notification {notification_id!r} not found")
    if not row.get("read"):
        row["read"] = True
        row["read_at"] = utc_now().isoformat()
        row = await repo.update(notification_id, row)
        await publish_notification_event(
            "NOTIFICATION_READ", tenant_id, {"notification_id": notification_id}
        )
    return row


async def mark_all_notifications_read(tenant_id: str) -> int:
    """Mark every unread, non-archived notification read. Returns the count."""
    repo = get_inbox_repository()
    rows = await repo.find_many(filters={"tenant_id": tenant_id}, limit=_SCAN_LIMIT)
    now_iso = utc_now().isoformat()
    updated = 0
    for row in rows:
        if row.get("read") or row.get("archived"):
            continue
        row["read"] = True
        row["read_at"] = now_iso
        await repo.update(row["id"], row)
        updated += 1
    if updated:
        await publish_notification_event(
            "NOTIFICATION_READ", tenant_id, {"read_all": True, "count": updated}
        )
    return updated


async def archive_notification(tenant_id: str, notification_id: str) -> dict:
    """Archive one notification (tenant-scoped). Idempotent. Archived rows
    drop out of listings and the unread count."""
    repo = get_inbox_repository()
    row = await repo.find_by_id(notification_id)
    if not row or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"Inbox notification {notification_id!r} not found")
    if not row.get("archived"):
        row["archived"] = True
        row["archived_at"] = utc_now().isoformat()
        row = await repo.update(notification_id, row)
    return row
