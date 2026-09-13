"""Fraud360 — domain-synthesis convergence package (Phase 4 of Risk/Fraud360).

Fraud360 is a **domain-synthesis** intelligence projection (ADR-010) over the
Unified Intelligence Graph. It is the hypothesis layer that stands between
"a suspicious pattern was detected" (the shipped fraud scoring engine,
``services/fraud``; fraud-network intelligence, ``services/fraud_networks``;
flow-of-funds tracing) and "fraud occurred".

Fraud360 is **read-only** and **never owns canonical truth**
(``graphMutationPolicy: read_only``, ``ownsCanonicalTruth: false``). It reads
canonical Aether facts — evidence, identities, relationships, networks, flows,
risk assessments — and projects typed, evidence-grounded ``FraudHypothesis``
records through the shared Intelligence Projection Plane contracts. It creates
no fraud graph, no identity/evidence/population model, and no outcome ledger.
A hypothesis is never rendered stronger than its underlying ``EpistemicStatus``
permits (the no-silent-escalation rule lives in
``shared/contracts_models/epistemic.py`` and is enforced by the
``FraudHypothesisStateMachine`` in ``services.fraud360.contracts``).

This package ships:

* :mod:`~services.fraud360.contracts` — the fraud-synthesis vocabulary
  (``FraudPattern`` / ``FraudHypothesis`` / ``FraudHypothesisState`` /
  :class:`FraudHypothesisStateMachine`, reusing the canonical ``EpistemicStatus``
  / ``EvidenceRef`` / ``GraphSnapshotRef`` / ``MonetaryAmount`` primitives);
* :mod:`~services.fraud360.patterns` — the Day-1 ``FraudPattern`` registry
  aligned to the shipped network taxonomy;
* :mod:`~services.fraud360.store` — the tenant-scoped JSONB
  ``FraudHypothesisRepository`` (table ``fraud_hypotheses``);
* :mod:`~services.fraud360.provider` — the ``Fraud360Provider`` implementing the
  plane's ``IntelligenceProjectionProvider`` Protocol (read-only, fail-isolated,
  tenant-scoped echo of stored hypothesis state + claim state, with an injectable
  :class:`~services.fraud360.provider.FraudSourceReader` seam);
* :mod:`~services.fraud360.routes` — the read-only ``/v1/fraud360`` FastAPI
  router (all GET, tenant-scoped, ``fraud360.read``-gated).

The full synthesis findings handoff (risk assessments / network clusters / flow
traces / decisions into NEW material hypotheses) is Phase 6.
"""

from services.fraud360.contracts import (  # noqa: F401
    FraudHypothesis,
    FraudHypothesisRun,
    FraudHypothesisState,
    FraudHypothesisStateMachine,
    FraudPattern,
)
from services.fraud360.provider import (  # noqa: F401
    Fraud360Provider,
    FraudSourceReader,
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    RepositoryFraudSourceReader,
    SECTION_DEPENDENCIES,
    register_provider,
)
from services.fraud360.routes import (  # noqa: F401
    EXPLORE_CAPABILITY,
    READ_CAPABILITY,
    create_router,
    router,
)
from services.fraud360.hypotheses import (  # noqa: F401
    FraudEvidenceReader,
    FraudHypothesisEvidence,
    HypothesisGenerationResult,
    PatternMatch,
    RepositoryFraudEvidenceReader,
    SYNTHESIS_DEFINITION_ID,
    SYNTHESIS_DEFINITION_VERSION,
    correct_hypothesis,
    dispute_hypothesis,
    evaluate_pattern,
    generate_hypotheses,
    hypothesis_materiality,
    mark_stale,
    persist_hypotheses,
    supersede_hypothesis,
)
from services.fraud360.downstream import (  # noqa: F401
    DISABLED_ENVELOPE,
    FINDING_TYPE,
    dispose_finding,
    hypothesis_to_finding_candidate,
    material_hypotheses_to_findings,
)

__all__ = [
    "DISABLED_ENVELOPE",
    "EXPLORE_CAPABILITY",
    "FINDING_TYPE",
    "Fraud360Provider",
    "FraudEvidenceReader",
    "FraudHypothesis",
    "FraudHypothesisEvidence",
    "FraudHypothesisRun",
    "FraudHypothesisState",
    "FraudHypothesisStateMachine",
    "FraudPattern",
    "FraudSourceReader",
    "HypothesisGenerationResult",
    "OUTPUT_SECTIONS",
    "PatternMatch",
    "PROJECTION_ID",
    "READ_CAPABILITY",
    "RepositoryFraudEvidenceReader",
    "RepositoryFraudSourceReader",
    "SECTION_DEPENDENCIES",
    "SYNTHESIS_DEFINITION_ID",
    "SYNTHESIS_DEFINITION_VERSION",
    "correct_hypothesis",
    "create_router",
    "dispose_finding",
    "dispute_hypothesis",
    "evaluate_pattern",
    "generate_hypotheses",
    "hypothesis_materiality",
    "hypothesis_to_finding_candidate",
    "mark_stale",
    "material_hypotheses_to_findings",
    "persist_hypotheses",
    "register_provider",
    "router",
    "supersede_hypothesis",
]
