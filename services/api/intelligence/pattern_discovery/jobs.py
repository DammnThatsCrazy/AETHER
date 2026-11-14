"""Scheduled discovery: a durable job per tenant, enqueued by a periodic sweep.

* ``pattern_discovery.run`` — durable job handler; runs one discovery pass
  for ``ctx.tenant_id`` (window and event cap from settings, or the payload).
* :func:`run_sweep_loop` — the ``pattern_discovery_sweep`` worker. Every
  ``PATTERN_DISCOVERY_INTERVAL_MINUTES`` it enqueues one job per tenant with
  recent analytics events. The idempotency key is the interval bucket, so a
  restarted worker never doubles a pass. Inert unless both
  ``AETHER_PATTERN_DISCOVERY_ENABLED`` and ``PATTERN_DISCOVERY_SCHEDULER_ENABLED``
  are on (re-read every pass, so flipping a flag needs no restart).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.pattern_discovery.jobs")

JOB_TYPE = "pattern_discovery.run"
MAX_TENANTS_PER_SWEEP = 1_000


async def run_job(payload: dict, ctx: Any) -> Any:
    from workers.jobs.handlers import JobOutcome

    from .service import get_service

    payload = payload or {}
    out = await get_service().run(
        ctx.tenant_id,
        window_hours=payload.get("window_hours"),
        max_events=payload.get("max_events"),
        requested_by="scheduler",
    )
    return JobOutcome(status="succeeded", result={
        "run_id": out["run_id"], "patterns_detected": out["patterns_detected"],
        "patterns_by_status": out["patterns_by_status_after_merge"], "coverage": out["coverage"],
    })


def register_pattern_discovery_handlers() -> None:
    """Register the discovery job (idempotent)."""
    from workers.jobs.handlers import HANDLER_REGISTRY, register_handler

    if JOB_TYPE not in HANDLER_REGISTRY:
        register_handler(JOB_TYPE)(run_job)


async def _tenants_with_events() -> list[str]:
    """Tenants holding analytics events (each gets only its own job)."""
    from repositories.repos import AnalyticsRepository, get_pool

    pool = await get_pool()
    if pool is None:
        from dependencies.providers import get_cache

        store = AnalyticsRepository(get_cache())._events._store  # noqa: SLF001 - local dev only
        return sorted({r["tenant_id"] for r in store.values() if r.get("tenant_id")})[:MAX_TENANTS_PER_SWEEP]
    rows = await pool.fetch(
        "SELECT DISTINCT tenant_id FROM events WHERE tenant_id IS NOT NULL AND tenant_id <> '' LIMIT $1",
        MAX_TENANTS_PER_SWEEP,
    )
    return sorted(r["tenant_id"] for r in rows)


def _bucket(now: datetime, interval_minutes: int) -> str:
    minutes = int(now.timestamp() // 60)
    return str(minutes // max(1, interval_minutes))


async def sweep_once(now: Optional[datetime] = None, *, tenants: Any = None, jobs: Any = None,
                     settings: Any = None) -> int:
    if settings is None:
        from config.settings import settings as _settings

        settings = _settings
    cfg = settings.pattern_discovery
    if not (cfg.enabled and cfg.scheduler_enabled):
        return 0
    if jobs is None:
        from workers.jobs.service import get_jobs_service

        jobs = get_jobs_service()
    now = now or datetime.now(timezone.utc)
    bucket = _bucket(now, cfg.scheduler_interval_minutes)
    enqueued = 0
    for tenant_id in await (tenants or _tenants_with_events)():
        await jobs.enqueue(tenant_id, JOB_TYPE, {}, idempotency_key=f"pattern_discovery:{tenant_id}:{bucket}")
        enqueued += 1
    return enqueued


async def run_sweep_loop() -> None:
    from config.settings import settings

    while True:
        try:
            await sweep_once()
        except Exception as exc:  # noqa: BLE001 - the next pass retries
            logger.warning("pattern_discovery_sweep_failed", extra={"error_type": type(exc).__name__})
        # Check flags frequently; the bucket key keeps passes to one per interval.
        await asyncio.sleep(max(60, min(900, settings.pattern_discovery.scheduler_interval_minutes * 60 // 4)))


def build_sweep_coro():
    return run_sweep_loop()
