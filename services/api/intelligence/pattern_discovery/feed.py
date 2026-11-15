""""What's new since I last looked": per-viewer last-seen, digests, notifications.

Every pattern carries ``surfaced_at`` (when it first became visible),
``changed_at`` (when its evidence fingerprint last changed, i.e. a new
``version``) and ``deprecated_at`` (when it was retired). A viewer's
``last_seen_at`` per *scope* turns those into three lists:

* **new** — surfaced after the viewer last looked;
* **changed** — already surfaced before, but changed since (grew, gained
  evidence, changed risk reading);
* **retired** — deprecated since the viewer last looked.

Scopes: ``feed`` (the whole tenant), ``<surface>:<entity key>`` for a 360
section (``profile360:user:123``), and ``lens:<lens>:<subject>`` for the
segment lenses (``lens:campaign360:spring_sale``). Viewing never marks
anything seen; the viewer marks a scope seen explicitly (or the UI does when
the user dismisses the "new" banner), so nothing is lost by a page load.

After each discovery run the service raises one in-app notification
(deduplicated per tenant per day) when high or critical patterns surfaced.
"""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.temporal.instant import coerce_utc_lenient

from .contracts import STATUS_SURFACED, VISIBLE_STATUSES, content_hash

logger = get_logger("aether.pattern_discovery.feed")

DEFAULT_LOOKBACK_DAYS = 7
MAX_SCOPE_LEN = 400
NOTIFY_SEVERITIES = ("high", "critical")


class PatternViewerStateRepository(BaseRepository):
    """One row per (tenant, viewer, scope): when that viewer last looked."""

    def __init__(self) -> None:
        super().__init__("pattern_viewer_state")

    @staticmethod
    def record_id(tenant_id: str, viewer_id: str, scope: str) -> str:
        return f"{tenant_id}:pvs:{content_hash([viewer_id, scope], 24)}"

    async def get_last_seen(self, tenant_id: str, viewer_id: str, scope: str) -> Optional[str]:
        row = await self.find_by_id(self.record_id(tenant_id, viewer_id, scope))
        if row and row.get("tenant_id") == tenant_id:
            return row.get("last_seen_at")
        return None

    async def mark_seen(self, tenant_id: str, viewer_id: str, scope: str, at: Optional[str] = None) -> dict[str, Any]:
        rid = self.record_id(tenant_id, viewer_id, scope)
        now = at or utc_now().isoformat()
        row = {"tenant_id": tenant_id, "viewer_id": viewer_id, "scope": scope[:MAX_SCOPE_LEN],
               "last_seen_at": now}
        existing = await self.find_by_id(rid)
        if existing is None or existing.get("tenant_id") != tenant_id:
            if not await self.insert_if_absent(rid, copy.deepcopy(row), tenant_id):
                existing = await self.find_by_id(rid)
        if existing is not None and existing.get("tenant_id") == tenant_id:
            await self.replace_if_matches(rid, {**existing, **row}, tenant_id,
                                          {"last_seen_at": existing.get("last_seen_at")})
        return row

    async def delete_viewers(self, tenant_id: str, viewer_ids: list[str]) -> int:
        return await self.delete_for_tenant_where(tenant_id, "viewer_id", viewer_ids)


def _after(value: Any, since: datetime) -> bool:
    ts = coerce_utc_lenient(value)
    return bool(ts and ts > since)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "by_kind": dict(Counter(r.get("kind") for r in rows).most_common()),
        "by_severity": dict(Counter(r.get("severity") or "low" for r in rows).most_common()),
        "by_segment": dict(Counter(k for r in rows for k in r.get("segment_keys") or []).most_common(10)),
        "risk_categories": dict(Counter(c for r in rows for c in r.get("risk_categories") or []).most_common(10)),
    }


def whats_new(patterns: list[dict[str, Any]], *, since: datetime) -> dict[str, list[dict[str, Any]]]:
    new, changed, retired = [], [], []
    for p in patterns:
        status = p.get("status")
        if status == "deprecated" and _after(p.get("deprecated_at"), since):
            retired.append(p)
        elif status in VISIBLE_STATUSES and _after(p.get("surfaced_at"), since):
            new.append(p)
        elif status in VISIBLE_STATUSES and _after(p.get("changed_at"), since):
            changed.append(p)
    key = lambda p: (not p.get("pinned"), -float(p.get("severity_score") or 0), p.get("pattern_id", ""))  # noqa: E731
    return {"new": sorted(new, key=key), "changed": sorted(changed, key=key), "retired": sorted(retired, key=key)}


def resolve_since(explicit: Optional[str], last_seen: Optional[str]) -> datetime:
    for value in (explicit, last_seen):
        ts = coerce_utc_lenient(value)
        if ts is not None:
            return ts
    return datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)


def annotate_new(rows: list[dict[str, Any]], last_seen: Optional[str]) -> list[dict[str, Any]]:
    """Mark rows surfaced or changed after ``last_seen`` (no last-seen: none are 'new')."""
    since = coerce_utc_lenient(last_seen) if last_seen else None
    for r in rows:
        r["is_new"] = bool(since and _after(r.get("surfaced_at"), since))
        r["is_changed"] = bool(since and not r["is_new"] and _after(r.get("changed_at"), since))
    return rows


async def notify_new_patterns(tenant_id: str, surfaced: list[dict[str, Any]], *, run_id: str) -> Optional[dict]:
    """One in-app notification per tenant per day for newly surfaced high/critical patterns."""
    notable = [p for p in surfaced if p.get("status") == STATUS_SURFACED and p.get("severity") in NOTIFY_SEVERITIES]
    if not notable:
        return None
    critical = any(p.get("severity") == "critical" for p in notable)
    titles = "; ".join((p.get("display_title") or p.get("title") or "")[:80] for p in notable[:3])
    try:
        from journeys.notification_intelligence.inbox import create_inbox_notification

        return await create_inbox_notification(
            tenant_id,
            category="pattern_discovery",
            severity="P1" if critical else "P2",
            title=f"{len(notable)} new pattern{'s' if len(notable) != 1 else ''} surfaced",
            body=f"Discovered automatically: {titles}{'…' if len(notable) > 3 else ''}",
            link="/patterns?view=new",
            correlation_id=run_id,
            dedupe_key=f"pattern_discovery:{tenant_id}:{datetime.now(timezone.utc).date().isoformat()}",
        )
    except Exception as exc:  # noqa: BLE001 - the pattern record is the source of truth
        logger.warning("pattern_discovery.notify_failed",
                       extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
        return None
