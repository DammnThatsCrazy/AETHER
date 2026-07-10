"""
Aether Service — Job Center Kyber Operator Routes

Cross-tenant operator surface for the durable jobs control plane. Both
endpoints are gated fail-closed by ``require_kyber_operator`` — no Aether
tenant (including role-admins) can reach them.

Endpoints:
    GET  /v1/kyber/jobs/timeline          Cross-tenant job_events feed
    POST /v1/kyber/jobs/{job_id}/requeue  Requeue a failed/expired/cancelled job

This module only exports ``router``; mounting is done by the app
orchestrator (main.py), not here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from shared.common.common import APIResponse, ConflictError, NotFoundError
from shared.logger.logger import get_logger, metrics

from repositories.jobs_repo import get_jobs_repository
from services.jobs.models import JobStatus
from services.jobs.service import publish_platform_topic
from services.security.request_context import require_kyber_operator

logger = get_logger("aether.service.jobs.kyber_routes")
router = APIRouter(prefix="/v1/kyber/jobs", tags=["Job Center (Kyber)"])

_REQUEUEABLE = {
    JobStatus.FAILED.value,
    JobStatus.EXPIRED.value,
    JobStatus.CANCELLED.value,
}


@router.get("/timeline")
async def jobs_timeline(
    request: Request,
    actor=Depends(require_kyber_operator),
    tenant_id: Optional[str] = Query(
        None, description="Restrict the feed to one tenant; omit for all tenants."
    ),
    limit: int = Query(100, ge=1, le=500),
):
    """Newest-first job_events feed across all tenants (operator-only)."""
    events = await get_jobs_repository().recent_events(tenant_id=tenant_id, limit=limit)
    return APIResponse(data={
        "event_count": len(events),
        "tenant_id": tenant_id,
        "events": events,
    }).to_dict()


@router.post("/{job_id}/requeue")
async def requeue_job(
    job_id: str,
    request: Request,
    actor=Depends(require_kyber_operator),
):
    """Requeue a terminal-but-recoverable job (failed / expired / cancelled)
    with attempts reset, regardless of tenant."""
    repo = get_jobs_repository()
    job = await repo.get_job_any(job_id)
    if job is None:
        raise NotFoundError("job")
    if job["status"] not in _REQUEUEABLE:
        raise ConflictError(
            f"Cannot requeue job in status '{job['status']}' "
            f"(requeueable: {sorted(_REQUEUEABLE)})"
        )

    updated = await repo.requeue_any(job_id)
    if updated is None:  # lost a race with another transition
        raise ConflictError("Job left a requeueable status concurrently")
    await repo.append_job_event(
        updated["tenant_id"], job_id, "job.queued",
        payload={
            "job_id": job_id,
            "tenant_id": updated["tenant_id"],
            "job_type": updated["job_type"],
            "status": updated["status"],
            "requeued_by": actor.actor_id,
            "previous_status": job["status"],
        },
        correlation_id=updated.get("correlation_id"),
    )
    await publish_platform_topic(
        "JOB_QUEUED", updated["tenant_id"],
        {
            "job_id": job_id,
            "job_type": updated["job_type"],
            "status": updated["status"],
            "requeued_by": actor.actor_id,
        },
        correlation_id=updated.get("correlation_id") or "",
    )
    metrics.increment("jobs_kyber_requeued", labels={"job_type": updated["job_type"]})
    return APIResponse(data=updated).to_dict()
