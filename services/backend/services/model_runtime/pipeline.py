"""Cross-plane pipeline facade — context -> grounded synthesis -> verification (ADR-008, Commit 16).

The ONE callable the provider-neutral harness exposes end-to-end. It wires the
context facade (:class:`~services.model_runtime.context.service.ContextService`)
-> the grounded-synthesis facade
(:class:`~services.model_runtime.synthesis.service.SynthesisService`) -> the
fail-closed verification gate
(:class:`~services.model_runtime.verification.service.VerificationService`)
into a single ``run`` call that returns a structured :class:`PipelineOutput`.
Rendering is deliberately downstream: the pipeline returns the structured
``SynthesisResult`` (plus an optional ``VerificationResult``) so evaluation and
routing layers decide how to surface it.

Fail-closed posture:

* Every stage failure is normalized into a SHORT, content-free
  :class:`HarnessPipelineError` whose message names the failing stage and the
  exception class only (``"<stage>: <ShortClassName>"``).
* Content and credentials are NEVER included in the message and NEVER logged.
* Expected failures are mapped to their stage: context-layer guards
  (``ContextScopeViolation`` / ``EvidenceUnsafe`` / ``InjectionGuardError`` /
  ``PromptSizeError``) to ``context``; the grounding gate
  (``InsufficientEvidence`` / ``StaleEvidence`` / ``GroundingViolation``) to
  ``grounding``; the plan allowlist (``PlanNotAllowlisted``) to ``plans``; the
  answer-path guards (``UnsupportedSynthesis`` / ``SynthesisUnsafe``) to
  ``synthesis``; and the verification gate (``VerificationFailure`` /
  ``VerificationError`` / ``VerificationUnsafe``) to ``verification``.
* Because the facades normalize engine failures into service errors, the stage
  for synthesis/verification failures is recovered from the chained
  ``__cause__`` (the original exception is preserved for diagnostics by both
  facades); anything unexpected still fails closed under a stage name.

``compose`` binds a synthesizer into a small callable so evaluation/routing can
pass one object downstream.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import NoReturn

from services.model_runtime.context.builder import ContextScopeViolation
from services.model_runtime.context.evidence import EvidenceUnsafe
from services.model_runtime.context.prompt import InjectionGuardError, PromptSizeError
from services.model_runtime.context.service import ContextService
from services.model_runtime.synthesis.engine import Synthesizer, UnsupportedSynthesis
from services.model_runtime.synthesis.grounding import (
    GroundingViolation,
    InsufficientEvidence,
    StaleEvidence,
)
from services.model_runtime.synthesis.models import SynthesisRequest, SynthesisUnsafe
from services.model_runtime.synthesis.plans import PlanNotAllowlisted
from services.model_runtime.synthesis.service import SynthesisService
from services.model_runtime.verification.models import VerificationUnsafe
from services.model_runtime.verification.service import VerificationService
from services.model_runtime.verification.verifier import (
    VerificationError,
    VerificationFailure,
)

__all__ = ["HarnessPipelineError", "HarnessPipeline", "PipelineOutput"]


class HarnessPipelineError(Exception):
    """A pipeline stage failed closed.

    The message is intentionally SHORT and content-free: it names the failing
    stage and the exception class only, never synthesis/evidence content and
    never credential-shaped material. The underlying exception is preserved as
    ``__cause__`` for diagnostics.
    """


#: Failures belonging to the context stage (retrieval-before-synthesis and the
#: prompt-surface guards). ``InjectionGuardError`` / ``PromptSizeError`` are
#: context-layer guard errors even when raised inside the synthesis engine's
#: prompt build, so they map back to the context stage.
_CONTEXT_FAILURES: tuple[type[Exception], ...] = (
    ContextScopeViolation,
    EvidenceUnsafe,
    InjectionGuardError,
    PromptSizeError,
)

#: Failures belonging to the grounding gate (D6): missing/thin, stale, or
#: cross-tenant evidence before any synthesis.
_GROUNDING_FAILURES: tuple[type[Exception], ...] = (
    InsufficientEvidence,
    StaleEvidence,
    GroundingViolation,
)

#: Failures belonging to the plan allowlist.
_PLANS_FAILURES: tuple[type[Exception], ...] = (PlanNotAllowlisted,)

#: Failures belonging to the answer path (model answer checks).
_SYNTHESIS_FAILURES: tuple[type[Exception], ...] = (
    UnsupportedSynthesis,
    SynthesisUnsafe,
)

#: Failures belonging to the verification gate (D7).
_VERIFICATION_FAILURES: tuple[type[Exception], ...] = (
    VerificationFailure,
    VerificationError,
    VerificationUnsafe,
)

#: Every expected pipeline failure, for resolving the exception class name from
#: a wrapped (chained) service error.
_KNOWN_FAILURES: tuple[type[Exception], ...] = (
    *_CONTEXT_FAILURES,
    *_GROUNDING_FAILURES,
    *_PLANS_FAILURES,
    *_SYNTHESIS_FAILURES,
    *_VERIFICATION_FAILURES,
)


@dataclass(frozen=True)
class PipelineOutput:
    """Structured end-to-end pipeline output.

    ``result`` is the grounded :class:`~services.model_runtime.synthesis.models.SynthesisResult`;
    ``verified`` is the faithful
    :class:`~services.model_runtime.verification.models.VerificationResult`
    when ``verify=True``, else ``None``.
    """

    result: object  # SynthesisResult
    verified: object | None = None  # VerificationResult | None


class ComposedPipeline:
    """Small callable binding a synthesizer to a ``HarnessPipeline.run()`` call.

    A convenience so evaluation/routing can hand one object downstream instead
    of threading the synthesizer alongside every call.
    """

    def __init__(self, pipeline: HarnessPipeline, synthesizer: Synthesizer) -> None:
        self._pipeline = pipeline
        self._synthesizer = synthesizer

    async def __call__(self, **kwargs) -> PipelineOutput:
        return await self._pipeline.run(synthesizer=self._synthesizer, **kwargs)


class HarnessPipeline:
    """End-to-end provider-neutral harness: context -> synthesis -> verification.

    Fail-closed: any stage failure raises :class:`HarnessPipelineError` with a
    SHORT message naming the stage; content and credentials are never included
    in the message and never logged. All three facades are injectable for
    testing; defaults compose the canonical implementations.
    """

    def __init__(
        self,
        *,
        context: ContextService | None = None,
        synthesis: SynthesisService | None = None,
        verification: VerificationService | None = None,
    ) -> None:
        self._context = context if context is not None else ContextService()
        self._synthesis = synthesis if synthesis is not None else SynthesisService()
        self._verification = (
            verification if verification is not None else VerificationService()
        )

    async def run(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        query: str,
        plan_kind: str = "summarize",
        synthesizer: Synthesizer,
        instructions: str = "",
        verify: bool = True,
    ) -> PipelineOutput:
        """Run the end-to-end pipeline and return structured output.

        1. ``bundle = await context.build_context(...)`` — retrieval-before-
           synthesis (fail-closed on scope/secret/bounds).
        2. ``request = SynthesisRequest(...)`` carrying ``bundle.evidence``.
        3. ``result = await synthesis.synthesize(request, synthesizer)`` — the
           grounding gate, plan allowlist, prompt guard, and answer checks.
        4. When ``verify``: ``verified = await verification.enforce(result)`` —
           raises ``VerificationFailure`` when unfaithful/leaking.
        5. Return :class:`PipelineOutput` with the result and verified gate.
        """
        # 1. Context — retrieval-before-synthesis (fail-closed).
        try:
            bundle = await self._context.build_context(
                tenant_id=tenant_id,
                profile_id=profile_id,
                query=query,
                instructions=instructions,
            )
        except Exception as err:
            self._fail("context", err)

        # 2. Request assembly — carry the tenant-scoped evidence into synthesis.
        try:
            request = SynthesisRequest(
                tenant_id=tenant_id,
                profile_id=profile_id,
                query=query,
                plan_kind=plan_kind,
                evidence=bundle.evidence,
                synthesis_instructions=instructions,
            )
        except Exception as err:
            self._fail("context", err)

        # 3. Grounded synthesis — the synthesis facade normalizes every engine
        #    failure; classify the stage from the chained cause.
        try:
            result = await self._synthesis.synthesize(request, synthesizer)
        except Exception as err:
            self._fail(self._synthesis_stage(err), err)

        # 4. Verification — optional fail-closed gate. The verification facade's
        #    ``enforce`` is synchronous; an async implementation is also
        #    supported (provider-neutral), so await only when awaitable.
        verified: object | None = None
        if verify:
            try:
                enforced = self._verification.enforce(result)
                verified = await enforced if inspect.isawaitable(enforced) else enforced
            except Exception as err:
                self._fail("verification", err)

        # 5. Structured output.
        return PipelineOutput(result=result, verified=verified)

    def compose(self, synthesizer: Synthesizer) -> ComposedPipeline:
        """Return a small callable object forwarding to :meth:`run`.

        Binds ``synthesizer`` so callers can pass one object to
        evaluation/routing instead of threading the synthesizer through every
        call.
        """
        return ComposedPipeline(self, synthesizer)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _synthesis_stage(err: Exception) -> str:
        """Map a synthesis-stage failure to its stage name.

        The synthesis facade wraps every engine failure into
        ``SynthesisServiceError`` and chains the original exception via
        ``__cause__``; classify from that cause. Unknown failures fail closed
        under ``synthesis``.
        """
        cause = err.__cause__
        if isinstance(cause, _GROUNDING_FAILURES):
            return "grounding"
        if isinstance(cause, _PLANS_FAILURES):
            return "plans"
        if isinstance(cause, _SYNTHESIS_FAILURES):
            return "synthesis"
        if isinstance(cause, _CONTEXT_FAILURES):
            return "context"
        return "synthesis"

    @staticmethod
    def _fail(stage: str, err: Exception) -> NoReturn:
        """Raise a short, content-free ``HarnessPipelineError`` naming the stage.

        The exception class name is surfaced from the chained ``__cause__``
        when it is a known pipeline failure (so a wrapped service error reads
        ``"grounding: InsufficientEvidence"`` rather than ``SynthesisServiceError``);
        the original message — which could quote content or a credential — is
        never copied into the surfaced string.
        """
        name = type(err).__name__
        cause = err.__cause__
        if cause is not None and isinstance(cause, _KNOWN_FAILURES):
            name = type(cause).__name__
        raise HarnessPipelineError(f"{stage}: {name}") from err
