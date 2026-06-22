"""Journey CRUD + version history endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.engine.journey_compiler import JourneyCompiler

logger = get_logger("aether.measurement.routes.journeys")
router = APIRouter(prefix="/v1/journeys", tags=["Journeys"])

_journey_repo = JourneyRepository()
_compiler = JourneyCompiler()


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class RebuildRequest(BaseModel):
    trigger_reason: str = "manual"


@router.get("")
async def list_journeys(
    request: Request,
    profile_id: Optional[str] = Query(None),
    journey_state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
):
    tenant = _require_tenant(request)
    if profile_id:
        journeys = await _journey_repo.find_current_for_profile(tenant.tenant_id, profile_id)
    else:
        journeys = await _journey_repo.list_current(
            tenant.tenant_id,
            journey_state=journey_state,
            limit=limit,
            cursor=cursor,
        )

    next_cursor = journeys[-1].get("computed_at") if len(journeys) == limit else None
    return {
        "data": journeys,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.get("/{journey_id}")
async def get_journey(journey_id: str, request: Request):
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")
    return APIResponse(data=journey).to_dict()


@router.get("/{journey_id}/versions")
async def list_journey_versions(journey_id: str, request: Request):
    tenant = _require_tenant(request)
    versions = await _journey_repo.list_versions(tenant.tenant_id, journey_id)
    if not versions:
        raise NotFoundError("Journey")
    return APIResponse(data=versions, meta={"version_count": len(versions)}).to_dict()


@router.post("/{journey_id}/rebuild")
async def rebuild_journey(journey_id: str, request: Request, body: RebuildRequest):
    tenant = _require_tenant(request)
    current = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if current is None:
        raise NotFoundError("Journey")

    profile_id = current.get("profile_id") or current.get("cluster_id")
    if not profile_id:
        return APIResponse(data=None, meta={"reason": "no_profile_id"}).to_dict()

    new_version = await _compiler.compile_for_profile(
        tenant.tenant_id, profile_id, trigger_reason=body.trigger_reason
    )
    return APIResponse(data=new_version, meta={"rebuilt": True}).to_dict()
