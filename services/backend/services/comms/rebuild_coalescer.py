"""Coalesced journey/state rebuilds (Phase 15).

Multiple communication events for one profile inside a short window must
produce ONE rebuild job, not one rebuild per event. This module debounces
rebuild requests keyed by (tenant_id, profile_id): the first request arms a
flush timer; further requests inside the window only update the pending
record. On flush, the communication state is recomputed and the unified
journey recompiled once.

The coalescer is process-local and best-effort by design — rebuilds are
idempotent recomputations from durable facts, so a lost flush (process
restart) self-heals on the next event or manual rebuild.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.comms.rebuild_coalescer")

_DEFAULT_WINDOW_SECONDS = float(os.getenv("AETHER_COMMS_REBUILD_WINDOW_SECONDS", "5.0"))


@dataclass
class _PendingRebuild:
    tenant_id: str
    profile_id: str
    channel: str = "email"
    reasons: set[str] = field(default_factory=set)
    coalesced_events: int = 0
    first_requested_at: str = ""
    timer: Optional[asyncio.Task] = None


class JourneyRebuildCoalescer:
    """Debounced per-profile rebuild queue."""

    def __init__(self, window_seconds: float = _DEFAULT_WINDOW_SECONDS) -> None:
        self.window_seconds = window_seconds
        self._pending: dict[tuple[str, str], _PendingRebuild] = {}
        self._lock = asyncio.Lock()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def request_rebuild(
        self, tenant_id: str, profile_id: str,
        *, channel: str = "email", reason: str = "comm_event",
    ) -> None:
        """Register a rebuild request; bursts within the window coalesce."""
        key = (tenant_id, profile_id)
        async with self._lock:
            pending = self._pending.get(key)
            if pending is not None:
                pending.coalesced_events += 1
                pending.reasons.add(reason)
                pending.channel = channel
                metrics.increment(
                    "comms_rebuilds_coalesced_total", labels={"tenant_id": tenant_id}
                )
                return
            pending = _PendingRebuild(
                tenant_id=tenant_id, profile_id=profile_id, channel=channel,
                reasons={reason}, coalesced_events=1,
                first_requested_at=datetime.now(timezone.utc).isoformat(),
            )
            pending.timer = asyncio.create_task(self._flush_after_window(key))
            self._pending[key] = pending

    async def _flush_after_window(self, key: tuple[str, str]) -> None:
        try:
            await asyncio.sleep(self.window_seconds)
        except asyncio.CancelledError:
            return
        await self.flush_key(key)

    async def flush_key(self, key: tuple[str, str]) -> Optional[dict]:
        """Run the coalesced rebuild for one profile immediately."""
        async with self._lock:
            pending = self._pending.pop(key, None)
        if pending is None:
            return None
        if pending.timer is not None and not pending.timer.done():
            pending.timer.cancel()
        return await self._run_rebuild(pending)

    async def flush_all(self) -> int:
        """Test/shutdown helper — flush every pending rebuild now."""
        keys = list(self._pending.keys())
        flushed = 0
        for key in keys:
            if await self.flush_key(key) is not None:
                flushed += 1
        return flushed

    async def _run_rebuild(self, pending: _PendingRebuild) -> dict:
        reason = "comms:" + ",".join(sorted(pending.reasons))
        outcome = {"tenant_id": pending.tenant_id, "profile_id": pending.profile_id,
                   "coalesced_events": pending.coalesced_events,
                   "state_rebuilt": False, "journey_rebuilt": False}
        try:
            from services.comms.state import CommunicationStateService
            await CommunicationStateService().rebuild_for_entity(
                pending.tenant_id, pending.profile_id, channel=pending.channel,
            )
            outcome["state_rebuilt"] = True
        except Exception as exc:
            logger.warning(
                "coalesced_state_rebuild_failed profile=%s: %s", pending.profile_id, exc,
            )
        try:
            from services.measurement.engine.journey_compiler import JourneyCompiler
            await JourneyCompiler().compile_for_profile(
                pending.tenant_id, pending.profile_id, trigger_reason=reason,
            )
            outcome["journey_rebuilt"] = True
        except Exception as exc:
            logger.warning(
                "coalesced_journey_rebuild_failed profile=%s: %s", pending.profile_id, exc,
            )
        metrics.increment(
            "comms_rebuilds_flushed_total",
            labels={"tenant_id": pending.tenant_id},
        )
        metrics.gauge(
            "comms_rebuild_burst_size", pending.coalesced_events,
            labels={"tenant_id": pending.tenant_id},
        )
        return outcome


_coalescer: Optional[JourneyRebuildCoalescer] = None


def get_rebuild_coalescer() -> JourneyRebuildCoalescer:
    """Process-wide coalescer instance."""
    global _coalescer
    if _coalescer is None:
        _coalescer = JourneyRebuildCoalescer()
    return _coalescer
