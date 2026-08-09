"""Evaluation-runner tests (ADR-008 D7/D8, Commit 11) — case orchestration.

Covers the runner's fail-closed orchestration: a tiny canned :class:`Synthesizer`
drives a fake engine, and the report produced by :meth:`EvaluationRunner.run_case`
is scored by the real Commit-11 scorers. Assertions cover the happy path (all
four documented metrics, ``passed`` computed, ``request_id`` from the result),
failures (ground-truth mismatch, credential-leak content), the ungrounded
grounding-gate outcome (``InsufficientEvidence`` -> ``passed=False``), and the
sequential, failure-isolating :meth:`run_suite`.

Concurrency / gating: the sibling ``evaluation/models.py``, ``evaluation/scorers.py``
and the Commit-9 ``synthesis/models.py`` / ``synthesis/grounding.py`` land in
parallel. Each is importor-skipped so this suite stays collectable (as a skip)
until every module it depends on is importable.

Plain asserts only: ``_raises`` is the single tiny helper; async tests rely on
the project's ``asyncio_mode = "auto"`` pytest-asyncio configuration.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("services.model_runtime.evaluation.models")
pytest.importorskip("services.model_runtime.evaluation.scorers")
pytest.importorskip("services.model_runtime.synthesis.models")
pytest.importorskip("services.model_runtime.synthesis.grounding")

from services.model_runtime.evaluation.models import EvaluationCase  # noqa: E402
from services.model_runtime.evaluation.runner import (  # noqa: E402
    EvaluationRunner,
    EvaluationRunnerError,
)
from services.model_runtime.evaluation.scorers import (  # noqa: E402
    ExactMatchScorer,
    FaithfulnessScorer,
    LatencyScorer,
    LeakScorer,
)
from services.model_runtime.synthesis.grounding import (  # noqa: E402
    InsufficientEvidence,
)
from services.model_runtime.synthesis.models import (  # noqa: E402
    EvidenceCitation,
    SynthesisResult,
)

_NOW = datetime.now(timezone.utc)

_CANNED_GROUND_TRUTH = "Revenue grew strongly in the second quarter."


async def _raises(exc_type, awaitable_fn) -> None:
    """Assert that awaiting ``awaitable_fn()`` raises ``exc_type`` (plain asserts)."""
    try:
        await awaitable_fn()
    except exc_type:
        return
    except Exception as err:  # pragma: no cover - failure diagnostic path
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


class _CannedSynthesizer:
    """Tiny provider-neutral synthesizer returning a canned string."""

    def __init__(self, content: str) -> None:
        self.content = content

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        return self.content


class _ScriptedEngine:
    """Fake engine running a per-call script (result or exception, in order)."""

    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self.calls = 0

    async def run(self, request, synthesizer):
        self.calls += 1
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _case(**overrides) -> EvaluationCase:
    """Build a benign evaluation case (secret-marker-free fields)."""
    kwargs = {
        "tenant_id": "tenant-acme",
        "case_id": "case-001",
        "query": "Summarize the second quarter results.",
        "expected_ground_truth": _CANNED_GROUND_TRUTH,
        "scenario": "You are summarizing the quarterly results.",
        "allowed_plan_kinds": ("summarize",),
    }
    kwargs.update(overrides)
    return EvaluationCase(**kwargs)


def _citation(excerpt: str = "Revenue grew strongly in the second quarter.") -> EvidenceCitation:
    return EvidenceCitation(
        reference_id="ref-1",
        source="aether.records.financials",
        tenant_id="tenant-acme",
        excerpt=excerpt,
    )


def _benign_result(request_id: str = "req-123") -> SynthesisResult:
    """A result whose content is grounded in its citation and leak-free.

    The content is exactly the ground truth, so exact-match passes; it shares
    significant tokens with the citation excerpt, so faithfulness passes.
    """
    return SynthesisResult(
        request_id=request_id,
        plan_kind="summarize",
        content=_CANNED_GROUND_TRUTH,
        citations=(_citation(),),
        created_at=_NOW,
    )


def _leaky_result() -> SynthesisResult:
    """A result whose content carries a credential marker (``sk-``).

    Built via ``model_construct`` to bypass ``SynthesisUnsafe`` — the runner
    must detect the leak at scoring time rather than at construction time. The
    content is a numbered-list line so claim extraction yields no claim (and
    therefore cannot raise ``VerificationUnsafe`` while faithfulness scores).
    """
    return SynthesisResult.model_construct(
        request_id="req-leak",
        plan_kind="summarize",
        content="1. Revenue grew strongly using sk-123456 key.",
        citations=(_citation(),),
        created_at=_NOW,
    )


def _runner(engine) -> EvaluationRunner:
    """Runner with a latency-tolerant scorer set (fake engines are instant)."""
    return EvaluationRunner(
        engine=engine,
        scorers=(
            ExactMatchScorer(),
            FaithfulnessScorer(),
            LeakScorer(),
            LatencyScorer(max_seconds=5.0),
        ),
    )


def _synth() -> _CannedSynthesizer:
    return _CannedSynthesizer("canned, ignored by the fake engine")


# ---------------------------------------------------------------------------
# run_case — happy path and per-metric failures
# ---------------------------------------------------------------------------


async def test_happy_path_reports_four_scores_and_passed():
    case = _case()
    result = _benign_result()
    report = await _runner(_ScriptedEngine([result])).run_case(case, _synth())

    assert report.case_id == "case-001"
    assert report.request_id == result.request_id
    assert len(report.scores) == 4
    assert [score.name for score in report.scores] == [
        "exact-match",
        "faithfulness",
        "leak-scan",
        "latency",
    ]
    scores = {score.name: score for score in report.scores}
    assert scores["exact-match"].value == 1.0
    assert scores["faithfulness"].value == 1.0
    assert scores["leak-scan"].value == 1.0
    assert all(score.passed for score in report.scores)
    assert report.passed is True
    assert report.leak_detected is False


async def test_default_scorers_are_the_documented_four():
    # No scorers supplied: the constructor must default to the documented set.
    runner = EvaluationRunner(engine=_ScriptedEngine([_benign_result()]))
    report = await runner.run_case(_case(), _synth())

    assert [score.name for score in report.scores] == [
        "exact-match",
        "faithfulness",
        "leak-scan",
        "latency",
    ]
    # ``passed`` is always the conjunction of the score outcomes, regardless of
    # whether the default instantaneous latency gate happened to pass.
    assert report.passed == all(score.passed for score in report.scores)


async def test_mismatched_ground_truth_fails():
    case = _case(expected_ground_truth="Expenses declined sharply during the first quarter.")
    result = _benign_result()  # content still faithful to its citation
    report = await _runner(_ScriptedEngine([result])).run_case(case, _synth())

    assert report.passed is False
    assert report.leak_detected is False
    scores = {score.name: score for score in report.scores}
    assert scores["exact-match"].value == 0.0
    assert scores["exact-match"].passed is False
    # Faithfulness/leak/latency are untouched by a ground-truth mismatch.
    assert scores["faithfulness"].passed is True
    assert scores["leak-scan"].passed is True
    assert scores["latency"].passed is True


async def test_leak_content_fails_closed():
    case = _case()
    result = _leaky_result()  # content carries "sk-" via model_construct
    report = await _runner(_ScriptedEngine([result])).run_case(case, _synth())

    assert report.passed is False
    assert report.leak_detected is True
    scores = {score.name: score for score in report.scores}
    assert scores["leak-scan"].value == 0.0
    assert scores["leak-scan"].passed is False


# ---------------------------------------------------------------------------
# run_case — fail-closed engine outcomes
# ---------------------------------------------------------------------------


async def test_ungrounded_engine_fails_closed():
    case = _case()
    engine = _ScriptedEngine([InsufficientEvidence("grounding requires evidence")])
    report = await _runner(engine).run_case(case, _synth())

    assert report.case_id == "case-001"
    assert report.request_id == "eval:ungrounded"
    assert report.passed is False
    assert report.leak_detected is False
    # The grounding-gate failure is carried as a single failing score so the
    # report stays valid under the EvaluationReport fail-closed invariant.
    assert [score.name for score in report.scores] == ["grounding"]
    assert report.scores[0].passed is False


async def test_unexpected_engine_error_fails_closed():
    case = _case()
    engine = _ScriptedEngine([RuntimeError("boom")])
    report = await _runner(engine).run_case(case, _synth())

    assert report.case_id == "case-001"
    assert report.request_id == "eval:failed"
    assert report.passed is False
    assert report.leak_detected is False


async def test_empty_allowed_plan_kinds_raises_runner_error():
    case = _case(allowed_plan_kinds=())
    runner = _runner(_ScriptedEngine([]))

    await _raises(EvaluationRunnerError, lambda: runner.run_case(case, _synth()))


# ---------------------------------------------------------------------------
# run_suite — sequential, failure-isolating
# ---------------------------------------------------------------------------


async def test_run_suite_returns_reports_in_order():
    cases = [_case(case_id="case-a"), _case(case_id="case-b")]
    engine = _ScriptedEngine(
        [_benign_result(request_id="req-a"), _benign_result(request_id="req-b")]
    )
    reports = await _runner(engine).run_suite(cases, _synth())

    assert len(reports) == 2
    assert [report.case_id for report in reports] == ["case-a", "case-b"]
    assert [report.request_id for report in reports] == ["req-a", "req-b"]
    assert all(report.passed for report in reports)


async def test_run_suite_survives_a_failing_case():
    failing = _case(case_id="case-fail", expected_ground_truth="An unrelated expected answer.")
    ok = _case(case_id="case-ok")
    cases = [failing, ok]
    engine = _ScriptedEngine(
        [_benign_result(request_id="req-fail"), _benign_result(request_id="req-ok")]
    )
    reports = await _runner(engine).run_suite(cases, _synth())

    assert len(reports) == 2
    assert reports[0].case_id == "case-fail"
    assert reports[0].passed is False
    assert reports[1].case_id == "case-ok"
    assert reports[1].passed is True


async def test_run_suite_survives_an_engine_error():
    ok = _case(case_id="case-ok")
    cases = [_case(case_id="case-boom"), ok]
    engine = _ScriptedEngine([RuntimeError("boom"), _benign_result(request_id="req-ok")])
    reports = await _runner(engine).run_suite(cases, _synth())

    assert len(reports) == 2
    assert reports[0].case_id == "case-boom"
    assert reports[0].passed is False
    assert reports[1].case_id == "case-ok"
    assert reports[1].passed is True


async def test_run_suite_survives_an_unrunnable_case():
    # A case that cannot even build a request (no plan kinds) must not abort
    # the suite; it is converted into a fail-closed report.
    bad = _case(case_id="case-bad", allowed_plan_kinds=())
    ok = _case(case_id="case-ok")
    cases = [bad, ok]
    engine = _ScriptedEngine([_benign_result(request_id="req-ok")])
    reports = await _runner(engine).run_suite(cases, _synth())

    assert len(reports) == 2
    assert reports[0].case_id == "case-bad"
    assert reports[0].passed is False
    assert reports[1].case_id == "case-ok"
    assert reports[1].passed is True
