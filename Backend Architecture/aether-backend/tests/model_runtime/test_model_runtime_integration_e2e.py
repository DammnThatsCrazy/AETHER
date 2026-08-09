"""End-to-end integration tests for the provider-neutral harness (Commit 16, Agent F).

Proves the FULL plane works with a fake synthesizer — no real provider calls:

1. **Full happy path** — a real :class:`ContextBundle` is built from seeded
   ``NoopRetriever`` records via :class:`ContextService`; a canned synthesizer
   echoes the prompt's evidence through :class:`GroundedSynthesisEngine`; the
   result is verified via :class:`VerificationEngine` and rendered via
   :class:`SynthesisRenderer`. Assertions: citations match the evidence set,
   ``verified.faithful`` is True, and the rendered markdown carries
   ``request:`` / ``## Evidence`` with no credential markers.
2. **Fail-closed chain** — an ``'unsupported'`` answer propagates
   ``UnsupportedSynthesis``; unfaithful content raises ``VerificationFailure``
   on ``enforce``; ``sk-``-shaped content (built via ``model_construct``) is
   reported as ``leak_detected`` and blocked by ``enforce``.
3. **Evaluation plane** — an :class:`EvaluationCase` runs through
   :class:`EvaluationRunner.run_case` behind a full-plane engine; the report
   carries all four documented score names with ``passed`` computed, and
   :class:`RegressionGate.evaluate` yields the expected :class:`GateResult`.
4. **Pipeline path** — (``importorskip`` while ``pipeline.py`` lands
   concurrently) ``HarnessPipeline.run`` returns a ``PipelineOutput`` whose
   ``result`` and ``verified`` are populated.

House style: plain asserts only (``_raises`` / ``_raises_sync`` helpers), async
via pytest-asyncio ``asyncio_mode = "auto"``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("services.model_runtime.context.evidence")
pytest.importorskip("services.model_runtime.synthesis.engine")
pytest.importorskip("services.model_runtime.synthesis.models")
pytest.importorskip("services.model_runtime.verification.verifier")
pytest.importorskip("services.model_runtime.evaluation.runner")

from services.model_runtime.context.evidence import ContextBundle
from services.model_runtime.context.retrieval import (
    NoopRetriever,
    RetrievedRecord,
    ScopedRetriever,
)
from services.model_runtime.context.service import ContextService
from services.model_runtime.evaluation.gate import GateResult, RegressionGate
from services.model_runtime.evaluation.models import EvaluationCase, EvaluationReport
from services.model_runtime.evaluation.runner import EvaluationRunner
from services.model_runtime.evaluation.scorers import (
    ExactMatchScorer,
    FaithfulnessScorer,
    LatencyScorer,
    LeakScorer,
)
from services.model_runtime.synthesis.engine import (
    GroundedSynthesisEngine,
    UnsupportedSynthesis,
)
from services.model_runtime.synthesis.models import (
    EvidenceCitation,
    SynthesisRequest,
    SynthesisResult,
)
from services.model_runtime.synthesis.renderer import SynthesisRenderer
from services.model_runtime.verification.models import VerificationResult
from services.model_runtime.verification.verifier import (
    VerificationEngine,
    VerificationFailure,
)

TENANT = "tenant-a"
PROFILE = "profile-a"
QUERY = "Summarize the quarterly revenue and cost trends."
INSTRUCTIONS = "Answer in one sentence."
EVIDENCE_1 = "Revenue grew strongly in the second quarter of 2026."
EVIDENCE_2 = "Costs declined sharply during the first quarter of 2026."
EXPECTED_GROUND_TRUTH = (
    "Revenue grew strongly in the second quarter of 2026. "
    "Costs declined sharply during the first quarter of 2026."
)


async def _raises(exc_type, awaitable_fn) -> None:
    """Assert that awaiting ``awaitable_fn()`` raises ``exc_type``."""
    try:
        await awaitable_fn()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _raises_sync(exc_type, fn) -> None:
    """Assert that calling ``fn()`` raises ``exc_type``."""
    try:
        fn()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


class _EchoSynthesizer:
    """Provider-neutral synthesizer that echoes the prompt's evidence blocks.

    The rendered prompt carries each evidence item as a ``[ref:...] (source:
    ...)`` line followed by its content; this synthesizer returns those content
    lines joined, so the produced answer shares significant tokens with the
    citations (faithful) and is deterministically grounded.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        self.calls.append((prompt, plan_kind))
        return self._echo(prompt)

    @staticmethod
    def _echo(prompt: str) -> str:
        lines = prompt.splitlines()
        echoed: list[str] = []
        for index, line in enumerate(lines):
            if line.startswith("[ref:") and index + 1 < len(lines):
                content = lines[index + 1].strip()
                if content and not content.startswith("[ref:"):
                    echoed.append(content)
        return " ".join(echoed)


class _CannedSynthesizer:
    """Provider-neutral synthesizer returning a fixed canned string."""

    def __init__(self, content: str) -> None:
        self.content = content

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        return self.content


def _records() -> list[RetrievedRecord]:
    """Two tenant-scoped, fresh evidence records for ``TENANT``."""
    now = datetime.now(timezone.utc)
    return [
        RetrievedRecord(
            reference_id="ref-1",
            source="aether.records.financials.q2",
            tenant_id=TENANT,
            content=EVIDENCE_1,
            collected_at=now,
            metadata={"quarter": "q2-2026"},
        ),
        RetrievedRecord(
            reference_id="ref-2",
            source="aether.records.financials.q1",
            tenant_id=TENANT,
            content=EVIDENCE_2,
            collected_at=now,
            metadata={"quarter": "q1-2026"},
        ),
    ]


def _context_service() -> ContextService:
    """A real ``ContextService`` over the seeded no-op retrieval seam."""
    return ContextService(retriever=ScopedRetriever(NoopRetriever(_records())))


async def _build_bundle_and_request() -> tuple[ContextBundle, SynthesisRequest]:
    """Assemble a real context bundle and the synthesis request it grounds."""
    service = _context_service()
    bundle = await service.build_context(
        tenant_id=TENANT,
        profile_id=PROFILE,
        query=QUERY,
        instructions=INSTRUCTIONS,
    )
    request = SynthesisRequest(
        tenant_id=bundle.tenant_id,
        profile_id=bundle.profile_id,
        query=bundle.query,
        plan_kind="summarize",
        evidence=bundle.evidence,
        synthesis_instructions=bundle.synthesis_instructions,
        created_at=bundle.created_at,
    )
    return bundle, request


def _verification_engine() -> VerificationEngine:
    return VerificationEngine()


# ---------------------------------------------------------------------------
# 1. Full happy path — context -> grounded synthesis -> verification -> render
# ---------------------------------------------------------------------------


async def test_full_happy_path_synthesize_verify_render():
    bundle, request = await _build_bundle_and_request()
    assert isinstance(bundle, ContextBundle)
    assert len(bundle.evidence.items) == 2

    synthesizer = _EchoSynthesizer()
    engine = GroundedSynthesisEngine()
    result = await engine.run(request, synthesizer)

    assert isinstance(result, SynthesisResult)
    assert result.plan_kind == "summarize"
    # Citations are drawn ONLY from the evidence set, in order, 1:1.
    assert len(result.citations) == len(bundle.evidence.items)
    assert [c.reference_id for c in result.citations] == [
        item.reference_id for item in bundle.evidence.items
    ]
    assert all(isinstance(c, EvidenceCitation) for c in result.citations)
    assert all(c.tenant_id == TENANT for c in result.citations)
    # The synthesizer echoed the prompt's evidence (content shares tokens).
    assert "Revenue" in result.content
    assert "Costs" in result.content

    # Verification: content shares tokens with the evidence -> faithful.
    verified = _verification_engine().enforce(result)
    assert isinstance(verified, VerificationResult)
    assert verified.faithful is True
    assert verified.leak_detected is False
    assert len(verified.checks) == len(result.citations)
    assert all(check.supported for check in verified.checks)

    # Render: bounded grounded markdown with citations and no credential markers.
    rendered = SynthesisRenderer().render(result)
    assert "request:" in rendered
    assert "## Evidence" in rendered
    assert "ref-1" in rendered
    assert "ref-2" in rendered
    for marker in ("sk-", "AKIA", "Bearer ", "-----BEGIN", "eyJ", "password="):
        assert marker not in rendered


# ---------------------------------------------------------------------------
# 2. Fail-closed chain
# ---------------------------------------------------------------------------


async def test_fail_closed_unsupported_answer_propagates():
    _, request = await _build_bundle_and_request()
    synthesizer = _CannedSynthesizer("unsupported")

    await _raises(
        UnsupportedSynthesis, lambda: GroundedSynthesisEngine().run(request, synthesizer)
    )


async def test_fail_closed_unfaithful_content_fails_verification():
    result = SynthesisResult(
        request_id="req-unfaithful",
        plan_kind="summarize",
        content="The board approved a dividend payout.",
        citations=(
            EvidenceCitation(
                reference_id="ref-1",
                source="aether.records.financials.q2",
                tenant_id=TENANT,
                excerpt=EVIDENCE_1,
            ),
        ),
        created_at=datetime.now(timezone.utc),
    )

    _raises_sync(VerificationFailure, lambda: _verification_engine().enforce(result))


async def test_fail_closed_leak_detected_and_enforce_raises():
    # model_construct bypasses the synthesis content guard so the sk- marker
    # reaches the verification leak sweep (the marker line is a markdown header,
    # so claim extraction still succeeds and the leak is detected, not thrown
    # out as a claim-extraction failure).
    leaky = SynthesisResult.model_construct(
        request_id="req-leak",
        plan_kind="summarize",
        content="Revenue grew strongly last quarter.\n# api key sk-live-1234",
        citations=(
            EvidenceCitation(
                reference_id="ref-1",
                source="aether.records.financials.q2",
                tenant_id=TENANT,
                excerpt="Revenue grew strongly last quarter.",
            ),
        ),
        created_at=datetime.now(timezone.utc),
    )
    engine = _verification_engine()

    verified = engine.run(leaky)
    assert verified.leak_detected is True
    assert verified.faithful is False

    _raises_sync(VerificationFailure, lambda: engine.enforce(leaky))


# ---------------------------------------------------------------------------
# 3. Evaluation plane — full report + regression gate
# ---------------------------------------------------------------------------


class _FullPlaneEngine:
    """Duck-typed engine running the full plane behind the evaluation runner.

    The runner builds an evidence-less request (``evidence=None``) so the real
    grounding gate would fail closed; this wrapper performs Aether-side
    retrieval itself, grounds the request on the assembled bundle's evidence,
    and runs the real :class:`GroundedSynthesisEngine`.
    """

    def __init__(self, context: ContextService, engine: GroundedSynthesisEngine) -> None:
        self._context = context
        self._engine = engine

    async def run(self, request, synthesizer) -> SynthesisResult:
        bundle = await self._context.build_context(
            tenant_id=request.tenant_id,
            profile_id=request.profile_id,
            query=request.query,
            instructions=request.synthesis_instructions,
        )
        grounded = SynthesisRequest(
            tenant_id=request.tenant_id,
            profile_id=request.profile_id,
            query=request.query,
            plan_kind=request.plan_kind,
            evidence=bundle.evidence,
            synthesis_instructions=request.synthesis_instructions,
            created_at=bundle.created_at,
        )
        return await self._engine.run(grounded, synthesizer)


async def test_evaluation_plane_full_report_and_regression_gate():
    case = EvaluationCase(
        tenant_id=TENANT,
        case_id="case-e2e",
        query=QUERY,
        expected_ground_truth=EXPECTED_GROUND_TRUTH,
        scenario=INSTRUCTIONS,
        allowed_plan_kinds=("summarize",),
    )
    runner = EvaluationRunner(
        engine=_FullPlaneEngine(_context_service(), GroundedSynthesisEngine()),
        scorers=(
            ExactMatchScorer(),
            FaithfulnessScorer(),
            LeakScorer(),
            LatencyScorer(max_seconds=10.0),
        ),
    )

    report = await runner.run_case(case, _EchoSynthesizer())

    assert isinstance(report, EvaluationReport)
    assert report.case_id == "case-e2e"
    assert [score.name for score in report.scores] == [
        "exact-match",
        "faithfulness",
        "leak-scan",
        "latency",
    ]
    # ``passed`` is the conjunction of every score outcome (computed, not fixed).
    assert report.passed == all(score.passed for score in report.scores)
    assert report.passed is True
    assert report.leak_detected is False
    scores = {score.name: score for score in report.scores}
    assert scores["exact-match"].value == 1.0
    assert scores["faithfulness"].value == 1.0
    assert scores["leak-scan"].value == 1.0

    gate = RegressionGate().evaluate([report])
    assert isinstance(gate, GateResult)
    assert gate.passed is True
    assert gate.total_cases == 1
    assert gate.passed_cases == 1
    assert gate.failed_cases == 0
    assert gate.failed_case_ids == ()


# ---------------------------------------------------------------------------
# 4. Pipeline path — HarnessPipeline.run returns PipelineOutput
# ---------------------------------------------------------------------------


async def test_pipeline_path_returns_pipeline_output():
    # pipeline.py lands concurrently from this same commit; skip until present.
    pipeline_mod = pytest.importorskip("services.model_runtime.pipeline")
    HarnessPipeline = pipeline_mod.HarnessPipeline
    PipelineOutput = pipeline_mod.PipelineOutput

    pipeline = HarnessPipeline(context=_context_service())
    output = await pipeline.run(
        tenant_id=TENANT,
        profile_id=PROFILE,
        query=QUERY,
        plan_kind="summarize",
        synthesizer=_EchoSynthesizer(),
        instructions=INSTRUCTIONS,
    )

    assert isinstance(output, PipelineOutput)
    assert isinstance(output.result, SynthesisResult)
    assert [c.reference_id for c in output.result.citations] == ["ref-1", "ref-2"]
    assert isinstance(output.verified, VerificationResult)
    assert output.verified.faithful is True
