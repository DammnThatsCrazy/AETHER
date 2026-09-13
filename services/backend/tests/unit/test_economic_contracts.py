"""Unit tests for the Economic360 domain contracts (slice S3).

The economic contracts enforce the plane's USD-first invariants (ADR-010): no
cross-currency sums ever, monetary absences stay ``None`` (never coerced to
``0``), and anti-patterns (mixed currency / missing price / possible
double-count) surface as typed warnings — never as invented values. They also
reuse the canonical primitives (``EntityRef`` / ``EvidenceRef`` /
``TimeRangeFilter``) instead of re-declaring them, and fail closed on unknown
fields (``extra="forbid"``).
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.economic.economic360_contracts import (  # noqa: E402
    EconomicAdjustment,
    EconomicAllocation,
    EconomicContract,
    EconomicEvent,
    EconomicFlow,
    EconomicObligation,
    EconomicPosition,
    EconomicSettlement,
    EconomicValuationContext,
    EconomicWarning,
    EconomicWarningCode,
    MixedCurrencyError,
    MonetaryAmount,
    detect_double_count,
    economic_warnings_for_amounts,
    native_total,
    require_single_currency,
    safe_usd_total,
)
from services.operational_intelligence.models import (  # noqa: E402
    EntityRef,
    EvidenceRef,
    TimeRangeFilter,
)

# Canonical primitives this slice must REUSE — the economic package must not
# declare a second copy of any of them.
CANONICAL_PRIMITIVES = (EntityRef, EvidenceRef, TimeRangeFilter)


def _amount(amount: str, currency: str, usd: str | None = None) -> MonetaryAmount:
    return MonetaryAmount(
        amount=Decimal(amount),
        currency=currency,
        usd_value=None if usd is None else Decimal(usd),
    )


def _evidence(ident: str = "ev_1") -> EvidenceRef:
    return EvidenceRef(id=ident, type="transaction", source="payments")


# ---------------------------------------------------------------------------
# No redefinition of canonical primitives
# ---------------------------------------------------------------------------

def test_reuses_canonical_entity_ref() -> None:
    event = EconomicEvent(
        id="e1",
        tenant_id="tenant-a",
        subject=EntityRef(kind="economic_resource", id="r1"),
        event_type="payment",
        occurred_at="2026-08-24T00:00:00Z",
    )
    assert type(event.subject) is EntityRef
    # The economic package does NOT declare a second EntityRef — the only one it
    # exposes IS the canonical object (identity, not a shadow).
    import services.economic.economic360_contracts as contracts

    assert contracts.EntityRef is EntityRef
    assert not hasattr(contracts, "PageRequest")
    assert not hasattr(contracts, "TimeRangeFilter") or contracts.TimeRangeFilter is TimeRangeFilter


def test_reuses_canonical_evidence_ref() -> None:
    event = EconomicEvent(
        id="e2",
        tenant_id="tenant-a",
        subject=EntityRef(kind="economic_resource", id="r1"),
        event_type="payment",
        occurred_at="2026-08-24T00:00:00Z",
        evidence=[_evidence()],
    )
    assert type(event.evidence[0]) is EvidenceRef
    import services.economic.economic360_contracts as contracts

    assert contracts.EvidenceRef is EvidenceRef


def test_reuses_canonical_time_range_filter() -> None:
    flow = EconomicFlow(
        id="f1",
        tenant_id="tenant-a",
        flow_type="revenue",
        window=TimeRangeFilter(from_="2026-01-01", to="2026-02-01"),
    )
    assert type(flow.window) is TimeRangeFilter
    assert flow.window.from_ == "2026-01-01"


# ---------------------------------------------------------------------------
# USD-first value semantics: no cross-currency sums, ever
# ---------------------------------------------------------------------------

def test_native_total_single_currency_sums() -> None:
    total = native_total([_amount("10.00", "USD"), _amount("5.00", "USD")])
    assert total is not None
    assert total.amount == Decimal("15.00")
    assert total.currency == "USD"


def test_native_total_across_currencies_is_rejected() -> None:
    with pytest.raises(MixedCurrencyError):
        native_total([_amount("10.00", "USD"), _amount("5.00", "EUR")])
    # require_single_currency is the fail-closed gate behind it.
    with pytest.raises(MixedCurrencyError):
        require_single_currency([_amount("10.00", "USD"), _amount("5.00", "EUR")])


def test_safe_usd_total_sums_only_normalized_usd() -> None:
    total, warnings = safe_usd_total(
        [_amount("10.00", "USD", "10.00"), _amount("5.00", "EUR", "5.50")]
    )
    assert total == Decimal("15.50")
    codes = {w.code for w in warnings}
    assert EconomicWarningCode.MIXED_CURRENCY in codes
    # No MISSING_PRICE: every amount carried a trusted USD value.
    assert EconomicWarningCode.MISSING_PRICE not in codes


def test_monetary_absence_stays_none_never_zero() -> None:
    # An unpriced amount carries no usd_value and nothing coerces it to 0.
    unpriced = _amount("100.00", "EUR")
    assert unpriced.usd_value is None
    total, warnings = safe_usd_total([unpriced])
    assert total is None  # not 0
    assert EconomicWarningCode.MISSING_PRICE in {w.code for w in warnings}
    # A bare MonetaryAmount has no fabricated zeros either.
    bare = MonetaryAmount()
    assert bare.amount is None and bare.usd_value is None


def test_missing_price_signaled_without_inventing_a_value() -> None:
    warnings = economic_warnings_for_amounts(
        [_amount("50.00", "EUR"), _amount("20.00", "USD", "20.00")]
    )
    codes = {w.code for w in warnings}
    assert EconomicWarningCode.MISSING_PRICE in codes
    assert EconomicWarningCode.MIXED_CURRENCY in codes
    # The warning is a typed object, never a fabricated figure.
    missing = next(w for w in warnings if w.code == EconomicWarningCode.MISSING_PRICE)
    assert missing.severity == "warning"


# ---------------------------------------------------------------------------
# POSSIBLE_DOUBLE_COUNT detection
# ---------------------------------------------------------------------------

def test_detect_double_count_flags_derivative_with_underlying() -> None:
    underlying = EconomicPosition(
        id="pos-u",
        tenant_id="tenant-a",
        holder=EntityRef(kind="economic_resource", id="r1"),
        position_type="position",
        underlying_position_id="pos-1",
    )
    receipt = EconomicPosition(
        id="pos-d",
        tenant_id="tenant-a",
        holder=EntityRef(kind="economic_resource", id="r1"),
        position_type="receipt",
        is_derivative_receipt=True,
        underlying_position_id="pos-1",
    )
    warnings = detect_double_count([underlying, receipt])
    assert len(warnings) == 1
    assert warnings[0].code == EconomicWarningCode.POSSIBLE_DOUBLE_COUNT
    assert warnings[0].details == {"position_id": "pos-1"}


def test_detect_double_count_no_false_positive() -> None:
    receipt = EconomicPosition(
        id="pos-d",
        tenant_id="tenant-a",
        holder=EntityRef(kind="economic_resource", id="r1"),
        position_type="receipt",
        is_derivative_receipt=True,
        underlying_position_id="pos-9",  # underlying NOT held directly
    )
    assert detect_double_count([receipt]) == []


# ---------------------------------------------------------------------------
# extra="forbid" — the plane fails closed
# ---------------------------------------------------------------------------

def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MonetaryAmount(amount=Decimal("1"), currency="USD", bogus="nope")
    with pytest.raises(ValidationError):
        EconomicWarning(code=EconomicWarningCode.MISSING_PRICE, message="x", extra="no")
    # And the base itself is extra="forbid".
    assert EconomicContract.model_config.get("extra") == "forbid"


# ---------------------------------------------------------------------------
# Domain contracts construct + serialize honestly
# ---------------------------------------------------------------------------

def test_valuation_context_signals_unpriced_without_fabrication() -> None:
    priced = EconomicValuationContext(
        currency="USD", price_source="usd_identity", priced_at="2026-08-24T00:00:00Z"
    )
    assert priced.price_source == "usd_identity"
    assert priced.priced_at is not None
    # An unpriced context keeps price_source "unavailable" and priced_at None.
    unpriced = EconomicValuationContext(currency="EUR")
    assert unpriced.price_source == "unavailable"
    assert unpriced.priced_at is None


def test_all_domain_models_construct() -> None:
    holder = EntityRef(kind="economic_resource", id="r1")
    ev = _evidence()
    assert EconomicEvent(
        id="e", tenant_id="t", subject=holder, event_type="payment",
        occurred_at="2026-08-24T00:00:00Z", amount=_amount("1", "USD", "1"), evidence=[ev],
    )
    assert EconomicFlow(
        id="f", tenant_id="t", flow_type="revenue", source=holder, destination=holder,
        amount=_amount("1", "USD", "1"),
    )
    assert EconomicPosition(id="p", tenant_id="t", holder=holder, position_type="balance")
    assert EconomicObligation(
        id="o", tenant_id="t", obligation_type="payable", debtor=holder, creditor=holder
    )
    assert EconomicAllocation(
        id="a", tenant_id="t", policy="attribution_credit", source_amount=_amount("1", "USD", "1")
    )
    assert EconomicAdjustment(
        id="adj", tenant_id="t", target_id="p", reason="restate", prior_amount=_amount("1", "USD", "1")
    )
    assert EconomicSettlement(
        id="s", tenant_id="t", settlement_type="x402", source=holder, destination=holder,
        amount=_amount("1", "USD", "1"),
    )
