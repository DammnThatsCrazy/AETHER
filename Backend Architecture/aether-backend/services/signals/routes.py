"""
Aether — Signal Translator API Routes

GET /v1/signals/{entity_id}            — list all behavioral signals for an entity
GET /v1/signals/{entity_id}/{signal_id} — get a specific signal instance
POST /v1/signals/{entity_id}/refresh   — trigger signal recomputation for entity
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from shared.logger.logger import get_logger

logger = get_logger("aether.signals.routes")

router = APIRouter(prefix="/v1/signals", tags=["signals"])


@router.get("/{entity_id}")
async def list_signals(
    entity_id: str,
    window_days: int | None = Query(default=30, description="Time window: 30, 60, 90, or omit for lifetime"),
    sentiment: str | None = Query(default=None, description="Filter by sentiment: positive, caution, negative, informational"),
    severity: str | None = Query(default=None, description="Filter by severity: critical, high, medium, low, info"),
    include_stale: bool = Query(default=False, description="Include signals last detected > 30 days ago"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    List all behavioral signals for an entity.
    Signals are sorted by severity (critical → info) then confidence descending.
    """
    # TODO: wire to signal_repository once implemented
    return {
        "entity_id": entity_id,
        "kind": "signals",
        "items": [],
        "summary": {
            "total": 0,
            "by_sentiment": {"positive": 0, "caution": 0, "negative": 0, "informational": 0},
            "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
        },
        "pagination": {"limit": limit, "count": 0, "has_more": False},
        "computed_at": None,
        "provenance": {"sources": ["signal_translator"]},
    }


@router.post("/{entity_id}/refresh")
async def refresh_signals(entity_id: str):
    """
    Trigger signal recomputation for an entity.
    Reads latest gold-tier metrics and re-runs all applicable signal templates.
    """
    # TODO: enqueue signal recomputation job
    return {"entity_id": entity_id, "status": "queued", "message": "Signal recomputation queued."}
