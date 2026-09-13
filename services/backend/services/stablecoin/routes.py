"""Stablecoin Intelligence tenant API — /v1/stablecoins.

Read-only intelligence plus observation intake. INVARIANT: these routes
never originate, sign, or settle transfers (execution_by_aether=False is
enforced at the model boundary and re-checked per request).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from config.settings import settings
from repositories.stablecoin_repos import (
    FlowAggregateRepo,
    ReconciliationRepo,
    StablecoinObservationRepo,
    SupportAssertionRepo,
    ValuationSnapshotRepo,
)
from shared.auth.auth import Permissions
from services.stablecoin.foundation import (
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    require_flag,
    require_permission as _require_perm,
    validate_payload_tenant,
)
from services.stablecoin.models import (
    StablecoinFlowComputeRequest,
    StablecoinObservationIngest,
    StablecoinSupportRequest,
    StablecoinValuationRequest,
)
from services.stablecoin.flows import FlowService
from services.stablecoin.registry import StablecoinRegistry
from services.stablecoin.service import StablecoinObservationService
from services.stablecoin.support import SupportService
from services.stablecoin.valuation import ValuationService

router = APIRouter(prefix="/v1/stablecoins", tags=["stablecoins"])


def _gate(request: Request, permission: str = Permissions.STABLECOINS_READ) -> str:
    require_flag(settings.stablecoin.api_enabled, "Stablecoin Intelligence")
    _require_perm(request, permission)
    return _tenant_id(request)


def _meter(name: str, tenant_id: str) -> None:
    """Best-effort usage metering — never blocks the request path."""
    try:
        from shared.logger.logger import metrics
        metrics.increment(name)
    except Exception:
        pass


# ── Reference reads ─────────────────────────────────────────────────────────

@router.get("/assets")
async def list_assets(
    request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    _gate(request)
    registry = StablecoinRegistry()
    items = await registry.assets.find_many(limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@router.get("/deployments")
async def list_deployments(
    request: Request,
    canonical_asset_id: Optional[str] = None,
    chain_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    _gate(request)
    registry = StablecoinRegistry()
    filters: dict = {}
    if canonical_asset_id:
        filters["canonical_asset_id"] = canonical_asset_id
    if chain_id:
        filters["chain_id"] = chain_id
    items = await registry.deployments.find_many(filters or None, limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


# ── Tenant-scoped reads ─────────────────────────────────────────────────────

@router.get("/observations")
async def list_observations(
    request: Request,
    deployment_id: Optional[str] = None,
    finality_status: Optional[str] = None,
    observation_type: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict = {"tenant_id": tenant_id}
    if deployment_id:
        filters["deployment_id"] = deployment_id
    if finality_status:
        filters["finality_status"] = finality_status
    if observation_type:
        filters["observation_type"] = observation_type
    rows = await StablecoinObservationRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/valuations")
async def list_valuations(
    request: Request,
    deployment_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict = {"tenant_id": tenant_id}
    if deployment_id:
        filters["deployment_id"] = deployment_id
    rows = await ValuationSnapshotRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/support")
async def list_support_assertions(
    request: Request,
    deployment_id: Optional[str] = None,
    support_status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict = {"tenant_id": tenant_id}
    if deployment_id:
        filters["deployment_id"] = deployment_id
    if support_status:
        filters["support_status"] = support_status
    rows = await SupportAssertionRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/flows")
async def list_flow_aggregates(
    request: Request,
    canonical_asset_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict = {"tenant_id": tenant_id}
    if canonical_asset_id:
        filters["canonical_asset_id"] = canonical_asset_id
    rows = await FlowAggregateRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/reconciliation")
async def list_reconciliation_records(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict = {"tenant_id": tenant_id}
    if status:
        filters["status"] = status
    rows = await ReconciliationRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


# ── Observation intake ──────────────────────────────────────────────────────

@router.post("/observations", status_code=201)
async def ingest_observation(payload: StablecoinObservationIngest, request: Request):
    tenant_id = _gate(request)
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    require_flag(settings.stablecoin.ingestion_enabled, "Stablecoin ingestion")
    result = await StablecoinObservationService().ingest_observation(tenant_id, payload)
    _meter("stablecoin_observation_ingested", tenant_id)
    return result


@router.post("/valuations", status_code=201)
async def record_valuation(payload: StablecoinValuationRequest, request: Request):
    tenant_id = _gate(request)
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    require_flag(settings.stablecoin.valuation_enabled, "Stablecoin valuation")
    return await ValuationService().record_valuation(tenant_id, payload)


@router.post("/support", status_code=201)
async def assert_support(payload: StablecoinSupportRequest, request: Request):
    tenant_id = _gate(request, Permissions.STABLECOINS_MANAGE_SUPPORT)
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    return await SupportService().assert_support(tenant_id, payload)


@router.post("/flows/compute", status_code=201)
async def compute_flows(payload: StablecoinFlowComputeRequest, request: Request):
    tenant_id = _gate(request)
    validate_payload_tenant(payload, tenant_id)
    require_flag(settings.stablecoin.flows_enabled, "Stablecoin flows")
    result = await FlowService().compute_flow_aggregate(tenant_id, payload)
    _meter("stablecoin_flow_materialized", tenant_id)
    return result


def _stringify(rows: list[dict]) -> list[dict]:
    """Decimal-safe response encoding: canonical amounts as strings."""
    from decimal import Decimal

    out = []
    for row in rows:
        encoded = {}
        for key, value in row.items():
            encoded[key] = str(value) if isinstance(value, Decimal) else value
        out.append(encoded)
    return out
