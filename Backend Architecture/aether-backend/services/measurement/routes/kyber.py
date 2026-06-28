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


# ── Campaign Registry Health (operator) ──────────────────────────────────────

class CampaignReprocessRequest(BaseModel):
    limit: int = Field(500, ge=1, le=5000, description="Max spend records to reprocess")
    dry_run: bool = False


@router.get("/campaign/fleet-health")
async def campaign_fleet_health(request: Request):
    """Fleet-wide campaign resolution health for operator dashboard."""
    _require_kyber_tenant(request)
    try:
        from services.campaign.registry import CampaignRegistryService
        registry = CampaignRegistryService()
        # Registry quality is tenant-scoped; use requesting tenant as representative
        tenant = getattr(request.state, "tenant", None)
        quality = await registry.get_mapping_quality(tenant.tenant_id if tenant else "system")
        return APIResponse(data={
            "scope": "fleet",
            "quality": quality,
        }).to_dict()
    except Exception as exc:
        logger.warning("campaign_fleet_health_error: %s", exc)
        return APIResponse(data={"scope": "fleet", "quality": {}, "error": str(exc)}).to_dict()


@router.get("/campaign/tenant/{tenant_id_param}")
async def campaign_tenant_health(tenant_id_param: str, request: Request):
    """Per-tenant campaign resolution health drill-down."""
    kyber_tenant = _require_kyber_tenant(request)
    if kyber_tenant.tenant_id != tenant_id_param:
        from shared.common.common import ForbiddenError
        raise ForbiddenError("Cannot view another tenant's campaign health")

    try:
        from services.campaign.registry import CampaignRegistryService
        registry = CampaignRegistryService()
        quality = await registry.get_mapping_quality(tenant_id_param)
        reviews = await registry.list_mapping_reviews(tenant_id_param, status="open", limit=20)
        return APIResponse(data={
            "tenant_id": tenant_id_param,
            "quality": quality,
            "open_reviews_sample": reviews[:20],
        }).to_dict()
    except Exception as exc:
        logger.warning("campaign_tenant_health_error tenant=%s: %s", tenant_id_param, exc)
        return APIResponse(data={"tenant_id": tenant_id_param, "error": str(exc)}).to_dict()


@router.post("/campaign/tenant/{tenant_id_param}/reprocess")
async def campaign_tenant_reprocess(
    tenant_id_param: str,
    request: Request,
    body: CampaignReprocessRequest,
):
    """Trigger bounded campaign resolution reprocessing for a tenant (operator-only)."""
    kyber_tenant = _require_kyber_tenant(request)
    if kyber_tenant.tenant_id != tenant_id_param:
        from shared.common.common import ForbiddenError
        raise ForbiddenError("Cannot reprocess another tenant's campaign data")

    logger.info(
        "campaign_reprocess_requested tenant=%s limit=%d dry_run=%s operator=%s",
        tenant_id_param, body.limit, body.dry_run, kyber_tenant.tenant_id,
    )

    from shared.logger.logger import metrics as _metrics
    _metrics.increment("campaign_reprocess_requested_total", labels={"tenant_id": tenant_id_param})

    # Run bounded reprocessing inline as a background task so the HTTP response
    # returns immediately while work proceeds.
    import asyncio as _asyncio

    async def _run_backfill():
        try:
            from repositories.repos import get_pool
            from services.campaign.registry import CampaignRegistryService
            from services.campaign.normalization import normalize_platform, normalize_external_id
            pool = await get_pool()
            if pool is None:
                return
            registry = CampaignRegistryService()
            rows = await pool.fetch(
                """
                SELECT spend_record_id, tenant_id, platform, ad_account_id,
                       campaign_id, external_campaign_id, source_connector_id
                FROM spend_records
                WHERE tenant_id = $1
                  AND (campaign_resolution_status = 'not_applicable' OR campaign_resolution_status IS NULL)
                ORDER BY spend_record_id
                LIMIT $2
                """,
                tenant_id_param, body.limit,
            )
            resolved = 0
            for row in rows:
                if body.dry_run:
                    resolved += 1
                    continue
                try:
                    provider_id = row["external_campaign_id"] or str(row["campaign_id"] or "")
                    if not provider_id:
                        continue
                    campaign = await registry.upsert_external_campaign(
                        tenant_id=row["tenant_id"],
                        platform=row["platform"] or "unknown",
                        external_account_id=str(row["ad_account_id"] or ""),
                        external_campaign_id=provider_id,
                        source_connector_id=row["source_connector_id"],
                    )
                    await pool.execute(
                        """
                        UPDATE spend_records
                        SET campaign_id = $1, external_campaign_id = $2,
                            campaign_resolution_status = 'resolved',
                            campaign_resolution_method = 'kyber_reprocess',
                            campaign_resolution_version = '1.0'
                        WHERE spend_record_id = $3
                        """,
                        str(campaign["campaign_id"]), provider_id, row["spend_record_id"],
                    )
                    resolved += 1
                except Exception as exc:
                    logger.warning("reprocess row failed: %s", exc)
            _metrics.increment("campaign_reprocess_completed_total", labels={"tenant_id": tenant_id_param})
            logger.info("campaign_reprocess_complete tenant=%s resolved=%d dry_run=%s", tenant_id_param, resolved, body.dry_run)
        except Exception as exc:
            _metrics.increment("campaign_reprocess_failed_total", labels={"tenant_id": tenant_id_param})
            logger.error("campaign_reprocess_failed tenant=%s error=%s", tenant_id_param, exc)

    _asyncio.ensure_future(_run_backfill())

    return APIResponse(data={
        "tenant_id": tenant_id_param,
        "limit": body.limit,
        "dry_run": body.dry_run,
        "status": "running",
        "message": "Reprocessing started in background. Monitor campaign_reprocess_completed_total metric.",
    }).to_dict()


@router.get("/campaign/audit")
async def campaign_audit_log(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
):
    """Audit log for manual mapping mutations (resolve review, create alias, etc.)."""
    _require_kyber_tenant(request)
    # Audit entries are written to campaign_resolution_reviews.resolved_by/resolved_at.
    # This endpoint surfaces the most recent resolved reviews as an audit trail.
    try:
        from services.campaign.registry import CampaignRegistryService
        registry = CampaignRegistryService()
        tenant = getattr(request.state, "tenant", None)
        resolved = await registry.list_mapping_reviews(
            tenant.tenant_id if tenant else "system",
            status="resolved",
            limit=limit,
        )
        return APIResponse(data={
            "audit_entries": resolved,
            "count": len(resolved),
        }).to_dict()
    except Exception as exc:
        logger.warning("campaign_audit_log_error: %s", exc)
        return APIResponse(data={"audit_entries": [], "error": str(exc)}).to_dict()
