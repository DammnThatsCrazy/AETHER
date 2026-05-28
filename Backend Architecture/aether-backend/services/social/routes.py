"""
Aether — Social Intelligence API Routes

GET /v1/profile/{entity_id}/social-intelligence?window=30d|60d|90d|lifetime
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from shared.logger.logger import get_logger

logger = get_logger("aether.social.routes")

router = APIRouter(tags=["social"])

_WINDOW_MAP = {"30d": 30, "60d": 60, "90d": 90, "lifetime": None}


@router.get("/v1/profile/{entity_id}/social-intelligence")
async def get_social_intelligence(
    entity_id: str,
    window: str = Query(default="30d", description="30d | 60d | 90d | lifetime"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """
    Return aggregated cross-platform social data for an entity.
    Phase 1: Twitter, Farcaster, Lens, Discord, GitHub.
    """
    if window not in _WINDOW_MAP:
        raise HTTPException(status_code=400, detail=f"window must be one of: {list(_WINDOW_MAP.keys())}")

    return {
        "entity_id": entity_id,
        "kind": "social_intelligence",
        "window": window,
        "items": [],
        "summary": {
            "total_followers_deduped": 0,
            "influence_level": "low",
            "engagement_rate": 0.0,
            "platforms_connected": 0,
        },
        "pagination": {"limit": limit, "count": 0, "has_more": False},
        "computed_at": None,
        "provenance": {"sources": ["twitter", "farcaster", "lens", "discord", "github"]},
    }
