"""HarnessPipeline end-to-end facade tests (ADR-008 — Commit 16, Agent C).

The cross-plane pipeline facade is the ONE callable the provider-neutral harness
exposes end-to-end: context (retrieval-before-synthesis) -> grounded synthesis
-> optional fail-closed verification. A real :class:`ContextService` backed by
a seeded :class:`NoopRetriever` plus a tiny canned :class:`Synthesizer` drive
the full path; every stage failure is asserted to surface as a SHORT,
content-free :class:`HarnessPipelineError` naming the stage.

Plain asserts only: no pytest fixtures/raises/mocks. ``_raises`` /
``_raises_async`` are the only helpers (async variant for the async ``run``),
matching house style.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from services.model_runtime.context.retrieval import (
    NoopRetriever,
    RetrievedRecord,
    ScopedRetriever,
)
from services.model_runtime.context.service import ContextService
from services.model_runtime.pipeline import (
    HarnessPipeline,
    HarnessPipelineError,
    PipelineOutput,
)
from services.model_runtime.synthesis.models import SynthesisResult
from services.model_runtime.verification.models import VerificationResult

_SEEDED_CONTENT = "approved transfer TXN-9001 was settled"
#: The canned answer with the inline citation marker that strict cite-aware
#: verification requires: the ``[ref:r1]`` marker attributes the single claim
#: to the seeded ``r1`` citation so it is checked against (and supported by)
#: that citation rather than rejected as uncited.
_CITED_CONTENT = f"{_SEEDED_CONTENT} [ref:r1]."


def _record(content: str = _SEEDED_CONTENT) -> RetrievedRecord:
    """A tenant-scoped record the default retrieval/grounding gates accept."""
    return RetrievedRecord(
        reference_id="r1",
        source="ledger",
        tenant_id="tenant-a",
        content=content,
        collected_at=datetime.now(timezone.utc),
    )


def _context_service(*records: RetrievedRecord) -> ContextService:
    """A real ContextService over a seeded, server-scoped no-op retriever."""
    return ContextService(retriever=ScopedRetriever(NoopRetriever(list(records))))


class _CannedSynthesizer:
    """Provider-neutral seam fake returning a canned answer text."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.seen_prompts: list[str] = []

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        self.seen_prompts.append(prompt)
        return self._content


def _raises(exc_type: type[Exception], func) -> None:
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


async def _raises_async(exc_type: type[Exception], func) -> None:
    """Assert that ``await func()`` raises exc_type (async pipeline calls)."""
    try:
        await func()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


async def _pipeline_message(
    pipeline: HarnessPipeline,
    *,
    plan_kind: str = "summarize",
    synthesizer: _CannedSynthesizer | None = None,
) -> str:
    """Run a default failing request and return the HarnessPipelineError message."""
    if synthesizer is None:
        synthesizer = _CannedSynthesizer(content=f"{_SEEDED_CONTENT}.")
    try:
        await pipeline.run(
            tenant_id="tenant-a",
            profile_id="profile-1",
            query="recent transfers",
            plan_kind=plan_kind,
            synthesizer=synthesizer,
        )
    except HarnessPipelineError as exc:
        return str(exc)
    except Exception as err:
        raise AssertionError(
            f"expected HarnessPipelineError but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError("expected HarnessPipelineError to be raised")


# ---------------------------------------------------------------------------
# Surface
# ---------------------------------------------------------------------------


def test_module_all_matches_spec():
    import services.model_runtime.pipeline as pipeline_module

    assert pipeline_module.__all__ == [
        "HarnessPipelineError",
        "HarnessPipeline",
        "PipelineOutput",
    ]
    for name in pipeline_module.__all__:
        assert hasattr(pipeline_module, name), name


def test_pipeline_error_hierarchy():
    assert issubclass(HarnessPipelineError, Exception)


def test_pipeline_output_is_frozen():
    output = PipelineOutput(result="r", verified=None)
    _raises(dataclasses.FrozenInstanceError, lambda: setattr(output, "result", "x"))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_returns_grounded_verified_output():
    pipeline = HarnessPipeline(context=_context_service(_record()))
    synthesizer = _CannedSynthesizer(content=_CITED_CONTENT)

    output = await pipeline.run(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="recent transfers",
        synthesizer=synthesizer,
    )

    assert isinstance(output, PipelineOutput)
    assert isinstance(output.result, SynthesisResult)
    assert output.result.plan_kind == "summarize"
    assert output.result.content == _CITED_CONTENT
    assert [citation.reference_id for citation in output.result.citations] == ["r1"]
    assert isinstance(output.verified, VerificationResult)
    assert output.verified.faithful is True
    assert output.verified.leak_detected is False


async def test_happy_path_drives_synthesizer_with_grounded_prompt():
    pipeline = HarnessPipeline(context=_context_service(_record()))
    synthesizer = _CannedSynthesizer(content=_CITED_CONTENT)

    await pipeline.run(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="recent transfers",
        synthesizer=synthesizer,
    )

    assert len(synthesizer.seen_prompts) == 1
    assert "[ref:r1]" in synthesizer.seen_prompts[0]
    assert _SEEDED_CONTENT in synthesizer.seen_prompts[0]


async def test_verify_false_skips_verification():
    pipeline = HarnessPipeline(context=_context_service(_record()))

    output = await pipeline.run(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="recent transfers",
        synthesizer=_CannedSynthesizer(content=f"{_SEEDED_CONTENT}."),
        verify=False,
    )

    assert isinstance(output.result, SynthesisResult)
    assert output.verified is None


# ---------------------------------------------------------------------------
# Fail-closed stages
# ---------------------------------------------------------------------------


async def test_ungrounded_request_fails_closed():
    # No seeded records -> the bundle has empty evidence -> the grounding gate
    # fails closed before any synthesis.
    pipeline = HarnessPipeline(context=_context_service())

    message = await _pipeline_message(pipeline)

    assert "grounding" in message or "context" in message


async def test_non_allowlisted_plan_kind_fails_closed():
    pipeline = HarnessPipeline(context=_context_service(_record()))

    message = await _pipeline_message(pipeline, plan_kind="jump")

    assert "plans" in message


async def test_non_allowlisted_plan_raises_pipeline_error():
    pipeline = HarnessPipeline(context=_context_service(_record()))

    await _raises_async(
        HarnessPipelineError,
        lambda: pipeline.run(
            tenant_id="tenant-a",
            profile_id="profile-1",
            query="recent transfers",
            plan_kind="jump",
            synthesizer=_CannedSynthesizer(content=f"{_SEEDED_CONTENT}."),
        ),
    )


async def test_unsupported_answer_fails_closed():
    pipeline = HarnessPipeline(context=_context_service(_record()))

    message = await _pipeline_message(
        pipeline, synthesizer=_CannedSynthesizer(content="unsupported")
    )

    assert "synthesis" in message


async def test_unfaithful_content_fails_closed_when_verifying():
    # Content shares no significant tokens with the seeded evidence, so the D7
    # verification gate fails closed instead of surfacing an unsupported answer.
    pipeline = HarnessPipeline(context=_context_service(_record()))

    message = await _pipeline_message(
        pipeline, synthesizer=_CannedSynthesizer(content="Marketing spend declined sharply.")
    )

    assert "verification" in message


async def test_error_message_never_leaks_content_or_secrets():
    pipeline = HarnessPipeline(context=_context_service(_record()))

    message = await _pipeline_message(
        pipeline, synthesizer=_CannedSynthesizer(content="the secret is sk-live-12345 active")
    )

    # The secret-shaped answer fails closed in the synthesis stage (SynthesisUnsafe);
    # the surfaced message names only the stage and exception class.
    assert "synthesis" in message
    assert "sk-live-12345" not in message
    assert "sk-" not in message
    assert "approved transfer" not in message


# ---------------------------------------------------------------------------
# compose() convenience
# ---------------------------------------------------------------------------


async def test_compose_returns_callable_forwarding_to_run():
    pipeline = HarnessPipeline(context=_context_service(_record()))
    synthesizer = _CannedSynthesizer(content=_CITED_CONTENT)

    composed = pipeline.compose(synthesizer)
    output = await composed(
        tenant_id="tenant-a", profile_id="profile-1", query="recent transfers"
    )

    assert isinstance(output, PipelineOutput)
    assert isinstance(output.result, SynthesisResult)
    assert output.verified is not None
