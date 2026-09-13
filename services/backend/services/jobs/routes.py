"""
Aether Service — Job Center Routes (tenant-facing)

Endpoints:
    POST   /v1/jobs                          Enqueue a job (tenant-invocable types only)
    GET    /v1/jobs                          List tenant jobs
    GET    /v1/jobs/summary                  Status counts
    POST   /v1/jobs/schedules                Create a cron schedule
    GET    /v1/jobs/schedules                List schedules
    GET    /v1/jobs/schedules/{schedule_id}  Get one schedule
    PATCH  /v1/jobs/schedules/{schedule_id}  Update a schedule
    DELETE /v1/jobs/schedules/{schedule_id}  Delete a schedule
    GET    /v1/jobs/{job_id}                 Get one job
    GET    /v1/jobs/{job_id}/events          Job timeline
    POST   /v1/jobs/{job_id}/cancel          Cancel (queued→cancelled, running→cancel_requested)
    POST   /v1/jobs/{job_id}/retry           Retry a failed job

NOTE: the /schedules routes are registered BEFORE the /{job_id} routes —
FastAPI matches in registration order, and a literal "schedules" path
segment would otherwise be captured by the {job_id} parameter.

This module only exports ``router``; mounting is done by the app
orchestrator (main.py), not here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    utc_now,
)
from shared.logger.logger import get_logger

from services.jobs.handlers import HANDLER_REGISTRY, TENANT_INVOCABLE
from services.jobs.models import (
    MISFIRE_POLICIES,
    OVERLAP_POLICIES,
)
from services.jobs.scheduler import (
    compute_next_run,
    validate_cron_expression,
    validate_timezone,
)
from services.jobs.service import get_jobs_service

logger = get_logger("aether.service.jobs.routes")
router = APIRouter(prefix="/v1/jobs", tags=["Job Center"])


def _tenant(request: Request, permission: str):
    """Resolve the authenticated tenant and enforce a permission."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    tenant.require_permission(permission)
    return tenant


# ── Request models ────────────────────────────────────────────────────────────

class JobEnqueueRequest(BaseModel):
    job_type: str = Field(min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, max_length=500)
    correlation_id: Optional[str] = Field(default=None, max_length=200)
    priority: int = Field(default=100, ge=0, le=1000)
    max_attempts: int = Field(default=5, ge=1, le=20)
    scheduled_for: Optional[str] = None  # ISO-8601; defers execution


class ScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    job_type: str = Field(min_length=1, max_length=200)
    cron_expression: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="UTC", max_length=100)
    misfire_policy: str = "fire_once"
    overlap_policy: str = "skip"
    enabled: bool = True
    payload: dict = Field(default_factory=dict)


class ScheduleUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    cron_expression: Optional[str] = Field(default=None, min_length=1, max_length=200)
    timezone: Optional[str] = Field(default=None, max_length=100)
    misfire_policy: Optional[str] = None
    overlap_policy: Optional[str] = None
    enabled: Optional[bool] = None
    payload: Optional[dict] = None


def _validate_tenant_job_type(job_type: str) -> None:
    if job_type not in HANDLER_REGISTRY:
        raise BadRequestError(f"Unknown job_type '{job_type}'")
    if job_type not in TENANT_INVOCABLE:
        raise ForbiddenError(f"job_type '{job_type}' cannot be invoked directly")


def _validate_policies(misfire_policy: Optional[str], overlap_policy: Optional[str]) -> None:
    if misfire_policy is not None and misfire_policy not in MISFIRE_POLICIES:
        raise BadRequestError(
            f"misfire_policy must be one of {sorted(MISFIRE_POLICIES)}"
        )
    if overlap_policy is not None and overlap_policy not in OVERLAP_POLICIES:
        raise BadRequestError(
            f"overlap_policy must be one of {sorted(OVERLAP_POLICIES)}"
        )


# ── Jobs: enqueue / list / summary ───────────────────────────────────────────

@router.post("")
async def enqueue_job(body: JobEnqueueRequest, request: Request):
    """Enqueue a durable job. Only handler-registered, tenant-invocable
    job types are accepted; replays return the original job with
    ``replayed=true``."""
    tenant = _tenant(request, "write")
    _validate_tenant_job_type(body.job_type)

    job = await get_jobs_service().enqueue(
        tenant.tenant_id,
        body.job_type,
        body.payload,
        idempotency_key=body.idempotency_key,
        correlation_id=body.correlation_id,
        requested_by=getattr(tenant, "user_id", None) or tenant.tenant_id,
        priority=body.priority,
        max_attempts=body.max_attempts,
        scheduled_for=body.scheduled_for,
    )
    return APIResponse(data=job).to_dict()


@router.get("")
async def list_jobs(
    request: Request,
    status: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List the tenant's jobs, newest first."""
    tenant = _tenant(request, "read")
    jobs = await get_jobs_service().list_jobs(
        tenant.tenant_id, status=status, job_type=job_type, limit=limit, offset=offset
    )
    return APIResponse(data={"job_count": len(jobs), "jobs": jobs}).to_dict()


@router.get("/summary")
async def jobs_summary(request: Request):
    """Job counts by status for the tenant."""
    tenant = _tenant(request, "read")
    summary = await get_jobs_service().summary(tenant.tenant_id)
    return APIResponse(data=summary).to_dict()


# ── Schedules CRUD ───────────────────────────────────────────────────────────
# Registered BEFORE the /{job_id} routes so "schedules" is never captured as
# a job_id path parameter.

@router.post("/schedules")
async def create_schedule(body: ScheduleCreateRequest, request: Request):
    """Create a cron schedule for a tenant-invocable job type."""
    tenant = _tenant(request, "write")
    _validate_tenant_job_type(body.job_type)
    validate_cron_expression(body.cron_expression)
    validate_timezone(body.timezone)
    _validate_policies(body.misfire_policy, body.overlap_policy)

    next_run = compute_next_run(body.cron_expression, body.timezone, after=utc_now())
    schedule = await get_jobs_service().repo.create_schedule(
        tenant.tenant_id,
        name=body.name,
        job_type=body.job_type,
        cron_expression=body.cron_expression,
        timezone_name=body.timezone,
        misfire_policy=body.misfire_policy,
        overlap_policy=body.overlap_policy,
        enabled=body.enabled,
        owner_id=getattr(tenant, "user_id", None) or tenant.tenant_id,
        payload=body.payload,
        next_run_at=next_run,
    )
    return APIResponse(data=schedule).to_dict()


@router.get("/schedules")
async def list_schedules(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List the tenant's job schedules."""
    tenant = _tenant(request, "read")
    schedules = await get_jobs_service().repo.list_schedules(
        tenant.tenant_id, limit=limit, offset=offset
    )
    return APIResponse(
        data={"schedule_count": len(schedules), "schedules": schedules}
    ).to_dict()


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str, request: Request):
    """Get one schedule (tenant-scoped)."""
    tenant = _tenant(request, "read")
    schedule = await get_jobs_service().repo.get_schedule(tenant.tenant_id, schedule_id)
    if schedule is None:
        raise NotFoundError("schedule")
    return APIResponse(data=schedule).to_dict()


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, body: ScheduleUpdateRequest, request: Request):
    """Update a schedule; cron/timezone changes recompute next_run_at."""
    tenant = _tenant(request, "write")
    repo = get_jobs_service().repo
    schedule = await repo.get_schedule(tenant.tenant_id, schedule_id)
    if schedule is None:
        raise NotFoundError("schedule")

    updates = body.model_dump(exclude_none=True)
    _validate_policies(updates.get("misfire_policy"), updates.get("overlap_policy"))
    cron = updates.get("cron_expression", schedule["cron_expression"])
    tz_name = updates.get("timezone", schedule.get("timezone") or "UTC")
    if "cron_expression" in updates:
        validate_cron_expression(cron)
    if "timezone" in updates:
        validate_timezone(tz_name)
    if "cron_expression" in updates or "timezone" in updates:
        updates["next_run_at"] = compute_next_run(cron, tz_name, after=utc_now())
    if updates.get("enabled") is True and not schedule.get("enabled"):
        # Re-enabling: realign with the cron and clear the failure streak so
        # the stale next_run_at cannot immediately misfire.
        updates.setdefault(
            "next_run_at", compute_next_run(cron, tz_name, after=utc_now())
        )
        updates["consecutive_failures"] = 0

    updated = await repo.update_schedule(tenant.tenant_id, schedule_id, updates)
    return APIResponse(data=updated).to_dict()


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request):
    """Delete a schedule; already-enqueued jobs are unaffected."""
    tenant = _tenant(request, "write")
    deleted = await get_jobs_service().repo.delete_schedule(tenant.tenant_id, schedule_id)
    if not deleted:
        raise NotFoundError("schedule")
    return APIResponse(data={"schedule_id": schedule_id, "deleted": True}).to_dict()


# ── Jobs: single-row routes (AFTER /schedules) ───────────────────────────────

@router.get("/{job_id}")
async def get_job(job_id: str, request: Request):
    """Get one job (tenant-scoped)."""
    tenant = _tenant(request, "read")
    job = await get_jobs_service().get_job(tenant.tenant_id, job_id)
    if job is None:
        raise NotFoundError("job")
    return APIResponse(data=job).to_dict()


@router.get("/{job_id}/events")
async def list_job_events(job_id: str, request: Request):
    """Chronological job_events timeline for one job."""
    tenant = _tenant(request, "read")
    events = await get_jobs_service().list_events(tenant.tenant_id, job_id)
    return APIResponse(data={"event_count": len(events), "events": events}).to_dict()


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    """Cancel: queued/retrying → cancelled immediately; running →
    cancel_requested (the worker observes it at its next heartbeat)."""
    tenant = _tenant(request, "write")
    job = await get_jobs_service().cancel(tenant.tenant_id, job_id)
    return APIResponse(data=job).to_dict()


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, request: Request):
    """Re-queue a FAILED job with attempts reset."""
    tenant = _tenant(request, "write")
    job = await get_jobs_service().retry(tenant.tenant_id, job_id)
    return APIResponse(data=job).to_dict()
