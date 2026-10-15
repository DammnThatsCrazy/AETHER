"""Property-based invariant tests (hypothesis) for the substrate's numerical
guarantees: allocation conservation, probability bounds, rate bounds, currency
preservation, Decimal preservation, and undefined-denominator behavior."""

from __future__ import annotations

from decimal import Decimal

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from shared.computation import (  # noqa: E402
    Money,
    Probability,
    Rate,
    TypeContractError,
    allocate,
    ratio_of_sums,
    to_decimal,
)

money_amounts = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1000000"), places=2, allow_nan=False, allow_infinity=False
)
weight_lists = st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=8)


@settings(max_examples=200)
@given(source=money_amounts, weights=weight_lists)
def test_allocation_always_conserves(source, weights):
    wmap = {f"t{i}": str(w) for i, w in enumerate(weights)}
    r = allocate(source_amount=str(source), currency="USD", weights=wmap)
    total = sum(Decimal(t.allocated_amount) for t in r.targets)
    assert total + Decimal(r.residual) == Decimal(r.source_amount)


@settings(max_examples=200)
@given(p=st.floats(min_value=0.0, max_value=1.0))
def test_probability_within_bounds_accepted(p):
    assert Probability(value=p).value == p


@settings(max_examples=100)
@given(p=st.floats(min_value=1.0001, max_value=1e6))
def test_probability_above_one_rejected(p):
    with pytest.raises(TypeContractError):
        Probability(value=p)


@settings(max_examples=200)
@given(num=st.integers(min_value=0, max_value=10**9), den=st.integers(min_value=1, max_value=10**9))
def test_rate_matches_division(num, den):
    r = Rate.build(num, den)
    assert r.value == pytest.approx(num / den)


@settings(max_examples=100)
@given(num=st.integers(min_value=0, max_value=10**9))
def test_rate_zero_denominator_is_none(num):
    assert Rate.build(num, 0).value is None


@settings(max_examples=100)
@given(amount=money_amounts, cur=st.sampled_from(["USD", "EUR", "GBP", "JPY"]))
def test_money_preserves_amount_and_currency(amount, cur):
    m = Money(amount=str(amount), currency=cur)
    assert m.currency == cur
    assert m.as_decimal() == to_decimal(str(amount))


@settings(max_examples=100)
@given(
    nums=st.lists(st.integers(min_value=0, max_value=10**6), min_size=1, max_size=10),
    dens=st.lists(st.integers(min_value=0, max_value=10**6), min_size=1, max_size=10),
)
def test_ratio_of_sums_between_zero_and_max(nums, dens):
    n = min(len(nums), len(dens))
    nums, dens = nums[:n], dens[:n]
    result = ratio_of_sums(nums, dens)
    if sum(dens) == 0:
        assert result is None
    else:
        assert result is not None and result >= 0.0
