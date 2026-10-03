"""
Aether — Signal Translator API Routes

GET  /v1/signals/{entity_id}             — list all behavioral signals for an entity
GET  /v1/signals/{entity_id}/{signal_id} — get a specific signal instance
POST /v1/signals/{entity_id}/refresh     — trigger signal recomputation for entity
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from repositories.repos import SignalRepository
from services.signals.recompute import recompute_signals_for_entity
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

logger = get_logger("aether.signals.routes")

router = APIRouter(prefix="/v1/signals", tags=["signals"])

_signal_repo = SignalRepository()


def _summary(items: list[dict]) -> dict:
    by_sentiment: dict[str, int] = {"positive": 0, "caution": 0, "negative": 0, "informational": 0}
    by_severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for s in items:
        sent = s.get("sentiment", "informational")
        sev = s.get("severity", "info")
        by_sentiment[sent] = by_sentiment.get(sent, 0) + 1
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {"total": len(items), "by_sentiment": by_sentiment, "by_severity": by_severity}


@router.get("/{entity_id}")
async def list_signals(
    entity_id: str,
    request: Request,
    window_days: int | None = Query(default=30, description="Time window: 30, 60, 90, or omit for lifetime"),
    sentiment: str | None = Query(default=None, description="Filter by sentiment: positive, caution, negative, informational"),
    severity: str | None = Query(default=None, description="Filter by severity: critical, high, medium, low, info"),
    include_stale: bool = Query(default=False, description="Include signals last detected > 30 days ago"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List all behavioral signals for an entity sorted by severity then confidence descending."""
    tenant_id = request.state.tenant.tenant_id
    items = await _signal_repo.list_for_entity(
        entity_id, tenant_id,
        sentiment=sentiment,
        severity=severity,
        include_stale=include_stale,
        limit=limit,
    )
    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    items.sort(key=lambda s: (_SEVERITY_ORDER.get(s.get("severity", "info"), 4), -s.get("confidence", 0)))

    computed_at = items[0].get("created_at") if items else None
    return APIResponse(data={
        "entity_id": entity_id,
        "kind": "signals",
        "items": items,
        "summary": _summary(items),
        "pagination": {"limit": limit, "count": len(items), "has_more": len(items) == limit},
        "computed_at": computed_at,
        "provenance": {"sources": ["signal_translator"]},
    }).to_dict()


@router.get("/{entity_id}/{signal_id}")
async def get_signal(entity_id: str, signal_id: str, request: Request):
    """Get a specific signal instance."""
    tenant_id = request.state.tenant.tenant_id
    rec = await _signal_repo.find_by_id(signal_id)
    if rec is None or rec.get("entity_id") != entity_id or rec.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return APIResponse(data=rec).to_dict()


@router.post("/{entity_id}/refresh")
async def refresh_signals(entity_id: str, request: Request):
    """Recompute behavioral signals from the latest gold-tier metrics for an entity."""
    tenant_id = request.state.tenant.tenant_id
    request.state.tenant.require_permission("read")

    recomputed = await recompute_signals_for_entity(entity_id, tenant_id)
    logger.info(
        "Signal refresh for entity %s (tenant=%s): %s signals computed",
        entity_id,
        tenant_id,
        recomputed["signals_computed"],
    )

    return APIResponse(data={
        "entity_id": entity_id,
        "status": "completed",
        "signals_computed": recomputed["signals_computed"],
        "message": (
            f"Recomputed {recomputed['signals_computed']} signal(s) "
            "from latest behavior profile."
        ),
        "computed_at": recomputed["computed_at"],
    }).to_dict()
