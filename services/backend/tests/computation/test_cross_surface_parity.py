"""Cross-surface parity tests (task §26.6).

A canonical number must be IDENTICAL no matter which surface produces it. These
tests prove two forms of parity for campaign economics:

1.  **Same context + aggregates, two code paths, one answer.** The service-level
    :func:`services.computation.campaign.canonical_campaign_metrics` and the raw
    substrate :func:`shared.computation.runtime.rate_result` — driven by the same
    registered definitions and the same numerator/denominator — must agree
    exactly on value, status, definition version, numerator/denominator, unit,
    context hash, and uncertainty band.

2.  **Aggregating surfaces agree with the combined-denominator computation.** A
    rate summed across two campaign-day slices via
    :func:`shared.computation.aggregation.ratio_of_sums` must equal the single
    computation over the combined window — proving that a surface which rolls up
    daily slices lands on the same number as one that computes the whole window
    at once (and NOT on the average-of-averages that ratio-of-sums exists to
    prevent).

Everything is deterministic: fixed context timestamps, fixed aggregates, no
randomness. ``result_id``/``computed_at`` are provenance (uuid + wall clock) and
are intentionally excluded from the parity assertions.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.computation.campaign import CampaignAggregates, canonical_campaign_metrics
from shared.computation.aggregation import ratio_of_sums
from shared.computation.context import ComputationContext
from shared.computation.registry import get_definition
from shared.computation.result import ResultStatus
from shared.computation.runtime import rate_result


@pytest.fixture()
def ctx() -> ComputationContext:
    # Fully pinned scope — deterministic context hash across every path.
    return ComputationContext(
        tenant_id="t-parity",
        grain="campaign_day",
        event_time_start="2026-01-01T00:00:00+00:00",
        event_time_end="2026-01-02T00:00:00+00:00",
        as_of="2026-01-03T00:00:00+00:00",
        native_currency="EUR",
    )


@pytest.fixture()
def agg() -> CampaignAggregates:
    # Aggregates chosen so CTR / CPC / CPA / ROAS all resolve to AVAILABLE
    # (impressions >= CTR min-sample 30, clicks >= conversion-rate min-sample 30).
    return CampaignAggregates(
        impressions=100_000,
        clicks=2_000,
        media_spend="500.00",
        total_cost="550.00",
        currency="EUR",
        attributed_conversions="25",
        attributed_gross_revenue="1500.00",
    )


# Canonical metric key -> the exact (numerator, denominator) the service path
# feeds into rate_result, so the raw substrate path can be reconstructed 1:1.
def _raw_pairs(agg: CampaignAggregates) -> dict[str, tuple[object, object]]:
    total_cost = agg.total_cost if agg.total_cost is not None else agg.media_spend
    return {
        "campaign.ctr": (agg.clicks, agg.impressions),
        "campaign.cpc": (agg.media_spend, agg.clicks),
        "campaign.cpa": (total_cost, agg.attributed_conversions),
        "campaign.gross_roas": (agg.attributed_gross_revenue, agg.media_spend),
    }


# --------------------------------------------------------------------------- #
# 1. Service path vs. raw substrate path — identical canonical result
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("metric", ["campaign.ctr", "campaign.cpc", "campaign.cpa", "campaign.gross_roas"])
def test_service_and_raw_substrate_agree_exactly(ctx, agg, metric):
    numerator, denominator = _raw_pairs(agg)[metric]

    # (a) service surface
    service = canonical_campaign_metrics(ctx, agg)[metric]
    # (b) raw substrate surface — same definition, same inputs, same context
    raw = rate_result(
        get_definition(metric), ctx, numerator=numerator, denominator=denominator
    )

    # The canonical number and everything that qualifies it must match exactly.
    assert service.status == ResultStatus.AVAILABLE
    assert raw.status == service.status
    assert raw.value == service.value
    assert raw.definition_id == service.definition_id
    assert raw.definition_version == service.definition_version
    assert raw.value_type == service.value_type
    assert raw.unit == service.unit
    assert raw.numerator == service.numerator
    assert raw.denominator == service.denominator
    # Same scope identity -> same dedupe/supersession key.
    assert raw.context_hash == service.context_hash
    # Deterministic uncertainty band travels identically (Wilson for bounded
    # CTR; None for the unbounded currency/ratio rates).
    assert raw.uncertainty == service.uncertainty


def test_bounded_and_unbounded_rates_carry_the_expected_uncertainty(ctx, agg):
    results = canonical_campaign_metrics(ctx, agg)
    # CTR is a bounded [0,1] proportion -> Wilson band present on both surfaces.
    assert results["campaign.ctr"].uncertainty is not None
    assert results["campaign.ctr"].uncertainty.method == "wilson"
    # CPC/CPA/ROAS are unbounded currency/ratio rates -> no proportion band.
    for metric in ("campaign.cpc", "campaign.cpa", "campaign.gross_roas"):
        assert results[metric].uncertainty is None


def test_parity_holds_for_honest_absence_status(ctx):
    # A zero/undefined denominator must resolve to the SAME honest-absence status
    # (missing_inputs, value None) on both surfaces — parity is not just for the
    # happy path.
    empty = CampaignAggregates(
        impressions=0, clicks=0, media_spend="0.00", currency="EUR",
        attributed_conversions="0",
    )
    service = canonical_campaign_metrics(ctx, empty)["campaign.ctr"]
    raw = rate_result(
        get_definition("campaign.ctr"), ctx, numerator=empty.clicks, denominator=empty.impressions
    )
    assert service.status == ResultStatus.MISSING_INPUTS
    assert raw.status == service.status
    assert service.value is None and raw.value is None


# --------------------------------------------------------------------------- #
# 2. Ratio-of-sums over slices == single combined-window computation
# --------------------------------------------------------------------------- #
@pytest.fixture()
def day1() -> CampaignAggregates:
    return CampaignAggregates(
        impressions=1_000, clicks=100, media_spend="100.00", total_cost="100.00",
        currency="EUR", attributed_gross_revenue="300.00",
    )


@pytest.fixture()
def day2() -> CampaignAggregates:
    return CampaignAggregates(
        impressions=4_000, clicks=100, media_spend="400.00", total_cost="400.00",
        currency="EUR", attributed_gross_revenue="600.00",
    )


@pytest.fixture()
def combined() -> CampaignAggregates:
    # Element-wise sum of day1 + day2.
    return CampaignAggregates(
        impressions=5_000, clicks=200, media_spend="500.00", total_cost="500.00",
        currency="EUR", attributed_gross_revenue="900.00",
    )


@pytest.mark.parametrize("metric", ["campaign.ctr", "campaign.gross_roas"])
def test_ratio_of_sums_over_slices_equals_combined_window(ctx, day1, day2, combined, metric):
    r1 = canonical_campaign_metrics(ctx, day1)[metric]
    r2 = canonical_campaign_metrics(ctx, day2)[metric]
    rc = canonical_campaign_metrics(ctx, combined)[metric]

    # Every slice exposes its numerator/denominator, so a rolling-up surface can
    # aggregate honestly as a ratio-of-sums.
    aggregated = ratio_of_sums(
        [r1.numerator, r2.numerator], [r1.denominator, r2.denominator]
    )

    # The combined-window computation reaches the same value, exactly.
    assert rc.status == ResultStatus.AVAILABLE
    assert aggregated == pytest.approx(rc.value)

    # ...and the combined denominator IS the sum of the slice denominators
    # (single combined-denominator computation).
    assert Decimal(rc.denominator) == Decimal(r1.denominator) + Decimal(r2.denominator)
    assert Decimal(rc.numerator) == Decimal(r1.numerator) + Decimal(r2.numerator)

    # The whole point of ratio-of-sums: it is NOT the average of per-slice rates
    # (which would silently overweight the smaller-denominator slice).
    average_of_averages = (r1.value + r2.value) / 2
    assert aggregated != pytest.approx(average_of_averages)


def test_ratio_of_sums_matches_raw_substrate_combined_rate(ctx, day1, day2, combined):
    # The aggregation surface and the raw substrate rate agree on the combined
    # CTR when fed the summed numerator/denominator directly.
    r1 = canonical_campaign_metrics(ctx, day1)["campaign.ctr"]
    r2 = canonical_campaign_metrics(ctx, day2)["campaign.ctr"]
    aggregated = ratio_of_sums(
        [r1.numerator, r2.numerator], [r1.denominator, r2.denominator]
    )
    raw_combined = rate_result(
        get_definition("campaign.ctr"),
        ctx,
        numerator=combined.clicks,
        denominator=combined.impressions,
    )
    assert raw_combined.status == ResultStatus.AVAILABLE
    assert aggregated == pytest.approx(raw_combined.value)
