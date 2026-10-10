"""Canonical type-contract tests: the invariants that keep mathematical kinds
from being interchangeable and unknown from becoming zero."""

from __future__ import annotations

import pytest

from shared.computation import (
    FractionalCount,
    GraphMetric,
    IntegerCount,
    Money,
    Probability,
    Rank,
    Rate,
    Ratio,
    TypeContractError,
    to_decimal,
)


def test_money_rejects_float():
    with pytest.raises(TypeContractError):
        Money(amount=1.23, currency="USD")


def test_money_requires_currency():
    with pytest.raises(TypeContractError):
        Money(amount="1.23", currency="")


def test_money_accepts_decimal_string_and_none():
    assert Money(amount="10.50", currency="EUR").as_decimal() is not None
    # Unknown money is None, not 0.
    assert Money(amount=None, currency="EUR").amount is None


def test_probability_bounds():
    assert Probability(value=0.5).value == 0.5
    with pytest.raises(TypeContractError):
        Probability(value=1.5)
    with pytest.raises(TypeContractError):
        Probability(value=-0.01)


def test_probability_not_confused_with_score():
    # An uncalibrated probability object must declare it is uncalibrated.
    p = Probability(value=0.9)
    assert p.calibrated is False


def test_integer_count_non_negative_by_default():
    assert IntegerCount(value=3).value == 3
    with pytest.raises(TypeContractError):
        IntegerCount(value=-1)
    # Explicit opt-in allows signed counts (e.g. net change).
    assert IntegerCount(value=-1, allow_negative=True).value == -1


def test_fractional_count_preserves_fraction():
    fc = FractionalCount(amount="2.7")
    assert fc.as_decimal() == to_decimal("2.7")


def test_rate_exposes_numerator_and_denominator():
    r = Rate.build(50, 1000)
    assert r.numerator == "50" and r.denominator == "1000"
    assert r.value == pytest.approx(0.05)


def test_rate_undefined_denominator_is_none_not_zero():
    r = Rate.build(5, 0)
    assert r.value is None
    r2 = Rate.build(5, None)
    assert r2.value is None


def test_ratio_is_not_a_percentage():
    r = Ratio(value=0.05)
    # A ratio does not carry percentage semantics; conversion is explicit.
    assert r.math_type.value == "ratio"


def test_rank_is_one_based_and_bounded():
    assert Rank(value=1, population_size=10).value == 1
    with pytest.raises(TypeContractError):
        Rank(value=0)
    with pytest.raises(TypeContractError):
        Rank(value=11, population_size=10)


def test_graph_metric_requires_snapshot():
    gm = GraphMetric(value=0.3, graph_snapshot_id="snap-1", normalization_population="tenant")
    assert gm.graph_snapshot_id == "snap-1"
    with pytest.raises(Exception):
        GraphMetric(value=0.3)  # missing required snapshot id
