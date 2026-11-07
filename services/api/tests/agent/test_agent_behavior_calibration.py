"""Forward-coverage diagnostics over stored windows (calibration open item)."""
from __future__ import annotations

import pytest

from intelligence.agent_behavior.calibration import (
    MIN_PAIRS, STATUS_INSUFFICIENT, STATUS_NO_EVIDENCE, STATUS_UNDERCOVERS, forward_coverage,
)
from intelligence.agent_behavior.model import wilson
from intelligence.agent_behavior.snapshot_store import (
    BehaviorSnapshotRepository, calibration_over_stored_windows,
)
from repositories.repos import reset_in_memory_stores

F = "tool_success_rate"


def snap(successes, n=40, day=1):
    low, high = wilson(successes, n)
    return {"agent_ref": "a", "window": [f"d{day}", f"d{day + 1}"], "version": 1,
            "rates": {F: {"n": n, "value": round(successes / n, 4), "interval": [low, high], "evidence": []}}}


def series(successes_per_window):
    return [snap(s, day=i) for i, s in enumerate(successes_per_window)]


def test_stable_agent_is_covered_but_never_called_calibrated():
    out = forward_coverage([series([36, 35, 37, 36] * 8)])  # 31 pairs, all near 0.9
    feat = out["features"][F]
    assert feat["pairs"] == 31 and feat["status"] == STATUS_NO_EVIDENCE
    assert feat["coverage"] == 1.0
    assert out["calibrated"] is False and out["basis"] == "derived"


def test_unstable_agent_shows_undercoverage():
    out = forward_coverage([series([38, 10] * 16)])  # alternates 0.95 / 0.25
    feat = out["features"][F]
    assert feat["status"] == STATUS_UNDERCOVERS and feat["coverage"] == 0.0


def test_too_few_pairs_report_insufficient_evidence_with_no_coverage_value():
    out = forward_coverage([series([36, 35, 37])])
    feat = out["features"][F]
    assert feat["pairs"] == 2 < MIN_PAIRS
    assert feat["status"] == STATUS_INSUFFICIENT and feat["coverage"] is None


def test_withheld_windows_are_skipped_and_pairs_do_not_cross_agents():
    thin = snap(2, n=3)  # below MIN_SAMPLE: value withheld by the model
    thin["rates"][F]["value"] = None
    out = forward_coverage([[snap(36), thin, snap(36)], [snap(36)]])
    assert out["features"][F]["pairs"] == 0 and out["agents"] == 1


@pytest.mark.asyncio
async def test_stored_windows_are_tenant_scoped():
    reset_in_memory_stores()
    repo = BehaviorSnapshotRepository()
    for i, s in enumerate(series([36, 35, 37])):
        await repo.put("t-a", "a", {**s, "window": [f"2026-10-0{i + 1}", f"2026-10-0{i + 2}"]})
    mine = await calibration_over_stored_windows(repo, "t-a", "a")
    other = await calibration_over_stored_windows(repo, "t-b", "a")
    assert mine["features"][F]["pairs"] == 2
    assert other["features"][F]["pairs"] == 0 and other["agents"] == 0
    reset_in_memory_stores()
