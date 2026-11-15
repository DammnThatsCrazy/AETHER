"""Activity-driven journey rebuilds (flag ``JOURNEY_ACTIVITY_REBUILD_ENABLED``).

Canonical activity reaches ``canonical_activity`` from the silver projectors,
but nothing recompiled the journey that activity belongs to: journeys rebuilt
only on identity restatement, comms, privacy, repair, a redeemed handoff or an
operator rebuild. A late mobile event, or the first events of a desktop session
after a cross-device handoff, therefore never appeared in the journey.

This module debounces rebuild requests per typed identity
``(tenant_id, identity_type, identity_id)``: the first activity arms a flush
timer, later activity inside the window only counts. On flush the journey is
compiled once. The most specific identity on the row wins (profile, then
cluster, then anonymous), matching how the compiler types journeys.

Process-local and best-effort by design, like ``journeys.comms.rebuild_coalescer``:
compilation is an idempotent recomputation from durable facts, so a flush lost
to a restart self-heals on the next activity for that identity.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.journeys.activity_rebuild")

_DEFAULT_WINDOW_SECONDS = float(os.getenv("AETHER_JOURNEY_ACTIVITY_REBUILD_WINDOW_SECONDS", "30"))
# Bound on identities waiting for a flush in one process. Past it, new
# identities are dropped (and counted) rather than growing memory unbounded.
_MAX_PENDING = int(os.getenv("AETHER_JOURNEY_ACTIVITY_REBUILD_MAX_PENDING", "10000"))

Key = tuple[str, str, str]


def identity_for_activity(activity: dict[str, Any]) -> Optional[tuple[str, str]]:
    """The typed identity whose journey owns ``activity``, or None."""
    for identity_type, column in (("profile", "profile_id"), ("cluster", "cluster_id"),
                                  ("anonymous", "anonymous_id")):
        value = activity.get(column)
        if value:
            return identity_type, str(value)
    return None


def enabled() -> bool:
    from config.settings import settings

    return bool(settings.identity_continuity.journey_activity_rebuild_enabled)


@dataclass
class _Pending:
    activity_count: int = 1
    timer: Optional[asyncio.Task] = None


class ActivityJourneyRebuilder:
    """Debounced per-identity journey compile queue."""

    def __init__(self, window_seconds: float = _DEFAULT_WINDOW_SECONDS,
                 max_pending: int = _MAX_PENDING) -> None:
        self.window_seconds = window_seconds
        self.max_pending = max_pending
        self._pending: dict[Key, _Pending] = {}
        self._lock = asyncio.Lock()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def request(self, tenant_id: str, identity_type: str, identity_id: str) -> bool:
        """Register new activity for an identity. Returns False when dropped."""
        key = (tenant_id, identity_type, identity_id)
        async with self._lock:
            pending = self._pending.get(key)
            if pending is not None:
                pending.activity_count += 1
                metrics.increment("journey_activity_rebuilds_coalesced_total")
                return True
            if len(self._pending) >= self.max_pending:
                metrics.increment("journey_activity_rebuilds_dropped_total")
                return False
            pending = _Pending()
            pending.timer = asyncio.create_task(self._flush_after_window(key))
            self._pending[key] = pending
            return True

    async def _flush_after_window(self, key: Key) -> None:
        try:
            await asyncio.sleep(self.window_seconds)
        except asyncio.CancelledError:
            return
        await self.flush_key(key)

    async def flush_key(self, key: Key) -> Optional[dict[str, Any]]:
        async with self._lock:
            pending = self._pending.pop(key, None)
        if pending is None:
            return None
        if pending.timer is not None and not pending.timer.done() \
                and pending.timer is not asyncio.current_task():
            pending.timer.cancel()
        tenant_id, identity_type, identity_id = key
        try:
            from journeys.measurement.engine.journey_compiler import JourneyCompiler

            version = await JourneyCompiler().compile_for_profile(
                tenant_id, identity_id, identity_type=identity_type,
                trigger_reason="activity_received",
            )
        except Exception as exc:  # noqa: BLE001 — the next activity retries
            metrics.increment("journey_activity_rebuilds_failed_total")
            logger.warning(
                "activity journey rebuild failed tenant=%s identity_type=%s: %s",
                tenant_id, identity_type, type(exc).__name__,
            )
            return None
        metrics.increment("journey_activity_rebuilds_flushed_total")
        return {"journey_id": version.get("journey_id"), "activity_count": pending.activity_count}

    async def flush_all(self) -> int:
        """Test/shutdown helper — flush every pending identity now."""
        flushed = 0
        for key in list(self._pending):
            if await self.flush_key(key) is not None:
                flushed += 1
        return flushed


_rebuilder: Optional[ActivityJourneyRebuilder] = None


def get_activity_rebuilder() -> ActivityJourneyRebuilder:
    global _rebuilder
    if _rebuilder is None:
        _rebuilder = ActivityJourneyRebuilder()
    return _rebuilder


async def request_for_activities(activities: list[dict[str, Any]]) -> int:
    """Request one debounced rebuild per identity in ``activities`` (flag-gated)."""
    if not activities or not enabled():
        return 0
    rebuilder = get_activity_rebuilder()
    requested = 0
    seen: set[Key] = set()
    for activity in activities:
        tenant_id = activity.get("tenant_id")
        identity = identity_for_activity(activity)
        if not tenant_id or identity is None:
            continue
        key = (str(tenant_id), identity[0], identity[1])
        if key in seen:
            continue
        seen.add(key)
        if await rebuilder.request(*key):
            requested += 1
    return requested
