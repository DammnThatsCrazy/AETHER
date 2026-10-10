"""Aggregation algebra.

Every metric definition declares how it aggregates. This module names the legal
aggregations and provides guarded implementations of the ones that are commonly
gotten wrong — so a rate is aggregated as a ratio-of-sums, not an average of
per-row rates, and balance/TVL snapshots are never summed through time.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Sequence

from shared.computation.errors import AggregationError


def _num(value: object) -> Optional[Decimal]:
    """Lenient numeric parse for aggregation of counts/weights.

    Unlike money-grade :func:`shared.computation.types.to_decimal` (which rejects
    binary floats to protect monetary math), aggregation legitimately combines
    float weights (e.g. attribution credit) and counts, so floats are accepted
    here via ``str()`` to avoid binary artifacts. Bad/absent input still yields
    ``None`` (never silently 0).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


class AggregationType(str, Enum):
    SUM = "sum"
    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"
    TIME_WEIGHTED_AVERAGE = "time_weighted_average"
    WEIGHTED_AVERAGE = "weighted_average"
    RATIO_OF_SUMS = "ratio_of_sums"
    DISTRIBUTION_MERGE = "distribution_merge"
    QUANTILE_SKETCH = "quantile_sketch"
    SET_UNION = "set_union"
    NON_AGGREGATABLE = "non_aggregatable"
    CUSTOM = "custom"


AGGREGATION_TYPES: tuple[str, ...] = tuple(a.value for a in AggregationType)


def ratio_of_sums(
    numerators: Sequence[object], denominators: Sequence[object]
) -> Optional[float]:
    """Correct rate aggregation: sum(numerators) / sum(denominators).

    Returns ``None`` (never 0) when the summed denominator is undefined/zero.
    This is what makes an aggregate CTR/ROAS/conversion-rate honest instead of an
    average-of-averages.
    """
    num = Decimal("0")
    den = Decimal("0")
    for n in numerators:
        d = _num(n)
        if d is not None:
            num += d
    for m in denominators:
        d = _num(m)
        if d is not None:
            den += d
    if den == 0:
        return None
    return float(num / den)


def weighted_average(
    values: Sequence[object], weights: Sequence[object]
) -> Optional[float]:
    """Weighted mean; ``None`` when total weight is 0. Never an average of averages."""
    if len(values) != len(weights):
        raise AggregationError("weighted_average: values and weights differ in length")
    total_w = Decimal("0")
    acc = Decimal("0")
    for v, w in zip(values, weights):
        dv = _num(v)
        dw = _num(w)
        if dv is None or dw is None:
            continue
        acc += dv * dw
        total_w += dw
    if total_w == 0:
        return None
    return float(acc / total_w)


def sum_money(amounts: Sequence[object], currencies: Sequence[str]) -> Decimal:
    """Sum monetary amounts only when they share ONE currency.

    Raises rather than silently producing a meaningless mixed-currency scalar.
    """
    distinct = {c for c in currencies if c}
    if len(distinct) > 1:
        raise AggregationError(
            f"refusing to raw-sum mixed currencies {sorted(distinct)}; "
            "group by currency or value to a reporting currency first"
        )
    total = Decimal("0")
    for a in amounts:
        d = _num(a)
        if d is not None:
            total += d
    return total


def reject_snapshot_sum(reason: str = "balance/TVL") -> None:
    """Explicitly refuse to sum point-in-time snapshots through time."""
    raise AggregationError(
        f"refusing to sum {reason} snapshots through time; use LAST/time-weighted"
    )


__all__ = [
    "AggregationType",
    "AGGREGATION_TYPES",
    "ratio_of_sums",
    "weighted_average",
    "sum_money",
    "reject_snapshot_sum",
]
