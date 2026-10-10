"""Explicit uncertainty forms for the Computation Substrate.

Generic, unqualified "confidence" is banned. Uncertainty must say what kind it
is: a source-reliability weight is not a standard error, evidence coverage is not
a calibrated probability, and a heuristic score's spread is not a prediction
interval. This module extends the measurement plane's uncertainty primitives
(wilson/bootstrap) with a typed :class:`Uncertainty` envelope.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

# Re-export the measurement plane's deterministic estimators so the substrate has
# one home for interval math rather than a competing implementation.
from shared.measurement.uncertainty import bootstrap_ci, wilson_interval


class UncertaintyKind(str, Enum):
    SOURCE_RELIABILITY = "source_reliability"
    EVIDENCE_COVERAGE = "evidence_coverage"
    STANDARD_ERROR = "standard_error"
    CONFIDENCE_INTERVAL = "confidence_interval"
    PREDICTION_INTERVAL = "prediction_interval"
    POSTERIOR_PROBABILITY = "posterior_probability"
    CALIBRATION_ERROR = "calibration_error"
    IDENTITY_MATCH_PROBABILITY = "identity_match_probability"
    VALUATION_CONFIDENCE = "valuation_confidence"
    ALLOCATION_UNCERTAINTY = "allocation_uncertainty"
    MODEL_DRIFT = "model_drift"
    OUT_OF_DISTRIBUTION = "out_of_distribution"


class Uncertainty(BaseModel):
    """A typed uncertainty band/scalar attached to a value.

    ``kind`` names the *sort* of uncertainty so consumers never mistake, say, a
    bootstrap CI for a source-reliability weight.
    """

    kind: UncertaintyKind
    method: str
    point: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    standard_error: Optional[float] = None
    confidence_level: float = 0.95


def wilson(successes: int, trials: int, *, z: float = 1.96) -> Uncertainty:
    """A Wilson score interval as a typed CI uncertainty (bounded proportions)."""
    low, high = wilson_interval(successes, trials, z=z)
    point = (successes / trials) if trials > 0 else None
    return Uncertainty(
        kind=UncertaintyKind.CONFIDENCE_INTERVAL,
        method="wilson",
        point=point,
        lower=low if trials > 0 else None,
        upper=high if trials > 0 else None,
    )


__all__ = [
    "UncertaintyKind",
    "Uncertainty",
    "wilson",
    "wilson_interval",
    "bootstrap_ci",
]
