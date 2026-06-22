"""Measurement quality, freshness, coverage, and health endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.connector_repo import ConnectorRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.spend_repo import SpendRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = get_logger("aether.measurement.routes.quality")
router = APIRouter(prefix="/v1/measurement", tags=["Measurement Quality"])

_run_repo = AttributionRunRepository()
_conversion_repo = ConversionRepository()
_connector_repo = ConnectorRepository()
_spend_repo = SpendRepository()
_touchpoint_repo = TouchpointRepository()


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


@router.get("/overview")
async def measurement_overview(
    request: Request,
    window_days: int = Query(30, ge=1, le=365),
):
    """High-level measurement health: spend, attributed revenue, ROAS, coverage, freshness."""
    tenant = _require_tenant(request)
    tid = tenant.tenant_id

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=window_days)

    # Connector health
    connectors = await _connector_repo.list_by_tenant(tid)
    healthy = sum(1 for c in connectors if c.get("health_status") == "healthy")
    total_connectors = len(connectors)

    # Attribution coverage (% conversions with active run)
    conversions = await _conversion_repo.list_by_tenant(
        tid,
        after_occurred=period_start,
        attribution_eligible_only=True,
        limit=5000,
    )
    attributed = 0
    for conv in conversions:
        run = await _run_repo.get_active_run(tid, conv.get("conversion_id", ""))
        if run and run.get("status") == "complete":
            attributed += 1

    attribution_coverage = (attributed / len(conversions)) if conversions else None

    # Data freshness: newest touchpoint
    freshness_status = "not_provisioned"
    last_touchpoint_at: Optional[str] = None
    if connectors and any(c.get("last_success_at") for c in connectors):
        latest = max(
            (c.get("last_success_at", "") for c in connectors if c.get("last_success_at")),
            default=None,
        )
        last_touchpoint_at = latest
        if latest:
            age_hours = (now - datetime.fromisoformat(str(latest).replace("Z", "+00:00"))).total_seconds() / 3600
            freshness_status = "complete" if age_hours < 2 else ("partial" if age_hours < 24 else "stale")

    quality_status = "complete"
    warnings: list[str] = []
    if total_connectors == 0:
        quality_status = "not_provisioned"
        warnings.append("No measurement connectors configured")
    elif healthy < total_connectors:
        quality_status = "degraded"
        warnings.append(f"{total_connectors - healthy} connector(s) unhealthy")
    if attribution_coverage is not None and attribution_coverage < 0.9:
        quality_status = "partial"
        warnings.append(f"Attribution coverage {attribution_coverage:.0%} (< 90%)")

    return APIResponse(data={
        "window_days": window_days,
        "quality": {
            "status": quality_status,
            "freshness": last_touchpoint_at,
            "attribution_coverage": attribution_coverage,
            "connector_health": {
                "total": total_connectors,
                "healthy": healthy,
            },
            "warnings": warnings,
        },
        "conversions": {
            "total": len(conversions),
            "attributed": attributed,
        },
    }).to_dict()


@router.get("/quality")
async def measurement_quality(
    request: Request,
    window_days: int = Query(30, ge=1, le=365),
):
    """Detailed quality metrics per dimension."""
    tenant = _require_tenant(request)
    tid = tenant.tenant_id
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=window_days)

    runs = await _run_repo.list_runs(tid, limit=5000)
    complete = sum(1 for r in runs if r.get("status") == "complete")
    failed = sum(1 for r in runs if r.get("status") == "failed")

    spend_rows = await _spend_repo.list_by_tenant(tid, period_start=period_start, limit=5000)
    connectors = await _connector_repo.list_by_tenant(tid)

    return APIResponse(data={
        "window_days": window_days,
        "attribution": {
            "total_runs": len(runs),
            "complete_runs": complete,
            "failed_runs": failed,
            "success_rate": (complete / len(runs)) if runs else None,
        },
        "spend": {
            "record_count": len(spend_rows),
            "connector_count": len(connectors),
        },
    }).to_dict()


@router.get("/freshness")
async def measurement_freshness(request: Request):
    """Per-connector freshness — last sync age in minutes."""
    tenant = _require_tenant(request)
    connectors = await _connector_repo.list_by_tenant(tenant.tenant_id)
    now = datetime.now(timezone.utc)

    results = []
    for c in connectors:
        last_sync = c.get("last_sync_at")
        age_minutes = None
        if last_sync:
            try:
                ts = datetime.fromisoformat(str(last_sync).replace("Z", "+00:00"))
                age_minutes = int((now - ts).total_seconds() / 60)
            except Exception:
                pass
        results.append({
            "connector_id": c.get("connector_id"),
            "connector_type": c.get("connector_type"),
            "name": c.get("name"),
            "health_status": c.get("health_status"),
            "last_sync_at": last_sync,
            "age_minutes": age_minutes,
        })

    return APIResponse(data=results).to_dict()


@router.get("/health")
async def measurement_health(request: Request):
    """Connector health statuses."""
    tenant = _require_tenant(request)
    connectors = await _connector_repo.list_by_tenant(tenant.tenant_id)
    by_status: dict[str, int] = {}
    for c in connectors:
        status = c.get("health_status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    return APIResponse(data={
        "connectors": connectors,
        "summary": by_status,
        "total": len(connectors),
    }).to_dict()
