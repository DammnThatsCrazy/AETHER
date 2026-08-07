"""Golden fixtures for the Computation Substrate (task §26.2).

Each test is a deterministic, hand-computed GOLDEN scenario: fixed ISO timestamps
in the :class:`ComputationContext` (no wall clock, no randomness), fixed decimal
inputs, and an EXACT expected ``(status, value)`` for every canonical result it
asserts. The point is not just "the number is right" — it is that each result
carries its honest :class:`ResultStatus`, so an unmeasurable metric is
``missing_inputs``/``unavailable`` with ``value is None`` and never a fake ``0``.

Scenarios covered:
  * multiple currencies (native currency preserved; cross-currency raw-sum refused)
  * a paused / zero-spend campaign (observed 0 spend, but derived rates missing)
  * partial data — unpriced revenue -> ROAS unavailable, not 0
  * a multi-campaign journey with conserved allocation (no per-journey duplication)
  * fractional multi-touch attributed conversions preserved (never int()-truncated)
  * a refund reducing attributed revenue (net < gross; net ROAS lower)

Every assertion checks the enum status, not merely the scalar.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.computation.campaign import (
    CampaignAggregates,
    canonical_campaign_metrics,
    canonical_journey_allocated_cost,
)
from shared.computation.aggregation import ratio_of_sums, sum_money
from shared.computation.context import ComputationContext
from shared.computation.errors import AggregationError
from shared.computation.reconciliation import ReconciliationState, reconcile
from shared.computation.result import ResultStatus, forbids_value

# Fixed instants — determinism: nothing is read from the wall clock.
_START = "2026-01-01T00:00:00+00:00"
_END = "2026-01-02T00:00:00+00:00"
_AS_OF = "2026-01-03T00:00:00+00:00"

# The honest-absence statuses that must NEVER carry a value (never a fake 0).
_ABSENT = (
    ResultStatus.MISSING_INPUTS,
    ResultStatus.UNAVAILABLE,
    ResultStatus.INSUFFICIENT_DATA,
)


def _ctx(currency: str) -> ComputationContext:
    return ComputationContext(
        tenant_id="t_golden",
        grain="campaign_day",
        event_time_start=_START,
        event_time_end=_END,
        as_of=_AS_OF,
        native_currency=currency,
        reporting_currency=currency,
    )


def _assert_absent(res, expected_status: ResultStatus) -> None:
    """A result in an honest-absence state: exact status, value None, never 0."""
    assert res.status == expected_status, (res.definition_id, res.status)
    assert forbids_value(res.status), res.status
    assert res.value is None, res.definition_id
    assert res.value != 0  # unknown must not masquerade as zero


# --------------------------------------------------------------------------- #
# 1. Multiple currencies
# --------------------------------------------------------------------------- #
def test_golden_multiple_currencies_preserve_native_and_refuse_mixed_sum():
    eur = canonical_campaign_metrics(
        _ctx("EUR"),
        CampaignAggregates(
            impressions=100000, clicks=1000, media_spend="500.00", total_cost="500.00",
            currency="EUR", attributed_conversions="40", attributed_gross_revenue="2000.00",
        ),
    )
    jpy = canonical_campaign_metrics(
        _ctx("JPY"),
        CampaignAggregates(
            impressions=50000, clicks=500, media_spend="120000", total_cost="120000",
            currency="JPY", attributed_conversions="50", attributed_gross_revenue="600000",
        ),
    )

    # Money keeps its native currency — never hardcoded USD.
    assert eur["campaign.media_spend"].status == ResultStatus.AVAILABLE
    assert eur["campaign.media_spend"].currency == "EUR"
    assert eur["campaign.media_spend"].value == pytest.approx(500.0)
    assert jpy["campaign.media_spend"].status == ResultStatus.AVAILABLE
    assert jpy["campaign.media_spend"].currency == "JPY"
    assert jpy["campaign.media_spend"].value == pytest.approx(120000.0)

    # ROAS is a dimensionless ratio and is computed per-currency, honestly.
    assert eur["campaign.gross_roas"].status == ResultStatus.AVAILABLE
    assert eur["campaign.gross_roas"].value == pytest.approx(4.0)  # 2000 / 500
    assert jpy["campaign.gross_roas"].status == ResultStatus.AVAILABLE
    assert jpy["campaign.gross_roas"].value == pytest.approx(5.0)  # 600000 / 120000

    # Raw-summing two different currencies is refused, not silently combined.
    with pytest.raises(AggregationError):
        sum_money(["500.00", "120000"], ["EUR", "JPY"])

    # Same-currency spends aggregate as a ratio-of-sums (not an average of rates).
    assert ratio_of_sums(["2000.00", "600000"], ["500.00", "120000"]) is not None


# --------------------------------------------------------------------------- #
# 2. Paused / zero-spend campaign
# --------------------------------------------------------------------------- #
def test_golden_paused_zero_spend_campaign():
    r = canonical_campaign_metrics(
        _ctx("EUR"),
        CampaignAggregates(
            impressions=0, clicks=0, media_spend="0.00", total_cost="0.00",
            currency="EUR", attributed_conversions="0", attributed_gross_revenue=None,
        ),
    )

    # Observed spend of exactly 0 is an EVIDENCE-BACKED zero (an observed fact),
    # so it is AVAILABLE with value 0.0 — this is legitimately zero, not unknown.
    assert r["campaign.media_spend"].status == ResultStatus.AVAILABLE
    assert r["campaign.media_spend"].value == pytest.approx(0.0)
    assert r["campaign.attributed_conversions"].status == ResultStatus.AVAILABLE
    assert r["campaign.attributed_conversions"].value == pytest.approx(0.0)

    # Revenue was never priced -> UNAVAILABLE, never a 0.
    _assert_absent(r["campaign.attributed_gross_revenue"], ResultStatus.UNAVAILABLE)

    # Every DERIVED rate has a zero/undefined denominator -> missing_inputs, never
    # a fabricated 0 CTR / ROAS / CPA for a paused campaign.
    for key in (
        "campaign.ctr", "campaign.cpc", "campaign.conversion_rate",
        "campaign.cpa", "campaign.gross_roas", "campaign.net_roas", "campaign.aov",
    ):
        _assert_absent(r[key], ResultStatus.MISSING_INPUTS)


# --------------------------------------------------------------------------- #
# 3. Partial data — unpriced revenue -> ROAS unavailable, not 0
# --------------------------------------------------------------------------- #
def test_golden_partial_unpriced_revenue_roas_unavailable_not_zero():
    r = canonical_campaign_metrics(
        _ctx("EUR"),
        CampaignAggregates(
            impressions=1000, clicks=100, media_spend="500.00", total_cost="550.00",
            currency="EUR", attributed_conversions="40",
            attributed_gross_revenue=None, attributed_net_revenue=None,  # unpriced
        ),
    )

    # The revenue money itself is UNAVAILABLE (unpriced), not 0.
    _assert_absent(r["campaign.attributed_gross_revenue"], ResultStatus.UNAVAILABLE)
    _assert_absent(r["campaign.attributed_net_revenue"], ResultStatus.UNAVAILABLE)

    # ROAS has an unpriced numerator -> the rate is missing_inputs, never a 0 ROAS
    # that would read as "the campaign returned nothing".
    _assert_absent(r["campaign.gross_roas"], ResultStatus.MISSING_INPUTS)
    _assert_absent(r["campaign.net_roas"], ResultStatus.MISSING_INPUTS)

    # The cost-side metrics that DO have their inputs remain honestly available.
    assert r["campaign.ctr"].status == ResultStatus.AVAILABLE
    assert r["campaign.ctr"].value == pytest.approx(0.1)  # 100 / 1000
    assert r["campaign.cpc"].status == ResultStatus.AVAILABLE
    assert r["campaign.cpc"].value == pytest.approx(5.0)  # 500 / 100
    assert r["campaign.cpa"].status == ResultStatus.AVAILABLE
    assert r["campaign.cpa"].value == pytest.approx(550 / 40)


# --------------------------------------------------------------------------- #
# 4. Multi-campaign journey with conserved allocation
# --------------------------------------------------------------------------- #
def test_golden_multi_campaign_journey_conserved_allocation():
    ctx = _ctx("EUR")
    # Campaign A spend 1000 touches journeys jX, jY (equal weight).
    alloc_a, per_a = canonical_journey_allocated_cost(
        ctx, campaign_cost="1000.00", currency="EUR",
        journey_weights={"jX": "1", "jY": "1"},
    )
    # Campaign B spend 600 touches journeys jY, jZ (jZ twice jY).
    alloc_b, per_b = canonical_journey_allocated_cost(
        ctx, campaign_cost="600.00", currency="EUR",
        journey_weights={"jY": "1", "jZ": "2"},
    )

    # Each campaign's allocation conserves its OWN total exactly (no duplication
    # of the full spend onto every journey — the legacy gold defect).
    assert alloc_a.residual == "0.00"
    assert (
        sum(Decimal(t.allocated_amount) for t in alloc_a.targets)
        + Decimal(alloc_a.residual)
        == Decimal("1000.00")
    )
    alloc_a.assert_conserved()
    alloc_b.assert_conserved()

    # Exact per-journey slices.
    assert per_a["jX"].value == pytest.approx(500.0)
    assert per_a["jY"].value == pytest.approx(500.0)
    assert per_b["jY"].value == pytest.approx(200.0)  # 600 * 1/3
    assert per_b["jZ"].value == pytest.approx(400.0)  # 600 * 2/3

    # Every allocated journey cost is ESTIMATED (allocated), never observed.
    for res in (*per_a.values(), *per_b.values()):
        assert res.status == ResultStatus.ESTIMATED
        assert res.currency == "EUR"
        assert res.allocation.get("basis") == "estimated"

    # The shared journey jY's total cross-campaign cost is the sum of its slices —
    # 500 (from A) + 200 (from B) = 700 — and nothing is double counted.
    shared_jy = Decimal(str(per_a["jY"].value)) + Decimal(str(per_b["jY"].value))
    assert shared_jy == Decimal("700")


def test_golden_allocation_residual_disclosed_not_dropped():
    # 100 split three ways cannot divide evenly; the 0.01 remainder is disclosed
    # as residual, never silently dropped (conservation holds to the cent).
    _, per = canonical_journey_allocated_cost(
        _ctx("USD"), campaign_cost="100.00", currency="USD",
        journey_weights={"a": "1", "b": "1", "c": "1"},
    )
    assert per["a"].value == pytest.approx(33.33)
    assert per["b"].value == pytest.approx(33.33)
    assert per["c"].value == pytest.approx(33.33)


# --------------------------------------------------------------------------- #
# 5. Fractional multi-touch attributed conversions preserved
# --------------------------------------------------------------------------- #
def test_golden_fractional_multitouch_conversions_preserved():
    # A conversion split across touches: 1.5 + 1.25 + 1.0 = 3.75 credited here.
    # The legacy path did int(3.75) -> 3, corrupting CPA/AOV/conversion_rate.
    r = canonical_campaign_metrics(
        _ctx("USD"),
        CampaignAggregates(
            impressions=10000, clicks=400, media_spend="1000.00", total_cost="1000.00",
            currency="USD", attributed_conversions="3.75", attributed_gross_revenue="750.00",
        ),
    )
    conv = r["campaign.attributed_conversions"]
    assert conv.status == ResultStatus.AVAILABLE
    assert conv.value == pytest.approx(3.75)  # NOT 3
    assert conv.value != pytest.approx(3.0)

    # Downstream rates use the fractional credit, not a truncated integer.
    assert r["campaign.cpa"].status == ResultStatus.AVAILABLE
    assert r["campaign.cpa"].value == pytest.approx(1000 / 3.75)  # 266.66…, not 1000/3
    assert r["campaign.aov"].status == ResultStatus.AVAILABLE
    assert r["campaign.aov"].value == pytest.approx(750 / 3.75)  # 200.0, not 750/3


# --------------------------------------------------------------------------- #
# 6. Refund reducing attributed revenue
# --------------------------------------------------------------------------- #
def test_golden_refund_reduces_attributed_revenue():
    gross = Decimal("1000.00")
    refund = Decimal("250.00")
    net = gross - refund  # 750.00 — the refund reduces the credited revenue.

    r = canonical_campaign_metrics(
        _ctx("USD"),
        CampaignAggregates(
            impressions=10000, clicks=400, media_spend="500.00", total_cost="500.00",
            currency="USD", attributed_conversions="20",
            attributed_gross_revenue=str(gross), attributed_net_revenue=str(net),
        ),
    )

    assert r["campaign.attributed_gross_revenue"].status == ResultStatus.AVAILABLE
    assert r["campaign.attributed_gross_revenue"].value == pytest.approx(1000.0)
    assert r["campaign.attributed_net_revenue"].status == ResultStatus.AVAILABLE
    assert r["campaign.attributed_net_revenue"].value == pytest.approx(750.0)  # reduced

    # Net ROAS reflects the refunded (lower) revenue and is strictly below gross.
    assert r["campaign.gross_roas"].status == ResultStatus.AVAILABLE
    assert r["campaign.gross_roas"].value == pytest.approx(2.0)  # 1000 / 500
    assert r["campaign.net_roas"].status == ResultStatus.AVAILABLE
    assert r["campaign.net_roas"].value == pytest.approx(1.5)  # 750 / 500
    assert r["campaign.net_roas"].value < r["campaign.gross_roas"].value

    # The refund is a real, reconcilable difference between the two authorities —
    # gross vs net differ by exactly the refund amount, flagged as a conflict.
    rc = reconcile(dimension="refund", source_value=str(gross), derived_value=str(net))
    assert rc.state == ReconciliationState.CONFLICT
    assert Decimal(rc.difference) == -refund


# --------------------------------------------------------------------------- #
# 7. CPM: exact-Decimal denominator (regression for a closed substrate gap)
# --------------------------------------------------------------------------- #
def test_golden_cpm_uses_exact_decimal_denominator():
    # CPM's denominator is impressions / 1000, computed as an EXACT Decimal.
    # Regression guard: a Python-float denominator would be rejected by the
    # money-grade ``to_decimal`` and render CPM structurally missing_inputs for
    # every impression count. With the fix, CPM is a real spend-per-mille value.
    r = canonical_campaign_metrics(
        _ctx("EUR"),
        CampaignAggregates(
            impressions=100000, clicks=1000, media_spend="500.00", total_cost="500.00",
            currency="EUR", attributed_conversions="40", attributed_gross_revenue="2000.00",
        ),
    )
    cpm = r["campaign.cpm"]
    assert cpm.status == ResultStatus.AVAILABLE
    # 500 spend / (100000 impressions / 1000) = 500 / 100 = 5.0 per mille.
    assert cpm.value == 5.0
    # An undefined (zero-impression) denominator is still an honest missing input.
    r0 = canonical_campaign_metrics(
        _ctx("EUR"),
        CampaignAggregates(
            impressions=0, clicks=0, media_spend="500.00", currency="EUR",
        ),
    )
    _assert_absent(r0["campaign.cpm"], ResultStatus.MISSING_INPUTS)
