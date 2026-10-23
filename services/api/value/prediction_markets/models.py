"""Canonical prediction-market observation contracts.

Observation-only: these records describe what a venue reported about a market.
A quoted outcome price is not a fill, a reported resolution is not a settlement,
and Aether never places orders. All numeric fields are ``Decimal`` (floats are
rejected) and provider references are preserved verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Optional

SCHEMA_VERSION = "prediction_market.observation.v1"


class PredictionMarketValidationError(ValueError):
    """Provider data cannot be safely normalized."""


class MarketVenue(StrEnum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class MarketStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OutcomeQuote:
    """One outcome's reported price, as an implied probability in [0, 1]."""

    label: str
    price: Optional[Decimal]

    def __post_init__(self) -> None:
        if isinstance(self.price, float):
            raise PredictionMarketValidationError("price must not be a float")
        if self.price is not None and not (Decimal("0") <= self.price <= Decimal("1")):
            raise PredictionMarketValidationError("price must be within [0, 1]")


@dataclass(frozen=True)
class MarketObservation:
    venue: MarketVenue
    market_ref: str
    title: str
    status: MarketStatus
    outcomes: tuple[OutcomeQuote, ...] = field(default_factory=tuple)
    volume: Optional[Decimal] = None
    closes_at: Optional[str] = None
    # Venue-reported resolution label only; never evidence that funds settled.
    reported_resolution: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    execution_by_aether: bool = False

    def __post_init__(self) -> None:
        if not self.market_ref:
            raise PredictionMarketValidationError("market_ref is required")
        if isinstance(self.volume, float):
            raise PredictionMarketValidationError("volume must not be a float")
        if self.execution_by_aether:
            raise PredictionMarketValidationError("Aether never executes market orders")


def _dec_str(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


def _dec_from(value: object, name: str) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise PredictionMarketValidationError(f"{name} is not a decimal: {value!r}") from exc


def observation_to_payload(observation: MarketObservation) -> dict:
    """JSON-safe, deterministic form of an observation (Decimals as strings)."""
    return {
        "schema_version": observation.schema_version,
        "venue": observation.venue.value,
        "market_ref": observation.market_ref,
        "title": observation.title,
        "status": observation.status.value,
        "outcomes": [
            {"label": quote.label, "price": _dec_str(quote.price)}
            for quote in observation.outcomes
        ],
        "volume": _dec_str(observation.volume),
        "closes_at": observation.closes_at,
        "reported_resolution": observation.reported_resolution,
        "execution_by_aether": observation.execution_by_aether,
    }


def observation_from_payload(payload: dict) -> MarketObservation:
    return MarketObservation(
        venue=MarketVenue(payload["venue"]),
        market_ref=payload["market_ref"],
        title=payload.get("title", ""),
        status=MarketStatus(payload["status"]),
        outcomes=tuple(
            OutcomeQuote(item["label"], _dec_from(item.get("price"), "price"))
            for item in payload.get("outcomes", [])
        ),
        volume=_dec_from(payload.get("volume"), "volume"),
        closes_at=payload.get("closes_at"),
        reported_resolution=payload.get("reported_resolution"),
        schema_version=payload.get("schema_version", SCHEMA_VERSION),
        execution_by_aether=bool(payload.get("execution_by_aether", False)),
    )
