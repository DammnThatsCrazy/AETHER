"""Derivatives Intelligence tenant API — /v1/derivatives.

Read-only intelligence plus canonical observation intake. INVARIANT: no
endpoint places, amends, cancels, or closes anything; account links carry
read-only credential authority only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from config.settings import settings
from repositories.derivatives_repos import (
    FillRepo,
    InstrumentRepo,
    MarketRepo,
    OrderRepo,
    PnlSnapshotRepo,
    PositionRepo,
    ReconciliationVarianceRepo,
    TradingAccountRepo,
    VenueRepo,
)
from shared.auth.auth import Permissions
from services.derivatives.foundation import (
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    deterministic_idempotency_key,
    require_flag,
    require_permission as _require_perm,
    require_read_only_authority,
    utc_now_iso,
    validate_payload_tenant,
)
from services.derivatives.models import AccountLinkRequest, DerivativesObservationIn

router = APIRouter(prefix="/v1/derivatives", tags=["derivatives"])

# Event intake routing: canonical event name -> (repo factory, id field)
_FACT_ROUTES = {
    "derivatives_order_observed": (OrderRepo, "order_id"),
    "derivatives_order_updated_observed": (OrderRepo, "order_id"),
    "derivatives_order_cancelled_observed": (OrderRepo, "order_id"),
    "derivatives_order_rejected_observed": (OrderRepo, "order_id"),
    "derivatives_order_expired_observed": (OrderRepo, "order_id"),
    "derivatives_fill_observed": (FillRepo, "fill_id"),
    "derivatives_position_opened_observed": (PositionRepo, "position_id"),
    "derivatives_position_increased_observed": (PositionRepo, "position_id"),
    "derivatives_position_reduced_observed": (PositionRepo, "position_id"),
    "derivatives_position_closed_observed": (PositionRepo, "position_id"),
    "derivatives_position_liquidated_observed": (PositionRepo, "position_id"),
}


def _gate(request: Request, permission: str = Permissions.DERIVATIVES_READ) -> str:
    require_flag(settings.derivatives.api_enabled, "Derivatives Intelligence")
    _require_perm(request, permission)
    return _tenant_id(request)


def _meter(name: str) -> None:
    try:
        from shared.logger.logger import metrics
        metrics.increment(name)
    except Exception:
        pass


def _stringify(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        out.append({
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in row.items()
        })
    return out


async def _tenant_list(
    repo_cls, request: Request, filters: Optional[dict], limit: int, offset: int,
):
    tenant_id = _gate(request)
    merged = {"tenant_id": tenant_id, **(filters or {})}
    rows = await repo_cls().find_many(merged, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


# ── Global reference reads ───────────────────────────────────────────────────

@router.get("/venues")
async def list_venues(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await VenueRepo().find_many(limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/instruments")
async def list_instruments(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await InstrumentRepo().find_many(limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/markets")
async def list_markets(
    request: Request, venue_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    _gate(request)
    filters = {"venue_id": venue_id} if venue_id else None
    rows = await MarketRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


# ── Tenant-scoped reads ──────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    return await _tenant_list(TradingAccountRepo, request, None, limit, offset)


@router.get("/orders")
async def list_orders(
    request: Request, trading_account_id: Optional[str] = None,
    order_status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters: dict = {}
    if trading_account_id:
        filters["trading_account_id"] = trading_account_id
    if order_status:
        filters["order_status"] = order_status
    return await _tenant_list(OrderRepo, request, filters, limit, offset)


@router.get("/fills")
async def list_fills(
    request: Request, trading_account_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters = {"trading_account_id": trading_account_id} if trading_account_id else None
    return await _tenant_list(FillRepo, request, filters, limit, offset)


@router.get("/positions")
async def list_positions(
    request: Request, trading_account_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters: dict = {}
    if trading_account_id:
        filters["trading_account_id"] = trading_account_id
    if status:
        filters["status"] = status
    return await _tenant_list(PositionRepo, request, filters, limit, offset)


@router.get("/pnl")
async def list_pnl_snapshots(
    request: Request, trading_account_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    require_flag(settings.derivatives.pnl_enabled, "Derivatives P&L")
    filters = {"trading_account_id": trading_account_id} if trading_account_id else None
    return await _tenant_list(PnlSnapshotRepo, request, filters, limit, offset)


@router.get("/reconciliation/variances")
async def list_variances(
    request: Request, status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters = {"status": status} if status else None
    return await _tenant_list(ReconciliationVarianceRepo, request, filters, limit, offset)


# ── Intake ───────────────────────────────────────────────────────────────────

@router.post("/accounts/link", status_code=201)
async def link_account(payload: AccountLinkRequest, request: Request):
    """Observe a read-only account link. Aether stores a credential
    REFERENCE at most — never a secret, never trade/withdraw authority."""
    tenant_id = _gate(request, Permissions.DERIVATIVES_CONNECT)
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    require_read_only_authority(payload.authority_type)

    basis = f"{tenant_id}|{payload.venue_id}|{payload.external_account_ref}"
    record = {
        "tenant_id": tenant_id,
        "trading_account_id": f"dacct_{deterministic_idempotency_key(basis)[:24]}",
        "venue_id": payload.venue_id,
        "venue_deployment_id": payload.venue_deployment_id,
        "external_account_ref": payload.external_account_ref,
        "owner_entity_kind": payload.owner_entity_kind,
        "owner_entity_id": payload.owner_entity_id,
        "credential_reference_id": payload.credential_reference_id,
        "connector_state": "configured",
        "data_quality_state": "complete",
        "idempotency_key": deterministic_idempotency_key(basis),
        "execution_by_aether": False,
        "created_at": utc_now_iso(),
    }
    inserted = await TradingAccountRepo().insert(record)
    _meter("derivatives_event_ingested")
    return {
        "inserted": inserted,
        "trading_account_id": record["trading_account_id"],
        "authority_type": "read_only",
    }


@router.post("/observations", status_code=201)
async def ingest_observation(payload: DerivativesObservationIn, request: Request):
    """Canonical derivatives event intake (order/fill/position facts)."""
    tenant_id = _gate(request)
    require_flag(settings.derivatives.runtime_enabled, "Derivatives runtime")
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    _check_no_execution(payload.payload)

    from services.ingestion.generated_registry import CANONICAL_EVENT_TYPES

    if payload.event_name not in CANONICAL_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown event type: {payload.event_name}")
    route = _FACT_ROUTES.get(payload.event_name)
    if route is None:
        raise HTTPException(
            status_code=422,
            detail=f"{payload.event_name} is not ingestable via /observations",
        )
    repo_cls, id_field = route
    entity_id = payload.payload.get(id_field)
    if not entity_id:
        raise HTTPException(status_code=422, detail=f"payload missing {id_field}")

    basis = f"{tenant_id}|{payload.event_name}|{entity_id}|{payload.payload.get('order_status') or payload.payload.get('status') or ''}"
    record = {
        "tenant_id": tenant_id,
        "idempotency_key": deterministic_idempotency_key(basis),
        "execution_by_aether": False,
        **{k: v for k, v in payload.payload.items() if k != "execution_by_aether"},
    }
    repo = repo_cls()
    record = {k: v for k, v in record.items() if k in repo.columns}
    record.setdefault(id_field, entity_id)
    inserted = await repo.insert(record)
    _meter("derivatives_event_ingested")
    return {"inserted": inserted, id_field: entity_id, "event_name": payload.event_name}
