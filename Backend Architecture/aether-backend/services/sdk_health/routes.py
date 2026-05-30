"""
Aether Service — SDK Health Routes

Endpoints:
    POST /v1/diagnostics/sdk/heartbeat       Ingest SDK heartbeat (API key auth)
    GET  /v1/diagnostics/sdk/health          Fleet status for caller's tenant
    GET  /v1/diagnostics/sdk/health/{sdk_id} Single SDK health score
    GET  /v1/diagnostics/sdk/fleet           Admin — cross-tenant fleet summary
    GET  /v1/diagnostics/sdk/silent          SDKs that have gone silent
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger
from shared.observability import trace_request, emit_latency

from services.sdk_health.service import SDKHeartbeat, get_sdk_health_service

logger = get_logger("aether.service.sdk_health.routes")
router = APIRouter(
    prefix="/v1/diagnostics/sdk",
    tags=["SDK — Health Monitoring"],
)


class HeartbeatRequest(BaseModel):
    sdk_id: str = Field(..., min_length=1, max_length=128)
    sdk_version: str = Field(..., min_length=1, max_length=64)
    platform: str = Field(..., pattern="^(web|ios|android|react-native|node|other)$")
    app_version: str = Field(default="")
    queue_depth: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    dropped_events: int = Field(default=0, ge=0)
    endpoint_latency_ms: float = Field(default=0.0, ge=0.0)
    ingestion_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    schema_hash: str = Field(default="")
    auth_valid: bool = Field(default=True)
    consent_valid: bool = Field(default=True)
    wallet_connected: bool = Field(default=False)
    config_version: str = Field(default="0")
    rollout_cohort: str = Field(default="default")


@router.post("/heartbeat")
async def ingest_heartbeat(body: HeartbeatRequest, request: Request):
    """
    Ingest a signed health heartbeat from an SDK instance.

    Called by SDK health agents every ~60 s. No admin permission required —
    only a valid API key/JWT for the tenant is needed.
    """
    ctx = trace_request(request, service="sdk_health")
    tenant = request.state.tenant

    hb = SDKHeartbeat(
        tenant_id=tenant.tenant_id,
        sdk_id=body.sdk_id,
        sdk_version=body.sdk_version,
        platform=body.platform,
        app_version=body.app_version,
        queue_depth=body.queue_depth,
        retry_count=body.retry_count,
        dropped_events=body.dropped_events,
        endpoint_latency_ms=body.endpoint_latency_ms,
        ingestion_success_rate=body.ingestion_success_rate,
        schema_hash=body.schema_hash,
        auth_valid=body.auth_valid,
        consent_valid=body.consent_valid,
        wallet_connected=body.wallet_connected,
        config_version=body.config_version,
        rollout_cohort=body.rollout_cohort,
    )

    svc = get_sdk_health_service()
    score = await svc.ingest_heartbeat(hb)

    emit_latency("sdk_heartbeat_ingest", ctx.elapsed_ms())
    return APIResponse(data={
        "sdk_id": hb.sdk_id,
        "score": score.composite,
        "status": score.status,
        "ack": True,
    }).to_dict()


@router.get("/health")
async def get_fleet_health(request: Request):
    """Return fleet health summary for the caller's tenant."""
    ctx = trace_request(request, service="sdk_health")
    tenant = request.state.tenant

    svc = get_sdk_health_service()
    fleet = await svc.get_fleet_status(tenant.tenant_id)

    emit_latency("sdk_fleet_health_fetch", ctx.elapsed_ms())
    return APIResponse(data=fleet.to_dict()).to_dict()


@router.get("/health/{sdk_id}")
async def get_sdk_health(sdk_id: str, request: Request):
    """Return health score for a specific SDK instance."""
    ctx = trace_request(request, service="sdk_health")
    tenant = request.state.tenant

    if not sdk_id:
        raise BadRequestError("sdk_id is required")

    svc = get_sdk_health_service()
    score = await svc.score_sdk(sdk_id, tenant.tenant_id)

    if score is None:
        return APIResponse(data={"sdk_id": sdk_id, "status": "unknown", "score": None}).to_dict()

    emit_latency("sdk_score_fetch", ctx.elapsed_ms())
    return APIResponse(data=score.to_dict()).to_dict()


@router.get("/fleet")
async def get_admin_fleet(request: Request, tenant_id: Optional[str] = None):
    """
    Admin-only: cross-tenant fleet summary.

    Optionally filter by tenant_id. Without it, returns the caller's tenant fleet.
    """
    ctx = trace_request(request, service="sdk_health")
    caller = request.state.tenant
    caller.require_permission("admin")

    target_tenant = tenant_id or caller.tenant_id

    svc = get_sdk_health_service()
    fleet = await svc.get_fleet_status(target_tenant)

    emit_latency("sdk_admin_fleet_fetch", ctx.elapsed_ms())
    return APIResponse(data=fleet.to_dict()).to_dict()


@router.get("/silent")
async def get_silent_sdks(request: Request):
    """Return SDK instances that have gone silent (no heartbeat within threshold)."""
    ctx = trace_request(request, service="sdk_health")
    tenant = request.state.tenant

    svc = get_sdk_health_service()
    silent = await svc.detect_silent_sdks(tenant.tenant_id)

    emit_latency("sdk_silent_fetch", ctx.elapsed_ms())
    return APIResponse(data={"silent_sdks": silent, "count": len(silent)}).to_dict()
