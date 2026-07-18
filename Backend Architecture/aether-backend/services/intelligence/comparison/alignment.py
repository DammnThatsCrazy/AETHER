"""Semantic alignment of comparison subjects across baselines.

Every alignment decision is a TYPED outcome from the registry vocabulary
(``ALIGNMENT_OUTCOMES``) — there is no silent best-effort matching. A
dimension that cannot be aligned is excluded from computation and the
exclusion is recorded on the run with its typed reason.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from services.intelligence.comparison.collection import DimensionObservations, MetricValue
from services.intelligence.comparison.generated_vocabulary import ALIGNMENT_OUTCOMES

# Best → worst. Used to roll per-dimension outcomes into the run-level one;
# the worst outcome wins so a run never looks better aligned than its weakest
# compared dimension.
_ALIGNMENT_PRECEDENCE: tuple[str, ...] = (
    "aligned",
    "aligned_after_conversion",
    "partially_aligned",
    "grain_mismatch",
    "missing_unit",
    "missing_price",
    "stale_price",
    "semantic_mismatch",
    "insufficient_provenance",
    "not_comparable",
)

# Outcomes that allow metric deltas to be computed.
COMPARABLE_OUTCOMES: frozenset[str] = frozenset(
    {"aligned", "aligned_after_conversion", "partially_aligned"}
)

# Relative window-length mismatch below which counts can be converted to
# per-day rates instead of refusing on grain.
_GRAIN_CONVERSION_LIMIT = 0.5


class AlignedMetricPair(BaseModel):
    """One metric present (and unit-compatible) on both sides."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str
    subject_value: float
    baseline_value: float
    converted: bool = False
    conversion: Optional[str] = None


class AlignmentDecision(BaseModel):
    """Typed alignment outcome for one dimension."""

    model_config = ConfigDict(extra="forbid")

    dimension: str
    outcome: str  # ALIGNMENT_OUTCOMES member
    reason: Optional[str] = None
    pairs: list[AlignedMetricPair] = Field(default_factory=list)
    subject_only_metrics: list[str] = Field(default_factory=list)
    baseline_only_metrics: list[str] = Field(default_factory=list)

    @property
    def comparable(self) -> bool:
        return self.outcome in COMPARABLE_OUTCOMES


def _decision(dimension: str, outcome: str, **kwargs) -> AlignmentDecision:
    if outcome not in ALIGNMENT_OUTCOMES:
        raise ValueError(f"Not a registry alignment outcome: {outcome!r}")
    return AlignmentDecision(dimension=dimension, outcome=outcome, **kwargs)


def _to_rate(metric: MetricValue) -> Optional[MetricValue]:
    """Convert a windowed count into a per-day rate (None when impossible)."""
    if metric.unit != "count" or not metric.window_days:
        return None
    return MetricValue(
        name=f"{metric.name}_per_day",
        value=metric.value / metric.window_days,
        unit="count_per_day",
        window_days=metric.window_days,
        provenance=metric.provenance,
    )


def _windows_mismatch(a: MetricValue, b: MetricValue) -> bool:
    if a.window_days is None or b.window_days is None:
        return False
    longer = max(a.window_days, b.window_days)
    if longer <= 0:
        return False
    return abs(a.window_days - b.window_days) / longer > _GRAIN_CONVERSION_LIMIT


def align_dimension(
    subject: DimensionObservations, baseline: DimensionObservations
) -> AlignmentDecision:
    """Align one dimension's observations across the two sides.

    Preconditions handled by the engine's data-truth preflight: this is only
    called when at least one side has observations and both are collectable.
    """
    dimension = subject.dimension
    if baseline.dimension != dimension:
        return _decision(
            dimension,
            "semantic_mismatch",
            reason=f"baseline dimension {baseline.dimension!r} != subject dimension {dimension!r}",
        )
    if not subject.collectable or not baseline.collectable:
        return _decision(
            dimension,
            "not_comparable",
            reason="one side has no observation source for this dimension",
        )
    if subject.source != baseline.source and "none" in (subject.source, baseline.source):
        return _decision(
            dimension, "insufficient_provenance", reason="observation source unknown"
        )

    subject_by_name = {m.name: m for m in subject.metrics}
    baseline_by_name = {m.name: m for m in baseline.metrics}
    shared = sorted(set(subject_by_name) & set(baseline_by_name))
    subject_only = sorted(set(subject_by_name) - set(baseline_by_name))
    baseline_only = sorted(set(baseline_by_name) - set(subject_by_name))

    if not shared and (subject_by_name or baseline_by_name):
        return _decision(
            dimension,
            "semantic_mismatch",
            reason="no shared metrics between subject and baseline",
            subject_only_metrics=subject_only,
            baseline_only_metrics=baseline_only,
        )

    pairs: list[AlignedMetricPair] = []
    any_converted = False
    for name in shared:
        s, b = subject_by_name[name], baseline_by_name[name]
        if not s.unit or not b.unit:
            return _decision(
                dimension, "missing_unit", reason=f"metric {name!r} lacks a unit"
            )
        if s.unit == b.unit and not (s.unit == "count" and _windows_mismatch(s, b)):
            pairs.append(
                AlignedMetricPair(
                    name=name, unit=s.unit,
                    subject_value=s.value, baseline_value=b.value,
                )
            )
            continue
        # Units differ, or same-unit counts over materially different
        # windows: try the count → per-day-rate conversion.
        s_rate, b_rate = _to_rate(s), _to_rate(b)
        if s_rate is not None and b_rate is not None:
            any_converted = True
            pairs.append(
                AlignedMetricPair(
                    name=s_rate.name, unit=s_rate.unit,
                    subject_value=s_rate.value, baseline_value=b_rate.value,
                    converted=True, conversion="count_to_per_day_rate",
                )
            )
            continue
        if s.unit != b.unit:
            return _decision(
                dimension,
                "semantic_mismatch",
                reason=f"metric {name!r} units differ ({s.unit!r} vs {b.unit!r}) and no conversion exists",
            )
        return _decision(
            dimension,
            "grain_mismatch",
            reason=(
                f"metric {name!r} observed over materially different windows "
                f"({s.window_days} vs {b.window_days} days) and cannot be converted"
            ),
        )

    if not pairs:
        return _decision(
            dimension, "not_comparable", reason="no alignable metric pairs"
        )

    if subject_only or baseline_only:
        outcome = "partially_aligned"
        reason = "some metrics exist on only one side"
    elif any_converted:
        outcome = "aligned_after_conversion"
        reason = "count metrics converted to per-day rates"
    else:
        outcome = "aligned"
        reason = None

    return _decision(
        dimension,
        outcome,
        reason=reason,
        pairs=pairs,
        subject_only_metrics=subject_only,
        baseline_only_metrics=baseline_only,
    )


def overall_alignment(decisions: list[AlignmentDecision]) -> Optional[str]:
    """Worst per-dimension outcome, or None when nothing was aligned."""
    worst: Optional[str] = None
    worst_rank = -1
    for decision in decisions:
        rank = _ALIGNMENT_PRECEDENCE.index(decision.outcome)
        if rank > worst_rank:
            worst_rank = rank
            worst = decision.outcome
    return worst


__all__ = [
    "AlignedMetricPair",
    "AlignmentDecision",
    "COMPARABLE_OUTCOMES",
    "align_dimension",
    "overall_alignment",
]
