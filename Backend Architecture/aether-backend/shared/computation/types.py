"""Canonical mathematical types for the Aether Computation Substrate.

Every authoritative number in Aether is one of these types. A type is not just a
unit label — it declares *what kind of mathematical object* the number is, which
aggregations are legal on it, how it serializes, and what "no value" means for
it. This is what stops a heuristic score from being read as a probability, an
allocated cost from being read as observed, or a page total from being summed as
a population total.

Design rules enforced here:
  - Money carries a currency and is a Decimal/decimal-string — never a float.
  - Probability is bounded ``[0, 1]``; ordinal/heuristic scores are explicitly
    NOT probabilities.
  - A Rate exposes its numerator and denominator; an undefined denominator
    yields ``value=None`` (never 0).
  - A Ratio is not silently a Percentage.
  - Graph metrics identify their snapshot and normalization population.

This module is pure (stdlib + pydantic). It intentionally does NOT import from
``services/`` so it can sit at the ``shared`` layer; the ``services/computation``
layer bridges these types to ``services/value`` for real valuation/rollups.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.computation.errors import TypeContractError


# --------------------------------------------------------------------------- #
# Decimal helpers (pure mirror of services/value semantics; unknown != 0)
# --------------------------------------------------------------------------- #
def to_decimal(value: object) -> Optional[Decimal]:
    """Parse to a finite ``Decimal`` or ``None`` — never 0 for bad/absent input.

    Booleans are rejected (``bool`` is an ``int`` subclass) and non-finite values
    become ``None`` so callers must decide explicitly (unknown is not zero).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        # Money/quantities must not be constructed from binary floats; callers
        # that legitimately have a float must stringify at their boundary.
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def to_decimal_string(value: object) -> Optional[str]:
    """Normalize a numeric value to a plain (non-scientific) decimal string."""
    d = to_decimal(value)
    return None if d is None else format(d, "f")


# --------------------------------------------------------------------------- #
# Type taxonomy
# --------------------------------------------------------------------------- #
class MathType(str, Enum):
    """The canonical mathematical type of a computed value."""

    INTEGER_COUNT = "integer_count"
    FRACTIONAL_COUNT = "fractional_count"
    MONEY = "money"
    RATE = "rate"
    RATIO = "ratio"
    PERCENTAGE = "percentage"
    DURATION = "duration"
    QUANTITY = "quantity"
    BALANCE = "balance"
    PROBABILITY = "probability"
    ORDINAL_SCORE = "ordinal_score"
    HEURISTIC_SCORE = "heuristic_score"
    UNCALIBRATED_SCORE = "uncalibrated_score"
    RANK = "rank"
    PERCENTILE = "percentile"
    DISTRIBUTION = "distribution"
    INTERVAL = "interval"
    VECTOR = "vector"
    GRAPH_METRIC = "graph_metric"
    TRISTATE = "tristate"
    TIMESTAMPED_VALUE = "timestamped_value"


MATH_TYPES: tuple[str, ...] = tuple(m.value for m in MathType)


class CanonicalValue(BaseModel):
    """Base for every canonical value type.

    Subclasses set ``math_type`` and add their own fields/invariants. All are
    frozen: a canonical value is an immutable fact once constructed.
    """

    model_config = ConfigDict(frozen=True)

    math_type: MathType


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #
class IntegerCount(CanonicalValue):
    """A whole-number count of discrete, observed things. Never fractional."""

    math_type: MathType = MathType.INTEGER_COUNT
    value: Optional[int] = None
    unit: str = "count"
    allow_negative: bool = False

    @model_validator(mode="after")
    def _check(self) -> "IntegerCount":
        if self.value is not None and not self.allow_negative and self.value < 0:
            raise TypeContractError(f"IntegerCount must be >= 0 (got {self.value})")
        return self


class FractionalCount(CanonicalValue):
    """A fractional count — e.g. attributed conversions credited across touches.

    Stored as a decimal string so credit is never silently truncated to an int.
    """

    math_type: MathType = MathType.FRACTIONAL_COUNT
    amount: Optional[str] = None
    unit: str = "count"

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Optional[str]:
        if v is None or isinstance(v, str):
            return v
        s = to_decimal_string(v)
        if s is None and v is not None:
            raise TypeContractError(f"FractionalCount amount is not numeric: {v!r}")
        return s

    def as_decimal(self) -> Optional[Decimal]:
        return to_decimal(self.amount)


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #
class Money(CanonicalValue):
    """A monetary amount in a specific currency.

    ``amount`` is a decimal string (or ``None`` for an unknown/unpriced value —
    never 0). ``currency`` is required and non-empty: an amount without a
    currency is meaningless and forbidden. Binary floats are rejected outright.
    """

    math_type: MathType = MathType.MONEY
    amount: Optional[str] = None
    currency: str

    @field_validator("currency")
    @classmethod
    def _currency_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise TypeContractError("Money requires a non-empty currency")
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Optional[str]:
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, float):
            raise TypeContractError(
                "Money amount must be a Decimal/decimal string, not a float"
            )
        s = to_decimal_string(v)
        if s is None:
            raise TypeContractError(f"Money amount is not a finite number: {v!r}")
        return s

    def as_decimal(self) -> Optional[Decimal]:
        return to_decimal(self.amount)


# --------------------------------------------------------------------------- #
# Rates / ratios / percentages
# --------------------------------------------------------------------------- #
class Rate(CanonicalValue):
    """A rate = numerator / denominator, always exposing both.

    An undefined denominator (``None`` or 0) yields ``value=None`` — an
    unmeasurable rate is not a real 0.
    """

    math_type: MathType = MathType.RATE
    numerator: Optional[str] = None
    denominator: Optional[str] = None
    value: Optional[float] = None
    unit: str = "ratio"

    @model_validator(mode="after")
    def _derive(self) -> "Rate":
        num = to_decimal(self.numerator)
        den = to_decimal(self.denominator)
        if den is None or den == 0:
            object.__setattr__(self, "value", None)
        elif num is not None and self.value is None:
            object.__setattr__(self, "value", float(num / den))
        return self

    @classmethod
    def build(cls, numerator: object, denominator: object, *, unit: str = "ratio") -> "Rate":
        return cls(
            numerator=to_decimal_string(numerator),
            denominator=to_decimal_string(denominator),
            unit=unit,
        )


class Ratio(CanonicalValue):
    """A dimensionless ratio. NOT automatically a percentage."""

    math_type: MathType = MathType.RATIO
    value: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None

    @model_validator(mode="after")
    def _bounds(self) -> "Ratio":
        if self.value is not None:
            if self.lower is not None and self.value < self.lower:
                raise TypeContractError(f"Ratio {self.value} below lower {self.lower}")
            if self.upper is not None and self.value > self.upper:
                raise TypeContractError(f"Ratio {self.value} above upper {self.upper}")
        return self


class Percentage(CanonicalValue):
    """A percentage (0–100 scale) carrying the metadata that it IS a percentage.

    A ratio is never silently rendered as a percentage; the conversion is
    explicit via :meth:`from_ratio`.
    """

    math_type: MathType = MathType.PERCENTAGE
    value: Optional[float] = None

    @classmethod
    def from_ratio(cls, ratio: Optional[float]) -> "Percentage":
        return cls(value=None if ratio is None else ratio * 100.0)


# --------------------------------------------------------------------------- #
# Probability vs scores (semantically distinct)
# --------------------------------------------------------------------------- #
class Probability(CanonicalValue):
    """A probability in ``[0, 1]``.

    ``calibrated`` must be truthful: an empirically-uncalibrated number must not
    claim to be a calibrated probability (use :class:`UncalibratedScore`).
    """

    math_type: MathType = MathType.PROBABILITY
    value: Optional[float] = None
    calibrated: bool = False
    calibration_segment: Optional[str] = None

    @model_validator(mode="after")
    def _bounds(self) -> "Probability":
        if self.value is not None and not (0.0 <= self.value <= 1.0):
            raise TypeContractError(f"Probability must be in [0,1] (got {self.value})")
        return self


class OrdinalScore(CanonicalValue):
    """A rule-based ordinal score on a declared scale. NOT a probability."""

    math_type: MathType = MathType.ORDINAL_SCORE
    value: Optional[float] = None
    scale_min: float = 0.0
    scale_max: float = 100.0

    @model_validator(mode="after")
    def _bounds(self) -> "OrdinalScore":
        if self.value is not None and not (self.scale_min <= self.value <= self.scale_max):
            raise TypeContractError(
                f"OrdinalScore {self.value} outside [{self.scale_min}, {self.scale_max}]"
            )
        return self


class HeuristicScore(OrdinalScore):
    """A handcrafted heuristic score. NOT calibrated, NOT a probability."""

    math_type: MathType = MathType.HEURISTIC_SCORE


class UncalibratedScore(CanonicalValue):
    """A model score that is NOT empirically calibrated to a probability."""

    math_type: MathType = MathType.UNCALIBRATED_SCORE
    value: Optional[float] = None
    note: str = "uncalibrated — do not interpret as a probability"


# --------------------------------------------------------------------------- #
# Rank / percentile / distribution / interval / vector
# --------------------------------------------------------------------------- #
class Rank(CanonicalValue):
    """A 1-based rank within a population of a declared size."""

    math_type: MathType = MathType.RANK
    value: Optional[int] = None
    population_size: Optional[int] = None

    @model_validator(mode="after")
    def _check(self) -> "Rank":
        if self.value is not None and self.value < 1:
            raise TypeContractError(f"Rank is 1-based (got {self.value})")
        if (
            self.value is not None
            and self.population_size is not None
            and self.value > self.population_size
        ):
            raise TypeContractError("Rank exceeds population size")
        return self


class Percentile(CanonicalValue):
    """A percentile in ``[0, 100]``."""

    math_type: MathType = MathType.PERCENTILE
    value: Optional[float] = None

    @model_validator(mode="after")
    def _bounds(self) -> "Percentile":
        if self.value is not None and not (0.0 <= self.value <= 100.0):
            raise TypeContractError(f"Percentile must be in [0,100] (got {self.value})")
        return self


class Interval(CanonicalValue):
    """A closed interval ``[low, high]`` (e.g. a confidence/prediction band)."""

    math_type: MathType = MathType.INTERVAL
    low: Optional[float] = None
    high: Optional[float] = None

    @model_validator(mode="after")
    def _order(self) -> "Interval":
        if self.low is not None and self.high is not None and self.low > self.high:
            raise TypeContractError(f"Interval low {self.low} > high {self.high}")
        return self


class Distribution(CanonicalValue):
    """A discrete distribution over named buckets (weights need not sum to 1)."""

    math_type: MathType = MathType.DISTRIBUTION
    buckets: dict[str, float] = Field(default_factory=dict)


class Vector(CanonicalValue):
    """A numeric vector of a declared dimension."""

    math_type: MathType = MathType.VECTOR
    values: list[float] = Field(default_factory=list)
    dimension: Optional[int] = None

    @model_validator(mode="after")
    def _dim(self) -> "Vector":
        if self.dimension is not None and len(self.values) != self.dimension:
            raise TypeContractError("Vector length does not match declared dimension")
        return self


class GraphMetric(CanonicalValue):
    """A graph-derived metric that identifies the graph it was computed over.

    A graph score is meaningless without its snapshot and normalization
    population — scores from different snapshots are not comparable.
    """

    math_type: MathType = MathType.GRAPH_METRIC
    value: Optional[float] = None
    graph_snapshot_id: str
    node_population: Optional[str] = None
    normalization_population: Optional[str] = None
    algorithm: Optional[str] = None
    algorithm_version: Optional[str] = None


# --------------------------------------------------------------------------- #
# Duration / quantity / balance / tristate / timestamped
# --------------------------------------------------------------------------- #
class Duration(CanonicalValue):
    """A time span in seconds."""

    math_type: MathType = MathType.DURATION
    seconds: Optional[float] = None


class Quantity(CanonicalValue):
    """A dimensioned physical/logical quantity (decimal amount + unit)."""

    math_type: MathType = MathType.QUANTITY
    amount: Optional[str] = None
    unit: str

    def as_decimal(self) -> Optional[Decimal]:
        return to_decimal(self.amount)


class Balance(CanonicalValue):
    """A point-in-time balance. Balances are NOT summed through time."""

    math_type: MathType = MathType.BALANCE
    amount: Optional[str] = None
    currency: Optional[str] = None
    as_of: Optional[str] = None


class TriState(CanonicalValue):
    """True / False / Unknown — where unknown is a first-class value."""

    math_type: MathType = MathType.TRISTATE
    value: Optional[bool] = None  # None == unknown


class TimestampedValue(CanonicalValue):
    """A scalar value bound to the instant it is true for."""

    math_type: MathType = MathType.TIMESTAMPED_VALUE
    value: Optional[float] = None
    at: Optional[str] = None


__all__ = [
    "to_decimal",
    "to_decimal_string",
    "MathType",
    "MATH_TYPES",
    "CanonicalValue",
    "IntegerCount",
    "FractionalCount",
    "Money",
    "Rate",
    "Ratio",
    "Percentage",
    "Probability",
    "OrdinalScore",
    "HeuristicScore",
    "UncalibratedScore",
    "Rank",
    "Percentile",
    "Interval",
    "Distribution",
    "Vector",
    "GraphMetric",
    "Duration",
    "Quantity",
    "Balance",
    "TriState",
    "TimestampedValue",
]
