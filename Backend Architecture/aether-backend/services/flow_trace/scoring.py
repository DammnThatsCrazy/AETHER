"""Flow-of-Funds Trace — pure scoring functions.

No I/O, no async, no side effects. All scores in [0, 100].
"""

from __future__ import annotations


def score_path(
    hop_count: int,
    total_amount_usd: float,
    contains_cycle: bool,
    passes_through_sink: bool,
    passes_through_source: bool,
    pattern_count: int,
) -> float:
    """Score a single flow path on a 0-100 risk scale.

    Weights:
        path depth (hops)        → 25%
        total amount (log scale) → 25%
        cycle in path            → 20%
        passes through sink      → 15%
        passes through source    → 10%
        pattern breadth          →  5%
    """
    import math

    depth_norm = min(hop_count / 10.0, 1.0)
    depth_contrib = depth_norm * 100.0 * 0.25

    amt_norm = min(math.log1p(max(total_amount_usd, 0)) / math.log1p(1_000_000), 1.0)
    amt_contrib = amt_norm * 100.0 * 0.25

    cycle_contrib = 100.0 * 0.20 if contains_cycle else 0.0
    sink_contrib = 100.0 * 0.15 if passes_through_sink else 0.0
    source_contrib = 100.0 * 0.10 if passes_through_source else 0.0

    pattern_norm = min(pattern_count / 5.0, 1.0)
    pattern_contrib = pattern_norm * 100.0 * 0.05

    total = depth_contrib + amt_contrib + cycle_contrib + sink_contrib + source_contrib + pattern_contrib
    return round(min(total, 100.0), 4)


def score_trace(
    path_risk_scores: list[float],
    cycle_detected: bool,
    source_count: int,
    sink_count: int,
    aggregation_point_count: int,
    total_path_count: int,
) -> float:
    """Score an entire flow trace on a 0-100 risk scale.

    Weights:
        max path risk            → 35%
        average path risk        → 25%
        cycle detection          → 20%
        structural complexity    → 15%  (sinks + sources + aggregation nodes)
        path count               →  5%
    """
    if not path_risk_scores:
        return 0.0

    max_path = max(path_risk_scores)
    avg_path = sum(path_risk_scores) / len(path_risk_scores)

    max_contrib = max_path * 0.35
    avg_contrib = avg_path * 0.25
    cycle_contrib = 100.0 * 0.20 if cycle_detected else 0.0

    structural = source_count + sink_count + aggregation_point_count
    structural_norm = min(structural / 20.0, 1.0)
    structural_contrib = structural_norm * 100.0 * 0.15

    path_norm = min(total_path_count / 50.0, 1.0)
    path_contrib = path_norm * 100.0 * 0.05

    total = max_contrib + avg_contrib + cycle_contrib + structural_contrib + path_contrib
    return round(min(total, 100.0), 4)
