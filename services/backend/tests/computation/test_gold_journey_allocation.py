"""Site-gap regression: journey materialization must ALLOCATE campaign spend by
the journey's conversion share (conserving campaign spend across journeys), not
duplicate the full campaign spend onto every journey; and undefined gold ratios
are NULL, not 0.0."""

from __future__ import annotations

from decimal import Decimal

from services.measurement.engine.gold_materializer import _allocate_journey_campaign_spend


def test_allocation_is_conversion_share_not_full_spend():
    # Campaign spent 1000 with 10 total attributed conversions; this journey holds
    # 3 of them -> allocated 300, NOT the full 1000.
    got = _allocate_journey_campaign_spend(Decimal("1000"), Decimal("10"), Decimal("3"))
    assert got == Decimal("300")
    assert got < Decimal("1000")


def test_allocation_conserves_across_journeys():
    spend, total = Decimal("1000"), Decimal("10")
    shares = [Decimal("3"), Decimal("5"), Decimal("2")]  # sum == total
    allocated = sum(
        (_allocate_journey_campaign_spend(spend, total, s) for s in shares), Decimal("0")
    )
    assert allocated == spend  # fully conserved, no duplication


def test_no_conversions_allocates_zero_not_full_spend():
    assert _allocate_journey_campaign_spend(Decimal("1000"), Decimal("0"), Decimal("0")) == Decimal("0")


def test_share_capped_at_one():
    # A journey cannot be allocated more than the campaign's spend.
    assert _allocate_journey_campaign_spend(Decimal("500"), Decimal("2"), Decimal("5")) == Decimal("500")
