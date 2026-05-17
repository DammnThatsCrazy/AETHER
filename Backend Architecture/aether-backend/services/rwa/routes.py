"""
Aether Service — RWA Intelligence Graph API

Tokenized real-world asset intelligence: observation, analysis, scoring.
Aether does NOT issue RWAs — this is intelligence only.

Asset management:
    POST /v1/rwa/assets                          Register an RWA asset
    GET  /v1/rwa/assets                          List RWA assets
    GET  /v1/rwa/assets/{id}                     Get asset details

Policy:
    POST /v1/rwa/policies                        Register a compliance policy
    GET  /v1/rwa/assets/{id}/policies            Get policies for an asset
    POST /v1/rwa/simulate-transfer               Simulate transfer policy check

Cashflow:
    POST /v1/rwa/cashflows                       Record a cashflow event
    GET  /v1/rwa/assets/{id}/cashflows            Get cashflow history

Exposure:
    GET  /v1/rwa/exposure/{entity_id}             Get RWA exposure for entity

Scoring:
    GET  /v1/rwa/assets/{id}/reserve-credibility  Reserve credibility score
    GET  /v1/rwa/assets/{id}/redemption-pressure  Redemption pressure score

Holders:
    POST /v1/rwa/holders                          Register a holder record
    GET  /v1/rwa/assets/{id}/holders              Get holders for an asset
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Request, Query
from pydantic import BaseModel

from shared.common.common import APIResponse, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics
from services.rwa.models import (
    RWAAssetCreate, PolicyCreate, CashflowEventCreate,
    PolicySimulation,
)
from services.rwa.engine import (
    register_asset, register_policy, record_cashflow,
    compute_exposure, simulate_transfer,
    score_reserve_credibility, score_redemption_pressure,
    asset_repo, policy_repo, cashflow_repo, holder_repo,
)

logger = get_logger("aether.service.rwa")
router = APIRouter(prefix="/v1/rwa", tags=["RWA Intelligence"])


class HolderCreate(BaseModel):
    asset_id: str
    entity_id: str
    entity_type: str = "wallet"
    amount: float = 0.0
    exposure_type: str = "direct"
    source_tag: str = ""


# ═══════════════════════════════════════════════════════════════════
# ASSETS
# ═══════════════════════════════════════════════════════════════════

@router.post("/assets")
async def create_asset(body: RWAAssetCreate, request: Request):
    """Register a tokenized real-world asset as an intelligence object."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    result = await register_asset(body, tenant.tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/assets")
async def list_assets(
    request: Request,
    asset_class: Optional[str] = Query(None),
    chain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """List registered RWA assets."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    filters: dict = {"tenant_id": tenant.tenant_id}
    if asset_class:
        filters["asset_class"] = asset_class
    if chain:
        filters["chain"] = chain
    assets = await asset_repo.find_many(filters=filters, limit=limit)
    return APIResponse(data={"assets": assets, "count": len(assets)}).to_dict()


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, request: Request):
    """Get full asset details."""
    request.state.tenant.require_permission("read")
    asset = await asset_repo.find_by_id(asset_id)
    if not asset:
        raise NotFoundError("RWA asset")
    return APIResponse(data=asset).to_dict()


# ═══════════════════════════════════════════════════════════════════
# POLICIES
# ═══════════════════════════════════════════════════════════════════

@router.post("/policies")
async def create_policy(body: PolicyCreate, request: Request):
    """Register a compliance/transfer-restriction policy for an asset."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    result = await register_policy(body, tenant.tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/assets/{asset_id}/policies")
async def get_policies(asset_id: str, request: Request):
    """Get all policies for an asset."""
    request.state.tenant.require_permission("read")
    policies = await policy_repo.find_many(filters={"asset_id": asset_id}, limit=100)
    return APIResponse(data={"asset_id": asset_id, "policies": policies, "count": len(policies)}).to_dict()


@router.post("/simulate-transfer")
async def simulate_transfer_endpoint(body: PolicySimulation, request: Request):
    """Simulate whether a transfer would violate any policy."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    result = await simulate_transfer(
        body.asset_id, body.from_entity, body.to_entity, body.amount, tenant.tenant_id
    )
    return APIResponse(data=result).to_dict()


# ═══════════════════════════════════════════════════════════════════
# CASHFLOWS
# ═══════════════════════════════════════════════════════════════════

@router.post("/cashflows")
async def create_cashflow(body: CashflowEventCreate, request: Request):
    """Record a cashflow event (coupon, dividend, redemption, etc.)."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    result = await record_cashflow(body, tenant.tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/assets/{asset_id}/cashflows")
async def get_cashflows(
    asset_id: str, request: Request,
    cashflow_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get cashflow history for an asset."""
    request.state.tenant.require_permission("read")
    filters: dict = {"asset_id": asset_id}
    if cashflow_type:
        filters["cashflow_type"] = cashflow_type
    cashflows = await cashflow_repo.find_many(filters=filters, limit=limit)
    return APIResponse(data={"asset_id": asset_id, "cashflows": cashflows, "count": len(cashflows)}).to_dict()


# ═══════════════════════════════════════════════════════════════════
# EXPOSURE
# ═══════════════════════════════════════════════════════════════════

@router.get("/exposure/{entity_id}")
async def get_exposure(
    entity_id: str, request: Request,
    entity_type: str = Query("wallet"),
    include_inferred: bool = Query(True),
    include_beneficial: bool = Query(True),
):
    """Get RWA exposure for a wallet/entity/profile."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    result = await compute_exposure(
        entity_id, entity_type, include_inferred, include_beneficial, tenant.tenant_id
    )
    return APIResponse(data=result).to_dict()


# ═══════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════

@router.get("/assets/{asset_id}/reserve-credibility")
async def reserve_credibility(asset_id: str, request: Request):
    """Score reserve/backing credibility for an asset."""
    request.state.tenant.require_permission("read")
    result = await score_reserve_credibility(asset_id, request.state.tenant.tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/assets/{asset_id}/redemption-pressure")
async def redemption_pressure(asset_id: str, request: Request):
    """Score redemption pressure on an asset."""
    request.state.tenant.require_permission("read")
    result = await score_redemption_pressure(asset_id, request.state.tenant.tenant_id)
    return APIResponse(data=result).to_dict()


# ═══════════════════════════════════════════════════════════════════
# HOLDERS
# ═══════════════════════════════════════════════════════════════════

@router.post("/holders")
async def register_holder(body: HolderCreate, request: Request):
    """Register a holder record for an asset."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    record = {
        "id": str(uuid.uuid4()),
        "asset_id": body.asset_id,
        "entity_id": body.entity_id,
        "entity_type": body.entity_type,
        "amount": body.amount,
        "exposure_type": body.exposure_type,
        "source_tag": body.source_tag,
        "tenant_id": tenant.tenant_id,
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
    }
    result = await holder_repo.insert(record["id"], record)
    metrics.increment("rwa_holder_registered")
    return APIResponse(data=result).to_dict()


@router.get("/assets/{asset_id}/holders")
async def get_holders(
    asset_id: str, request: Request,
    limit: int = Query(100, ge=1, le=1000),
):
    """Get holders for an asset."""
    request.state.tenant.require_permission("read")
    holders = await holder_repo.find_many(filters={"asset_id": asset_id}, limit=limit)
    return APIResponse(data={"asset_id": asset_id, "holders": holders, "count": len(holders)}).to_dict()
