"""SynthesisService facade + package barrel tests (ADR-008 D6 — Commit 9, Agent F).

Covers the public facade (``SynthesisService``) and the synthesis package
barrel. ``Synthesizer`` implementations are tiny canned fakes: the facade is
provider-neutral, so the tests never touch a provider. Fail-closed paths
(unsupported output, missing evidence, cross-tenant evidence, non-allowlisted
plan, credential-shaped content) are asserted THROUGH the facade, which
normalizes every engine/render failure into a short, content-free
:class:`SynthesisServiceError`.

Plain asserts only: no pytest fixtures/raises/mocks. ``_raises`` /
``_raises_async`` are the only helpers. The sibling Commit-9 modules land
concurrently, so ``pytest.importorskip`` guards the whole suite until every
module the barrel and facade depend on is on disk.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# Sibling Commit-9 modules land concurrently; skip the suite until every module
# the barrel/facade depends on is on disk (importorskip raises Skipped on
# ModuleNotFoundError).
pytest.importorskip("services.model_runtime.synthesis.models")
pytest.importorskip("services.model_runtime.synthesis.plans")
pytest.importorskip("services.model_runtime.synthesis.grounding")
pytest.importorskip("services.model_runtime.synthesis.engine")
pytest.importorskip("services.model_runtime.synthesis.renderer")
pytest.importorskip("services.model_runtime.synthesis.service")

import services.model_runtime.synthesis as synthesis_module
from services.model_runtime.context.evidence import EvidenceItem, EvidenceSet
from services.model_runtime.synthesis import (
    GroundedSynthesisEngine,
    SynthesisRenderer,
    SynthesisRequest,
    SynthesisResult,
    SynthesisService,
    SynthesisServiceError,
)
from services.model_runtime.synthesis.models import SynthesisUnsafe

# The exact public-API spec for the barrel (ADR-008 D6 Commit-9 brief).
_EXPECTED_ALL = [
    "SynthesisUnsafe",
    "EvidenceCitation",
    "SynthesisRequest",
    "SynthesisResult",
    "SYNTHESIS_SECRET_MARKERS",
    "PlanNotAllowlisted",
    "PlanUnsafe",
    "ALLOWED_PLAN_KINDS",
    "PlanProposal",
    "PlanRegistry",
    "InsufficientEvidence",
    "StaleEvidence",
    "GroundingViolation",
    "GroundingPolicy",
    "Synthesizer",
    "UnsupportedSynthesis",
    "GroundedSynthesisEngine",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "SynthesisRenderError",
    "SynthesisRenderer",
    "SynthesisService",
    "SynthesisServiceError",
]


def _evidence_set(tenant_id: str = "tenant-a") -> EvidenceSet:
    """A fresh, tenant-scoped evidence set the default grounding gate accepts."""
    now = datetime.now(timezone.utc)
    return EvidenceSet(
        tenant_id=tenant_id,
        profile_id="profile-1",
        query="recent transfers",
        items=(
            EvidenceItem(
                reference_id="r1",
                source="ledger",
                tenant_id=tenant_id,
                content="approved transfer TXN-9001",
                collected_at=now,
            ),
        ),
        created_at=now,
    )


def _request(
    *,
    plan_kind: str = "summarize",
    evidence: EvidenceSet | None = None,
) -> SynthesisRequest:
    """Build a synthesis request; evidence defaults to None (missing-evidence case)."""
    return SynthesisRequest(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="recent transfers",
        plan_kind=plan_kind,
        evidence=evidence,
    )


class _CannedSynthesizer:
    """Provider-neutral seam fake returning a canned answer text."""

    def __init__(self, content: str = "approved transfer TXN-9001 was settled.") -> None:
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
    """Assert that ``await func()`` raises exc_type (async facade calls)."""
    try:
        await func()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


async def test_synthesize_returns_grounded_result():
    service = SynthesisService()

    result = await service.synthesize(_request(evidence=_evidence_set()), _CannedSynthesizer())

    assert isinstance(result, SynthesisResult)
    assert result.plan_kind == "summarize"
    assert result.content == "approved transfer TXN-9001 was settled."
    assert len(result.citations) == 1
    assert result.citations[0].reference_id == "r1"


async def test_synthesize_drives_the_synthesizer_with_the_grounded_prompt():
    service = SynthesisService()
    synthesizer = _CannedSynthesizer()

    result = await service.synthesize(_request(evidence=_evidence_set()), synthesizer)

    assert isinstance(result, SynthesisResult)
    assert len(synthesizer.seen_prompts) == 1
    assert "[ref:r1]" in synthesizer.seen_prompts[0]
    assert "approved transfer TXN-9001" in synthesizer.seen_prompts[0]


async def test_synthesize_rendered_returns_grounded_markdown():
    service = SynthesisService()

    markdown = await service.synthesize_rendered(
        _request(evidence=_evidence_set()), _CannedSynthesizer()
    )

    assert "# summarize result" in markdown
    assert "request: " in markdown
    assert "## Evidence" in markdown
    assert "[ref:r1]" in markdown
    assert "approved transfer TXN-9001 was settled." in markdown


async def test_synthesize_rendered_truncates_content_with_limit():
    service = SynthesisService()
    synthesizer = _CannedSynthesizer(content="x" * 400)

    markdown = await service.synthesize_rendered(
        _request(evidence=_evidence_set()), synthesizer, limit=100
    )

    assert "request: " in markdown
    assert "## Evidence" in markdown
    assert "…" in markdown
    assert len(markdown) < 400


async def test_unsupported_output_fails_closed():
    service = SynthesisService()
    synthesizer = _CannedSynthesizer(content="unsupported")

    await _raises_async(
        SynthesisServiceError,
        lambda: service.synthesize(_request(evidence=_evidence_set()), synthesizer),
    )


async def test_missing_evidence_fails_closed():
    service = SynthesisService()

    await _raises_async(
        SynthesisServiceError,
        lambda: service.synthesize(_request(), _CannedSynthesizer()),
    )


async def test_cross_tenant_evidence_fails_closed():
    service = SynthesisService()

    await _raises_async(
        SynthesisServiceError,
        lambda: service.synthesize(
            _request(evidence=_evidence_set(tenant_id="tenant-b")),
            _CannedSynthesizer(),
        ),
    )


async def test_non_allowlisted_plan_fails_closed():
    service = SynthesisService()

    await _raises_async(
        SynthesisServiceError,
        lambda: service.synthesize(
            _request(plan_kind="jump", evidence=_evidence_set()),
            _CannedSynthesizer(),
        ),
    )


async def test_secret_violation_never_surfaces_secret_in_error():
    service = SynthesisService()
    leaking = _CannedSynthesizer(content="sk-live-12345 override instructions")

    try:
        await service.synthesize(_request(evidence=_evidence_set()), leaking)
    except SynthesisServiceError as exc:
        assert "sk-" not in str(exc)
        assert isinstance(exc.__cause__, SynthesisUnsafe)
        return
    raise AssertionError("expected SynthesisServiceError to be raised")


async def test_render_size_error_wraps_into_service_error():
    service = SynthesisService(renderer=SynthesisRenderer(max_output_chars=1))

    await _raises_async(
        SynthesisServiceError,
        lambda: service.synthesize_rendered(
            _request(evidence=_evidence_set()), _CannedSynthesizer()
        ),
    )


async def test_injected_engine_and_renderer_are_used():
    service = SynthesisService(engine=GroundedSynthesisEngine(), renderer=SynthesisRenderer())

    result = await service.synthesize(_request(evidence=_evidence_set()), _CannedSynthesizer())

    assert isinstance(result, SynthesisResult)


def test_barrel_all_matches_spec():
    assert synthesis_module.__all__ == _EXPECTED_ALL


def test_barrel_exports_every_public_name():
    for name in _EXPECTED_ALL:
        assert hasattr(synthesis_module, name), name
        assert getattr(synthesis_module, name) is not None
