"""Canonical economic domain contracts for the Economic360 projection (S3).

Economic360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). These models are the plane's *economic
domain* vocabulary: the typed shapes the projection uses to read canonical
economic facts (payments, commerce, campaign economics, value normalization)
and to describe them back without re-answering questions the canonical planes
already answer.

Non-negotiable invariants:

* **No cross-currency arithmetic, ever.** Every monetary amount is either
  USD-normalized (``MonetaryAmount.usd_value``) or carries a native amount +
  currency with an explicit normalized ``usd_value``. ``safe_usd_total`` sums
  ONLY normalized USD figures; a raw native sum across multiple currencies is
  rejected (:class:`MixedCurrencyError`). Native amounts are only ever summed
  within a single currency (:func:`native_total`).
* **Monetary absences stay ``None``.** An unpriced amount is ``usd_value =
  None`` — never coerced to ``0``. ``MISSING_PRICE`` is a typed warning, never
  an invented figure.
* **Reuse, never redefine.** ``EntityRef`` / ``EvidenceRef`` /
  ``TimeRangeFilter`` are the canonical operational-intelligence primitives
  imported from ``services/operational_intelligence/models.py``. This module
  declares NO second copy of any of them.
* **Anti-patterns surface as typed warnings / degradations.** Mixed currency,
  missing price, and possible double-count are :class:`EconomicWarning`
  values with stable :class:`EconomicWarningCode` codes — never silent
  assertions and never fabricated USD.

All models inherit :class:`EconomicContract` (``extra="forbid"``) so a
misspelled field raises instead of silently passing — the projection plane
fails closed.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Reused canonical primitives (single-monolith reuse — never redefined here).
from services.operational_intelligence.models import (
    EntityRef,
    EvidenceRef,
    TimeRangeFilter,
)

# The union of section states the projection plane can carry. Imported so the
# economic contracts can type section/content state honestly without importing
# the whole projection plane at module scope.
EconomicSectionState = Literal[
    "available",
    "degraded",
    "empty",
    "missing",
    "not_applicable",
    "suppressed",
    "unknown",
]


class EconomicContract(BaseModel):
    """Economic-domain contract base — fails closed on unknown fields."""

    model_config = ConfigDict(extra="forbid")


class EconomicWarningCode(str, Enum):
    """Stable typed codes for the economic anti-patterns a projection surfaces.

    These mirror ``EconomicWarningCode`` in ``packages/shared/economic-metrics.ts``.
    They are surfaced as warnings/degradations on the projection result — never
    used to fabricate a value.
    """

    MIXED_CURRENCY = "MIXED_CURRENCY"
    MISSING_PRICE = "MISSING_PRICE"
    POSSIBLE_DOUBLE_COUNT = "POSSIBLE_DOUBLE_COUNT"
    STALE_PRICE = "STALE_PRICE"
    LOW_CONFIDENCE_ATTRIBUTION = "LOW_CONFIDENCE_ATTRIBUTION"


class EconomicWarning(EconomicContract):
    """One typed anti-pattern warning on an economic projection result."""

    code: EconomicWarningCode
    message: str
    severity: Literal["info", "warning", "critical"] = "warning"
    details: Optional[dict[str, Any]] = None


class EconomicValuationContext(EconomicContract):
    """Price source + priced_at for a monetary amount's USD normalization.

    Carries enough to signal ``MISSING_PRICE`` WITHOUT fabricating a value: when
    a native amount cannot be priced, ``price_source`` stays ``"unavailable"``
    and ``priced_at`` is ``None``, so a caller can distinguish "unpriced" from
    "priced" and never guess a number.
    """

    currency: str
    price_source: str = "unavailable"
    priced_at: Optional[str] = None
    rate: Optional[Decimal] = None
    freshness: Optional[str] = None
    confidence: Optional[str] = None


class MonetaryAmount(EconomicContract):
    """A single monetary amount — native denomination + explicit USD value.

    ``amount`` / ``currency`` are the native denomination. ``usd_value`` is the
    explicit normalized USD figure and is ``None`` when unpriced — never coerced
    to ``0``. ``valuation`` records how/when the USD figure was derived.
    """

    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    usd_value: Optional[Decimal] = None
    valuation: Optional[EconomicValuationContext] = None


class EconomicEvent(EconomicContract):
    """One observed economic event (payment, charge, refund, settlement)."""

    id: str
    tenant_id: str
    subject: EntityRef
    event_type: str
    occurred_at: str
    amount: Optional[MonetaryAmount] = None
    flow_id: Optional[str] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


class EconomicFlow(EconomicContract):
    """A flow of value between subjects over a window (spend, revenue, x402)."""

    id: str
    tenant_id: str
    flow_type: str
    source: Optional[EntityRef] = None
    destination: Optional[EntityRef] = None
    amount: Optional[MonetaryAmount] = None
    window: Optional[TimeRangeFilter] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


class EconomicPosition(EconomicContract):
    """A stock economic position (balance, exposure, reserve, holding)."""

    id: str
    tenant_id: str
    holder: EntityRef
    position_type: str
    amount: Optional[MonetaryAmount] = None
    as_of: Optional[str] = None
    # Double-count signals: a derivative receipt whose underlying position is
    # ALSO held directly risks being counted twice (POSSIBLE_DOUBLE_COUNT).
    is_derivative_receipt: bool = False
    underlying_position_id: Optional[str] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


class EconomicObligation(EconomicContract):
    """A payable / receivable / owed economic obligation."""

    id: str
    tenant_id: str
    obligation_type: str
    debtor: EntityRef
    creditor: EntityRef
    amount: Optional[MonetaryAmount] = None
    due_at: Optional[str] = None
    status: str = "open"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


class EconomicAllocationTarget(EconomicContract):
    """One target of an :class:`EconomicAllocation`."""

    target_id: str
    allocated_amount: Optional[MonetaryAmount] = None
    weight: Optional[Decimal] = None


class EconomicAllocation(EconomicContract):
    """An allocation of a cost/value across targets (campaign -> journeys).

    Mirrors the canonical allocation semantics in ``services/computation``
    (``canonical_journey_allocated_cost``): the sum of targets + residual
    conserves the source amount within a single currency.
    """

    id: str
    tenant_id: str
    policy: str
    source_amount: Optional[MonetaryAmount] = None
    targets: list[EconomicAllocationTarget] = Field(default_factory=list)
    residual: Optional[MonetaryAmount] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


class EconomicAdjustment(EconomicContract):
    """A restatement / correction applied to a prior amount."""

    id: str
    tenant_id: str
    target_id: str
    reason: str
    prior_amount: Optional[MonetaryAmount] = None
    adjusted_amount: Optional[MonetaryAmount] = None
    applied_at: Optional[str] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


class EconomicSettlement(EconomicContract):
    """A settlement on a payment rail (x402, card, ach, internal credit)."""

    id: str
    tenant_id: str
    settlement_type: str
    source: EntityRef
    destination: EntityRef
    amount: Optional[MonetaryAmount] = None
    settled_at: Optional[str] = None
    status: str = "completed"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[EconomicWarning] = Field(default_factory=list)


# ── Anti-pattern detection / safe-value helpers ──────────────────────────────


class MixedCurrencyError(ValueError):
    """Raised when a caller attempts a raw cross-currency monetary sum.

    The USD-first invariant (ADR-010 / ``services/value``): a mixed native
    scalar is never produced. Normalized-USD sums remain legal and are the
    projection's only flat-total shape.
    """


def native_currencies(amounts: Iterable[MonetaryAmount]) -> set[str]:
    """Distinct native currencies present on amounts that bear an amount."""
    currencies: set[str] = set()
    for amount in amounts:
        if amount.amount is not None and amount.currency:
            currencies.add(amount.currency)
    return currencies


def economic_warnings_for_amounts(
    amounts: Iterable[MonetaryAmount],
) -> list[EconomicWarning]:
    """Typed anti-pattern warnings for a set of monetary amounts.

    * ``MISSING_PRICE`` — a native amount exists but has no trusted USD value
      (an absence, never a fabricated figure);
    * ``MIXED_CURRENCY`` — amounts span multiple native currencies (the USD
      total is only as good as the per-currency valuations).
    """
    warnings: list[EconomicWarning] = []
    currencies: set[str] = set()
    missing_price = False
    for amount in amounts:
        if amount.amount is not None and amount.currency:
            currencies.add(amount.currency)
        if amount.amount is not None and amount.usd_value is None:
            missing_price = True
    if missing_price:
        warnings.append(
            EconomicWarning(
                code=EconomicWarningCode.MISSING_PRICE,
                message=(
                    "one or more native amounts have no trusted USD valuation; "
                    "the USD total may be understated"
                ),
                severity="warning",
            )
        )
    if len(currencies) > 1:
        warnings.append(
            EconomicWarning(
                code=EconomicWarningCode.MIXED_CURRENCY,
                message=(
                    "amounts span multiple native currencies; flat totals use "
                    "USD normalization only, never a raw native sum"
                ),
                severity="warning",
                details={"currencies": sorted(currencies)},
            )
        )
    return warnings


def safe_usd_total(
    amounts: Iterable[MonetaryAmount],
) -> tuple[Optional[Decimal], list[EconomicWarning]]:
    """Sum ONLY normalized USD figures; returns (None, warnings) when none priced.

    Monetary absences stay absent: if no amount carries a ``usd_value`` the
    total is ``None`` — never ``0``. This is the USD-first / safe-rollup shape
    from ``services/value`` applied to typed amounts.
    """
    # Materialize ONCE — the input may be a single-use generator.
    materialized = list(amounts)
    warnings = economic_warnings_for_amounts(materialized)
    total = Decimal(0)
    priced_any = False
    for amount in materialized:
        if amount.usd_value is not None:
            total += amount.usd_value
            priced_any = True
    return (total if priced_any else None), warnings


def require_single_currency(amounts: Iterable[MonetaryAmount]) -> Optional[str]:
    """The one native currency across amounts, or raise :class:`MixedCurrencyError`.

    Fail-closed: a raw native sum across currencies is REJECTED — the only
    legal flat total is USD-normalized.
    """
    currencies = native_currencies(amounts)
    if len(currencies) > 1:
        raise MixedCurrencyError(
            f"refusing to sum native amounts across currencies "
            f"{sorted(currencies)} — USD-first normalization required"
        )
    return next(iter(currencies), None)


def native_total(amounts: Iterable[MonetaryAmount]) -> Optional[MonetaryAmount]:
    """Sum native amounts ONLY when a single currency is present.

    Raises :class:`MixedCurrencyError` across currencies; returns ``None`` when
    there is nothing to sum. The result carries no ``usd_value`` unless a single
    trusted USD figure is derivable from the inputs' valuations.
    """
    # Materialize ONCE — the input may be a single-use generator.
    materialized = list(amounts)
    currency = require_single_currency(materialized)
    if currency is None:
        return None
    total = Decimal(0)
    for amount in materialized:
        if amount.amount is not None:
            total += amount.amount
    return MonetaryAmount(amount=total, currency=currency)


def detect_double_count(
    positions: Iterable[EconomicPosition],
) -> list[EconomicWarning]:
    """Flag positions where a derivative receipt and its underlying both appear.

    Mirrors ``detectDoubleCountRisk`` in ``packages/shared/economic-metrics.ts``:
    when a receipt's ``underlying_position_id`` is also held directly, the value
    risks being counted twice. Typed warning — never a fabricated figure.
    """
    # Only positions that are NOT themselves derivative receipts can be a held
    # underlying — a receipt's own underlying_position_id must never match itself.
    underlying: set[str] = {
        p.underlying_position_id
        for p in positions
        if not p.is_derivative_receipt and p.underlying_position_id is not None
    }
    warnings: list[EconomicWarning] = []
    for position in positions:
        if (
            position.is_derivative_receipt
            and position.underlying_position_id is not None
            and position.underlying_position_id in underlying
        ):
            warnings.append(
                EconomicWarning(
                    code=EconomicWarningCode.POSSIBLE_DOUBLE_COUNT,
                    message=(
                        f"derivative receipt and its underlying position are both "
                        f"present for {position.underlying_position_id}; value may "
                        f"be double-counted"
                    ),
                    severity="warning",
                    details={"position_id": position.underlying_position_id},
                )
            )
    return warnings


__all__ = [
    "EconomicAdjustment",
    "EconomicAllocation",
    "EconomicAllocationTarget",
    "EconomicContract",
    "EconomicEvent",
    "EconomicFlow",
    "EconomicObligation",
    "EconomicPosition",
    "EconomicSectionState",
    "EconomicSettlement",
    "EconomicValuationContext",
    "EconomicWarning",
    "EconomicWarningCode",
    "MixedCurrencyError",
    "MonetaryAmount",
    "detect_double_count",
    "economic_warnings_for_amounts",
    "native_currencies",
    "native_total",
    "require_single_currency",
    "safe_usd_total",
]
