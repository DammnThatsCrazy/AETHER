"""
Aether Service — Geo Intelligence
Geographic intelligence pipeline. Returns null data until the pipeline is provisioned.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

logger = get_logger("aether.service.geo")

router = APIRouter(prefix="/v1/geo", tags=["geo"])

_NOT_PROVISIONED = {
    "status": "not_provisioned",
    "message": "Geographic intelligence pipeline not yet provisioned for this account.",
}


@router.get("/summary")
async def get_geo_summary(request: Request) -> APIResponse:
    """Return geographic summary. Returns null until the geo pipeline is provisioned."""
    return APIResponse(data=None, meta=_NOT_PROVISIONED)


@router.get("/entities")
async def get_geo_entities(request: Request) -> APIResponse:
    """Return geographic entities. Returns null until the geo pipeline is provisioned."""
    return APIResponse(data=None, meta=_NOT_PROVISIONED)
