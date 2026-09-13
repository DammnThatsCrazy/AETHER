"""
Aether Service — Expectation Engine API

Negative-space intelligence: what should have happened but did not.

Macro:
    GET /v1/expectations/summary              Population expectation overview
    GET /v1/expectations/contradictions       Top contradictions across population
    GET /v1/expectations/silence              Source silence vs real behavior change

Meso:
    GET /v1/expectations/group/{pop_id}       Group expectation view
    GET /v1/expectations/group/{pop_id}/gaps  Group missing expected behaviors

Micro:
    GET /v1/expectations/entity/{id}          Entity expectation view (full scan)
    GET /v1/expectations/entity/{id}/signals  Entity signals by type
    GET /v1/expectations/entity/{id}/explain  Why this entity is unusual
    POST /v1/expectations/scan/{id}           Trigger full scan for an entity

Cross-level:
    GET /v1/expectations/signal/{signal_id}   Get signal details with provenance
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, Query

from shared.common.common import APIResponse, NotFoundError, utc_now
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_cache, get_graph
from services.expectations.engine import ExpectationEngine, signal_repo
from services.expectations.models import SignalType

logger = get_logger("aether.service.expectations")
router = APIRouter(prefix="/v1/expectations", tags=["Expectation Engine"])

_engine: Optional[ExpectationEngine] = None


def _get_engine(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> ExpectationEngine:
    global _engine
    if _engine is None:
        _engine = ExpectationEngine(graph=graph, cache=cache)
    return _engine


# ══════════════════════════════════════════════════════════════════
# MACRO — Population-level expectation views
# ══════════════════════════════════════════════════════════════════

@router.get("/summary")
async def expectation_summary(request: Request):
    """Population-wide expected vs actual summary."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    type_counts = {}
    for st in SignalType:
        signals = await signal_repo.get_signals_by_type(st.value, tenant.tenant_id, limit=1000)
        type_counts[st.value] = len(signals)

    total = sum(type_counts.values())
    true_absence = total - type_counts.get(SignalType.SOURCE_SILENCE.value, 0)
    source_silence = type_counts.get(SignalType.SOURCE_SILENCE.value, 0)

    metrics.increment("expectation_macro_summary")
    return APIResponse(data={
        "total_signals": total,
        "true_absence_signals": true_absence,
        "source_silence_signals": source_silence,
        "by_type": type_counts,
        "top_types": sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/contradictions")
async def top_contradictions(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
):
    """Top contradictions across the population."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    contradiction_types = [
        SignalType.IDENTITY_CONTRADICTION.value,
        SignalType.RELATIONSHIP_CONTRADICTION.value,
        SignalType.TEMPORAL_CONTRADICTION.value,
        SignalType.GRAPH_CONTRADICTION.value,
        SignalType.MODEL_CONTRADICTION.value,
    ]

    all_contradictions = []
    for ct in contradiction_types:
        signals = await signal_repo.get_signals_by_type(ct, tenant.tenant_id, limit=limit)
        all_contradictions.extend(signals)

    # Sort by confidence (highest first)
    all_contradictions.sort(key=lambda s: s.get("confidence", 0), reverse=True)

    return APIResponse(data={
        "contradictions": all_contradictions[:limit],
        "count": len(all_contradictions),
    }).to_dict()


@router.get("/silence")
async def source_silence_view(request: Request):
    """Source silence vs real behavior change population view."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    silence = await signal_repo.get_signals_by_type(
        SignalType.SOURCE_SILENCE.value, tenant.tenant_id, limit=500
    )
    real_absence = []
    for st in [SignalType.MISSING_EXPECTED_ACTION.value, SignalType.MISSING_EXPECTED_EDGE.value]:
        real_absence.extend(
            await signal_repo.get_signals_by_type(st, tenant.tenant_id, limit=500)
        )

    return APIResponse(data={
        "source_silence_count": len(silence),
        "true_absence_count": len(real_absence),
        "source_silence_entities": list({s["entity_id"] for s in silence}),
        "true_absence_entities": list({s["entity_id"] for s in real_absence}),
        "message": "Source silence = data stopped arriving. True absence = behavior changed.",
    }).to_dict()


# ══════════════════════════════════════════════════════════════════
# MESO — Group-level expectation views
# ══════════════════════════════════════════════════════════════════

@router.get("/group/{population_id}")
async def group_expectations(population_id: str, request: Request):
    """Group expectation view — signals for a population/cohort."""
    request.state.tenant.require_permission("read")

    signals = await signal_repo.get_signals_for_population(population_id)
    type_counts = {}
    for s in signals:
        st = s.get("signal_type", "unknown")
        type_counts[st] = type_counts.get(st, 0) + 1

    return APIResponse(data={
        "population_id": population_id,
        "total_signals": len(signals),
        "by_type": type_counts,
        "signals": signals[:50],
    }).to_dict()


@router.get("/group/{population_id}/gaps")
async def group_gaps(population_id: str, request: Request):
    """Missing expected behaviors for a group."""
    request.state.tenant.require_permission("read")

    signals = await signal_repo.get_signals_for_population(population_id)
    gaps = [s for s in signals if s.get("signal_type") in (
        SignalType.MISSING_EXPECTED_ACTION.value,
        SignalType.MISSING_EXPECTED_EDGE.value,
        SignalType.BROKEN_SEQUENCE.value,
    )]

    return APIResponse(data={
        "population_id": population_id,
        "gap_count": len(gaps),
        "gaps": gaps,
    }).to_dict()


# ══════════════════════════════════════════════════════════════════
# MICRO — Entity-level expectation views
# ══════════════════════════════════════════════════════════════════

@router.get("/entity/{entity_id}")
async def entity_expectations(
    entity_id: str,
    request: Request,
    engine: ExpectationEngine = Depends(_get_engine),
):
    """Full expectation view for an entity — runs all detectors."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    result = await engine.run_full_scan(entity_id, tenant.tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/entity/{entity_id}/signals")
async def entity_signals(
    entity_id: str,
    request: Request,
    signal_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Get signals for an entity, optionally filtered by type."""
    request.state.tenant.require_permission("read")

    signals = await signal_repo.get_signals_for_entity(entity_id, signal_type, limit)
    return APIResponse(data={
        "entity_id": entity_id,
        "signals": signals,
        "count": len(signals),
    }).to_dict()


@router.get("/entity/{entity_id}/explain")
async def explain_entity(
    entity_id: str,
    request: Request,
    engine: ExpectationEngine = Depends(_get_engine),
):
    """Explain why this entity is unusual — top signals with explanations."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    signals = await signal_repo.get_signals_for_entity(entity_id, limit=20)

    if not signals:
        # Run a scan first
        result = await engine.run_full_scan(entity_id, tenant.tenant_id)
        signals = result.get("signals", [])

    # Sort by severity and confidence
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    signals.sort(key=lambda s: (severity_order.get(s.get("severity", "info"), 5), -s.get("confidence", 0)))

    explanations = []
    for s in signals[:10]:
        explanations.append({
            "signal_type": s.get("signal_type"),
            "severity": s.get("severity"),
            "confidence": s.get("confidence"),
            "expected": s.get("expected"),
            "observed": s.get("observed"),
            "explanation": s.get("explanation"),
            "baseline_source": s.get("baseline_source"),
            "is_source_silence": s.get("is_source_silence", False),
        })

    return APIResponse(data={
        "entity_id": entity_id,
        "is_unusual": len(explanations) > 0,
        "top_signals": len(explanations),
        "explanations": explanations,
    }).to_dict()


@router.post("/scan/{entity_id}")
async def trigger_scan(
    entity_id: str,
    request: Request,
    engine: ExpectationEngine = Depends(_get_engine),
):
    """Trigger a full expectation scan for an entity."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    result = await engine.run_full_scan(entity_id, tenant.tenant_id)
    metrics.increment("expectation_scan_triggered")
    return APIResponse(data=result).to_dict()


# ══════════════════════════════════════════════════════════════════
# CROSS-LEVEL — Signal detail with provenance
# ══════════════════════════════════════════════════════════════════

@router.get("/signal/{signal_id}")
async def get_signal(signal_id: str, request: Request):
    """Get signal details with full provenance."""
    request.state.tenant.require_permission("read")

    signal = await signal_repo.find_by_id(signal_id)
    if not signal:
        raise NotFoundError("Expectation signal")

    return APIResponse(data=signal).to_dict()
