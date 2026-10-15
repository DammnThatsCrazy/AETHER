"""Calibration artifacts and metrics.

Where calibrated probabilities matter operationally (fraud, churn, identity
match), a raw model/heuristic score must be mapped to a probability by a fitted
calibrator and evaluated with reliability metrics. This module provides the
artifact shape and the metric computations (Brier, expected calibration error);
fitting pipelines (Platt/isotonic) are staged behind this interface.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence

from pydantic import BaseModel, Field


class CalibrationMethod(str, Enum):
    PLATT = "platt"
    ISOTONIC = "isotonic"
    IDENTITY = "identity"  # no calibration applied (scores are already probabilities)


class CalibrationArtifact(BaseModel):
    """A fitted calibrator plus its evaluation metrics for a segment."""

    artifact_id: str
    definition_id: str
    method: CalibrationMethod
    segment: Optional[str] = None
    fitted_at: Optional[str] = None
    sample_size: Optional[int] = None
    brier_score: Optional[float] = None
    expected_calibration_error: Optional[float] = None
    reliability_curve: list[dict[str, float]] = Field(default_factory=list)
    params: dict[str, float] = Field(default_factory=dict)


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> Optional[float]:
    """Mean squared error between predicted probabilities and 0/1 outcomes."""
    if not probabilities or len(probabilities) != len(outcomes):
        return None
    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities)


def expected_calibration_error(
    probabilities: Sequence[float], outcomes: Sequence[int], *, bins: int = 10
) -> Optional[float]:
    """ECE: |confidence - accuracy| averaged over equal-width probability bins."""
    if not probabilities or len(probabilities) != len(outcomes):
        return None
    n = len(probabilities)
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i
            for i, p in enumerate(probabilities)
            if (p > lo or (b == 0 and p >= lo)) and p <= hi
        ]
        if not idx:
            continue
        conf = sum(probabilities[i] for i in idx) / len(idx)
        acc = sum(outcomes[i] for i in idx) / len(idx)
        total += (len(idx) / n) * abs(conf - acc)
    return total


__all__ = [
    "CalibrationMethod",
    "CalibrationArtifact",
    "brier_score",
    "expected_calibration_error",
]
