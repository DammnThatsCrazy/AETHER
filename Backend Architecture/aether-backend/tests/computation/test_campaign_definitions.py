"""Canonical campaign-economics definition + runtime tests.

These pin the honest behavior that the gold materializer previously violated:
zero-denominator ratios are null (not 0.0), fractional attributed conversions are
preserved (not int()-truncated), and money carries a currency."""

from __future__ import annotations

import pytest

from shared.computation import (
    ComputationContext,
    ResultStatus,
    count_result,
    get_definition,
    money_result,
    rate_result,
)
from shared.computation.definition import ComputationKind, LifecycleState
from shared.computation.types import MathType


@pytest.fixture()
def ctx():
    return ComputationContext(
        tenant_id="t1",
        grain="campaign_day",
        event_time_start="2026-01-01T00:00:00+00:00",
        event_time_end="2026-01-02T00:00:00+00:00",
        native_currency="USD",
    )


def test_core_campaign_definitions_are_active():
    for did in [
        "campaign.cpc",
        "campaign.cpm",
        "campaign.ctr",
        "campaign.conversion_rate",
        "campaign.cpa",
        "campaign.gross_roas",
        "campaign.net_roas",
        "campaign.attributed_conversions",
        "campaign.journey_allocated_cost",
    ]:
        d = get_definition(did)
        assert d is not None, did
        assert d.lifecycle_state == LifecycleState.ACTIVE


def test_ctr_zero_impressions_is_missing_not_zero(ctx):
    d = get_definition("campaign.ctr")
    r = rate_result(d, ctx, numerator=0, denominator=0)
    assert r.status == ResultStatus.MISSING_INPUTS
    assert r.value is None


def test_roas_zero_spend_is_missing_not_zero(ctx):
    d = get_definition("campaign.gross_roas")
    r = rate_result(d, ctx, numerator="1234.56", denominator="0")
    assert r.status == ResultStatus.MISSING_INPUTS
    assert r.value is None


def test_ctr_below_min_sample_is_insufficient(ctx):
    d = get_definition("campaign.ctr")  # min_sample 30
    r = rate_result(d, ctx, numerator=2, denominator=10)
    assert r.status == ResultStatus.INSUFFICIENT_DATA
    assert r.value is None


def test_ctr_available_with_wilson(ctx):
    d = get_definition("campaign.ctr")
    r = rate_result(d, ctx, numerator=50, denominator=1000)
    assert r.status == ResultStatus.AVAILABLE
    assert r.value == pytest.approx(0.05)
    assert r.uncertainty is not None
    assert r.uncertainty.lower is not None and r.uncertainty.upper is not None


def test_attributed_conversions_are_fractional(ctx):
    d = get_definition("campaign.attributed_conversions")
    assert d.output_type == MathType.FRACTIONAL_COUNT
    assert d.computation_kind == ComputationKind.ALLOCATED_VALUE
    r = count_result(d, ctx, amount="2.7", fractional=True)
    assert r.value == pytest.approx(2.7)  # NOT truncated to 2


def test_media_spend_unpriced_is_unavailable(ctx):
    d = get_definition("campaign.media_spend")
    r = money_result(d, ctx, amount=None, currency="USD")
    assert r.status == ResultStatus.UNAVAILABLE
    assert r.value is None


def test_media_spend_valued_carries_currency(ctx):
    d = get_definition("campaign.media_spend")
    r = money_result(d, ctx, amount="500.00", currency="USD")
    assert r.status == ResultStatus.AVAILABLE
    assert r.currency == "USD"
    assert r.value == pytest.approx(500.0)
