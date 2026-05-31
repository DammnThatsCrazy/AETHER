"""
Aether — PNL API Routes

GET /v1/profile/{entity_id}/pnl?window=30d|60d|90d|lifetime
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from shared.logger.logger import get_logger

logger = get_logger("aether.pnl.routes")

router = APIRouter(tags=["pnl"])

_WINDOW_MAP = {"30d": 30, "60d": 60, "90d": 90, "lifetime": None}


@router.get("/v1/profile/{entity_id}/pnl")
async def get_pnl(
    entity_id: str,
    request: Request,
    window: str = Query(default="30d", description="30d | 60d | 90d | lifetime"),
):
    request.state.tenant.require_permission("read")
    """
    Return realized + unrealized PNL and TVL delta for an entity.
    Source: silver_web3_events (FIFO cost basis) + CoinGecko historical prices.
    """
    if window not in _WINDOW_MAP:
        raise HTTPException(status_code=400, detail=f"window must be one of: {list(_WINDOW_MAP.keys())}")

    window_days = _WINDOW_MAP[window]

    # TODO: wire to PNLCalculator + ClickHouse once available in dependency injection
    return {
        "entity_id": entity_id,
        "kind": "pnl",
        "window": window,
        "items": [],
        "summary": {
            "realized_pnl_usd": 0,
            "unrealized_pnl_usd": 0,
            "tvl_delta_usd": 0,
            "tvl_delta_pct": 0,
            "cost_basis_method": "FIFO",
            "data_confidence": "estimated",
        },
        "pagination": {"limit": 1, "count": 0, "has_more": False},
        "computed_at": None,
        "provenance": {"sources": ["silver_web3_events", "gold_entity_pnl", "coingecko"]},
    }
