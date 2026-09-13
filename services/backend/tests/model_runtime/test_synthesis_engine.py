"""Grounded-synthesis engine tests (ADR-008 D6, Commit 9).

Covers the provider-neutral engine's fail-closed ``run()`` pipeline: the
grounding gate, the plan allowlist, prompt rendering, provider-neutral
synthesis, ``'unsupported'`` rejection, secret-shaped-content propagation, and
evidence-only citations.

Defensive imports: the sibling synthesis modules land concurrently. If any
module (notably ``grounding``) is not on disk yet, ``pytest.importorskip``
skips this module so the suite stays collectable until the full Commit-9 set
is present.

Plain asserts only: ``_raises`` is the single async-aware helper, matching the
house style used by the sibling synthesis tests.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

pytest.importorskip("services.model_runtime.synthesis.grounding")
pytest.importorskip("services.model_runtime.synthesis.models")
pytest.importorskip("services.model_runtime.synthesis.plans")

from services.model_runtime.context.evidence import EvidenceItem, EvidenceSet
from services.model_runtime.synthesis.engine import (
    GroundedSynthesisEngine,
    UnsupportedSynthesis,
)
from services.model_runtime.synthesis.grounding import (
    GroundingViolation,
    InsufficientEvidence,
)
from services.model_runtime.synthesis.models import (
    EvidenceCitation,
    SynthesisRequest,
    SynthesisResult,
    SynthesisUnsafe,
)
from services.model_runtime.synthesis.plans import PlanNotAllowlisted

_NOW = datetime.now(timezone.utc)

_BENIGN_QUERY = "What is the current ledger balance?"
_BENIGN_CONTENT = "The ledger balance is $1,024.50 as of 2026-08-08."


class _CannedSynthesizer:
    """A tiny provider-neutral synthesizer returning a canned string."""

    def __init__(self, content: str) -> None:
        self.content = content
        #: (prompt, plan_kind) tuples recorded per invocation.
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        self.calls.append((prompt, plan_kind))
        return self.content


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


def _evidence_item(reference_id="ref-1", tenant_id="t1"):
    # collected_at is computed at construction so the items stay inside the
    # grounding policy's freshness bound regardless of when the module was
    # imported or how long the suite has been running.
    return EvidenceItem(
        reference_id=reference_id,
        source=f"aether.records.ledger.{reference_id}",
        tenant_id=tenant_id,
        content=_BENIGN_CONTENT,
        collected_at=datetime.now(timezone.utc),
    )


def _evidence_set(items=(), tenant_id="t1"):
    return EvidenceSet(
        tenant_id=tenant_id,
        profile_id="p1",
        query=_BENIGN_QUERY,
        items=items,
        created_at=_NOW,
    )


def _request(evidence=None, plan_kind="summarize", tenant_id="t1"):
    return SynthesisRequest(
        tenant_id=tenant_id,
        profile_id="p1",
        query=_BENIGN_QUERY,
        plan_kind=plan_kind,
        evidence=evidence,
        synthesis_instructions="Answer in one sentence.",
        created_at=_NOW,
    )


def _engine():
    return GroundedSynthesisEngine()


# ---------------------------------------------------------------------------
# Happy path — grounded content, evidence-only citations, request plumbing
# ---------------------------------------------------------------------------


async def test_happy_path_returns_grounded_content_with_evidence_only_citations():
    evidence = _evidence_set(items=(_evidence_item("ref-1"), _evidence_item("ref-2")))
    request = _request(evidence=evidence)
    fake = _CannedSynthesizer(_BENIGN_CONTENT)
    engine = _engine()

    result = await engine.run(request, fake)

    assert isinstance(result, SynthesisResult)
    assert result.content == _BENIGN_CONTENT
    # plan_kind carried through to the result and to the synthesizer call.
    assert result.plan_kind == "summarize"
    assert len(fake.calls) == 1
    prompt, plan_kind = fake.calls[0]
    assert plan_kind == "summarize"
    # The rendered prompt is the bounded, evidence-only synthesis prompt.
    assert "Synthesize ONLY from the evidence below" in prompt
    assert "[ref:ref-1]" in prompt
    assert "[ref:ref-2]" in prompt
    # Citations are drawn ONLY from the request's evidence items.
    assert len(result.citations) == 2
    assert all(isinstance(c, EvidenceCitation) for c in result.citations)
    assert [c.reference_id for c in result.citations] == ["ref-1", "ref-2"]
    assert result.citations[0].tenant_id == "t1"
    assert result.citations[0].source == "aether.records.ledger.ref-1"
    assert result.citations[0].excerpt == _BENIGN_CONTENT
    # request_id is a 32-hex string; created_at is a tz-aware timestamp.
    assert re.fullmatch(r"[0-9a-f]{32}", result.request_id) is not None
    assert result.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Fail-closed: model answers 'unsupported'
# ---------------------------------------------------------------------------


async def test_unsupported_answer_fails_closed():
    evidence = _evidence_set(items=(_evidence_item(),))
    request = _request(evidence=evidence)
    fake = _CannedSynthesizer("  Unsupported  ")  # case/whitespace-insensitive
    engine = _engine()

    await _raises(UnsupportedSynthesis, lambda: engine.run(request, fake))
    # The model was consulted; its 'unsupported' answer was rejected.
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Fail-closed: plan allowlist enforced before the synthesizer is invoked
# ---------------------------------------------------------------------------


async def test_non_allowlisted_plan_fails_closed_before_synthesizer():
    evidence = _evidence_set(items=(_evidence_item(),))
    request = _request(evidence=evidence, plan_kind="shadow_ban")
    fake = _CannedSynthesizer("should never be produced")
    engine = _engine()

    await _raises(PlanNotAllowlisted, lambda: engine.run(request, fake))
    assert fake.calls == []  # synthesizer NOT invoked


# ---------------------------------------------------------------------------
# Fail-closed: grounding gate (no/None evidence, tenant mismatch)
# ---------------------------------------------------------------------------


async def test_none_evidence_fails_closed_insufficient_evidence():
    request = _request(evidence=None)
    fake = _CannedSynthesizer("should never be produced")
    engine = _engine()

    await _raises(InsufficientEvidence, lambda: engine.run(request, fake))
    assert fake.calls == []  # synthesizer NOT invoked


async def test_empty_evidence_fails_closed_insufficient_evidence():
    request = _request(evidence=_evidence_set(items=()))
    fake = _CannedSynthesizer("should never be produced")
    engine = _engine()

    await _raises(InsufficientEvidence, lambda: engine.run(request, fake))
    assert fake.calls == []  # synthesizer NOT invoked


async def test_tenant_mismatch_fails_closed_grounding_violation():
    evidence = _evidence_set(items=(_evidence_item("ref-x", tenant_id="other"),), tenant_id="other")
    request = _request(evidence=evidence, tenant_id="t1")
    fake = _CannedSynthesizer("should never be produced")
    engine = _engine()

    await _raises(GroundingViolation, lambda: engine.run(request, fake))
    assert fake.calls == []  # synthesizer NOT invoked


# ---------------------------------------------------------------------------
# Fail-closed: credential-shaped content propagates (engine does not sanitize)
# ---------------------------------------------------------------------------


async def test_secret_shaped_content_propagates_synthesis_unsafe():
    evidence = _evidence_set(items=(_evidence_item(),))
    request = _request(evidence=evidence)
    fake = _CannedSynthesizer("the api key is sk-ant-12345")
    engine = _engine()

    await _raises(SynthesisUnsafe, lambda: engine.run(request, fake))
    # The model was consulted; its secret-shaped answer was rejected on result
    # construction (SynthesisUnsafe from sibling A's validator) and propagated.
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


def test_engine_module_exports_complete():
    import services.model_runtime.synthesis.engine as engine_module

    expected = {"Synthesizer", "UnsupportedSynthesis", "GroundedSynthesisEngine"}
    assert set(engine_module.__all__) == expected
    for name in expected:
        assert hasattr(engine_module, name), name
