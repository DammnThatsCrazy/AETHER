"""Aether Gateway — public status history (90-day per-component uptime).

The public status page (``apps/public-site/src/pages/status-page.tsx``) draws live
state from ``/v1/health`` and, separately, one bar per day per component from
``GET /v1/status/history?days=90``. This module owns both halves of that feed.

Where samples come from
-----------------------
Nothing new computes health. Each time an API process answers ``/v1/health``
(the ALB target-group check and the ECS container check call it continuously)
the handler hands its freshly derived verdict to :class:`StatusHistoryRecorder`.
At most once per :data:`DEFAULT_SAMPLE_INTERVAL_SECONDS` per process the
recorder folds that verdict into ``status_component_daily`` — one sample per
component, plus ``api`` for the payload's top-level status — as a background
task that runs after the liveness response is sent and can never fail it.

How a day is scored
-------------------
A day's row holds sample counts (``ok``/``degraded``/``down``/``unknown``).

* ``unknown`` samples are unobserved, not healthy and not failed, so they are
  excluded from the denominator (the same rule component_status.py obeys: an
  unobserved signal is never health).
* A day with no observed samples is **omitted** from the feed, so the page
  renders "no data" for it. It is never reported as 0% or 100%.
* ``uptime_pct`` = ``(ok + degraded) / (ok + degraded + down)``: a degraded
  component is still serving. It is rounded *down* to two decimals, so a day
  with any ``down`` sample can never display as 100%.
* ``status`` is the worst observed sample: any ``down`` → ``outage``, else any
  ``degraded`` → ``degraded``, else ``operational``.

The measurement is self-reported by live API processes: a period in which no
API process is serving records no samples at all, so it lowers neither the
numerator nor the denominator. The feed says what the platform observed about
itself; it is not an external synthetic probe.

What is published
-----------------
Only aggregate availability per component: date, status and uptime. No tenant
data, hostnames, dependency names, error text or sample counts leave this
module. Public incidents are not published by this feed yet (``incidents`` is
always an empty list).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from services.gateway import component_status
from services.gateway.status_history_repository import (
    SAMPLE_STATUSES,
    DailyRollup,
    StatusHistoryRepository,
)
from shared.common.common import utc_now
from shared.rate_limit.auth_throttle import client_ip  # noqa: F401  (re-exported: gateway/routes.py)
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.gateway.status_history")

# ── contract constants ───────────────────────────────────────────────────────

#: Largest (and default) window the public feed serves, in days.
MAX_HISTORY_DAYS = 90
DEFAULT_HISTORY_DAYS = MAX_HISTORY_DAYS

#: The pseudo-component carrying the ``/v1/health`` top-level status.
API_COMPONENT = "api"

#: Every component the feed may publish, in display-stable order.
HISTORY_COMPONENTS: tuple[str, ...] = (API_COMPONENT,) + component_status.COMPONENT_NAMES

#: Day statuses the site parser accepts (``no_data`` is expressed by omission).
DAY_OPERATIONAL = "operational"
DAY_DEGRADED = "degraded"
DAY_OUTAGE = "outage"

#: How often one API process folds its health verdict into the rollups.
DEFAULT_SAMPLE_INTERVAL_SECONDS = 300.0
#: Upper bound on one background flush; a slow database drops the sample.
RECORD_TIMEOUT_SECONDS = 5.0
#: Rollups older than this many days are pruned on write. Longer than the
#: public window so a later, longer view has data to start from.
RETENTION_DAYS = 400

#: ``Cache-Control`` for the public feed. Samples land at most every five
#: minutes per process, so a five-minute shared cache loses nothing material.
CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=600"
#: How long one process reuses a built response before re-reading Postgres.
RESPONSE_CACHE_SECONDS = 60.0

#: Per-client-IP requests per minute before the public feed answers 429.
PUBLIC_RATE_LIMIT_PER_MINUTE = 60


# ── sampling ─────────────────────────────────────────────────────────────────


def normalize_sample(status: Any) -> str:
    """Map a component_status verdict onto the sample vocabulary.

    Anything this module does not recognise is ``unknown`` — never ``ok``.
    """
    if status in SAMPLE_STATUSES:
        return str(status)
    return component_status.STATUS_UNKNOWN


def samples_from_health(
    *, overall_healthy: bool, components: Mapping[str, Mapping[str, Any]]
) -> dict[str, str]:
    """One sample per published component from a ``/v1/health`` evaluation.

    ``api`` mirrors the payload's top-level verdict the status page shows
    (``healthy`` → ok, ``degraded`` → degraded); every other component takes its
    own derived status. Components outside :data:`HISTORY_COMPONENTS` are
    ignored so nothing unexpected is ever persisted or published.
    """
    samples = {
        API_COMPONENT: (
            component_status.STATUS_OK if overall_healthy else component_status.STATUS_DEGRADED
        )
    }
    for name in component_status.COMPONENT_NAMES:
        entry = components.get(name)
        status = entry.get("status") if isinstance(entry, Mapping) else None
        samples[name] = normalize_sample(status)
    return samples


# ── scoring ──────────────────────────────────────────────────────────────────


def score_day(rollup: DailyRollup) -> Optional[dict[str, Any]]:
    """The published entry for one day, or None when nothing was observed."""
    observed = rollup.ok + rollup.degraded + rollup.down
    if observed <= 0:
        return None
    available = rollup.ok + rollup.degraded
    # Integer floor keeps the rounding exact and never rounds up to 100.
    uptime_pct = (available * 10000 // observed) / 100
    if rollup.down > 0:
        status = DAY_OUTAGE
    elif rollup.degraded > 0:
        status = DAY_DEGRADED
    else:
        status = DAY_OPERATIONAL
    return {"date": rollup.day.isoformat(), "status": status, "uptime_pct": uptime_pct}


def history_window(days: int, today: date) -> tuple[date, date]:
    """Inclusive UTC window of ``days`` days ending ``today`` (the site's axis)."""
    if not 1 <= days <= MAX_HISTORY_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_HISTORY_DAYS}, got {days}")
    return today - timedelta(days=days - 1), today


def build_history(
    rollups: Iterable[DailyRollup],
    *,
    days: int,
    today: date,
    generated_at: datetime,
) -> dict[str, Any]:
    """The public payload ``apps/public-site/src/site/status.ts`` parses.

    Every published component is listed (in :data:`HISTORY_COMPONENTS` order),
    each with only the days that have observed samples, oldest first.
    """
    start, end = history_window(days, today)
    per_component: dict[str, dict[date, DailyRollup]] = {name: {} for name in HISTORY_COMPONENTS}
    for rollup in rollups:
        bucket = per_component.get(rollup.component)
        if bucket is None or not start <= rollup.day <= end:
            continue
        existing = bucket.get(rollup.day)
        if existing is not None:
            # Defensive: merge duplicate rows instead of letting one hide another.
            rollup = DailyRollup(
                day=rollup.day,
                component=rollup.component,
                ok=existing.ok + rollup.ok,
                degraded=existing.degraded + rollup.degraded,
                down=existing.down + rollup.down,
                unknown=existing.unknown + rollup.unknown,
            )
        bucket[rollup.day] = rollup

    components = []
    for name in HISTORY_COMPONENTS:
        entries = []
        for day in sorted(per_component[name]):
            entry = score_day(per_component[name][day])
            if entry is not None:
                entries.append(entry)
        components.append({"name": name, "days": entries})

    return {
        "generated_at": generated_at.isoformat(),
        "window_days": days,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "components": components,
        "incidents": [],
    }


# ── recording ────────────────────────────────────────────────────────────────


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_seconds(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


class StatusHistoryRecorder:
    """Throttled, failure-isolated writer of health samples.

    :meth:`claim` is synchronous and cheap: it decides whether this health
    evaluation is due to be recorded. The returned coroutine performs the write
    and swallows (logs + counts) every failure, so it is safe to run as a
    response background task on the liveness path.
    """

    def __init__(
        self,
        repository: Optional[StatusHistoryRepository] = None,
        *,
        interval_seconds: Optional[float] = None,
        enabled: Optional[bool] = None,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository or StatusHistoryRepository()
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else _env_seconds("STATUS_HISTORY_SAMPLE_INTERVAL_SECONDS", DEFAULT_SAMPLE_INTERVAL_SECONDS)
        )
        self._enabled = (
            enabled if enabled is not None else _env_bool("STATUS_HISTORY_RECORDING_ENABLED", True)
        )
        self._clock = clock
        self._monotonic = monotonic
        self._last_claim: Optional[float] = None

    def claim(
        self, *, overall_healthy: bool, components: Mapping[str, Mapping[str, Any]]
    ) -> Optional[Callable[[], Awaitable[None]]]:
        """Return the write to run for this evaluation, or None when not due."""
        if not self._enabled:
            return None
        now = self._monotonic()
        if self._last_claim is not None and now - self._last_claim < self._interval:
            return None
        self._last_claim = now
        samples = samples_from_health(overall_healthy=overall_healthy, components=components)
        at = self._clock()

        async def _write() -> None:
            await self.write(at, samples)

        return _write

    async def write(self, at: datetime, samples: Mapping[str, str]) -> bool:
        """Persist one sample set; never raises. Returns whether it landed."""
        prune_before = at.date() - timedelta(days=RETENTION_DAYS)
        try:
            await asyncio.wait_for(
                self._repository.record(at, samples, prune_before=prune_before),
                timeout=RECORD_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - never fail the liveness path
            metrics.increment("status_history_record_failures_total")
            logger.warning(f"status history sample not recorded: {type(exc).__name__}")
            return False
        metrics.increment("status_history_samples_recorded_total")
        return True


# ── serving ──────────────────────────────────────────────────────────────────


@dataclass
class _CachedResponse:
    expires_at: float
    body: dict[str, Any]


class StatusHistoryService:
    """Builds the public payload with a short per-process response cache."""

    def __init__(
        self,
        repository: Optional[StatusHistoryRepository] = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        cache_seconds: float = RESPONSE_CACHE_SECONDS,
    ) -> None:
        self._repository = repository or StatusHistoryRepository()
        self._clock = clock
        self._monotonic = monotonic
        self._cache_seconds = cache_seconds
        self._cache: dict[int, _CachedResponse] = {}

    async def history(self, days: int) -> dict[str, Any]:
        now = self._monotonic()
        cached = self._cache.get(days)
        if cached is not None and cached.expires_at > now:
            return cached.body
        generated_at = self._clock()
        today = generated_at.date()
        start, end = history_window(days, today)
        rollups = await self._repository.read_window(start, end)
        body = build_history(rollups, days=days, today=today, generated_at=generated_at)
        self._cache[days] = _CachedResponse(expires_at=now + self._cache_seconds, body=body)
        return body

    def clear_cache(self) -> None:
        self._cache.clear()


class PublicIpRateLimiter:
    """Fixed one-minute window per client IP (Redis when reachable, else memory).

    Same shape as the public registration limiter in
    ``services/registration/routes.py``; the in-memory fallback prunes expired
    windows so an unauthenticated caller cannot grow it without bound.
    """

    _MAX_MEMORY_KEYS = 10_000

    def __init__(
        self,
        limit_per_minute: int = PUBLIC_RATE_LIMIT_PER_MINUTE,
        *,
        key_prefix: str = "status-history",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._limit = limit_per_minute
        self._prefix = key_prefix
        self._clock = clock
        self._buckets: dict[str, list[float]] = {}

    async def check(self, ip: str, redis: Any = None) -> Optional[int]:
        """None when allowed; otherwise the seconds until the window resets."""
        now = self._clock()
        window_start = int(now // 60) * 60
        key = f"public:{self._prefix}:{ip}:{window_start}"
        if redis is not None:
            try:
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, 60)
                return None if count <= self._limit else max(1, int(window_start + 60 - now))
            except Exception:  # noqa: BLE001 - fall back to the local window
                pass
        if len(self._buckets) >= self._MAX_MEMORY_KEYS:
            for stale in [k for k, (reset, _) in self._buckets.items() if reset <= now]:
                del self._buckets[stale]
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = [window_start + 60.0, 1.0]
            return None
        bucket[1] += 1
        if bucket[1] > self._limit:
            return max(1, int(bucket[0] - now))
        return None


# Process-wide instances used by the gateway routes.
recorder = StatusHistoryRecorder()
service = StatusHistoryService()
rate_limiter = PublicIpRateLimiter()
