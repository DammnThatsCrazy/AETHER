"""Risk360 — universal contextual risk-assessment intelligence projection.

Risk360 is an **intelligence-projection convergence package** under the
Intelligence Projection Plane (ADR-010, ``intelligence-projection-registry.json``
row ``risk360``). It evaluates what could be materially harmful, abnormal,
unstable, compromised, deceptive, or uncertain about a subject and why, by
**delegating** to the shipped risk/fraud subsystems — risk overlays,
agent capability-risk, trust vectors, fraud-decision history, comparison
baselines, fraud-network detectors, cluster membership, and economic360
exposure. It **never owns canonical truth**: ``graphMutationPolicy: read_only``,
``ownsCanonicalTruth: false``, ``requiresEvidence: true``.

Phases 3 and 4 of the Risk360/Fraud360 convergence program ship the domain
vocabulary and the read-only projection runtime:

* :mod:`services.risk360.contracts` — the canonical domain contracts
  (``RiskSignal``, ``RiskComponent``/``RiskVector``, ``ExposureAssessment``,
  ``RiskAssessment``, ``RiskAssessmentRun``) that import canonical primitives
  (``EntityRef``, ``EvidenceRef``, ``GraphSnapshotRef``,
  ``shared.contracts_models.epistemic.EpistemicStatus``,
  ``shared.measurement.value_states.ValueState``,
  ``services.economic.economic360_contracts.MonetaryAmount``) and declare **no
  second copy** of any of them.
* :mod:`services.risk360.dimensions` — the versioned ``RiskDimension`` registry
  seeded from the SoT ``RISK_FRAUD_360.md`` §4 24-dimension set, with
  ``ValueState`` honesty semantics (a missing dimension is never a fabricated
  zero).
* :mod:`services.risk360.store` — tenant-scoped JSONB repositories for risk
  signals and risk assessments over ``BaseRepository`` (no Alembic migration).
* :mod:`services.risk360.provider` — the ``Risk360Provider`` implementing the
  ``IntelligenceProjectionProvider`` protocol: a read-only, fail-isolated,
  tenant-scoped projection that degrades honestly (``degraded`` / ``missing`` /
  ``empty``) when the backing store, a dependency, or a backing source is
  unavailable, and never fabricates a risk figure.
* :mod:`services.risk360.routes` — the read-only ``/v1/risk360`` FastAPI router
  (all GET, tenant-scoped, ``risk360.read``-gated).

Phase 5 adds the convergence/evaluation runtime on top of the Phase-3/4 spine:

* :mod:`services.risk360.policies` — the declarative :class:`RiskPolicy`
  registry: dimension weights over ``RISK_DIMENSION_KEYS`` + the canonical
  ``DecisionPolicy`` threshold rows. Thresholds live only there.
* :mod:`services.risk360.signals` — producer→``RiskSignal`` convergence adapters
  (fraud result, fraud-network detectors, device risk, geo enrichment,
  behavioral scan, trust vector) with registered dimensions, honest claim
  states, reused ``EvidenceRef``(s), and no fabricated/uncalibrated scores.
* :mod:`services.risk360.pipeline` — the deterministic evaluation runtime:
  converge → aggregate (``RiskVector``) → project (``RiskPolicy``) → record
  (``RiskAssessment`` + ``RiskAssessmentRun`` with deterministic
  ``context_hash``) → materiality candidate hook.
* :mod:`services.risk360.exposure` — ``ExposureAssessment`` builder from the
  economic360 reader seam + ``revenue_adjustments`` (net of realized reversals).
* :mod:`services.risk360.materiality` — findings-candidate materiality hook.
"""

from __future__ import annotations

from .contracts import (
    ExposureAssessment,
    RiskAssessment,
    RiskAssessmentRun,
    RiskComponent,
    RiskSignal,
    RiskVector,
)
from .dimensions import RISK_DIMENSIONS, RISK_DIMENSION_KEYS, RiskDimension, dimension
from .provider import (
    EXPLORE_CAPABILITY,
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    READ_CAPABILITY,
    RepositoryRiskSourceReader,
    Risk360Provider,
    RiskSourceReader,
    build_projection_request,
    register_provider,
)
from .routes import create_router, router
from .store import RiskAssessmentRepository, RiskSignalRepository

# Phase 5 — convergence + evaluation runtime.
from .exposure import (
    EconomicRecordsReader,
    exposure_from_rollup,
    subject_exposure,
)
from .materiality import materiality_for_assessment
from .pipeline import (
    AssessmentResult,
    aggregate_signals,
    assess_subject,
    assessment_computation_context,
    compute_assessment,
    materiality_candidate,
    scored_dimensions,
)
from .policies import (
    DEFAULT_POLICY_ID,
    RISK_POLICIES,
    RISK_POLICY_IDS,
    RiskPolicy,
    policy,
    weighted_aggregate_score,
)
from .signals import (
    FraudNetworkSignalEvidence,
    KNOWN_PRODUCERS,
    RiskEvidenceBundle,
    adapt_producer_signal,
    signal_from_behavioral_scan,
    signal_from_device_risk,
    signal_from_fraud_result,
    signal_from_geo_lookup,
    signal_from_trust_vector,
    signals_from_evidence_bundle,
    signals_from_fraud_network_evidence,
)

__all__ = [
    # Contracts
    "RiskSignal",
    "RiskComponent",
    "RiskVector",
    "ExposureAssessment",
    "RiskAssessment",
    "RiskAssessmentRun",
    # Dimension registry
    "RiskDimension",
    "RISK_DIMENSIONS",
    "RISK_DIMENSION_KEYS",
    "dimension",
    # Storage
    "RiskSignalRepository",
    "RiskAssessmentRepository",
    # Provider (Phase 4)
    "EXPLORE_CAPABILITY",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "READ_CAPABILITY",
    "RepositoryRiskSourceReader",
    "Risk360Provider",
    "RiskSourceReader",
    "build_projection_request",
    "register_provider",
    # Routes (Phase 4)
    "create_router",
    "router",
    # Policy registry (Phase 5)
    "DEFAULT_POLICY_ID",
    "RISK_POLICIES",
    "RISK_POLICY_IDS",
    "RiskPolicy",
    "policy",
    "weighted_aggregate_score",
    # Producer convergence + evidence bundle (Phase 5)
    "FraudNetworkSignalEvidence",
    "KNOWN_PRODUCERS",
    "RiskEvidenceBundle",
    "adapt_producer_signal",
    "signal_from_behavioral_scan",
    "signal_from_device_risk",
    "signal_from_fraud_result",
    "signal_from_geo_lookup",
    "signal_from_trust_vector",
    "signals_from_evidence_bundle",
    "signals_from_fraud_network_evidence",
    # Evaluation pipeline + exposure + materiality (Phase 5)
    "AssessmentResult",
    "aggregate_signals",
    "assess_subject",
    "assessment_computation_context",
    "compute_assessment",
    "materiality_candidate",
    "scored_dimensions",
    "EconomicRecordsReader",
    "exposure_from_rollup",
    "subject_exposure",
    "materiality_for_assessment",
]
