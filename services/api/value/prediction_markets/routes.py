"""Prediction-market observation routes (observation-only, flag-gated).

``POST /v1/prediction-markets/observations/normalize`` validates a venue market
payload and returns the canonical ``MarketObservation``. It does not persist,
publish or execute anything; persistence and graph projection are separate,
later work. The venue must be enabled in addition to ingestion.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from actions.agentic_observability.foundation import active_tenant_id, require_permission
from shared.common.common import APIResponse
from value.prediction_markets.models import MarketVenue, PredictionMarketValidationError
from value.prediction_markets.normalizers import (
    normalize_kalshi_market,
    normalize_polymarket_market,
)

router = APIRouter(prefix="/v1/prediction-markets", tags=["prediction-markets"])

_NORMALIZERS = {
    MarketVenue.POLYMARKET: normalize_polymarket_market,
    MarketVenue.KALSHI: normalize_kalshi_market,
}


class NormalizeRequest(BaseModel):
    venue: MarketVenue
    payload: dict[str, Any]


def _venue_enabled(venue: MarketVenue) -> bool:
    from config.settings import settings

    cfg = settings.prediction_markets
    if not cfg.ingestion_enabled:
        return False
    return cfg.polymarket_enabled if venue is MarketVenue.POLYMARKET else cfg.kalshi_enabled


@router.post("/observations/normalize")
async def normalize_market_observation(body: NormalizeRequest, request: Request):
    require_permission(request, "write")
    if not _venue_enabled(body.venue):
        raise HTTPException(status_code=404, detail="Prediction-market observation is disabled")
    tenant_id = active_tenant_id(request)
    try:
        observation = _NORMALIZERS[body.venue](body.payload)
    except PredictionMarketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data = asdict(observation)
    data["tenant_id"] = tenant_id
    data["persisted"] = False
    return APIResponse(data=data).to_dict()
