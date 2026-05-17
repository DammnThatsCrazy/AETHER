"""Event replay routes — replay job management and single-event ingest for EventPipelineEnvelope.

    POST  /v1/events/replay                   Submit a new replay job
    GET   /v1/events/replay                   List replay jobs for a tenant
    GET   /v1/events/replay/{job_id}          Get replay job status
    POST  /v1/events/replay/{job_id}/cancel   Cancel a queued or running replay job
    POST  /v1/events/ingest                   Ingest a single EventPipelineEnvelope
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics
from services.operational_intelligence.models import (
    EntityRef,
    EvidenceRef,
    ExplainabilityMetadata,
    InvestigationAnnotation,
    InvestigationCase,
    GovernanceDecision,
    EventPipelineEnvelope,
    TenantScopedRequest,
)
from repositories.repos import EventReplayRepository

logger = get_logger("aether.service.events")

router = APIRouter(prefix="/v1/events", tags=["Event Replay"])

# ── In-memory store for ingested events (kept as-is, not repo-backed yet) ─────

_EVENTS: dict[str, dict] = {}

_repo = EventReplayRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


# ── Request / Response models ─────────────────────────────────────────────────

class ReplayRequest(TenantScopedRequest):
    sourceTag: str
    fromTime: str
    toTime: Optional[str] = None
    eventTypes: Optional[list[str]] = None
    dryRun: bool = False


class ReplayJobResponse(BaseModel):
    id: str
    tenantId: str
    sourceTag: str
    fromTime: str
    toTime: Optional[str] = None
    eventTypes: Optional[list[str]] = None
    dryRun: bool
    status: str
    cursor: Optional[str] = None
    submittedAt: str
    completedAt: Optional[str] = None
    totalReplayed: int = 0


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/replay", response_model=ReplayJobResponse)
async def submit_replay(
    body: ReplayRequest,
    request: Request,
) -> ReplayJobResponse:
    """Submit a new event replay job sourced from the given Bronze-tier tag.

    The job is created with status 'queued' and can be polled via GET /v1/events/replay/{job_id}.
    """
    _require(request, body.tenantId, "write")
    job_dict: dict = {
        "id": str(uuid.uuid4()),
        "tenantId": body.tenantId,
        "sourceTag": body.sourceTag,
        "fromTime": body.fromTime,
        "toTime": body.toTime,
        "eventTypes": body.eventTypes,
        "dryRun": body.dryRun,
        "status": "queued",
        "cursor": None,
        "submittedAt": _utc_now(),
        "completedAt": None,
        "totalReplayed": 0,
    }
    job_dict["tenant_id"] = job_dict["tenantId"]  # repo filter key
    result = await _repo.create(job_dict)
    logger.info(
        "event_replay_submitted",
        extra={
            "job_id": result["id"],
            "tenant_id": body.tenantId,
            "source_tag": body.sourceTag,
            "dry_run": body.dryRun,
        },
    )
    metrics.increment("event_replay_submitted")
    return ReplayJobResponse(**result)


@router.get("/replay", response_model=list[ReplayJobResponse])
async def list_replay_jobs(
    request: Request,
    tenantId: str = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ReplayJobResponse]:
    """List all replay jobs for the authenticated tenant."""
    _require(request, tenantId, "read")
    rows = await _repo.list_by_tenant(tenantId, limit=limit)
    return [ReplayJobResponse(**r) for r in rows]


@router.get("/replay/{job_id}", response_model=ReplayJobResponse)
async def get_replay_job(
    job_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> ReplayJobResponse:
    """Get the current status of a specific replay job."""
    _require(request, tenantId, "read")
    row = await _repo.find_by_id(job_id)
    if row is None or row.get("tenantId") != tenantId:
        raise NotFoundError(f"Replay job {job_id!r} not found")
    return ReplayJobResponse(**row)


@router.post("/replay/{job_id}/cancel", response_model=ReplayJobResponse)
async def cancel_replay_job(
    job_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> ReplayJobResponse:
    """Cancel a queued or in-progress replay job."""
    _require(request, tenantId, "write")
    row = await _repo.find_by_id(job_id)
    if row is None or row.get("tenantId") != tenantId:
        raise NotFoundError(f"Replay job {job_id!r} not found")
    completed_at = _utc_now()
    updated = await _repo.update(job_id, {"status": "cancelled", "completedAt": completed_at})
    logger.info("event_replay_cancelled", extra={"job_id": job_id, "tenant_id": tenantId})
    metrics.increment("event_replay_cancelled")
    return ReplayJobResponse(**updated)


@router.post("/ingest")
async def ingest_event(
    envelope: EventPipelineEnvelope,
    request: Request,
) -> dict[str, Any]:
    """Ingest a single EventPipelineEnvelope (used by the replay feed to re-introduce events).

    Validates tenant isolation before accepting the event into the in-memory store.
    """
    _require(request, envelope.tenantId, "write")
    _EVENTS[envelope.id] = envelope.model_dump()
    logger.info(
        "event_replay_ingested",
        extra={"event_id": envelope.id, "type": envelope.type, "tenant_id": envelope.tenantId},
    )
    metrics.increment("event_replay_ingested")
    return {"ingested": True, "id": envelope.id}
