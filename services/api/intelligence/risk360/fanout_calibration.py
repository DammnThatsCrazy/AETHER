"""Evaluate fan-out thresholds against adjudicated principals.

Reports what each candidate threshold would have done on real adjudications. It changes
nothing: a person reads the result and updates ``fanout.POLICY``. Below ``MIN_LABELS`` of
each class, results are marked insufficient and no threshold is recommended, because a
threshold fit to a handful of cases is a guess presented as a measurement.
"""
from __future__ import annotations

from typing import Any, Iterable

MIN_LABELS = 50
THRESHOLD_GRID: tuple[float, ...] = (0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5)
RATE_SIGNALS: tuple[str, ...] = ("authority_failure_rate", "out_of_scope_execution_rate")


def _peak_rate(signals: dict[str, Any]) -> float:
    return max((signals.get(name) or 0.0 for name in RATE_SIGNALS), default=0.0)


def evaluate(points: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """``points`` hold each principal's ``signals`` and ``confirmed`` (bool) from adjudication."""
    labeled = [point for point in points if isinstance(point.get("confirmed"), bool)]
    positives = sum(1 for point in labeled if point["confirmed"])
    negatives = len(labeled) - positives
    results = []
    for threshold in THRESHOLD_GRID:
        tp = fp = fn = 0
        for point in labeled:
            flagged = _peak_rate(point.get("signals") or {}) >= threshold
            if flagged and point["confirmed"]:
                tp += 1
            elif flagged:
                fp += 1
            elif point["confirmed"]:
                fn += 1
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
        results.append({
            "threshold": threshold, "precision": precision, "recall": recall, "f1": f1,
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        })
    sufficient = positives >= MIN_LABELS and negatives >= MIN_LABELS
    scored = [row for row in results if row["f1"] is not None]
    recommended = max(scored, key=lambda row: row["f1"])["threshold"] if sufficient and scored else None
    return {
        "positives": positives, "negatives": negatives, "min_labels_per_class": MIN_LABELS,
        "sufficient": sufficient, "recommended_threshold": recommended, "results": results,
    }
