"""Prediction-market observation routes (observation-only, flag-gated).

- ``POST /observations/normalize`` validates a venue market payload and returns
  the canonical ``MarketObservation`` without storing it.
- ``POST /observations`` normalizes and stores it (idempotent per content).
- ``GET /markets/{venue}/{market_ref}`` returns the latest stored observation,
  optionally as of an instant.

The venue must be enabled in addition to ingestion. Nothing here publishes,
projects into the graph, or executes orders; a reported resolution is not
settlement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from actions.agentic_observability.foundation import active_tenant_id, require_permission
from shared.common.common import APIResponse
from value.prediction_markets.models import (
    MarketVenue,
    PredictionMarketValidationError,
    observation_to_payload,
)
from value.prediction_markets.normalizers import (
    normalize_kalshi_market,
    normalize_polymarket_market,
)
from value.prediction_markets.repository import PredictionMarketObservationRepository

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


def _normalize(body: NormalizeRequest):
    try:
        return _NORMALIZERS[body.venue](body.payload)
    except PredictionMarketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_enabled(venue: MarketVenue) -> None:
    if not _venue_enabled(venue):
        raise HTTPException(status_code=404, detail="Prediction-market observation is disabled")


@router.post("/observations/normalize")
async def normalize_market_observation(body: NormalizeRequest, request: Request):
    require_permission(request, "write")
    _require_enabled(body.venue)
    tenant_id = active_tenant_id(request)
    data = observation_to_payload(_normalize(body))
    data["tenant_id"] = tenant_id
    data["persisted"] = False
    return APIResponse(data=data).to_dict()


@router.post("/observations")
async def record_market_observation(body: NormalizeRequest, request: Request):
    require_permission(request, "write")
    _require_enabled(body.venue)
    tenant_id = active_tenant_id(request)
    observation = _normalize(body)
    _, created = await PredictionMarketObservationRepository().record(tenant_id, observation)
    data = observation_to_payload(observation)
    data["tenant_id"] = tenant_id
    data["persisted"] = True
    data["created"] = created
    return APIResponse(data=data).to_dict()


@router.get("/markets/{venue}/{market_ref:path}")
async def get_market_observation(
    venue: MarketVenue,
    market_ref: str,
    request: Request,
    as_of: Optional[datetime] = Query(default=None),
):
    require_permission(request, "read")
    _require_enabled(venue)
    tenant_id = active_tenant_id(request)
    try:
        found = await PredictionMarketObservationRepository().latest(
            tenant_id, venue, market_ref, as_of=as_of
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="No observation for this market")
    observation, received_at = found
    data = observation_to_payload(observation)
    data["tenant_id"] = tenant_id
    data["received_at"] = received_at.isoformat()
    return APIResponse(data=data).to_dict()
