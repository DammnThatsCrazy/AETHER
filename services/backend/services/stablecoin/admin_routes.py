"""Kyber operator surfaces for Stablecoin Intelligence —
/v1/admin/kyber/stablecoins. Operator-gated, audited, observation-only."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from repositories.stablecoin_repos import (
    FinalityCheckpointRepo,
    ReconciliationRepo,
    StablecoinObservationRepo,
)
from shared.auth.auth import Permissions
from shared.common.common import ForbiddenError
from services.stablecoin.finality import FinalityEngine
from services.stablecoin.foundation import require_flag
from services.stablecoin.registry import StablecoinRegistry

admin_router = APIRouter(prefix="/v1/admin/kyber/stablecoins", tags=["kyber-stablecoins"])


from services.security.request_context import is_kyber_operator as _is_kyber_operator


def _gate(request: Request) -> None:
    require_flag(settings.stablecoin.kyber_enabled, "Kyber Stablecoin Ops")
    tenant = request.state.tenant
    # Canonical fail-closed operator check (replaces the never-set
    # is_platform_admin flag): only kyber:operator grant or the operator
    # tenant-id allowlist passes; Aether tenants (incl. Role.ADMIN) are denied.
    if not _is_kyber_operator(tenant):
        raise ForbiddenError("Kyber operator access required; Aether tenants may not access Kyber")
    tenant.require_permission(Permissions.STABLECOINS_OPERATOR)


class CheckpointAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    chain_id: str
    block_number: int = Field(ge=0)
    block_hash: Optional[str] = None
    confirmation_horizon: int = Field(default=12, ge=0)
    confirm_observations: bool = True


class ReorgRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    chain_id: str
    from_block: int = Field(ge=0)
    reason: str = Field(min_length=10, description="Audited justification")


@admin_router.get("/registry/status")
async def registry_status(request: Request):
    _gate(request)
    registry = StablecoinRegistry()
    asset_count = await registry.assets.count()
    deployment_count = await registry.deployments.count()
    return {
        "asset_count": asset_count,
        "deployment_count": deployment_count,
    }


@admin_router.post("/registry/seed", status_code=201)
async def seed_registry(request: Request):
    """Seed canonical assets/deployments from the x402 verified contracts."""
    _gate(request)
    return await StablecoinRegistry().seed_canonical_assets()


@admin_router.get("/finality/checkpoints")
async def list_checkpoints(
    request: Request, limit: int = Query(default=50, ge=1, le=200),
):
    _gate(request)
    rows = await FinalityCheckpointRepo().find_many(limit=limit)
    return {"items": rows, "count": len(rows)}


@admin_router.post("/finality/advance", status_code=201)
async def advance_checkpoint(payload: CheckpointAdvanceRequest, request: Request):
    _gate(request)
    engine = FinalityEngine()
    result = await engine.advance_checkpoint(
        payload.tenant_id, payload.chain_id, payload.block_number,
        payload.block_hash, payload.confirmation_horizon,
    )
    if payload.confirm_observations:
        confirmed = await engine.confirm_observations(
            payload.tenant_id, payload.chain_id,
            payload.block_number - payload.confirmation_horizon,
        )
        result["finalized_count"] = confirmed["finalized_count"]
        result["emitted_events"] = result["emitted_events"] + confirmed["emitted_events"]
    return result


@admin_router.post("/finality/reorg", status_code=201)
async def handle_reorg(payload: ReorgRequest, request: Request):
    """Audited observation correction: demotes non-finalized observations at
    or above the fork block. Finalized observations are never touched."""
    _gate(request)
    result = await FinalityEngine().handle_reorg(
        payload.tenant_id, payload.chain_id, payload.from_block,
    )
    result["reason"] = payload.reason
    return result


@admin_router.get("/reconciliation")
async def list_reconciliation(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    _gate(request)
    filters = {"status": status} if status else None
    rows = await ReconciliationRepo().find_many(filters, limit=limit)
    return {"items": rows, "count": len(rows)}


@admin_router.get("/observations/unresolved")
async def unresolved_observations(
    request: Request, limit: int = Query(default=50, ge=1, le=200),
):
    """Observations whose deployment could not be resolved (registry gaps)."""
    _gate(request)
    rows = await StablecoinObservationRepo().find_many(
        {"canonical_asset_id": "unresolved"}, limit=limit,
    )
    return {"items": rows, "count": len(rows)}
