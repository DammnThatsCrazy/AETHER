"""Uncertainty quantification helpers (Wilson interval, percentile bootstrap).

Honest measurement means never presenting a point estimate as if it were exact.
These helpers produce reproducible confidence bands: the Wilson score interval
for proportions, and a seeded percentile bootstrap for the mean of arbitrary
samples. Determinism is a first-class requirement — a fixed seed always yields
the same interval, so a stored result can be re-derived and audited.
"""

from __future__ import annotations

import math

import numpy as np

from shared.measurement.contracts import Uncertainty


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, clamped to ``[0, 1]``.

    ``trials <= 0`` yields ``(0.0, 0.0)`` (no evidence, no interval).
    """

    if trials <= 0:
        return (0.0, 0.0)

    n = float(trials)
    p_hat = float(successes) / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = p_hat + z2 / (2.0 * n)
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + z2 / (4.0 * n)) / n)

    lower = (center - margin) / denominator
    upper = (center + margin) / denominator

    lower = max(0.0, min(1.0, lower))
    upper = max(0.0, min(1.0, upper))
    return (lower, upper)


def bootstrap_ci(
    samples: list[float],
    *,
    confidence: float = 0.95,
    iterations: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for the mean of ``samples``.

    Uses a seeded :class:`numpy.random.RandomState` so the same inputs and seed
    always produce the same interval. Empty ``samples`` yields ``(0.0, 0.0)``.
    """

    if not samples:
        return (0.0, 0.0)

    data = np.asarray(samples, dtype=float)
    n = data.shape[0]
    rng = np.random.RandomState(seed)

    # (iterations, n) resample-with-replacement indices → per-iteration means.
    indices = rng.randint(0, n, size=(iterations, n))
    means = data[indices].mean(axis=1)

    alpha = (1.0 - confidence) / 2.0
    lower = float(np.percentile(means, alpha * 100.0))
    upper = float(np.percentile(means, (1.0 - alpha) * 100.0))
    return (lower, upper)


def as_uncertainty(
    method: str,
    point: float | None,
    lower: float | None,
    upper: float | None,
    confidence_level: float = 0.95,
) -> Uncertainty:
    """Build an :class:`Uncertainty` record from raw band components."""

    return Uncertainty(
        method=method,
        point=point,
        lower=lower,
        upper=upper,
        confidence_level=confidence_level,
    )
