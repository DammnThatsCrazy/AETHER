"""Kyber (operator) measurement operations — connector management, backfill, recompute."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError, BadRequestError
from shared.logger.logger import get_logger
from services.measurement.repositories.connector_repo import ConnectorRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.engine.attribution_engine import AttributionEngine
from services.measurement.engine.journey_compiler import JourneyCompiler
from services.measurement.engine.gold_materializer import backfill_tenant

logger = get_logger("aether.measurement.routes.kyber")
router = APIRouter(prefix="/v1/kyber/measurement", tags=["Kyber Measurement Ops"])

_connector_repo = ConnectorRepository()
_conversion_repo = ConversionRepository()
_run_repo = AttributionRunRepository()
_journey_repo = JourneyRepository()
_engine = AttributionEngine()
_compiler = JourneyCompiler()


def _require_kyber_tenant(request: Request):
    """Kyber routes require elevated operator context."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class BackfillRequest(BaseModel):
    start_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date: str = Field(..., description="ISO date YYYY-MM-DD")
    model_type: str = "last_touch"


class RecomputeAllRequest(BaseModel):
    model_type: str = "last_touch"
    limit: int = Field(1000, ge=1, le=10000)


# ── Connector operations ──────────────────────────────────────────────────────

@router.post("/connectors/{connector_id}/restart")
async def restart_connector(connector_id: str, request: Request):
    tenant = _require_kyber_tenant(request)
    conn = await _connector_repo.get(tenant.tenant_id, connector_id)
    if conn is None:
        raise NotFoundError("Connector")
    await _connector_repo.set_status(tenant.tenant_id, connector_id, "active")
    return APIResponse(data={"connector_id": connector_id, "status": "active"}).to_dict()


@router.post("/connectors/{connector_id}/backfill")
async def backfill_connector(connector_id: str, request: Request, body: BackfillRequest):
    tenant = _require_kyber_tenant(request)
    conn = await _connector_repo.get(tenant.tenant_id, connector_id)
    if conn is None:
        raise NotFoundError("Connector")

    try:
        start = date.fromisoformat(body.start_date)
        end = date.fromisoformat(body.end_date)
    except ValueError as exc:
        raise BadRequestError(f"Invalid date: {exc}")

    result = await backfill_tenant(tenant.tenant_id, start, end)
    return APIResponse(data={
        "connector_id": connector_id,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "campaign_perf_rows": result.campaign_perf_rows,
        "journey_econ_rows": result.journey_econ_rows,
        "errors": result.errors[:20],
    }).to_dict()


# ── Journey operations ────────────────────────────────────────────────────────

@router.post("/journeys/{journey_id}/rebuild")
async def rebuild_journey(journey_id: str, request: Request):
    tenant = _require_kyber_tenant(request)
    current = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if current is None:
        raise NotFoundError("Journey")

    profile_id = current.get("profile_id") or current.get("cluster_id")
    if not profile_id:
        return APIResponse(data=None, meta={"reason": "no_profile"}).to_dict()

    version = await _compiler.compile_for_profile(
        tenant.tenant_id, profile_id, trigger_reason="operator_rebuild"
    )
    return APIResponse(data=version, meta={"rebuilt": True}).to_dict()


# ── Conversion / attribution operations ──────────────────────────────────────

@router.post("/conversions/{conversion_id}/recompute")
async def recompute_conversion(conversion_id: str, request: Request):
    tenant = _require_kyber_tenant(request)
    try:
        run = await _engine.run_for_conversion(
            tenant.tenant_id, conversion_id, trigger_reason="operator_recompute",
        )
    except ValueError as exc:
        raise NotFoundError("Conversion")
    return APIResponse(data=run, meta={"recomputed": True}).to_dict()


@router.post("/tenants/{tenant_id_param}/recompute-all")
async def recompute_all_for_tenant(
    tenant_id_param: str,
    request: Request,
    body: RecomputeAllRequest,
):
    tenant = _require_kyber_tenant(request)
    # Only allow recompute for own tenant (or kyber admin)
    if tenant.tenant_id != tenant_id_param:
        from shared.common.common import ForbiddenError
        raise ForbiddenError("Cannot recompute another tenant's conversions")

    conversions = await _conversion_repo.list_by_tenant(
        tenant.tenant_id,
        attribution_eligible_only=True,
        limit=body.limit,
    )
    success = 0
    failed = 0
    for conv in conversions:
        try:
            await _engine.run_for_conversion(
                tenant.tenant_id,
                conv.get("conversion_id", ""),
                model_type=body.model_type,
                trigger_reason="operator_bulk_recompute",
            )
            success += 1
        except Exception as exc:
            failed += 1
            logger.warning("Recompute failed: conversion=%s error=%s", conv.get("conversion_id"), exc)

    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "total": len(conversions),
        "success": success,
        "failed": failed,
    }).to_dict()


# ── Observation dashboards ────────────────────────────────────────────────────

@router.get("/overview")
async def kyber_overview(request: Request):
    """Global measurement health for operator dashboard."""
    tenant = _require_kyber_tenant(request)
    connectors = await _connector_repo.list_by_tenant(tenant.tenant_id)
    total = len(connectors)
    healthy = sum(1 for c in connectors if c.get("health_status") == "healthy")
    lagging = sum(1 for c in connectors if c.get("health_status") == "lagging")
    failing = sum(1 for c in connectors if c.get("health_status") in ("error", "unknown"))

    return APIResponse(data={
        "connectors": {
            "total": total,
            "healthy": healthy,
            "lagging": lagging,
            "failing": failing,
        },
        "connectors_list": connectors,
    }).to_dict()


@router.get("/journey-health")
async def journey_health(request: Request):
    """Journey compiler health — throughput, queue depth, quality breakdown, rebuild audit log."""
    tenant = _require_kyber_tenant(request)

    # Page through all current journeys for tenant-wide accuracy.
    # When running without a DB pool the in-memory store ignores the cursor and always
    # returns the same first page, so we cap at one pass in that case.
    from repositories.repos import get_pool as _get_pool
    pool = await _get_pool()
    all_journeys: list[dict] = []
    cursor = None
    while True:
        page = await _journey_repo.list_current(tenant.tenant_id, limit=500, cursor=cursor)
        all_journeys.extend(page)
        if len(page) < 500 or pool is None:
            break
        raw_cursor = page[-1].get("computed_at")
        cursor = raw_cursor.isoformat() if hasattr(raw_cursor, "isoformat") else raw_cursor

    quality_counts: dict[str, int] = {}
    failed_rebuilds: list[dict] = []
    total_steps = 0
    compiler_versions: dict[str, int] = {}

    for j in all_journeys:
        step_count = j.get("step_count") or 0
        cv = j.get("compiler_version") or "unknown"

        # rebuild_reason is always set (it equals trigger_reason), so it cannot
        # distinguish healthy from failed compiles. Use step_count == 0 as the
        # only available failure signal; all non-empty journeys are classified complete.
        qs = "empty" if step_count == 0 else "complete"

        quality_counts[qs] = quality_counts.get(qs, 0) + 1
        total_steps += step_count
        compiler_versions[cv] = compiler_versions.get(cv, 0) + 1
        if qs == "empty":
            failed_rebuilds.append({
                "journey_id": j.get("journey_id"),
                "profile_id": j.get("profile_id"),
                "quality_status": qs,
                "compiler_version": cv,
                "computed_at": j.get("computed_at"),
            })

    avg_steps = round(total_steps / len(all_journeys), 1) if all_journeys else 0

    return APIResponse(data={
        "summary": {
            "total_journeys": len(all_journeys),
            "avg_steps_per_journey": avg_steps,
            "quality_breakdown": quality_counts,
            "compiler_versions": compiler_versions,
        },
        "failed_or_partial": failed_rebuilds[:50],
        "web3_finality_backlog": None,
        "rebuild_queue_depth": None,
    }).to_dict()


@router.get("/tenants/{tenant_id_param}")
async def kyber_tenant_drill_down(tenant_id_param: str, request: Request):
    """Per-tenant measurement drill-down."""
    tenant = _require_kyber_tenant(request)
    if tenant.tenant_id != tenant_id_param:
        from shared.common.common import ForbiddenError
        raise ForbiddenError("Cannot view another tenant's measurement data")

    connectors = await _connector_repo.list_by_tenant(tenant.tenant_id)
    runs = await _run_repo.list_runs(tenant.tenant_id, limit=100)
    journeys = await _journey_repo.list_current(tenant.tenant_id, limit=100)

    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "connectors": connectors,
        "recent_runs": runs[:10],
        "active_journeys": len(journeys),
    }).to_dict()
