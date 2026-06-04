from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, BadRequestError
from .stitching import journey_stitcher, serialize_journey

router = APIRouter(prefix="/v1/journeys", tags=["Journeys"])
admin_router = APIRouter(prefix="/v1/admin/journey-health", tags=["Journey Health"])


def _tenant_id(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    return getattr(tenant, "tenant_id", "local-dev")


@router.get("/users/{user_id}")
async def list_user_journeys(user_id: str, request: Request):
    tenant_id = _tenant_id(request)
    journeys = [serialize_journey(j) for j in journey_stitcher.list_for_user(tenant_id, user_id)]
    return APIResponse(data={"items": journeys, "journeys": journeys, "count": len(journeys)}).to_dict()


@router.get("/summary")
async def journey_summary(request: Request):
    return APIResponse(data=journey_stitcher.health(_tenant_id(request))).to_dict()


@router.get("/{journey_id}")
async def get_journey(journey_id: str, request: Request):
    journey = journey_stitcher.get(_tenant_id(request), journey_id)
    if journey is None:
        raise BadRequestError("journey not found")
    return APIResponse(data=serialize_journey(journey)).to_dict()


@router.get("/{journey_id}/timeline")
async def get_journey_timeline(journey_id: str, request: Request):
    journey = journey_stitcher.get(_tenant_id(request), journey_id)
    if journey is None:
        raise BadRequestError("journey not found")
    return APIResponse(data={"items": serialize_journey(journey)["timeline"]}).to_dict()


@router.get("/{journey_id}/handoffs")
async def get_journey_handoffs(journey_id: str, request: Request):
    journey = journey_stitcher.get(_tenant_id(request), journey_id)
    if journey is None:
        raise BadRequestError("journey not found")
    return APIResponse(data={"items": journey.handoffs, "count": len(journey.handoffs)}).to_dict()


@admin_router.get("")
async def global_journey_health():
    health = journey_stitcher.health()
    health.update({
        "sdk_parity_gaps": [],
        "schema_drift_warnings": [],
        "ambiguous_clusters": health["low_confidence_count"],
        "stitches_created_total": health["journey_count"],
    })
    return APIResponse(data=health).to_dict()


@admin_router.get("/tenants/{tenant_id}")
async def tenant_journey_health(tenant_id: str):
    return APIResponse(data=journey_stitcher.health(tenant_id)).to_dict()


@admin_router.get("/sdk-parity")
async def sdk_parity():
    health = journey_stitcher.health()
    return APIResponse(data={"platforms": health["sdk_emission_by_platform"], "gaps": []}).to_dict()


@admin_router.get("/dropped-events")
async def dropped_events():
    return APIResponse(data={"items": [], "count": journey_stitcher.health()["dropped_invalid_events"]}).to_dict()
