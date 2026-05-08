"""
Aether Service — Behavior Profile (Profile 360)

Read-side endpoint for the derived behavior layer. Snapshots are produced
by the BehaviorScorer worker on a rolling window plus a `BEHAVIOR_PROFILE_UPDATED`
event handler.

Endpoints:
    GET /v1/behavior/{entity_id}            Latest snapshot
    GET /v1/behavior/{entity_id}/history    Historical snapshots
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger
from repositories.repos import BehaviorProfileRepository

logger = get_logger("aether.service.behavior")
router = APIRouter(prefix="/v1/behavior", tags=["Profile 360 / Behavior"])

_repo = BehaviorProfileRepository()


@router.get("/{entity_id}")
async def latest(entity_id: str, request: Request):
    """Latest behavior snapshot for an entity (per-entity row, recomputed)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _repo.find_by_id(entity_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Behavior profile")
    return APIResponse(data=record).to_dict()


@router.get("/{entity_id}/history")
async def history(
    entity_id: str,
    request: Request,
    window: str = Query("7d", description="Rolling window label (e.g. 1d, 7d, 30d)"),
    limit: int = Query(50, ge=1, le=500),
):
    """Historical behavior snapshots (one row per recompute, kept best-effort).

    The current implementation returns the single latest snapshot since
    BehaviorScorer overwrites per-entity. When the worker is upgraded to
    timestamped rows, this endpoint shape stays identical.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await _repo.find_many(
        filters={"entity_id": entity_id, "tenant_id": tenant.tenant_id},
        limit=limit,
    )
    return APIResponse(data={
        "entity_id": entity_id,
        "window": window,
        "snapshots": rows,
        "count": len(rows),
    }).to_dict()
