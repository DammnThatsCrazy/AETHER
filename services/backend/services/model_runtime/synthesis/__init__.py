"""Grounded-synthesis public API barrel (ADR-008 D6 — Commit 9).

The ``synthesis`` subpackage is the answering path of the provider-neutral
model runtime: Aether retrieves a tenant-scoped, freshness-bounded evidence
set; the grounding gate fails closed on missing/stale/out-of-tenant evidence;
the plan allowlist rejects non-allowlisted proposals; a
:class:`Synthesizer` produces the answer ONLY over that evidence; and the
:class:`SynthesisRenderer` emits bounded, secret-free markdown. This barrel is
the single import surface callers consume.

Ownership (Commit 9, ADR-008 D6):

* ``models`` — secret-free request/result contracts and the citation model
  (:class:`SynthesisRequest`, :class:`SynthesisResult`,
  :class:`EvidenceCitation`, :class:`SynthesisUnsafe`,
  :data:`SYNTHESIS_SECRET_MARKERS`);
* ``plans`` — plan allowlist and proposal model (:class:`PlanProposal`,
  :class:`PlanRegistry`, :class:`PlanNotAllowlisted`, :class:`PlanUnsafe`,
  :data:`ALLOWED_PLAN_KINDS`);
* ``grounding`` — fail-closed D6 gate (:class:`GroundingPolicy`,
  :class:`InsufficientEvidence`, :class:`StaleEvidence`,
  :class:`GroundingViolation`);
* ``engine`` — provider-neutral orchestration (:class:`GroundedSynthesisEngine`,
  :class:`Synthesizer`, :class:`UnsupportedSynthesis`);
* ``renderer`` — grounded markdown rendering (:class:`SynthesisRenderer`,
  :class:`SynthesisRenderError`, :data:`DEFAULT_MAX_OUTPUT_CHARS`);
* ``service`` — the public facade (:class:`SynthesisService`,
  :class:`SynthesisServiceError`).

Security posture: the package never logs content or credentials; every
pipeline failure propagates through the facade as a short, content-free
:class:`SynthesisServiceError` so the answering path fails closed.
"""

from __future__ import annotations

from services.model_runtime.synthesis.engine import (
    GroundedSynthesisEngine,
    Synthesizer,
    UnsupportedSynthesis,
)
from services.model_runtime.synthesis.grounding import (
    GroundingPolicy,
    GroundingViolation,
    InsufficientEvidence,
    StaleEvidence,
)
from services.model_runtime.synthesis.models import (
    SYNTHESIS_SECRET_MARKERS,
    EvidenceCitation,
    SynthesisRequest,
    SynthesisResult,
    SynthesisUnsafe,
)
from services.model_runtime.synthesis.plans import (
    ALLOWED_PLAN_KINDS,
    PlanNotAllowlisted,
    PlanProposal,
    PlanRegistry,
    PlanUnsafe,
)
from services.model_runtime.synthesis.renderer import (
    DEFAULT_MAX_OUTPUT_CHARS,
    SynthesisRenderError,
    SynthesisRenderer,
)
from services.model_runtime.synthesis.service import (
    SynthesisService,
    SynthesisServiceError,
)

__all__ = [
    # synthesis/models.py — secret-free request/result contracts
    "SynthesisUnsafe",
    "EvidenceCitation",
    "SynthesisRequest",
    "SynthesisResult",
    "SYNTHESIS_SECRET_MARKERS",
    # synthesis/plans.py — plan allowlist + proposal model
    "PlanNotAllowlisted",
    "PlanUnsafe",
    "ALLOWED_PLAN_KINDS",
    "PlanProposal",
    "PlanRegistry",
    # synthesis/grounding.py — fail-closed D6 gate
    "InsufficientEvidence",
    "StaleEvidence",
    "GroundingViolation",
    "GroundingPolicy",
    # synthesis/engine.py — provider-neutral orchestration
    "Synthesizer",
    "UnsupportedSynthesis",
    "GroundedSynthesisEngine",
    # synthesis/renderer.py — grounded markdown rendering
    "DEFAULT_MAX_OUTPUT_CHARS",
    "SynthesisRenderError",
    "SynthesisRenderer",
    # synthesis/service.py — the public facade
    "SynthesisService",
    "SynthesisServiceError",
]
