"""Pure, offline normalizers: venue market payloads -> ``MarketObservation``."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from value.prediction_markets.models import (
    MarketObservation,
    MarketStatus,
    MarketVenue,
    OutcomeQuote,
    PredictionMarketValidationError,
)


def _dec(value: Any, name: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise PredictionMarketValidationError(f"{name} is not a decimal: {value!r}") from exc


def _json_list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise PredictionMarketValidationError(f"{name} is not valid JSON") from exc
    if not isinstance(value, list):
        raise PredictionMarketValidationError(f"{name} must be a list")
    return value


def normalize_polymarket_market(payload: Mapping[str, Any]) -> MarketObservation:
    """Normalize a Polymarket Gamma ``markets`` record. Prices are already 0-1."""
    ref = payload.get("conditionId") or payload.get("id")
    labels = _json_list(payload.get("outcomes"), "outcomes")
    prices = _json_list(payload.get("outcomePrices"), "outcomePrices")
    if prices and len(prices) != len(labels):
        raise PredictionMarketValidationError("outcomes and outcomePrices length differ")
    quotes = tuple(
        OutcomeQuote(str(label), _dec(prices[i], "outcomePrices") if prices else None)
        for i, label in enumerate(labels)
    )
    if payload.get("closed"):
        status = MarketStatus.CLOSED
    elif payload.get("active"):
        status = MarketStatus.OPEN
    else:
        status = MarketStatus.UNKNOWN
    return MarketObservation(
        venue=MarketVenue.POLYMARKET,
        market_ref=str(ref or ""),
        title=str(payload.get("question") or ""),
        status=status,
        outcomes=quotes,
        volume=_dec(payload.get("volume"), "volume"),
        closes_at=payload.get("endDate"),
    )


def normalize_kalshi_market(payload: Mapping[str, Any]) -> MarketObservation:
    """Normalize a Kalshi market record. Prices are integer cents -> probability."""
    last = _dec(payload.get("last_price"), "last_price")
    yes = last / Decimal(100) if last is not None else None
    no = Decimal(1) - yes if yes is not None else None
    raw_status = str(payload.get("status") or "").lower()
    result = payload.get("result") or None
    if raw_status in ("settled", "finalized", "determined") or result:
        status = MarketStatus.RESOLVED
    elif raw_status in ("closed", "inactive"):
        status = MarketStatus.CLOSED
    elif raw_status in ("open", "active", "initialized"):
        status = MarketStatus.OPEN
    else:
        status = MarketStatus.UNKNOWN
    return MarketObservation(
        venue=MarketVenue.KALSHI,
        market_ref=str(payload.get("ticker") or ""),
        title=str(payload.get("title") or ""),
        status=status,
        outcomes=(OutcomeQuote("yes", yes), OutcomeQuote("no", no)),
        volume=_dec(payload.get("volume"), "volume"),
        closes_at=payload.get("close_time"),
        reported_resolution=str(result) if result else None,
    )
