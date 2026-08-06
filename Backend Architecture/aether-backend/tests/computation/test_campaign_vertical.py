"""Campaign vertical regression tests.

These encode the CORRECT campaign economics that the legacy gold materializer
violated (fractional-conversion truncation, zero-denominator-as-zero, hardcoded
USD, and full-campaign-spend duplicated per journey). Each test fails against the
old behavior and passes against the substrate-backed computation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.computation.campaign import (
    CampaignAggregates,
    canonical_campaign_metrics,
    canonical_journey_allocated_cost,
)
from shared.computation.context import ComputationContext
from shared.computation.result import ResultStatus


@pytest.fixture()
def ctx():
    return ComputationContext(
        tenant_id="t1",
        grain="campaign_day",
        event_time_start="2026-01-01T00:00:00+00:00",
        event_time_end="2026-01-02T00:00:00+00:00",
        native_currency="EUR",
    )


def test_fractional_conversions_preserved_not_truncated(ctx):
    # 2.7 attributed conversions. The legacy path did int(2.7) -> 2, corrupting
    # CPA/conversion_rate. The substrate preserves the fraction.
    agg = CampaignAggregates(
        impressions=100000, clicks=1000, media_spend="500.00", total_cost="550.00",
        currency="EUR", attributed_conversions="2.7",
        attributed_gross_revenue="1350.00", attributed_net_revenue="1200.00",
    )
    r = canonical_campaign_metrics(ctx, agg)
    conv = r["campaign.attributed_conversions"]
    assert conv.value == pytest.approx(2.7)  # NOT 2
    # CPA = total_cost / attributed_conversions = 550 / 2.7 (not 550/2 = 275)
    cpa = r["campaign.cpa"]
    assert cpa.status == ResultStatus.AVAILABLE
    assert cpa.value == pytest.approx(550 / 2.7)
    assert cpa.value != pytest.approx(550 / 2)


def test_zero_denominator_is_missing_not_zero(ctx):
    agg = CampaignAggregates(
        impressions=0, clicks=0, media_spend="0.00", currency="EUR",
        attributed_conversions="0", attributed_gross_revenue=None,
    )
    r = canonical_campaign_metrics(ctx, agg)
    for key in ("campaign.ctr", "campaign.cpc", "campaign.cpm", "campaign.gross_roas"):
        assert r[key].status == ResultStatus.MISSING_INPUTS, key
        assert r[key].value is None, key


def test_money_preserves_native_currency_not_usd(ctx):
    agg = CampaignAggregates(
        impressions=1000, clicks=50, media_spend="500.00", currency="EUR",
        attributed_conversions="10",
    )
    r = canonical_campaign_metrics(ctx, agg)
    spend = r["campaign.media_spend"]
    assert spend.currency == "EUR"  # not hardcoded USD
    assert spend.value == pytest.approx(500.0)


def test_unpriced_revenue_makes_roas_unavailable_not_zero(ctx):
    agg = CampaignAggregates(
        impressions=1000, clicks=50, media_spend="500.00", currency="EUR",
        attributed_conversions="10", attributed_gross_revenue=None,  # unpriced
    )
    r = canonical_campaign_metrics(ctx, agg)
    roas = r["campaign.gross_roas"]
    # Numerator unpriced -> the rate cannot be an honest number; not 0.
    assert roas.status == ResultStatus.MISSING_INPUTS
    assert roas.value is None


def test_journey_cost_is_allocated_and_conserved_not_duplicated(ctx):
    # One campaign with 1000.00 spend touches three journeys. The legacy path
    # attributed the FULL 1000 to EACH journey (3000 total, triple-counted). The
    # allocation engine distributes exactly 1000 across them.
    allocation, per_journey = canonical_journey_allocated_cost(
        ctx,
        campaign_cost="1000.00",
        currency="EUR",
        journey_weights={"j1": "1", "j2": "1", "j3": "2"},
    )
    total = sum(Decimal(t.allocated_amount) for t in allocation.targets)
    assert total + Decimal(allocation.residual) == Decimal("1000.00")
    assert total <= Decimal("1000.00")  # never exceeds the source (no duplication)
    # Each journey's cost is estimated (allocated), never observed.
    for jid, res in per_journey.items():
        assert res.status == ResultStatus.ESTIMATED
        assert res.currency == "EUR"
        assert res.allocation.get("basis") == "estimated"
    # Weighted split: j3 (weight 2) gets twice j1/j2.
    assert Decimal(per_journey["j3"].value.__str__()) or True  # value present
    assert per_journey["j3"].value == pytest.approx(500.0)
    assert per_journey["j1"].value == pytest.approx(250.0)


def test_conversion_rate_below_min_sample_is_insufficient(ctx):
    agg = CampaignAggregates(
        impressions=100, clicks=5, media_spend="10.00", currency="EUR",
        attributed_conversions="1",
    )
    r = canonical_campaign_metrics(ctx, agg)
    # conversion_rate min_sample is 30 clicks; 5 clicks -> insufficient_data.
    assert r["campaign.conversion_rate"].status == ResultStatus.INSUFFICIENT_DATA
    assert r["campaign.conversion_rate"].value is None
