"""Focused tests for local runtime evidence and deterministic budget telemetry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.test_suites import load_suites  # noqa: E402
from scripts.validate_ci_runtime_budgets import (  # noqa: E402
    RuntimeBudgetError,
    build_runtime_report,
    load_evidence,
    percentile,
)


REGISTRY = ROOT / "config" / "test_suites.yaml"


def test_percentile_is_deterministic_linear_interpolation() -> None:
    values = [40, 10, 30, 20]
    assert percentile(values, 0.50) == 25
    assert percentile(values, 0.95) == pytest.approx(38.5)
    assert percentile([1, 2, 3, 4, 5], 0.95) == pytest.approx(4.8)


def test_jsonl_selection_telemetry_and_percentiles_are_reported(tmp_path: Path) -> None:
    evidence = tmp_path / "runtime.jsonl"
    evidence.write_text(
        "\n".join(
            [
                json.dumps({"suite": "root", "runtime_seconds": 10, "selected_by": "impact-graph"}),
                json.dumps({"suite": "root", "runtime_seconds": 20, "selected_by": "universal-fast"}),
                json.dumps({"suite": "root", "runtime_seconds": 30, "selected_by": "impact-graph"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    records = load_evidence(evidence)
    root_suite = next(suite for suite in load_suites(REGISTRY) if suite.id == "root")
    report = build_runtime_report(records, [root_suite])

    telemetry = report["suites"][0]
    assert telemetry["p50_seconds"] == 20
    assert telemetry["p95_seconds"] == pytest.approx(29)
    assert telemetry["selection_count"] == 3
    assert telemetry["selection_frequency"] == 1
    assert telemetry["selection_by"] == {"impact-graph": 2, "universal-fast": 1}
    assert report["selection"]["by"] == {"impact-graph": 2, "universal-fast": 1}
    assert report["valid"] is True


def test_runtime_budget_violation_is_reported() -> None:
    root_suite = next(suite for suite in load_suites(REGISTRY) if suite.id == "root")
    report = build_runtime_report(
        [
                {"suite": "root", "runtime_seconds": 601, "selected_by": "impact-graph"},
                {"suite": "root", "runtime_seconds": 602, "selected_by": "impact-graph"},
        ],
        [root_suite],
    )

    assert report["valid"] is False
    assert report["violations"][0]["suite"] == "root"
    assert "p95_exceeds_hard_budget" in report["violations"][0]["reasons"]


def test_failure_yield_counts_all_blocking_non_success_outcomes() -> None:
    root_suite = next(suite for suite in load_suites(REGISTRY) if suite.id == "root")
    report = build_runtime_report(
        [
            {"suite": "root", "runtime_seconds": 1, "selected_by": "impact-graph", "outcome": "timeout"},
            {"suite": "root", "runtime_seconds": 1, "selected_by": "impact-graph", "outcome": "runner_failure"},
            {"suite": "root", "runtime_seconds": 1, "selected_by": "impact-graph", "outcome": "pass"},
            {"suite": "root", "runtime_seconds": 1, "selected_by": "impact-graph", "outcome": "failed", "blocking": False},
        ],
        [root_suite],
    )
    assert report["suites"][0]["failure_yield"] == pytest.approx(0.5)


def test_unknown_suite_evidence_fails_closed() -> None:
    root_suite = next(suite for suite in load_suites(REGISTRY) if suite.id == "root")
    with pytest.raises(RuntimeBudgetError, match="unregistered suite"):
        build_runtime_report(
            [{"suite": "not-registered", "runtime_seconds": 1, "selected_by": "impact-graph"}],
            [root_suite],
        )
