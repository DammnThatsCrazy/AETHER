"""ADR-008 D6 grounded-synthesis context / evidence layer — public API barrel.

The context/evidence layer runs retrieval-before-synthesis: Aether executes all
retrieval, the harness assembles a tenant-scoped, secret-free evidence set, and
the model synthesizes ONLY over that evidence, citing each claim with a
``[ref:<reference_id>]`` marker. This barrel is the single import surface the
grounded-synthesis layer (later commits) consumes.

Ownership (same commit, ADR-008 D6):

* ``evidence`` — frozen, secret-checked data models and bounds
  (:class:`EvidenceItem`, :class:`EvidenceSet`, :class:`ContextBundle`,
  :class:`EvidenceBudget`, :class:`EvidenceUnsafe`, :class:`EvidenceBounds`);
* ``retrieval`` — the Aether-side retrieval seam and server-authoritative scope
  wrapper (:class:`RetrievalSource`, :class:`RetrievedRecord`,
  :class:`ScopedRetriever`, :class:`NoopRetriever`,
  :class:`RetrievalScopeViolation`, :class:`RetrievalBounds`);
* ``builder`` — records -> :class:`ContextBundle` assembly
  (:class:`RetrievalItem`, :class:`ContextBuilder`,
  :class:`ContextScopeViolation`);
* ``assembly`` — wire the retrieval seam into the builder
  (:class:`ContextAssembler`, :func:`assemble_from_records`);
* ``prompt`` — the bounded, injection-guarded synthesis prompt
  (:class:`GroundedPromptBuilder`, :class:`PromptSizeError`,
  :class:`InjectionGuardError`, ``MAX_PROMPT_CHARS``);
* ``service`` — the public facade (:class:`ContextService`).

Security posture: credentials are never placed in evidence, prompts, or logs;
tenant scope is server-authoritative; every context-layer failure propagates
so the pipeline fails closed.
"""

from __future__ import annotations

from services.model_runtime.context.assembly import (
    ContextAssembler,
    assemble_from_records,
)
from services.model_runtime.context.builder import (
    ContextBuilder,
    ContextScopeViolation,
    RetrievalItem,
)
from services.model_runtime.context.evidence import (
    ContextBundle,
    EvidenceBounds,
    EvidenceBudget,
    EvidenceItem,
    EvidenceSet,
    EvidenceUnsafe,
)
from services.model_runtime.context.prompt import (
    GroundedPromptBuilder,
    InjectionGuardError,
    MAX_PROMPT_CHARS,
    PromptSizeError,
)
from services.model_runtime.context.retrieval import (
    NoopRetriever,
    RetrievedRecord,
    RetrievalBounds,
    RetrievalScopeViolation,
    RetrievalSource,
    ScopedRetriever,
)
from services.model_runtime.context.service import ContextService

__all__ = [
    # context/evidence.py — data models, budget, fail-closed exceptions
    "EvidenceItem",
    "EvidenceSet",
    "ContextBundle",
    "EvidenceBudget",
    "EvidenceUnsafe",
    "EvidenceBounds",
    # context/builder.py — records -> ContextBundle assembly
    "RetrievalItem",
    "ContextBuilder",
    "ContextScopeViolation",
    # context/retrieval.py — retrieval seam + tenant-scoped wrapper
    "RetrievalSource",
    "RetrievedRecord",
    "ScopedRetriever",
    "NoopRetriever",
    "RetrievalScopeViolation",
    "RetrievalBounds",
    # context/assembly.py — wire retrieval seam into the builder
    "ContextAssembler",
    "assemble_from_records",
    # context/prompt.py — bounded, injection-guarded synthesis prompt
    "GroundedPromptBuilder",
    "PromptSizeError",
    "InjectionGuardError",
    "MAX_PROMPT_CHARS",
    # context/service.py — the public facade
    "ContextService",
]
