"""
Aether Service — SDK Drift Detection Routes

Endpoints:
    POST /v1/diagnostics/sdk/drift/analyze    Admin — run drift analysis for an SDK instance
    GET  /v1/diagnostics/sdk/drift/incidents  List drift incidents for tenant
    GET  /v1/diagnostics/sdk/drift/report     Aggregate drift report for tenant
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger
from shared.observability import trace_request, emit_latency

from services.sdk_drift.service import get_sdk_drift_detector
from services.sdk_health.service import get_sdk_health_service

logger = get_logger("aether.service.sdk_drift.routes")
router = APIRouter(
    prefix="/v1/diagnostics/sdk/drift",
    tags=["SDK — Drift Detection"],
)


class DriftAnalyzeRequest(BaseModel):
    sdk_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: Optional[str] = Field(default=None)


@router.post("/analyze")
async def analyze_drift(body: DriftAnalyzeRequest, request: Request):
    """
    Admin: run all drift checks against the most recent heartbeat for the given SDK.

    The caller may optionally specify a `tenant_id`; otherwise defaults to the
    caller's own tenant.
    """
    ctx = trace_request(request, service="sdk_drift")
    caller = request.state.tenant
    caller.require_permission("admin")

    target_tenant = body.tenant_id or caller.tenant_id

    # Retrieve latest heartbeat
    health_svc = get_sdk_health_service()
    score = await health_svc.score_sdk(body.sdk_id, target_tenant)
    if score is None:
        return APIResponse(data={
            "sdk_id": body.sdk_id,
            "incidents": [],
            "message": "No heartbeat found for this SDK instance.",
        }).to_dict()

    # Pull heartbeat raw data from store
    heartbeat_store = health_svc._heartbeat_store
    hb_raw = await heartbeat_store.get(
        health_svc._heartbeat_key(target_tenant, body.sdk_id)
    )
    if hb_raw is None:
        return APIResponse(data={
            "sdk_id": body.sdk_id,
            "incidents": [],
            "message": "Heartbeat expired from store.",
        }).to_dict()

    detector = get_sdk_drift_detector()
    incidents = await detector.run_all_checks(hb_raw)

    emit_latency("sdk_drift_analyze", ctx.elapsed_ms())
    return APIResponse(data={
        "sdk_id": body.sdk_id,
        "tenant_id": target_tenant,
        "incidents_detected": len(incidents),
        "incidents": [i.to_dict() for i in incidents],
    }).to_dict()


@router.get("/incidents")
async def list_incidents(
    request: Request,
    drift_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
):
    """List drift incidents for the caller's tenant."""
    ctx = trace_request(request, service="sdk_drift")
    tenant = request.state.tenant

    if limit < 1 or limit > 500:
        raise BadRequestError("limit must be between 1 and 500")

    detector = get_sdk_drift_detector()
    incidents = await detector.get_incidents(
        tenant_id=tenant.tenant_id,
        drift_type=drift_type,
        severity=severity,
        limit=limit,
    )

    emit_latency("sdk_drift_incidents_list", ctx.elapsed_ms())
    return APIResponse(data={"incidents": incidents, "count": len(incidents)}).to_dict()


@router.get("/report")
async def get_drift_report(request: Request):
    """Aggregate drift report (counts by type and severity) for caller's tenant."""
    ctx = trace_request(request, service="sdk_drift")
    tenant = request.state.tenant

    detector = get_sdk_drift_detector()
    report = await detector.get_report(tenant.tenant_id)

    emit_latency("sdk_drift_report", ctx.elapsed_ms())
    return APIResponse(data=report).to_dict()
