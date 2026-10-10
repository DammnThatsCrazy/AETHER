"""Allocation-engine tests: conservation, residual disclosure, and the
observed-vs-estimated distinction that fixes journey cost duplication."""

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.computation import AllocationPolicy, AllocationError, allocate


def test_proportional_conserves_total():
    r = allocate(source_amount="100.00", currency="USD", weights={"a": "1", "b": "3"})
    assert r.targets[0].allocated_amount == "25.00"
    assert r.targets[1].allocated_amount == "75.00"
    assert r.residual == "0.00"
    r.assert_conserved()


def test_equal_split_conserves_and_discloses_residual():
    # 100 / 3 does not divide evenly; the residual must be disclosed, not dropped.
    r = allocate(
        source_amount="100.00",
        currency="USD",
        weights={"a": "0", "b": "0", "c": "0"},
        policy=AllocationPolicy.EQUAL,
    )
    total = sum(Decimal(t.allocated_amount) for t in r.targets)
    assert total + Decimal(r.residual) == Decimal("100.00")
    r.assert_conserved()


def test_zero_total_weight_makes_everything_residual():
    r = allocate(source_amount="50.00", currency="USD", weights={"a": "0", "b": "0"})
    assert r.residual == "50.00"
    assert all(t.allocated_amount == "0" for t in r.targets)
    r.assert_conserved()


def test_no_targets_makes_everything_residual():
    r = allocate(source_amount="50.00", currency="USD", weights={})
    assert r.residual == "50.00"
    r.assert_conserved()


def test_allocation_is_estimated_not_observed():
    r = allocate(source_amount="100.00", currency="USD", weights={"a": "1"})
    assert r.basis == "estimated"


def test_allocation_requires_currency():
    with pytest.raises(AllocationError):
        allocate(source_amount="100.00", currency="", weights={"a": "1"})


def test_allocation_rejects_nonfinite_source():
    with pytest.raises(AllocationError):
        allocate(source_amount="not-a-number", currency="USD", weights={"a": "1"})
