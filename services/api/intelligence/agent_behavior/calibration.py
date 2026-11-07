"""Forward-coverage diagnostics for stored behavior snapshots (open item: calibration).

Every rate Aether reports is uncalibrated: a Wilson interval says how much a
sample constrains a rate, not that the rate predicts anything. This module adds
the one evidence-based check the stored snapshots allow without labelled
outcomes: does the interval of window ``i`` contain the rate actually observed
in window ``i + 1``?

The observed next-window rate carries its own sampling noise, so this is a
stability diagnostic, not a calibration proof. It can show evidence that
intervals are too narrow for how the agent actually behaves, and it never
promotes a rate to "calibrated". Derived and rebuildable; writes nothing.
"""
from __future__ import annotations

from typing import Any, Iterable

from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.dynamics import _RATE_FEATURES
from intelligence.agent_behavior.model import MIN_SAMPLE, wilson

NOMINAL_COVERAGE = 0.95
MIN_PAIRS = 20  # window pairs per feature before any status other than insufficient_evidence

STATUS_INSUFFICIENT = "insufficient_evidence"
STATUS_UNDERCOVERS = "intervals_undercover_forward_rates"
STATUS_NO_EVIDENCE = "no_evidence_of_undercoverage"


def _pair_outcome(prev: dict[str, Any], nxt: dict[str, Any]) -> bool | None:
    """True if ``prev``'s interval contains ``nxt``'s rate; None if either is withheld."""
    if not prev or not nxt:
        return None
    if prev.get("value") is None or nxt.get("value") is None:
        return None
    if (prev.get("n") or 0) < MIN_SAMPLE or (nxt.get("n") or 0) < MIN_SAMPLE:
        return None
    interval = prev.get("interval")
    if not interval or interval[0] is None or interval[1] is None:
        return None
    return interval[0] <= nxt["value"] <= interval[1]


def forward_coverage(snapshot_series: Iterable[Iterable[dict[str, Any]]]) -> dict[str, Any]:
    """Coverage of consecutive-window intervals, pooled over agents.

    ``snapshot_series`` is one chronologically ordered list of window snapshots
    per agent. Pairs never cross agents."""
    tally = {k: [0, 0] for k in _RATE_FEATURES}  # covered, pairs
    agents = 0
    for series in snapshot_series:
        snaps = list(series)
        if len(snaps) < 2:
            continue
        agents += 1
        for prev, nxt in zip(snaps, snaps[1:]):
            for feature in _RATE_FEATURES:
                hit = _pair_outcome(prev["rates"].get(feature), nxt["rates"].get(feature))
                if hit is None:
                    continue
                tally[feature][1] += 1
                tally[feature][0] += int(hit)

    features: dict[str, Any] = {}
    for feature, (covered, pairs) in tally.items():
        low, high = wilson(covered, pairs)
        if pairs < MIN_PAIRS:
            status = STATUS_INSUFFICIENT
        elif high is not None and high < NOMINAL_COVERAGE:
            status = STATUS_UNDERCOVERS
        else:
            status = STATUS_NO_EVIDENCE
        features[feature] = {
            "pairs": pairs, "covered": covered,
            "coverage": round(covered / pairs, 4) if pairs >= MIN_PAIRS else None,
            "coverage_interval": [low, high] if pairs else None,
            "status": status,
        }
    return {
        "basis": c.DERIVED,
        "method": "forward_interval_coverage_wilson_95",
        "nominal": NOMINAL_COVERAGE,
        "agents": agents,
        "features": features,
        "calibrated": False,
        "note": (
            "Stability diagnostic over stored windows, not calibration: the "
            "next-window rate has its own sampling noise and no labelled outcomes "
            "are used. Rates stay uncalibrated whatever this reports."
        ),
    }
