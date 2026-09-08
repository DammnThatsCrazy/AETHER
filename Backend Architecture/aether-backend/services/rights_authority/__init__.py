"""Aether — Rights Authority: canonical rights decision / IRRL runtime.

The ``rights_irrl`` spine authority. Composes the existing consent / data-rights /
lifecycle / lineage / storage authorities into durable, tenant-scoped
``RightsDecision`` records and governs generalization, Olympus internal
intelligence, learning/model-training eligibility, disclosure, retention and
revocation — always fail closed (blueprint §1.5 / §13).

Additive only: ``routes.py`` is an optional HTTP router for an integrator to
mount (see its docstring); nothing here is auto-wired into ``main.py``.
"""

from __future__ import annotations

from .consent import default_consent_evaluator
from .contracts import (
    RightsContext,
    RightsDecision,
    RightsDecisionRequest,
    RightsImpact,
    RightsLineage,
)
from .envelope import (
    apply_rights_ref,
    decision_evidence_ref,
    rights_envelope_fields,
)
from .generalization import (
    GeneralizationDecision,
    GeneralizationDeniedError,
    GeneralizationEligibilityContext,
    GeneralizationGateway,
    GeneralizationRequest,
    GeneralizedArtifact,
    TRANSFORMATION_APPLY,
    TRANSFORMATION_REGISTRY,
    generalization_gateway,
)
from .impact import (
    RevocationError,
    RevocationSummary,
    compute_rights_impact,
    list_pending_impacts,
    revocation_pipeline,
)
from .lifecycle import LifecycleResolution, resolve_effective_lifecycle
from .model_governance import (
    TrainingDataManifest,
    assess_model_revocation,
    model_training_eligibility,
    validate_training_manifest,
)
from .model_training import (
    TrainingManifestVerification,
    evaluate_training_manifest,
    verify_training_request,
)
from .olympus import (
    OlympusInternalAuthority,
    OlympusInternalDecision,
    filter_graph_of_graphs_query,
    olympus_internal_authority,
    olympus_purpose_allowlist,
)
from .repositories import (
    rights_decision_repository,
    rights_impact_repository,
    rights_lineage_repository,
)
from .resolver import (
    EffectiveRightsResolver,
    configure_consent_evaluator,
    decision_identity,
    effective_rights_resolver,
    normalize_requested_use,
)
from .retention import (
    RetentionResolution,
    evaluate_retention,
    schedule_retention,
)
from .rollout import (
    RolloutMode,
    configure_rollout,
    current_mode,
    reset_rollout,
)

__all__ = [
    # contracts
    "RightsDecisionRequest",
    "RightsDecision",
    "RightsLineage",
    "RightsContext",
    "RightsImpact",
    # resolver
    "EffectiveRightsResolver",
    "effective_rights_resolver",
    "decision_identity",
    "normalize_requested_use",
    "configure_consent_evaluator",
    # consent seam
    "default_consent_evaluator",
    # envelope / spine propagation seam
    "rights_envelope_fields",
    "decision_evidence_ref",
    "apply_rights_ref",
    # rollout / activation
    "RolloutMode",
    "current_mode",
    "configure_rollout",
    "reset_rollout",
    # retention
    "RetentionResolution",
    "evaluate_retention",
    "schedule_retention",
    # model training
    "TrainingManifestVerification",
    "evaluate_training_manifest",
    "verify_training_request",
    # generalization gateway
    "GeneralizationGateway",
    "generalization_gateway",
    "GeneralizationRequest",
    "GeneralizationEligibilityContext",
    "GeneralizationDecision",
    "GeneralizedArtifact",
    "GeneralizationDeniedError",
    "TRANSFORMATION_REGISTRY",
    "TRANSFORMATION_APPLY",
    # impact / revocation
    "revocation_pipeline",
    "compute_rights_impact",
    "list_pending_impacts",
    "RevocationSummary",
    "RevocationError",
    # lifecycle
    "resolve_effective_lifecycle",
    "LifecycleResolution",
    # model governance
    "TrainingDataManifest",
    "model_training_eligibility",
    "validate_training_manifest",
    "assess_model_revocation",
    # olympus internal
    "OlympusInternalAuthority",
    "olympus_internal_authority",
    "OlympusInternalDecision",
    "olympus_purpose_allowlist",
    "filter_graph_of_graphs_query",
    # repositories
    "rights_decision_repository",
    "rights_lineage_repository",
    "rights_impact_repository",
]
