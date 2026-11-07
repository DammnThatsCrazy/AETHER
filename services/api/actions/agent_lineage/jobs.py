"""Durable job handler so a tenant ``job_schedules`` row can drive reconciliation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.agent_lineage.jobs")

JOB_TYPE = "agent_lineage.reconcile"
SWEEP_INTERVAL_SECONDS = 3600
#: The UTC hour the sweep requests a full rebuild, which picks up facts that arrived
#: with old timestamps. Incremental passes stop at the first page with nothing new.
FULL_REBUILD_HOUR_UTC = 3


async def reconcile_job(payload: dict, ctx: Any) -> Any:
    from workers.jobs.handlers import JobOutcome

    from .service import get_service

    service = await get_service()
    stats = await service.reconcile(ctx.tenant_id, full=bool((payload or {}).get("full")))
    return JobOutcome(status="succeeded", result=stats)


def register_agent_lineage_handlers() -> None:
    """Register the reconcile job (idempotent)."""
    from workers.jobs.handlers import HANDLER_REGISTRY, register_handler

    if JOB_TYPE not in HANDLER_REGISTRY:
        register_handler(JOB_TYPE)(reconcile_job)


async def _tenants_with_agent_facts() -> list[str]:
    """Tenants holding execution facts. Used only to enqueue each tenant's own job."""
    from ingestion.silver import writer as silver_writer
    from repositories.repos import get_pool

    pool = await get_pool()
    if pool is None:
        rows = silver_writer._local_tables.get("silver_agent_execution_facts", {}).values()
        return sorted({row["tenant_id"] for row in rows if row.get("tenant_id")})
    rows = await pool.fetch("SELECT DISTINCT tenant_id FROM silver_agent_execution_facts WHERE tenant_id IS NOT NULL")
    return sorted(row["tenant_id"] for row in rows)


async def sweep_once(now: Optional[datetime] = None, *, tenants: Any = None, jobs: Any = None) -> int:
    """Enqueue one reconcile per tenant. The hour bucket keeps a restart from doubling it."""
    from config.settings import settings

    if not settings.external_agent_telemetry.registry_enabled:
        return 0
    if jobs is None:
        from workers.jobs.service import get_jobs_service

        jobs = get_jobs_service()
    now = now or datetime.now(timezone.utc)
    full = now.hour == FULL_REBUILD_HOUR_UTC
    bucket = now.strftime("%Y%m%d%H")
    enqueued = 0
    for tenant_id in await (tenants or _tenants_with_agent_facts)():
        await jobs.enqueue(
            tenant_id, JOB_TYPE, {"full": full},
            idempotency_key=f"agent_lineage:{tenant_id}:{bucket}",
        )
        enqueued += 1
    return enqueued


async def run_reconcile_sweep_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await sweep_once()
        except Exception as exc:  # noqa: BLE001 - the next pass retries
            logger.warning("agent_lineage_sweep_failed", extra={"error": type(exc).__name__})
        await asyncio.sleep(interval_seconds)


def build_reconcile_sweep_coro():
    return run_reconcile_sweep_loop()
