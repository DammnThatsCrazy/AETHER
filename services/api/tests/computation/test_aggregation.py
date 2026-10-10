"""Aggregation-algebra tests: ratio-of-sums correctness and the illegal
aggregations the algebra must refuse."""

from __future__ import annotations

import pytest

from shared.computation import AggregationError, ratio_of_sums, sum_money, weighted_average
from shared.computation.aggregation import reject_snapshot_sum


def test_ratio_of_sums_is_not_average_of_averages():
    # Two campaigns: (clicks, impressions) = (1, 10) and (99, 100).
    # Average of per-campaign CTRs = (0.1 + 0.99)/2 = 0.545 — WRONG.
    # Ratio of sums = 100 / 110 = 0.909... — CORRECT.
    ctr = ratio_of_sums([1, 99], [10, 100])
    assert ctr == pytest.approx(100 / 110)
    assert ctr != pytest.approx(0.545)


def test_ratio_of_sums_zero_denominator_is_none():
    assert ratio_of_sums([0, 0], [0, 0]) is None


def test_sum_money_refuses_mixed_currency():
    with pytest.raises(AggregationError):
        sum_money(["1", "2"], ["USD", "EUR"])
    # Single-currency sum is fine.
    assert sum_money(["1.50", "2.50"], ["USD", "USD"]) == 4


def test_weighted_average_handles_zero_weight():
    assert weighted_average([1, 2], [0, 0]) is None
    assert weighted_average([1.0, 3.0], [1, 1]) == pytest.approx(2.0)


def test_reject_snapshot_sum():
    with pytest.raises(AggregationError):
        reject_snapshot_sum("TVL")
