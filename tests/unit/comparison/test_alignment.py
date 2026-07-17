"""Semantic alignment produces TYPED registry outcomes — no silent matching."""
from __future__ import annotations

from services.intelligence.comparison.alignment import (
    align_dimension,
    overall_alignment,
)
from services.intelligence.comparison.collection import (
    DimensionObservations,
    MetricValue,
)
from services.intelligence.comparison.generated_vocabulary import ALIGNMENT_OUTCOMES


def obs(
    dimension: str = "behavior",
    metrics: list[MetricValue] | None = None,
    *,
    collectable: bool = True,
    count: int | None = None,
) -> DimensionObservations:
    metrics = metrics or []
    return DimensionObservations(
        dimension=dimension,
        collectable=collectable,
        observation_count=count if count is not None else (len(metrics) and 10),
        metrics=metrics,
        source="analytics_events" if collectable else "none",
    )


def metric(name="event_count", value=10.0, unit="count", window_days=30.0):
    return MetricValue(name=name, value=value, unit=unit, window_days=window_days)


class TestTypedOutcomes:
    def test_identical_metrics_align(self):
        d = align_dimension(obs(metrics=[metric()]), obs(metrics=[metric(value=5.0)]))
        assert d.outcome == "aligned"
        assert d.comparable
        assert d.pairs[0].subject_value == 10.0
        assert d.pairs[0].baseline_value == 5.0

    def test_window_mismatch_converts_to_rates(self):
        d = align_dimension(
            obs(metrics=[metric(value=30.0, window_days=30.0)]),
            obs(metrics=[metric(value=7.0, window_days=7.0)]),
        )
        assert d.outcome == "aligned_after_conversion"
        pair = d.pairs[0]
        assert pair.converted and pair.unit == "count_per_day"
        assert pair.subject_value == 1.0
        assert pair.baseline_value == 1.0

    def test_partial_overlap_is_partially_aligned(self):
        d = align_dimension(
            obs(metrics=[metric(), metric(name="distinct_event_types", unit="types")]),
            obs(metrics=[metric(value=3.0)]),
        )
        assert d.outcome == "partially_aligned"
        assert d.subject_only_metrics == ["distinct_event_types"]

    def test_disjoint_metrics_are_semantic_mismatch(self):
        d = align_dimension(
            obs(metrics=[metric(name="a")]), obs(metrics=[metric(name="b")])
        )
        assert d.outcome == "semantic_mismatch"
        assert not d.comparable
        assert "no shared metrics" in (d.reason or "")

    def test_incompatible_units_are_semantic_mismatch(self):
        d = align_dimension(
            obs(metrics=[metric(unit="usd", window_days=None)]),
            obs(metrics=[metric(unit="types", window_days=None)]),
        )
        assert d.outcome == "semantic_mismatch"
        assert "units differ" in (d.reason or "")

    def test_missing_unit_is_typed(self):
        d = align_dimension(
            obs(metrics=[metric(unit="")]), obs(metrics=[metric(unit="")])
        )
        assert d.outcome == "missing_unit"

    def test_uncollectable_side_is_not_comparable(self):
        d = align_dimension(obs(metrics=[metric()]), obs(collectable=False, count=0))
        assert d.outcome == "not_comparable"

    def test_cross_dimension_is_semantic_mismatch(self):
        d = align_dimension(obs("behavior", [metric()]), obs("devices", [metric()]))
        assert d.outcome == "semantic_mismatch"

    def test_every_outcome_is_registry_vocabulary(self):
        cases = [
            align_dimension(obs(metrics=[metric()]), obs(metrics=[metric()])),
            align_dimension(obs(metrics=[metric(name="a")]), obs(metrics=[metric(name="b")])),
            align_dimension(obs(metrics=[metric()]), obs(collectable=False, count=0)),
        ]
        for decision in cases:
            assert decision.outcome in ALIGNMENT_OUTCOMES


class TestOverallAlignment:
    def test_worst_outcome_wins(self):
        good = align_dimension(obs(metrics=[metric()]), obs(metrics=[metric()]))
        bad = align_dimension(obs(metrics=[metric()]), obs(collectable=False, count=0))
        assert overall_alignment([good, bad]) == "not_comparable"
        assert overall_alignment([good]) == "aligned"
        assert overall_alignment([]) is None
