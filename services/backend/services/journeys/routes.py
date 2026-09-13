from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, BadRequestError
from .stitching import journey_stitcher, serialize_journey

# DEPRECATED — not mounted. This in-memory stitcher router previously shadowed
# the persisted /v1/journeys authority (services/measurement/routes/journeys.py)
# because it was registered first with an always-empty in-process store. It is
# intentionally excluded from application mounting in main.py; route all
# /v1/journeys traffic through the persisted measurement authority. Do not
# re-mount without removing the colliding GET /{journey_id} and /summary paths.
# JourneyStitchingService remains in use as the journey compiler's confidence
# scorer.
router = APIRouter(prefix="/v1/journeys", tags=["Journeys"])
# admin_router IS mounted (main.py, as journey_health_router): operator-only,
# non-colliding fleet journey-health diagnostics under /v1/admin/journey-health.
admin_router = APIRouter(prefix="/v1/admin/journey-health", tags=["Journey Health"])


def _envelope(data: Any) -> dict:
    """Return the ``{data, status, timestamp, meta}`` envelope Kyber/Aether expect.

    The frontend ``wrap()`` schema requires top-level ``status`` and ``timestamp``
    (see the agent control-plane routes for the same pattern); a bare
    ``APIResponse(...).to_dict()`` only emits ``{data, meta}`` and fails client
    response validation in live mode.
    """
    base = APIResponse(data=data).to_dict()
    return {
        "data": base["data"],
        "status": "success",
        "timestamp": base["meta"]["timestamp"],
        "meta": base["meta"],
    }


def _require_read(request: Request) -> str:
    """Enforce tenant read permission and return the caller's tenant id.

    Tenant-scoped journey data must not be readable by a caller that lacks the
    ``read`` scope, matching the persisted profile journey route this feature
    surfaces alongside.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    return getattr(tenant, "tenant_id", "local-dev")


def _require_admin(request: Request) -> None:
    """Gate fleet-wide journey-health views behind operator/admin permission.

    These endpoints aggregate across every tenant, so without this check any
    authenticated tenant could read another tenant's journey counts, SDK mix,
    confidence and handoff metrics.
    """
    request.state.tenant.require_permission("admin")


@router.get("/users/{user_id}")
async def list_user_journeys(user_id: str, request: Request):
    tenant_id = _require_read(request)
    journeys = [serialize_journey(j) for j in journey_stitcher.list_for_user(tenant_id, user_id)]
    return _envelope({"items": journeys, "journeys": journeys, "count": len(journeys)})


@router.get("/summary")
async def journey_summary(request: Request):
    return _envelope(journey_stitcher.health(_require_read(request)))


@router.get("/{journey_id}")
async def get_journey(journey_id: str, request: Request):
    journey = journey_stitcher.get(_require_read(request), journey_id)
    if journey is None:
        raise BadRequestError("journey not found")
    return _envelope(serialize_journey(journey))


@router.get("/{journey_id}/timeline")
async def get_journey_timeline(journey_id: str, request: Request):
    journey = journey_stitcher.get(_require_read(request), journey_id)
    if journey is None:
        raise BadRequestError("journey not found")
    return _envelope({"items": serialize_journey(journey)["timeline"]})


@router.get("/{journey_id}/handoffs")
async def get_journey_handoffs(journey_id: str, request: Request):
    journey = journey_stitcher.get(_require_read(request), journey_id)
    if journey is None:
        raise BadRequestError("journey not found")
    return _envelope({"items": journey.handoffs, "count": len(journey.handoffs)})


@admin_router.get("")
async def global_journey_health(request: Request):
    _require_admin(request)
    health = journey_stitcher.health()
    health.update({
        "sdk_parity_gaps": [],
        "schema_drift_warnings": [],
        "ambiguous_clusters": health["low_confidence_count"],
        "stitches_created_total": health["journey_count"],
    })
    return _envelope(health)


@admin_router.get("/tenants/{tenant_id}")
async def tenant_journey_health(tenant_id: str, request: Request):
    _require_admin(request)
    return _envelope(journey_stitcher.health(tenant_id))


@admin_router.get("/sdk-parity")
async def sdk_parity(request: Request):
    _require_admin(request)
    health = journey_stitcher.health()
    return _envelope({"platforms": health["sdk_emission_by_platform"], "gaps": []})


@admin_router.get("/dropped-events")
async def dropped_events(request: Request):
    _require_admin(request)
    items = journey_stitcher.dropped_events()
    return _envelope({"items": items, "count": len(items)})
