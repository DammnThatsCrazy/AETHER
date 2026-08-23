"""Grounded-synthesis engine (ADR-008 D6, Commit 9).

The engine is the provider-neutral heart of the grounded-synthesis answering
path. It runs retrieval-before-synthesis: the grounding gate must pass, the
plan kind must be allowlisted, the bounded prompt is rendered from the
tenant-scoped evidence set, a :class:`Synthesizer` produces the answer text,
and the answer is wrapped in a :class:`SynthesisResult` whose citations are
drawn ONLY from the allowlisted evidence. Aether executes all retrieval and
all model calls; the engine itself never talks to a provider and never adds
new retrieval.

Fail-closed posture (every failure propagates; nothing is sanitized away):

- The grounding gate
  (:class:`~services.model_runtime.synthesis.grounding.GroundingPolicy`)
  rejects missing/stale/out-of-tenant evidence before any synthesis
  (``InsufficientEvidence`` / ``StaleEvidence`` / ``GroundingViolation``).
- The plan allowlist
  (:class:`~services.model_runtime.synthesis.plans.PlanRegistry`) rejects a
  non-allowlisted ``plan_kind`` before the synthesizer is invoked
  (``PlanNotAllowlisted``).
- The prompt builder
  (:class:`~services.model_runtime.context.prompt.GroundedPromptBuilder`)
  rejects injection tokens and credential-shaped text in the rendered prompt
  (``InjectionGuardError`` / ``PromptSizeError``).
- A model answer of ``"unsupported"`` (the prompt's own trailing contract line)
  raises :class:`UnsupportedSynthesis` instead of surfacing ungrounded text.
- Credential-shaped content in the model's answer is rejected when the
  :class:`~services.model_runtime.synthesis.models.SynthesisResult` is
  constructed (``SynthesisUnsafe``) — the engine does not sanitize, it
  propagates.

The engine never fabricates: every citation is built from a
``request.evidence`` item, so a synthesized claim can always be traced back to
retrieved evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from services.model_runtime.context.evidence import ContextBundle
from services.model_runtime.context.prompt import GroundedPromptBuilder
from services.model_runtime.synthesis.grounding import GroundingPolicy
from services.model_runtime.synthesis.models import (
    EvidenceCitation,
    SynthesisRequest,
    SynthesisResult,
)
from services.model_runtime.synthesis.plans import PlanRegistry

__all__ = [
    "GroundedSynthesisEngine",
    "Synthesizer",
    "UnsupportedSynthesis",
]


class Synthesizer(Protocol):
    """Provider-neutral synthesis seam.

    Aether executes all model calls through this interface; the engine never
    talks to a provider. An implementation translates the engine's
    provider-neutral prompt into a concrete model call (via the runtime
    adapters) and returns the model's answer text.
    """

    async def synthesize(self, prompt: str, *, plan_kind: str) -> str:
        """Render ``prompt`` through a model and return its answer text."""
        ...


class UnsupportedSynthesis(Exception):
    """The model answered ``'unsupported'`` (no grounded evidence for the query).

    Raised fail-closed: ungrounded output is never surfaced as synthesized
    content.
    """


class GroundedSynthesisEngine:
    """Orchestrate a grounded-synthesis run, failing closed at every gate.

    Dependencies are injectable and default to the canonical implementations:
    the bounded prompt builder, the grounding policy, and the default plan
    registry. The engine adds no retrieval and never talks to a provider.
    """

    def __init__(
        self,
        *,
        prompt_builder: GroundedPromptBuilder | None = None,
        grounding: GroundingPolicy | None = None,
        plans: PlanRegistry | None = None,
    ) -> None:
        self._prompt_builder = (
            prompt_builder if prompt_builder is not None else GroundedPromptBuilder()
        )
        self._grounding = grounding if grounding is not None else GroundingPolicy()
        self._plans = plans if plans is not None else PlanRegistry.default()

    async def run(
        self, request: SynthesisRequest, synthesizer: Synthesizer
    ) -> SynthesisResult:
        """Synthesize grounded content for ``request`` via ``synthesizer``.

        Raises:
            InsufficientEvidence: no evidence set was supplied.
            StaleEvidence: the supplied evidence is outside the freshness bound.
            GroundingViolation: evidence is not scoped to the request tenant.
            PlanNotAllowlisted: ``request.plan_kind`` is not a registered plan.
            InjectionGuardError: the prompt builder found an injection token or
                credential marker in the assembled context.
            PromptSizeError: the rendered prompt exceeds the builder's cap.
            UnsupportedSynthesis: the model answered ``'unsupported'``.
            SynthesisUnsafe: the model's answer carries credential-shaped text.
        """
        # 1. Grounding gate (fail-closed). ``check`` raises the specific
        #    ``InsufficientEvidence`` / ``StaleEvidence`` / ``GroundingViolation``
        #    before any synthesis; ``ready`` is the bool convenience used by
        #    callers that only need to probe the gate.
        self._grounding.check(request)

        # 2. Plan allowlist (fail-closed). An unregistered ``plan_kind`` raises
        #    ``PlanNotAllowlisted`` before the synthesizer is invoked.
        self._plans.require(request.plan_kind)

        # 3. Assemble the tenant-scoped, secret-free context bundle from the
        #    request. ``request.evidence`` is a non-empty ``EvidenceSet`` here
        #    because the grounding gate already rejected ``None``/empty sets.
        bundle = ContextBundle(
            tenant_id=request.tenant_id,
            profile_id=request.profile_id,
            query=request.query,
            evidence=request.evidence,
            synthesis_instructions=request.synthesis_instructions,
            created_at=request.created_at,
        )

        # 4. Render the bounded, injection-guarded prompt.
        prompt = self._prompt_builder.build(bundle)

        # 5. Invoke the provider-neutral synthesizer. Aether executes the call.
        content = await synthesizer.synthesize(prompt, plan_kind=request.plan_kind)

        # 6. Fail closed on the model's own ``'unsupported'`` answer (the
        #    prompt's trailing contract line): ungrounded output never becomes
        #    a result.
        if content.strip().lower() == "unsupported":
            raise UnsupportedSynthesis(
                "synthesis failed closed: model answered 'unsupported'"
            )

        # 7. Build the result. Citations come ONLY from the request's evidence
        #    items (no new retrieval, no fabrication). Credential-shaped content
        #    in the model's answer raises ``SynthesisUnsafe`` on construction.
        citations = tuple(
            EvidenceCitation(
                reference_id=item.reference_id,
                source=item.source,
                tenant_id=item.tenant_id,
                excerpt=item.content,
            )
            for item in request.evidence.items
        )
        return SynthesisResult(
            request_id=uuid.uuid4().hex,
            plan_kind=request.plan_kind,
            content=content,
            citations=citations,
            created_at=datetime.now(timezone.utc),
        )
