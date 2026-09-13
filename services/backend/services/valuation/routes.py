"""Event-time valuation API — /v1/valuation.

Read endpoints expose tenant-scoped valuation snapshots / the tenant's current
value policy and the global append-only market-price observations; write
endpoints observe prices and produce + persist valuation snapshots. INVARIANT:
the valuation domain OBSERVES and REPORTS — it never originates, signs, or
settles a transfer. Every persisted snapshot carries execution_by_aether False.

Gating mirrors services/assets/routes.py and the stablecoin domain: every route
fail-closes on ``settings.valuation.api_enabled`` (default OFF), writes
additionally require ``settings.valuation.ingestion_enabled`` + ADMIN. Reads
require the base READ permission. shared/auth has no ``valuation:*`` scope yet,
so this surface reuses the existing constants rather than inventing one.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from services.valuation.models import (
    MarketPriceObservation,
    ValuationBasis,
)
from services.valuation.price_providers import PROVIDERS
from services.valuation.service import ValuationService
from services.stablecoin.foundation import (
    active_tenant_id as _tenant_id,
    require_flag,
    require_permission as _require_perm,
)
from shared.auth.auth import Permissions

router = APIRouter(prefix="/v1/valuation", tags=["valuation"])


def _gate(request: Request, permission: str = Permissions.READ) -> str:
    require_flag(settings.valuation.api_enabled, "Event-time valuation")
    _require_perm(request, permission)
    return _tenant_id(request)


def _gate_ingestion(request: Request) -> str:
    require_flag(settings.valuation.api_enabled, "Event-time valuation")
    require_flag(settings.valuation.ingestion_enabled, "Valuation ingestion")
    return _tenant_id(request)


def _service() -> ValuationService:
    # Route singleton: typed repos share the process-wide in-memory stores under
    # AETHER_ENV=local and the shared pool in staging/production, so one instance
    # observes one consistent view (mirrors the composer/route-singleton pattern).
    return ValuationService()


def _http_bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


# ── Request models ───────────────────────────────────────────────────────────
# MarketPriceObservation and ValuationSnapshot already exist in
# services/valuation/models.py and are reused verbatim; only the route-specific
# write envelopes are defined here.

class ValueRequest(BaseModel):
    """A value-and-persist request.

    ``native`` is a value.ts-style native payload (amount + currency +
    optional canonical_asset_id/deployment/role). ``native`` is opaque
    observational input preserved verbatim in the snapshot evidence; the
    service canonicalizes it through the real registry (never guesses).
    """

    model_config = ConfigDict(extra="ignore")

    native: dict[str, Any]
    effective_at: str
    reporting_asset_id: Optional[str] = None
    deployment_id: Optional[str] = None
    valuation_basis: ValuationBasis = "event_time"
    economic_role: Optional[str] = None
    supersedes_snapshot_id: Optional[str] = None


class PolicyWriteRequest(BaseModel):
    """Upsert the tenant's current value policy (one row per tenant)."""

    model_config = ConfigDict(extra="ignore")

    allowed_reporting_asset_ids: Optional[list[str]] = None
    reporting_asset_id: Optional[str] = None
    provider_chain_policy: Optional[str] = None
    stale_threshold_seconds: Optional[int] = Field(default=None, ge=1)
    fallback_allowed: bool = False


# ── Reads (settings.valuation.api_enabled + READ) ───────────────────────────

@router.get("/snapshots")
async def list_snapshots(
    request: Request,
    canonical_asset_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    tenant_id = _gate(request)
    items = await _service().list_snapshots(
        tenant_id,
        canonical_asset_id=canonical_asset_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"tenant_id": tenant_id, "items": items, "count": len(items)}


@router.get("/snapshots/{valuation_id}")
async def get_snapshot(valuation_id: str, request: Request):
    tenant_id = _gate(request)
    row = await _service().get_snapshot(tenant_id, valuation_id)
    if row is None:
        return {"tenant_id": tenant_id, "valuation_id": valuation_id, "found": False}
    return {"tenant_id": tenant_id, "valuation_id": valuation_id, "found": True, "snapshot": row}


@router.get("/policy")
async def get_policy(request: Request):
    tenant_id = _gate(request)
    policy = await _service().read_policy(tenant_id)
    if policy is None:
        return {"tenant_id": tenant_id, "found": False}
    return {"tenant_id": tenant_id, "found": True, "policy": policy}


@router.get("/observations")
async def list_observations(
    request: Request,
    asset_id: Optional[str] = None,
    provider: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    # Price observations are global market facts (no tenant scope), but reading
    # them still requires the valuation read flag + READ permission.
    _gate(request)
    items = await _service().list_observations(
        asset_id=asset_id, provider=provider, limit=limit, offset=offset,
    )
    return {"items": items, "count": len(items)}


# ── Writes (ingestion_enabled + ADMIN) ───────────────────────────────────────
# Observe + value are observational writes: they append immutable market facts
# and tenant snapshots with execution_by_aether always False.

@router.post("/observe", status_code=201)
async def observe_price(payload: MarketPriceObservation, request: Request):
    """Record one price observation (idempotent single append path)."""
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    if payload.provider not in PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown price provider: {payload.provider!r}",
        )
    try:
        return await _service().record_price_observation(payload)
    except (ValueError, TypeError) as exc:
        raise _http_bad_request(exc) from exc


@router.post("/value", status_code=201)
async def value_native(payload: ValueRequest, request: Request):
    """Canonicalize → value → persist one tenant valuation snapshot.

    Optionally ``supersedes_snapshot_id`` corrects a prior snapshot by
    appending a NEW snapshot (the prior row is flipped to ``superseded`` —
    never updated in place).
    """
    tenant_id = _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    try:
        result = await _service().value_and_persist(
            tenant_id=tenant_id,
            native=payload.native,
            effective_at=payload.effective_at,
            reporting_asset_id=payload.reporting_asset_id,
            deployment_id=payload.deployment_id,
            valuation_basis=payload.valuation_basis,
            economic_role=payload.economic_role or "unknown",
            supersedes_snapshot_id=payload.supersedes_snapshot_id,
        )
    except (ValueError, TypeError) as exc:
        raise _http_bad_request(exc) from exc
    result["tenant_id"] = tenant_id
    return result


@router.put("/policy", status_code=200)
async def put_policy(payload: PolicyWriteRequest, request: Request):
    """Create or update the tenant's current value policy."""
    tenant_id = _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    try:
        result = await _service().upsert_policy(
            tenant_id,
            allowed_reporting_asset_ids=payload.allowed_reporting_asset_ids,
            reporting_asset_id=payload.reporting_asset_id,
            provider_chain_policy=payload.provider_chain_policy,
            stale_threshold_seconds=payload.stale_threshold_seconds,
            fallback_allowed=payload.fallback_allowed,
        )
    except ValueError as exc:
        raise _http_bad_request(exc) from exc
    result["tenant_id"] = tenant_id
    return result
