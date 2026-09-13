"""Regression-gate tests (ADR-008 D7/D9, Commit 11-E) — fail-closed quality gate.

Plain asserts only: no ``pytest.raises``, no fixture/mock libraries.
``_raises`` is the single tiny helper, so this suite runs identically under
the minimal test runtime used by some CI environments.

Concurrency / gating: the sibling ``evaluation/models.py`` (Commit 11-A) lands
in parallel. It is importor-skipped so this suite passes (as a skip) until it
is importable; once ``models.py`` is importable the suite runs against the real
``EvaluationReport`` / ``EvaluationScore`` contract and the gate rules are
enforced end to end.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

# The sibling models module (Commit 11-A) may land concurrently with this
# suite; until it is importable the whole suite skips.
models = pytest.importorskip("services.model_runtime.evaluation.models")

from services.model_runtime.evaluation.gate import (  # noqa: E402 - after importorskip guard
    GateResult,
    RegressionGate,
    RegressionGateError,
)

_REQUIRED = ("exact-match", "faithfulness", "leak-scan", "latency")


def _raises(exc_type, func):
    """Assert that calling func() raises exc_type (no pytest imports needed)."""
    try:
        func()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _scores(*names, fail=None):
    """Build an EvaluationScore tuple via sibling A's models (name/value/passed/threshold)."""
    return tuple(
        models.EvaluationScore(
            name=name,
            value=1.0,
            passed=(name != fail),
            threshold=0.5,
        )
        for name in names
    )


def _report(case_id, *, scores=None, fail_score=None, leak_detected=False):
    """Build a report via sibling A's models with a validator-consistent ``passed``.

    The sibling ``EvaluationReport`` model enforces ``passed ==
    all(scores passed) and not leak_detected`` at construction, so ``passed`` is
    derived rather than passed in.
    """
    if scores is None:
        scores = _scores(*_REQUIRED, fail=fail_score)
    passed = not leak_detected and all(score.passed for score in scores)
    return models.EvaluationReport(
        case_id=case_id,
        request_id=f"req-{case_id}",
        scores=scores,
        passed=passed,
        leak_detected=leak_detected,
    )


# ---------------------------------------------------------------------------
# Gate rules
# ---------------------------------------------------------------------------


def test_all_pass_suite_passes_with_correct_counts():
    gate = RegressionGate()
    reports = [_report("c-1"), _report("c-2"), _report("c-3")]
    result = gate.evaluate(reports)
    assert result.passed is True
    assert result.total_cases == 3
    assert result.passed_cases == 3
    assert result.failed_cases == 0
    assert result.failed_case_ids == ()


def test_one_failing_report_fails_gate_and_lists_case_id():
    gate = RegressionGate()
    reports = [
        _report("good-1"),
        _report("bad-1", fail_score="exact-match"),
        _report("good-2"),
    ]
    result = gate.evaluate(reports)
    assert result.passed is False
    assert result.total_cases == 3
    assert result.passed_cases == 2
    assert result.failed_cases == 1
    assert result.failed_case_ids == ("bad-1",)


def test_leak_detected_report_fails_gate():
    # Sibling A's model forbids passed=True + leak_detected=True, so a real
    # leak report is passed=False + leak_detected=True. Either way the gate
    # must fail the report and never ship it.
    reports = [_report("clean"), _report("leaky", leak_detected=True)]
    result = RegressionGate().evaluate(reports)
    assert result.passed is False
    assert result.passed_cases == 1
    assert result.failed_cases == 1
    assert result.failed_case_ids == ("leaky",)


def test_gate_fails_closed_on_leak_even_when_passed_flag_true():
    # Defense in depth: the gate must fail a leaked report on the leak flag
    # alone, even if a buggy upstream emitted the passed=True + leak_detected=True
    # combination the sibling model forbids. gate.py duck-types reports, so a
    # minimal stand-in exercises that branch.
    leaky_pass = SimpleNamespace(
        case_id="inconsistent",
        passed=True,
        leak_detected=True,
        scores=_scores(*_REQUIRED),
    )
    result = RegressionGate().evaluate([leaky_pass])
    assert result.passed is False
    assert result.failed_case_ids == ("inconsistent",)


def test_empty_reports_fail_closed():
    result = RegressionGate().evaluate([])
    assert result.passed is False
    assert result.total_cases == 0
    assert result.passed_cases == 0
    assert result.failed_cases == 0
    assert result.failed_case_ids == ()


def test_missing_required_score_fails_report():
    incomplete = _scores("exact-match", "faithfulness", "leak-scan")  # no latency
    result = RegressionGate().evaluate([_report("c-1", scores=incomplete)])
    assert result.passed is False
    assert result.failed_case_ids == ("c-1",)


def test_extra_scores_are_allowed():
    extra = _scores(*_REQUIRED, "grounding")
    result = RegressionGate().evaluate([_report("c-1", scores=extra)])
    assert result.passed is True
    assert result.failed_case_ids == ()


def test_custom_required_scores_override_defaults():
    gate = RegressionGate(required_scores=("exact-match", "faithfulness"))
    ok = _report("c-1", scores=_scores("exact-match", "faithfulness"))
    result = gate.evaluate([ok])
    assert result.passed is True
    assert result.failed_case_ids == ()


# ---------------------------------------------------------------------------
# require() behavior
# ---------------------------------------------------------------------------


def test_require_raises_when_suite_fails():
    gate = RegressionGate()
    reports = [_report("ok"), _report("no", fail_score="latency")]
    _raises(RegressionGateError, lambda: gate.require(reports))


def test_require_returns_gate_result_when_passing():
    gate = RegressionGate()
    result = gate.require([_report("ok")])
    assert isinstance(result, GateResult)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_failed_case_ids_preserve_report_order():
    reports = [
        _report("a", fail_score="exact-match"),
        _report("b"),
        _report("c", leak_detected=True),
        _report("d", fail_score="faithfulness"),
    ]
    result = RegressionGate().evaluate(reports)
    assert result.failed_case_ids == ("a", "c", "d")


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


def test_public_exports_exact():
    import services.model_runtime.evaluation.gate as gate_module

    assert gate_module.__all__ == [
        "RegressionGateError",
        "GateResult",
        "RegressionGate",
    ]


def test_gate_result_is_frozen_dataclass():
    assert dataclasses.is_dataclass(GateResult)
    result = GateResult(passed=True, total_cases=1, passed_cases=1, failed_cases=0)
    _raises(dataclasses.FrozenInstanceError, lambda: setattr(result, "passed", False))
