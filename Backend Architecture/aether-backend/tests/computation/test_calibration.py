"""Calibration-metric tests (task §26.3).

Exercises the substrate's calibration primitives on constructed
probability/outcome fixtures:

  * a reliability curve (per-bin confidence vs. observed accuracy),
  * :func:`brier_score`, and
  * :func:`expected_calibration_error` (ECE),

and asserts the sane, monotonic relationships that make these metrics
trustworthy — a perfectly-calibrated + sharp predictor drives ECE and Brier to
~0, a systematically-overconfident predictor drives both up, ECE grows
monotonically with the confidence/accuracy gap, and empty/mismatched inputs are
honest ``None`` rather than a fake 0.

It also pins the type boundary the substrate is built to protect: a
``Probability(calibrated=False)`` and a :class:`HeuristicScore` are DISTINCT
mathematical objects — a heuristic score is NOT a probability, even when its
numeric value happens to land in ``[0, 1]``.
"""

from __future__ import annotations

from typing import Sequence

import pytest

from shared.computation.calibration import (
    CalibrationArtifact,
    CalibrationMethod,
    brier_score,
    expected_calibration_error,
)
from shared.computation.errors import TypeContractError
from shared.computation.types import (
    HeuristicScore,
    MathType,
    OrdinalScore,
    Probability,
    UncalibratedScore,
)


# --------------------------------------------------------------------------- #
# Deterministic fixtures (no randomness anywhere)
# --------------------------------------------------------------------------- #
def _reliability_curve(
    probabilities: Sequence[float], outcomes: Sequence[int], *, bins: int = 10
) -> list[dict[str, float]]:
    """Equal-width reliability curve: per populated bin, mean confidence vs. accuracy.

    Mirrors the binning that :func:`expected_calibration_error` uses so the curve
    and the ECE scalar are consistent views of the same partition.
    """
    curve: list[dict[str, float]] = []
    n = len(probabilities)
    if n == 0 or n != len(outcomes):
        return curve
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
        curve.append(
            {
                "bin": float(b),
                "confidence": conf,
                "accuracy": acc,
                "count": float(len(idx)),
            }
        )
    return curve


# Perfectly calibrated AND sharp: probability 1.0 for every positive, 0.0 for
# every negative — the calibration ideal (ECE == Brier == 0).
PERFECT_P = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
PERFECT_O = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]

# Systematically overconfident: asserts p=0.9 for everyone, but only half the
# outcomes are positive — confidence far exceeds accuracy in that single bin.
OVERCONF_P = [0.9] * 10
OVERCONF_O = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]

# Well-calibrated but not fully sharp: three predicted-probability groups whose
# observed accuracy matches the predicted probability (0.2, 0.5, 0.8).
CAL_CURVE_P = [0.2] * 10 + [0.5] * 10 + [0.8] * 10
CAL_CURVE_O = ([1, 1] + [0] * 8) + ([1] * 5 + [0] * 5) + ([1] * 8 + [0, 0])


# --------------------------------------------------------------------------- #
# Reliability curve
# --------------------------------------------------------------------------- #
def test_reliability_curve_is_monotonic_and_matches_predicted_confidence():
    curve = _reliability_curve(CAL_CURVE_P, CAL_CURVE_O)
    # Three distinct predicted-probability groups -> three populated bins.
    assert len(curve) == 3
    confidences = [row["confidence"] for row in curve]
    accuracies = [row["accuracy"] for row in curve]

    # Bins are emitted in ascending order; confidence and accuracy both rise
    # monotonically (a well-formed, non-degenerate reliability diagram).
    assert confidences == sorted(confidences)
    assert accuracies == sorted(accuracies)
    assert all(later >= earlier for earlier, later in zip(accuracies, accuracies[1:]))

    # Well-calibrated: each bin's observed accuracy tracks its mean confidence.
    for row in curve:
        assert row["accuracy"] == pytest.approx(row["confidence"], abs=1e-9)

    # The curve partitions every sample.
    assert sum(row["count"] for row in curve) == float(len(CAL_CURVE_P))

    # A well-calibrated curve has near-zero aggregate calibration error.
    ece = expected_calibration_error(CAL_CURVE_P, CAL_CURVE_O)
    assert ece == pytest.approx(0.0, abs=1e-9)


def test_overconfident_reliability_curve_sits_below_the_diagonal():
    curve = _reliability_curve(OVERCONF_P, OVERCONF_O)
    assert len(curve) == 1
    (row,) = curve
    # Overconfidence: predicted confidence strictly exceeds observed accuracy.
    assert row["confidence"] > row["accuracy"]
    assert row["confidence"] == pytest.approx(0.9)
    assert row["accuracy"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Brier + ECE: perfect vs. overconfident
# --------------------------------------------------------------------------- #
def test_perfectly_calibrated_predictor_has_zero_ece_and_brier():
    assert brier_score(PERFECT_P, PERFECT_O) == pytest.approx(0.0, abs=1e-12)
    assert expected_calibration_error(PERFECT_P, PERFECT_O) == pytest.approx(0.0, abs=1e-12)


def test_overconfident_predictor_has_high_ece_and_brier():
    brier = brier_score(OVERCONF_P, OVERCONF_O)
    ece = expected_calibration_error(OVERCONF_P, OVERCONF_O)
    # Manual: mean((0.9 - o)^2) = (5*0.01 + 5*0.81)/10 = 0.41; ECE = |0.9 - 0.5|.
    assert brier == pytest.approx(0.41)
    assert ece == pytest.approx(0.4)


def test_overconfident_is_strictly_worse_than_perfect():
    # The core comparative claim: miscalibration raises BOTH metrics.
    assert brier_score(OVERCONF_P, OVERCONF_O) > brier_score(PERFECT_P, PERFECT_O)
    assert expected_calibration_error(OVERCONF_P, OVERCONF_O) > expected_calibration_error(
        PERFECT_P, PERFECT_O
    )


def test_ece_increases_monotonically_with_overconfidence():
    # Fixed 50/50 outcomes; a single constant prediction p lands in one bin, so
    # ECE == |p - base_rate| == |p - 0.5|. Sweeping p upward must raise ECE
    # monotonically (and Brier alongside it).
    outcomes = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    eces: list[float] = []
    briers: list[float] = []
    for p in (0.5, 0.6, 0.7, 0.8, 0.9):
        probs = [p] * 10
        eces.append(expected_calibration_error(probs, outcomes))
        briers.append(brier_score(probs, outcomes))
    assert eces == sorted(eces)
    assert all(b > a for a, b in zip(eces, eces[1:]))  # strictly increasing
    assert eces[0] == pytest.approx(0.0, abs=1e-9)  # p == base rate -> perfectly calibrated
    assert eces[-1] == pytest.approx(0.4)
    assert all(b > a for a, b in zip(briers, briers[1:]))  # Brier rises too


def test_brier_and_ece_are_bounded_for_probabilities_in_unit_interval():
    for probs, outcomes in (
        (PERFECT_P, PERFECT_O),
        (OVERCONF_P, OVERCONF_O),
        (CAL_CURVE_P, CAL_CURVE_O),
    ):
        brier = brier_score(probs, outcomes)
        ece = expected_calibration_error(probs, outcomes)
        assert 0.0 <= brier <= 1.0
        assert 0.0 <= ece <= 1.0


# --------------------------------------------------------------------------- #
# Boundary behavior: honest None, never a fake 0
# --------------------------------------------------------------------------- #
def test_empty_inputs_return_none_not_zero():
    assert brier_score([], []) is None
    assert expected_calibration_error([], []) is None


def test_mismatched_lengths_return_none():
    assert brier_score([0.5], [1, 0]) is None
    assert expected_calibration_error([0.5, 0.5], [1]) is None


def test_ece_bin_count_does_not_change_a_perfect_score():
    # Binning granularity must not manufacture calibration error where there is
    # none: a perfectly-sharp predictor scores 0 at every resolution.
    for bins in (1, 2, 5, 10, 20):
        assert expected_calibration_error(PERFECT_P, PERFECT_O, bins=bins) == pytest.approx(
            0.0, abs=1e-12
        )


# --------------------------------------------------------------------------- #
# CalibrationArtifact carries the metrics + curve
# --------------------------------------------------------------------------- #
def test_calibration_artifact_carries_metrics_and_curve():
    curve = _reliability_curve(CAL_CURVE_P, CAL_CURVE_O)
    artifact = CalibrationArtifact(
        artifact_id="cal_test_1",
        definition_id="ml.prediction",
        method=CalibrationMethod.IDENTITY,
        segment="default",
        fitted_at="2026-01-01T00:00:00+00:00",
        sample_size=len(CAL_CURVE_P),
        brier_score=brier_score(CAL_CURVE_P, CAL_CURVE_O),
        expected_calibration_error=expected_calibration_error(CAL_CURVE_P, CAL_CURVE_O),
        reliability_curve=curve,
    )
    assert artifact.method == CalibrationMethod.IDENTITY
    assert artifact.sample_size == 30
    assert artifact.brier_score == pytest.approx(brier_score(CAL_CURVE_P, CAL_CURVE_O))
    assert artifact.expected_calibration_error == pytest.approx(0.0, abs=1e-9)
    assert len(artifact.reliability_curve) == 3


# --------------------------------------------------------------------------- #
# Type boundary: a heuristic score is NOT a probability
# --------------------------------------------------------------------------- #
def test_probability_and_heuristic_score_are_typed_distinctly():
    # An empirically-uncalibrated probability is still typed as a PROBABILITY,
    # but it must not claim calibration it does not have.
    prob = Probability(value=0.7, calibrated=False)
    # A heuristic score whose numeric value happens to be 0.7 is a different
    # mathematical object on a declared scale (default [0, 100]).
    heuristic = HeuristicScore(value=0.7, scale_min=0.0, scale_max=1.0)

    # Distinct math types.
    assert prob.math_type == MathType.PROBABILITY
    assert heuristic.math_type == MathType.HEURISTIC_SCORE
    assert prob.math_type != heuristic.math_type

    # Distinct classes — and a heuristic score is NOT a probability instance,
    # even though its value lands in [0, 1].
    assert type(prob) is not type(heuristic)
    assert not isinstance(heuristic, Probability)
    assert not isinstance(prob, HeuristicScore)
    # A HeuristicScore is an ORDINAL score, never a probability.
    assert isinstance(heuristic, OrdinalScore)

    # calibrated=False is truthful and preserved (not silently flipped).
    assert prob.calibrated is False


def test_uncalibrated_score_is_not_a_probability():
    raw = UncalibratedScore(value=0.9)
    assert raw.math_type == MathType.UNCALIBRATED_SCORE
    assert not isinstance(raw, Probability)
    assert "uncalibrated" in raw.note


def test_probability_rejects_out_of_range_value():
    with pytest.raises(TypeContractError):
        Probability(value=1.7)
    with pytest.raises(TypeContractError):
        Probability(value=-0.01)
