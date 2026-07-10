"""Stablecoin Intelligence tenant and Kyber operator routes.

Feature-flagged; all routes default off until PR2-PR4 product surfaces are
verified in staging. Router is registered unconditionally in main.py so the
feature flag can be checked per-request without a restart.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from repositories.stablecoin_repos import StablecoinObservationRepository
from services.agentic_observability.foundation import active_tenant_id, require_permission
from services.stablecoins.profile360 import StablecoinProfile360Composer
from shared.common.common import APIResponse

router = APIRouter(prefix="/v1/stablecoin", tags=["stablecoin-intelligence"])
kyber_router = APIRouter(prefix="/v1/admin/kyber/stablecoin", tags=["kyber-stablecoin"])
# Unprefixed: profile-360 composition lives under the platform /v1/profile family.
profile_router = APIRouter(tags=["stablecoin-intelligence"])


def _feature_enabled(request: Request) -> bool:
    try:
        from config.settings import settings
        return bool(settings.stablecoin_intelligence.enabled and not settings.stablecoin_intelligence.kill_switch)
    except Exception:
        return False


@router.get("/health")
async def stablecoin_health() -> dict[str, str]:
    return {"status": "ok", "domain": "stablecoin_intelligence", "feature_gate": "off_by_default"}


@kyber_router.get("/health")
async def kyber_stablecoin_health() -> dict[str, str]:
    return {"status": "ok", "domain": "kyber_stablecoin_operations", "feature_gate": "off_by_default"}


@profile_router.get("/v1/profile/{profile_id}/stablecoins")
async def stablecoin_profile(profile_id: str, request: Request, kind: str = Query("overview"), limit: int = Query(100, ge=1, le=500)):
    require_permission(request, "read")
    if not _feature_enabled(request):
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is disabled")
    tenant_id = active_tenant_id(request)
    data = await StablecoinProfile360Composer().compose(tenant_id=tenant_id, profile_id=profile_id, kind=kind, limit=limit)
    return APIResponse(data=data).to_dict()


@profile_router.get("/v1/stablecoins/observations")
async def list_stablecoin_observations(request: Request, limit: int = Query(100, ge=1, le=500)):
    require_permission(request, "read")
    if not _feature_enabled(request):
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is disabled")
    tenant_id = active_tenant_id(request)
    rows = await StablecoinObservationRepository().find_many(filters={"tenant_id": tenant_id}, limit=limit)
    return APIResponse(data={"tenant_id": tenant_id, "items": rows, "count": len(rows)}).to_dict()
