"""
Aether — PNL API Routes

GET /v1/profile/{entity_id}/pnl?window=30d|60d|90d|lifetime
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from dependencies.providers import get_clickhouse, get_provider_gateway
from services.pnl.pnl_calculator import PNLCalculator
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

logger = get_logger("aether.pnl.routes")

router = APIRouter(tags=["pnl"])

_WINDOW_MAP = {"30d": 30, "60d": 60, "90d": 90, "lifetime": None}


def _coingecko_provider(gateway):
    """Extract CoinGecko provider from gateway or return None."""
    if gateway is None:
        return None
    try:
        return gateway.registry.get("coingecko")
    except Exception:
        return None


def _moralis_provider(gateway):
    """Extract Moralis provider from gateway or return None."""
    if gateway is None:
        return None
    try:
        return gateway.registry.get("moralis")
    except Exception:
        return None


class _NullProvider:
    """Stands in when the real provider is not configured."""

    async def execute(self, method: str, params: dict) -> dict | None:
        return None


@router.get("/v1/profile/{entity_id}/pnl")
async def get_pnl(
    entity_id: str,
    request: Request,
    window: str = Query(default="30d", description="30d | 60d | 90d | lifetime"),
    clickhouse=Depends(get_clickhouse),
    provider_gateway=Depends(get_provider_gateway),
):
    """Return realized + unrealized PNL and TVL delta for an entity.

    Source: silver_web3_events (FIFO cost basis) + CoinGecko historical prices.
    """
    request.state.tenant.require_permission("read")

    if window not in _WINDOW_MAP:
        raise HTTPException(status_code=400, detail=f"window must be one of: {list(_WINDOW_MAP.keys())}")

    tenant_id = request.state.tenant.tenant_id
    window_days = _WINDOW_MAP[window]

    coingecko = _coingecko_provider(provider_gateway) or _NullProvider()
    moralis = _moralis_provider(provider_gateway) or _NullProvider()

    calculator = PNLCalculator(
        clickhouse_client=clickhouse,
        coingecko_provider=coingecko,
        moralis_provider=moralis,
    )

    try:
        result = await calculator.compute(entity_id, tenant_id, window_days=window_days)
    except Exception as exc:
        logger.error(f"PNL compute failed for entity={entity_id}: {exc}")
        raise HTTPException(status_code=502, detail="PNL computation failed") from exc

    return APIResponse(data={
        "entity_id": entity_id,
        "kind": "pnl",
        "window": window,
        "summary": {
            "realized_pnl_usd": float(result.realized_pnl_usd),
            "unrealized_pnl_usd": float(result.unrealized_pnl_usd),
            "tvl_delta_usd": float(result.tvl_delta_usd),
            "tvl_delta_pct": result.tvl_delta_pct,
            "best_day_pnl_usd": float(result.best_day_pnl_usd) if result.best_day_pnl_usd is not None else None,
            "best_day_date": result.best_day_date,
            "worst_day_pnl_usd": float(result.worst_day_pnl_usd) if result.worst_day_pnl_usd is not None else None,
            "worst_day_date": result.worst_day_date,
            "cost_basis_method": result.cost_basis_method,
            "data_confidence": result.data_confidence,
        },
        "daily_series": result.daily_series,
        "pagination": {
            "limit": len(result.daily_series),
            "count": len(result.daily_series),
            "has_more": False,
        },
        "computed_at": None,
        "provenance": {"sources": ["silver_web3_events", "gold_entity_pnl", "coingecko"]},
    }).to_dict()
