"""Tests for the evaluation-plane data models (ADR-008 D7/D8).

The evaluation plane scores the multi-model harness by running canned,
tenant-scoped scenarios through the synthesis engine and scoring the output for
faithfulness/accuracy/leak-safety. These tests cover the data models that carry
those scenarios and outcomes: secret-marker rejection on every content-carrying
field of :class:`EvaluationCase`, the plain :class:`EvaluationScore` wiring, and
the fail-closed :class:`EvaluationReport` ``passed`` invariant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from services.model_runtime.evaluation.models import (
    EVALUATION_SECRET_MARKERS,
    EvaluationCase,
    EvaluationReport,
    EvaluationScore,
    EvaluationUnsafe,
)


def _raises(exc_type, call):
    """Assert that ``call()`` raises ``exc_type``, using only plain asserts."""
    try:
        call()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _case(**overrides):
    kwargs = {
        "tenant_id": "tenant-acme",
        "case_id": "case-001",
        "query": "Summarize the Q3 financial report.",
        "expected_ground_truth": "Revenue grew 12% in Q3.",
        "scenario": "",
        "allowed_plan_kinds": ("summarize",),
    }
    kwargs.update(overrides)
    return EvaluationCase(**kwargs)


def _score(**overrides):
    kwargs = {
        "name": "faithfulness",
        "value": 0.95,
        "passed": True,
        "threshold": 0.9,
        "method": "token-overlap",
    }
    kwargs.update(overrides)
    return EvaluationScore(**kwargs)


def _report(**overrides):
    kwargs = {
        "case_id": "case-001",
        "request_id": "req-001",
        "scores": (_score(),),
        "passed": True,
        "leak_detected": False,
    }
    kwargs.update(overrides)
    return EvaluationReport(**kwargs)


def test_models_are_frozen():
    _raises(ValidationError, lambda: setattr(_case(), "case_id", "case-002"))
    _raises(ValidationError, lambda: setattr(_score(), "value", 1.0))
    _raises(ValidationError, lambda: setattr(_report(), "passed", False))


def test_models_reject_extra_fields():
    _raises(ValidationError, lambda: _case(extra_field="x"))
    _raises(ValidationError, lambda: _score(extra_field="x"))
    _raises(ValidationError, lambda: _report(extra_field="x"))


def test_secret_markers_in_query_raise():
    for marker in ("sk-abc123", "AKIAIOSFODNN7EXAMPLE", "eyJhbGciOi", "password=supersecret"):
        _raises(
            EvaluationUnsafe,
            lambda m=marker: _case(query=f"Please echo this token: {m}"),
        )


def test_secret_markers_in_expected_ground_truth_raise():
    for marker in ("sk-abc123", "AKIAIOSFODNN7EXAMPLE", "eyJhbGciOi", "password=supersecret"):
        _raises(
            EvaluationUnsafe,
            lambda m=marker: _case(expected_ground_truth=f"Canonical answer: {m}"),
        )


def test_secret_markers_in_scenario_raise():
    for marker in ("sk-abc123", "AKIAIOSFODNN7EXAMPLE", "eyJhbGciOi", "password=supersecret"):
        _raises(
            EvaluationUnsafe,
            lambda m=marker: _case(scenario=f"Context block includes {m}."),
        )


def test_secret_marker_check_is_case_insensitive():
    _raises(EvaluationUnsafe, lambda: _case(query="the relay token is SK-live-001"))
    _raises(EvaluationUnsafe, lambda: _case(query="akiaIOSFODNN7EXAMPLE in the payload"))
    _raises(EvaluationUnsafe, lambda: _case(expected_ground_truth="beAREr deadbeef arrives"))


def test_benign_content_passes():
    case = _case(
        query="What are the top three risks in the earnings call?",
        expected_ground_truth="Risks: supply chain, FX, and labor costs.",
        scenario="Tenant onboarding for a FinTech client.",
    )
    assert case.tenant_id == "tenant-acme"
    assert case.case_id == "case-001"
    assert case.query == "What are the top three risks in the earnings call?"
    assert case.expected_ground_truth == "Risks: supply chain, FX, and labor costs."
    assert case.scenario == "Tenant onboarding for a FinTech client."


def test_default_scenario_and_allowed_plan_kinds():
    case = _case()
    assert case.scenario == ""
    assert case.allowed_plan_kinds == ("summarize",)
    assert case.allowed_plan_kinds[0] == "summarize"


def test_evaluation_score_wiring():
    score = _score(value=0.45, passed=False, threshold=0.5, method="exact-match")
    assert score.name == "faithfulness"
    assert score.value == 0.45
    assert score.passed is False
    assert score.threshold == 0.5
    assert score.method == "exact-match"
    assert _score().method == "token-overlap"  # explicit default
    assert _score().passed is True  # above-threshold default


def test_evaluation_report_defaults():
    report = _report()
    assert report.case_id == "case-001"
    assert report.request_id == "req-001"
    assert report.scores == (_score(),)
    assert report.scores[0].passed is True
    assert report.passed is True
    assert report.leak_detected is False
    assert isinstance(report.created_at, datetime)


def test_evaluation_report_created_at_defaults_to_utc_datetime():
    report = _report()
    assert isinstance(report.created_at, datetime)
    assert report.created_at.tzinfo is not None
    assert report.created_at.tzinfo is timezone.utc


def test_evaluation_report_empty_scores_with_no_leak_passes():
    report = _report(scores=(), passed=True)
    assert report.scores == ()
    assert report.passed is True
    assert report.leak_detected is False


def test_evaluation_report_passed_false_when_score_fails():
    report = _report(scores=(_score(passed=False),), passed=False)
    assert report.passed is False
    assert report.scores[0].passed is False


def test_evaluation_report_passed_false_when_leak_detected():
    report = _report(leak_detected=True, passed=False)
    assert report.leak_detected is True
    assert report.passed is False


def test_evaluation_report_rejects_inconsistent_passed():
    # passed=True while a score failed must fail closed.
    _raises(
        ValidationError,
        lambda: _report(scores=(_score(passed=False),), passed=True),
    )
    # passed=True while a leak was detected must fail closed.
    _raises(ValidationError, lambda: _report(leak_detected=True, passed=True))


def test_evaluation_secret_marker_list_exported():
    assert isinstance(EVALUATION_SECRET_MARKERS, tuple)
    for marker in ("sk-", "AKIA", "eyJ", "password=", "secret=", "key="):
        assert marker in EVALUATION_SECRET_MARKERS
