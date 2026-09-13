"""
Aether Service — Behavioral Continuity & Friction API

Derived signals from existing data: intent residue, wallet friction,
identity deltas, pre/post continuity, sequence scars, source shadow.

Endpoints:
    GET  /v1/behavioral/entity/{id}           Full behavioral scan
    GET  /v1/behavioral/entity/{id}/signals   Signals by family
    POST /v1/behavioral/scan/{id}             Trigger full scan
    GET  /v1/behavioral/summary               Population behavioral summary
    GET  /v1/behavioral/registry              Signal definitions
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, Query

from shared.common.common import APIResponse, utc_now
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger, metrics
from repositories.repos import AnalyticsRepository
from dependencies.providers import get_cache, get_graph
from services.behavioral.engines import (
    run_full_behavioral_scan, signal_repo,
)
from services.behavioral.signals import SIGNAL_REGISTRY, SignalFamily

logger = get_logger("aether.service.behavioral")
router = APIRouter(prefix="/v1/behavioral", tags=["Behavioral Continuity & Friction"])


def _get_analytics(cache: CacheClient = Depends(get_cache)) -> AnalyticsRepository:
    return AnalyticsRepository(cache)


@router.get("/entity/{entity_id}")
async def entity_behavioral_view(
    entity_id: str,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
):
    """Full behavioral scan — computes all signal families for an entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    analytics = AnalyticsRepository(cache)
    result = await run_full_behavioral_scan(entity_id, analytics, graph, tenant.tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/entity/{entity_id}/signals")
async def entity_signals(
    entity_id: str,
    request: Request,
    family: Optional[str] = Query(None, description="Filter by signal family"),
    limit: int = Query(50, ge=1, le=500),
):
    """Get persisted signals for an entity, optionally filtered by family."""
    request.state.tenant.require_permission("read")

    signals = await signal_repo.get_signals_for_entity(entity_id, family, limit)
    return APIResponse(data={
        "entity_id": entity_id,
        "signals": signals,
        "count": len(signals),
    }).to_dict()


@router.post("/scan/{entity_id}")
async def trigger_scan(
    entity_id: str,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
):
    """Trigger a full behavioral scan for an entity."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    analytics = AnalyticsRepository(cache)
    result = await run_full_behavioral_scan(entity_id, analytics, graph, tenant.tenant_id)
    metrics.increment("behavioral_scan_triggered")
    return APIResponse(data=result).to_dict()


@router.get("/summary")
async def behavioral_summary(request: Request):
    """Population-level behavioral signal summary."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    family_counts = {}
    for family in SignalFamily:
        signals = await signal_repo.find_many(
            filters={"signal_family": family.value, "tenant_id": tenant.tenant_id},
            limit=10000,
        )
        family_counts[family.value] = len(signals)

    total = sum(family_counts.values())
    return APIResponse(data={
        "total_signals": total,
        "by_family": family_counts,
        "top_families": sorted(family_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/registry")
async def signal_registry(request: Request):
    """Get signal definitions — what each signal needs, produces, and explains."""
    request.state.tenant.require_permission("read")

    return APIResponse(data={
        "signals": {
            name: {
                "family": defn["family"].value,
                "source_events": defn["source_events"],
                "outputs": defn["outputs"],
                "consumers": defn["consumers"],
            }
            for name, defn in SIGNAL_REGISTRY.items()
        },
        "total": len(SIGNAL_REGISTRY),
    }).to_dict()
