"""Canonical prediction-market observation contracts.

Observation-only: these records describe what a venue reported about a market.
A quoted outcome price is not a fill, a reported resolution is not a settlement,
and Aether never places orders. All numeric fields are ``Decimal`` (floats are
rejected) and provider references are preserved verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
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
