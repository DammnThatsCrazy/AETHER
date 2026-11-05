"""Durable job handler so a tenant ``job_schedules`` row can drive reconciliation."""
from __future__ import annotations

from typing import Any

JOB_TYPE = "agent_lineage.reconcile"


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
