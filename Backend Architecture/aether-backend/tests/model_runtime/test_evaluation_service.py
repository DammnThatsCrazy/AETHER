"""EvaluationService facade tests (ADR-008 D7/D8, Commit 11-F).

Covers the provider-neutral facade: ``run_case`` returns an
:class:`EvaluationReport` (and wraps ``EvaluationRunnerError`` into a short,
content-free :class:`EvaluationServiceError`); ``run_suite`` runs every catalog
case through the injected runner and requires the regression gate (passing with
a faithful synthesizer, failing with mismatched or leak-shaped content, and
never leaking content into the error message); ``summarize`` returns a safe
aggregate with no content keys; and the evaluation barrel exports every
documented name.

The synthesizer is a tiny canned double; the fake engine builds the
:class:`SynthesisResult` from the synthesizer's answer so the outcome is decided
by the caller-supplied content (exactly what the facade contracts). The citation
excerpt is the answer itself, so faithfulness always passes for claim-shaped
benign content and exact-match decides the verdict against the case ground
truth. Results are built via ``model_construct`` so a secret-shaped answer is
detected by the leak-scan scorer at scoring time rather than rejected by
``SynthesisUnsafe`` at construction — the runner must detect the leak.

Concurrency / gating: every sibling evaluation module lands in parallel. Each is
importor-skipped so this suite stays collectable (as a skip) until the full
Commit-11 set is present.

Plain asserts only: ``_raises`` / ``_capture_raises`` are the tiny helpers;
async tests rely on the project's ``asyncio_mode = "auto"`` pytest-asyncio
configuration.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("services.model_runtime.evaluation.models")
pytest.importorskip("services.model_runtime.evaluation.scorers")
pytest.importorskip("services.model_runtime.evaluation.runner")
pytest.importorskip("services.model_runtime.evaluation.scenarios")
pytest.importorskip("services.model_runtime.evaluation.gate")
pytest.importorskip("services.model_runtime.evaluation.service")
pytest.importorskip("services.model_runtime.synthesis.models")

import services.model_runtime.evaluation as evaluation_pkg  # noqa: E402
from services.model_runtime.evaluation.gate import GateResult  # noqa: E402
from services.model_runtime.evaluation.models import (  # noqa: E402
    EvaluationCase,
    EvaluationReport,
    EvaluationScore,
)
from services.model_runtime.evaluation.runner import EvaluationRunner  # noqa: E402
from services.model_runtime.evaluation.scenarios import (  # noqa: E402
    DEFAULT_TENANT_ID,
    ScenarioCatalog,
    ScenarioDefinition,
)
from services.model_runtime.evaluation.scorers import (  # noqa: E402
    ExactMatchScorer,
    FaithfulnessScorer,
    LatencyScorer,
    LeakScorer,
)
from services.model_runtime.evaluation.service import (  # noqa: E402
    EvaluationService,
    EvaluationServiceError,
)
from services.model_runtime.synthesis.models import (  # noqa: E402
    EvidenceCitation,
    SynthesisResult,
)

_NOW = datetime.now(timezone.utc)

_GROUND_TRUTH = "Revenue grew over the quarter."


async def _raises(exc_type, awaitable_fn) -> None:
    """Assert that awaiting ``awaitable_fn()`` raises ``exc_type``."""
    try:
        await awaitable_fn()
    except exc_type:
        return
    except Exception as err:  # pragma: no cover - failure diagnostic path
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


async def _capture_raises(exc_type, awaitable_fn):
    """Await ``awaitable_fn()`` and return the raised exception (or fail)."""
    try:
        await awaitable_fn()
    except exc_type as err:
        return err
    except Exception as err:  # pragma: no cover - failure diagnostic path
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


class _CannedSynthesizer:
    """Tiny provider-neutral synthesizer returning a canned string."""

    def __init__(self, content: str) -> None:
        self.content = content
        #: (prompt, plan_kind) tuples recorded per invocation.
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        self.calls.append((prompt, plan_kind))
        return self.content


class _FakeEngine:
    """Builds a SynthesisResult from the synthesizer's canned answer.

    The citation excerpt is the answer itself, so faithfulness passes for
    claim-shaped benign content. ``model_construct`` is used so a secret-shaped
    answer is scored by the leak-scan scorer at scoring time rather than
    rejected by ``SynthesisUnsafe`` at construction.
    """

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def run(self, request, synthesizer) -> SynthesisResult:
        self.calls.append(request)
        content = await synthesizer.synthesize(
            request.query, plan_kind=request.plan_kind
        )
        citation = EvidenceCitation.model_construct(
            reference_id="ref-1",
            source="aether.records.eval",
            tenant_id=request.tenant_id,
            excerpt=content,
        )
        return SynthesisResult.model_construct(
            request_id=f"eval-{len(self.calls)}",
            plan_kind=request.plan_kind,
            content=content,
            citations=(citation,),
            created_at=_NOW,
        )


def _catalog(*, tenant_id: str = "tenant-acme") -> ScenarioCatalog:
    """A one-case catalog so the facade test controls the ground truth."""
    return ScenarioCatalog(
        tenant_id=tenant_id,
        definitions=(
            ScenarioDefinition(
                case_id="revenue-trend",
                query="Summarize the quarterly revenue trend.",
                expected_ground_truth=_GROUND_TRUTH,
                scenario="summarize",
            ),
        ),
    )


def _case() -> EvaluationCase:
    return _catalog().all_cases()[0]


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


def _service(engine) -> EvaluationService:
    return EvaluationService(
        runner=_runner(engine),
        catalog=_catalog(),
    )


# ---------------------------------------------------------------------------
# run_case — returns an EvaluationReport; wraps runner errors content-free
# ---------------------------------------------------------------------------


async def test_run_case_returns_evaluation_report():
    service = _service(_FakeEngine())
    report = await service.run_case(_case(), _CannedSynthesizer(_GROUND_TRUTH))

    assert isinstance(report, EvaluationReport)
    assert report.case_id == "revenue-trend"
    assert report.passed is True
    assert report.leak_detected is False


async def test_run_case_wraps_runner_error():
    # A case with no allowed plan kinds makes the runner raise
    # EvaluationRunnerError; the facade wraps it into EvaluationServiceError
    # with a short, content-free message (failure class name only).
    service = _service(_FakeEngine())
    bad = EvaluationCase(
        tenant_id="tenant-acme",
        case_id="case-empty",
        query="Summarize the quarterly revenue trend.",
        expected_ground_truth=_GROUND_TRUTH,
        allowed_plan_kinds=(),
    )
    err = await _capture_raises(
        EvaluationServiceError,
        lambda: service.run_case(bad, _CannedSynthesizer("irrelevant")),
    )
    assert "EvaluationRunnerError" in str(err)
    assert _GROUND_TRUTH not in str(err)


# ---------------------------------------------------------------------------
# run_suite — faithful synthesizer passes the gate; failures raise
# ---------------------------------------------------------------------------


async def test_run_suite_faithful_synthesizer_passes_gate():
    service = _service(_FakeEngine())
    synth = _CannedSynthesizer(_GROUND_TRUTH)
    result = await service.run_suite(synth)

    assert isinstance(result, GateResult)
    assert result.passed is True
    assert result.total_cases == 1
    assert result.passed_cases == 1
    assert result.failed_cases == 0
    assert result.failed_case_ids == ()
    # The synthesizer was consulted once for the single catalog case.
    assert len(synth.calls) == 1


async def test_run_suite_mismatched_content_fails_gate():
    service = _service(_FakeEngine())
    synth = _CannedSynthesizer("Expenses declined during the quarter.")
    await _raises(EvaluationServiceError, lambda: service.run_suite(synth))


async def test_run_suite_leak_shaped_content_fails_closed():
    service = _service(_FakeEngine())
    # A numbered-list line yields no claims (so faithfulness cannot raise
    # VerificationUnsafe) and carries "sk-" for the leak-scan scorer to catch.
    synth = _CannedSynthesizer("1. Revenue grew using sk-123456 key.")
    await _raises(EvaluationServiceError, lambda: service.run_suite(synth))


async def test_run_suite_error_message_is_content_free():
    service = _service(_FakeEngine())
    synth = _CannedSynthesizer("Expenses declined during the quarter.")
    err = await _capture_raises(EvaluationServiceError, lambda: service.run_suite(synth))

    message = str(err)
    # The failing case_id IS named; the synthesizer content is NOT.
    assert "revenue-trend" in message
    assert "Expenses declined" not in message
    assert _GROUND_TRUTH not in message


async def test_run_suite_leak_error_message_has_no_secret_marker():
    service = _service(_FakeEngine())
    synth = _CannedSynthesizer("1. Revenue grew using sk-123456 key.")
    err = await _capture_raises(EvaluationServiceError, lambda: service.run_suite(synth))

    # The underlying failure was a secret violation, but the facade message
    # names only the failing case_id — never the "sk-" content.
    assert "sk-" not in str(err)


# ---------------------------------------------------------------------------
# summarize — safe aggregate with no content keys
# ---------------------------------------------------------------------------


def _passing_report(case_id: str = "case-pass") -> EvaluationReport:
    return EvaluationReport(
        case_id=case_id,
        request_id=f"req-{case_id}",
        scores=(),
        passed=True,
        leak_detected=False,
        created_at=_NOW,
    )


def _failing_report(case_id: str = "case-fail") -> EvaluationReport:
    return EvaluationReport(
        case_id=case_id,
        request_id=f"req-{case_id}",
        scores=(
            EvaluationScore(
                name="exact-match",
                value=0.0,
                passed=False,
                threshold=1.0,
                method="exact-match",
            ),
        ),
        passed=False,
        leak_detected=False,
        created_at=_NOW,
    )


def _leaky_report(case_id: str = "case-leak") -> EvaluationReport:
    return EvaluationReport(
        case_id=case_id,
        request_id=f"req-{case_id}",
        scores=(
            EvaluationScore(
                name="leak-scan",
                value=0.0,
                passed=False,
                threshold=1.0,
                method="leak-scan",
            ),
        ),
        passed=False,
        leak_detected=True,
        created_at=_NOW,
    )


def test_summarize_returns_safe_aggregate():
    service = EvaluationService()
    summary = service.summarize([_passing_report(), _failing_report()])

    assert summary == {
        "total": 2,
        "passed": 1,
        "failed_case_ids": ["case-fail"],
        "leak_free": True,
    }
    # No content keys and no report content in the aggregate.
    assert set(summary) == {"total", "passed", "failed_case_ids", "leak_free"}
    assert _GROUND_TRUTH not in str(summary)


def test_summarize_flags_leaks_and_empty_suite():
    service = EvaluationService()
    leaky = service.summarize([_leaky_report()])
    assert leaky == {
        "total": 1,
        "passed": 0,
        "failed_case_ids": ["case-leak"],
        "leak_free": False,
    }

    empty = service.summarize([])
    assert empty == {
        "total": 0,
        "passed": 0,
        "failed_case_ids": [],
        "leak_free": True,
    }


# ---------------------------------------------------------------------------
# Public API surface — service module + evaluation barrel
# ---------------------------------------------------------------------------


def test_service_module_exports_complete():
    import services.model_runtime.evaluation.service as service_module

    expected = {"EvaluationServiceError", "EvaluationService"}
    assert set(service_module.__all__) == expected
    for name in expected:
        assert hasattr(service_module, name), name


def test_barrel_exports_complete():
    expected = {
        # evaluation/models.py
        "EvaluationUnsafe",
        "EVALUATION_SECRET_MARKERS",
        "EvaluationCase",
        "EvaluationScore",
        "EvaluationReport",
        # evaluation/scorers.py
        "ScorerError",
        "EvaluationScorer",
        "ExactMatchScorer",
        "FaithfulnessScorer",
        "LeakScorer",
        "LatencyScorer",
        # evaluation/runner.py
        "EvaluationRunnerError",
        "EvaluationRunner",
        # evaluation/scenarios.py
        "ScenarioCatalogError",
        "DEFAULT_TENANT_ID",
        "ScenarioDefinition",
        "ScenarioCatalog",
        # evaluation/gate.py
        "RegressionGateError",
        "GateResult",
        "RegressionGate",
        # evaluation/service.py
        "EvaluationServiceError",
        "EvaluationService",
    }
    assert set(evaluation_pkg.__all__) == expected
    for name in expected:
        assert hasattr(evaluation_pkg, name), name


def test_default_tenant_id_constant():
    assert DEFAULT_TENANT_ID == "eval-tenant"
