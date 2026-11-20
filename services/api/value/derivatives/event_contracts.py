"""Canonical binary/categorical event-contract instruments (derivatives plane).

Prediction-market venues (Polymarket, Kalshi) list event contracts: a
condition with two or more mutually exclusive outcomes, each tradable as an
outcome token whose price is an implied probability in ``[0, 1]``. This module
makes those instruments first-class members of the derivatives plane so that
outcome positions share the read-only fill, position-epoch, P&L, and
propagation machinery used for perpetuals.

Identity:

* ``event_contract_ref`` — ``"<venue>:<deployment>:<condition>"``; the
  instrument a "same side" comparison is made against.
* ``canonical_market_id`` of an outcome token — ``"<venue>:<deployment>:<token>"``
  (the same shape ``VenueDerivativesAdapter.canonical_market_id`` produces), so
  fills on one outcome token reconstruct one position epoch.
* ``side`` of an outcome position — the outcome label bought. Selling an outcome
  token only reduces it; event contracts have no short side.

Observation-only: a quote is not a fill, a venue-reported resolution is not a
settlement, and Aether never trades. Floats are rejected for every amount that
is not already a market quote from a legacy JSON float (quotes from JSON floats
go through ``repr`` exactly as the original prediction-markets normalizer did).

The market-level normalizers (``normalize_polymarket_market`` /
``normalize_kalshi_market``) live here; ``value.prediction_markets.normalizers``
re-exports them for the existing observation routes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Mapping, Optional

from value.prediction_markets.models import (
    MarketObservation,
    MarketStatus,
    MarketVenue,
    OutcomeQuote,
    PredictionMarketValidationError,
)

INSTRUMENT_TYPE = "event_contract"
SCHEMA_VERSION = "derivatives.event_contract.v1"


class ResolutionState(StrEnum):
    """Venue-reported lifecycle of an event contract (never a settlement claim)."""

    OPEN = "open"
    CLOSED = "closed"
    RESOLVED_REPORTED = "resolved_reported"
    UNKNOWN = "unknown"


_STATUS_TO_RESOLUTION = {
    MarketStatus.OPEN: ResolutionState.OPEN,
    MarketStatus.CLOSED: ResolutionState.CLOSED,
    MarketStatus.RESOLVED: ResolutionState.RESOLVED_REPORTED,
    MarketStatus.UNKNOWN: ResolutionState.UNKNOWN,
}


@dataclass(frozen=True)
class EventOutcome:
    """One outcome of an event contract and its tradable token (if known)."""

    index: int
    label: str
    token_id: Optional[str] = None
    implied_probability: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if isinstance(self.implied_probability, float):
            raise PredictionMarketValidationError("implied_probability must not be a float")
        p = self.implied_probability
        if p is not None and not (Decimal("0") <= p <= Decimal("1")):
            raise PredictionMarketValidationError("implied_probability must be within [0, 1]")


@dataclass(frozen=True)
class EventContractInstrument:
    """Canonical event-contract instrument in the derivatives plane."""

    venue: str
    deployment: str
    condition_ref: str
    title: str
    resolution_state: ResolutionState
    outcomes: tuple[EventOutcome, ...] = field(default_factory=tuple)
    closes_at: Optional[str] = None
    reported_resolution: Optional[str] = None
    volume: Optional[Decimal] = None
    instrument_type: str = INSTRUMENT_TYPE
    schema_version: str = SCHEMA_VERSION
    execution_by_aether: bool = False

    def __post_init__(self) -> None:
        if not self.condition_ref:
            raise PredictionMarketValidationError("condition_ref is required")
        if self.execution_by_aether:
            raise PredictionMarketValidationError("Aether never executes event-contract orders")
        if isinstance(self.volume, float):
            raise PredictionMarketValidationError("volume must not be a float")
        labels = [o.label for o in self.outcomes]
        if len(labels) != len(set(labels)):
            raise PredictionMarketValidationError("outcome labels must be unique")

    @property
    def event_contract_ref(self) -> str:
        return event_contract_ref(self.venue, self.deployment, self.condition_ref)

    def outcome_for_token(self, token_id: str) -> Optional[EventOutcome]:
        for outcome in self.outcomes:
            if outcome.token_id == token_id:
                return outcome
        return None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instrument_type": self.instrument_type,
            "venue": self.venue,
            "deployment": self.deployment,
            "event_contract_ref": self.event_contract_ref,
            "condition_ref": self.condition_ref,
            "title": self.title,
            "resolution_state": self.resolution_state.value,
            "outcomes": [
                {
                    "index": o.index,
                    "label": o.label,
                    "token_id": o.token_id,
                    "implied_probability": _dec_str(o.implied_probability),
                    "canonical_market_id": (
                        outcome_market_id(self.venue, self.deployment, o.token_id)
                        if o.token_id
                        else None
                    ),
                }
                for o in self.outcomes
            ],
            "closes_at": self.closes_at,
            "reported_resolution": self.reported_resolution,
            "volume": _dec_str(self.volume),
            "execution_by_aether": False,
        }


def event_contract_ref(venue: str, deployment: str, condition_ref: str) -> str:
    return f"{venue}:{deployment}:{condition_ref}"


def outcome_market_id(venue: str, deployment: str, token_id: str) -> str:
    return f"{venue}:{deployment}:{token_id}"


def instrument_from_observation(
    observation: MarketObservation,
    *,
    deployment: str = "mainnet",
    token_ids: tuple[Optional[str], ...] = (),
) -> EventContractInstrument:
    """Lift a market-level observation into the canonical instrument."""
    outcomes = tuple(
        EventOutcome(
            index=i,
            label=quote.label,
            token_id=token_ids[i] if i < len(token_ids) else None,
            implied_probability=quote.price,
        )
        for i, quote in enumerate(observation.outcomes)
    )
    return EventContractInstrument(
        venue=observation.venue.value,
        deployment=deployment,
        condition_ref=observation.market_ref,
        title=observation.title,
        resolution_state=_STATUS_TO_RESOLUTION[observation.status],
        outcomes=outcomes,
        closes_at=observation.closes_at,
        reported_resolution=observation.reported_resolution,
        volume=observation.volume,
    )


# ── market-level normalizers (moved from value.prediction_markets) ──────────


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


def _dec_str(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


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


def polymarket_instrument(payload: Mapping[str, Any], *, deployment: str = "mainnet") -> EventContractInstrument:
    """Gamma market record -> canonical instrument, keeping ``clobTokenIds``."""
    observation = normalize_polymarket_market(payload)
    token_ids = tuple(str(t) for t in _json_list(payload.get("clobTokenIds"), "clobTokenIds"))
    if token_ids and len(token_ids) != len(observation.outcomes):
        raise PredictionMarketValidationError("outcomes and clobTokenIds length differ")
    return instrument_from_observation(observation, deployment=deployment, token_ids=token_ids)


def _kalshi_yes_probability(payload: Mapping[str, Any]) -> Optional[Decimal]:
    """Kalshi last trade as a YES probability.

    Current Kalshi records carry ``last_price_dollars`` (a 0-1 decimal string);
    older records carry integer-cent ``last_price``. Both are accepted.
    """
    dollars = _dec(payload.get("last_price_dollars"), "last_price_dollars")
    if dollars is not None:
        return dollars
    cents = _dec(payload.get("last_price"), "last_price")
    return cents / Decimal(100) if cents is not None else None


def normalize_kalshi_market(payload: Mapping[str, Any]) -> MarketObservation:
    """Normalize a Kalshi market record to a YES/NO observation."""
    yes = _kalshi_yes_probability(payload)
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
    volume = _dec(payload.get("volume_fp"), "volume_fp")
    if volume is None:
        volume = _dec(payload.get("volume"), "volume")
    return MarketObservation(
        venue=MarketVenue.KALSHI,
        market_ref=str(payload.get("ticker") or ""),
        title=str(payload.get("title") or ""),
        status=status,
        outcomes=(OutcomeQuote("yes", yes), OutcomeQuote("no", no)),
        volume=volume,
        closes_at=payload.get("close_time"),
        reported_resolution=str(result) if result else None,
    )


def kalshi_instrument(payload: Mapping[str, Any], *, deployment: str = "mainnet") -> EventContractInstrument:
    """Kalshi market record -> canonical instrument (YES/NO; no token ids)."""
    return instrument_from_observation(normalize_kalshi_market(payload), deployment=deployment)


__all__ = [
    "INSTRUMENT_TYPE",
    "EventContractInstrument",
    "EventOutcome",
    "ResolutionState",
    "event_contract_ref",
    "instrument_from_observation",
    "kalshi_instrument",
    "normalize_kalshi_market",
    "normalize_polymarket_market",
    "outcome_market_id",
    "polymarket_instrument",
]
