"""Delivery API routes — intent/job/receipt/outcome visibility + manual dispatch.

Prefix: /v1/delivery
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from repositories.delivery_repos import (
    DeliveryIntentRepository,
    DeliveryJobRepository,
    DeliveryAttemptRepository,
    ProviderReceiptRepository,
    ExternalResourceLinkRepository,
    ExternalOutcomeEventRepository,
    WebhookInboxRepository,
)

logger = get_logger("aether.service.delivery")

router = APIRouter(prefix="/v1/delivery", tags=["Delivery"])

# Module-level repo singletons
_intent_repo = DeliveryIntentRepository()
_job_repo = DeliveryJobRepository()
_attempt_repo = DeliveryAttemptRepository()
_receipt_repo = ProviderReceiptRepository()
_link_repo = ExternalResourceLinkRepository()
_outcome_repo = ExternalOutcomeEventRepository()
_inbox_repo = WebhookInboxRepository()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id and tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


# ─── DeliveryIntent ───────────────────────────────────────────────────────────

@router.get("/intents")
async def list_intents(
    request: Request,
    tenantId: str = Query(...),
    status: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List DeliveryIntents for a tenant."""
    _require(request, tenantId, "read")
    filters: dict[str, Any] = {"tenant_id": tenantId}
    if status:
        filters["status"] = status
    if source_type:
        filters["source_type"] = source_type
    results = await _intent_repo.find_many(filters=filters, limit=limit, offset=offset)
    return APIResponse(data=results).to_dict()


@router.get("/intents/{intent_id}")
async def get_intent(
    intent_id: str,
    request: Request,
    tenantId: str = Query(...),
):
    """Get a single DeliveryIntent."""
    _require(request, tenantId, "read")
    intent = await _intent_repo.find_by_id(intent_id)
    if not intent or intent.get("tenant_id") != tenantId:
        raise NotFoundError(f"DeliveryIntent {intent_id!r} not found")
    return APIResponse(data=intent).to_dict()


# ─── DeliveryJob ──────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    request: Request,
    tenantId: str = Query(...),
    state: Optional[str] = Query(None),
    intent_id: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List DeliveryJobs for a tenant."""
    _require(request, tenantId, "read")
    filters: dict[str, Any] = {"tenant_id": tenantId}
    if state:
        filters["state"] = state
    if intent_id:
        filters["intent_id"] = intent_id
    results = await _job_repo.find_many(filters=filters, limit=limit, offset=offset)
    return APIResponse(data=results).to_dict()


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    tenantId: str = Query(...),
):
    """Get a single DeliveryJob with its attempts."""
    _require(request, tenantId, "read")
    job = await _job_repo.find_by_id(job_id)
    if not job or job.get("tenant_id") != tenantId:
        raise NotFoundError(f"DeliveryJob {job_id!r} not found")
    attempts = await _attempt_repo.find_for_job(job_id)
    return APIResponse(data={"job": job, "attempts": attempts}).to_dict()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    tenantId: str = Query(...),
):
    """Cancel a queued or failed DeliveryJob."""
    _require(request, tenantId, "write")
    job = await _job_repo.find_by_id(job_id)
    if not job or job.get("tenant_id") != tenantId:
        raise NotFoundError(f"DeliveryJob {job_id!r} not found")
    if job.get("state") not in ("queued", "failed"):
        return APIResponse(data={"cancelled": False, "reason": f"job is in state {job.get('state')!r}"}).to_dict()
    from datetime import datetime, timezone
    updated = await _job_repo.update(job_id, {
        "state": "cancelled",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return APIResponse(data={"cancelled": True, "job": updated}).to_dict()


# ─── ProviderReceipts ────────────────────────────────────────────────────────

@router.get("/receipts")
async def list_receipts(
    request: Request,
    tenantId: str = Query(...),
    intent_id: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List ProviderReceipts — proof of delivery — for a tenant."""
    _require(request, tenantId, "read")
    filters: dict[str, Any] = {"tenant_id": tenantId}
    if intent_id:
        filters["intent_id"] = intent_id
    results = await _receipt_repo.find_many(filters=filters, limit=limit)
    return APIResponse(data=results).to_dict()


# ─── ExternalOutcomeEvents ───────────────────────────────────────────────────

@router.post("/outcomes/ingest")
async def ingest_outcome(
    request: Request,
    tenantId: str = Query(...),
):
    """Ingest an inbound outcome event from an external provider webhook callback."""
    _require(request, tenantId, "write")
    body = await request.json()

    from services.delivery.models import ExternalOutcomeEvent, ExternalOutcomeType
    try:
        outcome_type = ExternalOutcomeType(body.get("outcome_type", "delivered"))
    except ValueError:
        outcome_type = ExternalOutcomeType.DELIVERED

    event = ExternalOutcomeEvent(
        tenant_id=tenantId,
        provider=body.get("provider", "unknown"),
        external_id=body.get("external_id", ""),
        intent_id=body.get("intent_id"),
        receipt_id=body.get("receipt_id"),
        outcome_type=outcome_type,
        raw_payload=body,
    )
    stored = await _outcome_repo.insert(event.id, event.model_dump())
    return JSONResponse(status_code=201, content=APIResponse(data=stored).to_dict())


@router.get("/outcomes")
async def list_outcomes(
    request: Request,
    tenantId: str = Query(...),
    external_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List ExternalOutcomeEvents for a tenant."""
    _require(request, tenantId, "read")
    filters: dict[str, Any] = {"tenant_id": tenantId}
    if external_id:
        filters["external_id"] = external_id
    if provider:
        filters["provider"] = provider
    results = await _outcome_repo.find_many(filters=filters, limit=limit)
    return APIResponse(data=results).to_dict()


# ─── Intent-level detail ─────────────────────────────────────────────────────

@router.get("/intents/{intent_id}/receipts")
async def get_intent_receipts(
    intent_id: str,
    request: Request,
    tenantId: str = Query(...),
):
    """Get all ProviderReceipts for a DeliveryIntent."""
    _require(request, tenantId, "read")
    intent = await _intent_repo.find_by_id(intent_id)
    if not intent or intent.get("tenant_id") != tenantId:
        raise NotFoundError(f"DeliveryIntent {intent_id!r} not found")
    receipts = await _receipt_repo.find_for_intent(intent_id)
    links = await _link_repo.find_for_intent(intent_id)
    return APIResponse(data={"receipts": receipts, "external_links": links}).to_dict()


@router.get("/intents/{intent_id}/jobs")
async def get_intent_jobs(
    intent_id: str,
    request: Request,
    tenantId: str = Query(...),
):
    """Get all DeliveryJobs for a DeliveryIntent."""
    _require(request, tenantId, "read")
    intent = await _intent_repo.find_by_id(intent_id)
    if not intent or intent.get("tenant_id") != tenantId:
        raise NotFoundError(f"DeliveryIntent {intent_id!r} not found")
    jobs = await _job_repo.find_for_intent(intent_id, tenantId)
    return APIResponse(data=jobs).to_dict()


# ─── Replay (re-queue dead-letter job) ──────────────────────────────────────

@router.post("/jobs/{job_id}/replay")
async def replay_job(
    job_id: str,
    request: Request,
    tenantId: str = Query(...),
):
    """Re-queue a dead-letter DeliveryJob for another attempt.

    Resets attempt_count to 0, clears last_error, and moves the job back to
    QUEUED. Requires write permission. Only valid for DEAD_LETTER jobs.
    """
    _require(request, tenantId, "write")
    from datetime import datetime, timezone
    job = await _job_repo.find_by_id(job_id)
    if not job or job.get("tenant_id") != tenantId:
        raise NotFoundError(f"DeliveryJob {job_id!r} not found")
    if job.get("state") != "dead_letter":
        return APIResponse(
            data={"replayed": False, "reason": f"job is in state {job.get('state')!r}, expected dead_letter"}
        ).to_dict()
    updated = await _job_repo.update(job_id, {
        "state": "queued",
        "attempt_count": 0,
        "last_error": None,
        "next_attempt_at": None,
        "leased_by": None,
        "lease_expires_at": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("delivery_job_replayed id=%s tenant=%s", job_id, tenantId)
    return APIResponse(data={"replayed": True, "job": updated}).to_dict()


# ─── Admin: cross-tenant operator routes ────────────────────────────────────
# These routes require operator (Kyber) credentials. No tenantId filter applied.

admin_router = APIRouter(prefix="/v1/admin/delivery", tags=["Delivery (Admin)"])


def _require_operator(request: Request) -> None:
    """Verify the caller has operator-level access (Kyber service account)."""
    tenant = request.state.tenant
    tenant.require_permission("operator")


@admin_router.get("/jobs")
async def admin_list_jobs(
    request: Request,
    state: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    provider_adapter: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    page: int = Query(default=1, ge=1),
):
    """Cross-tenant DeliveryJob listing for Kyber operators."""
    _require_operator(request)
    filters: dict[str, Any] = {}
    if state:
        filters["state"] = state
    if tenant_id:
        filters["tenant_id"] = tenant_id
    if provider_adapter:
        filters["provider_adapter"] = provider_adapter
    # Support both offset and page-based pagination
    effective_offset = offset if offset else (page - 1) * limit
    results = await _job_repo.find_many(filters=filters, limit=limit, offset=effective_offset)
    return APIResponse(data={"items": results}).to_dict()
