"""Tenant-facing Stablecoin Intelligence API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from repositories.stablecoin_repos import StablecoinObservationRepository
from services.agentic_observability.foundation import active_tenant_id, require_permission
from services.stablecoins.profile360 import StablecoinProfile360Composer
from shared.common.common import APIResponse

router = APIRouter(tags=["Stablecoin Intelligence"])


def _feature_enabled(request: Request) -> bool:
    try:
        from config.settings import settings
        return bool(settings.stablecoin_intelligence.enabled and not settings.stablecoin_intelligence.kill_switch)
    except Exception:
        return False


@router.get("/v1/profile/{profile_id}/stablecoins")
async def stablecoin_profile(profile_id: str, request: Request, kind: str = Query("overview"), limit: int = Query(100, ge=1, le=500)):
    require_permission(request, "read")
    if not _feature_enabled(request):
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is disabled")
    tenant_id = active_tenant_id(request)
    data = await StablecoinProfile360Composer().compose(tenant_id=tenant_id, profile_id=profile_id, kind=kind, limit=limit)
    return APIResponse(data=data).to_dict()


@router.get("/v1/stablecoins/observations")
async def list_stablecoin_observations(request: Request, limit: int = Query(100, ge=1, le=500)):
    require_permission(request, "read")
    if not _feature_enabled(request):
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is disabled")
    tenant_id = active_tenant_id(request)
    rows = await StablecoinObservationRepository().find_many(filters={"tenant_id": tenant_id}, limit=limit)
    return APIResponse(data={"tenant_id": tenant_id, "items": rows, "count": len(rows)}).to_dict()
