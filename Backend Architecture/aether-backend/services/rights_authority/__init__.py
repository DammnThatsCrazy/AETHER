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

from .contracts import (
    RightsContext,
    RightsDecision,
    RightsDecisionRequest,
    RightsImpact,
    RightsLineage,
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
    decision_identity,
    effective_rights_resolver,
    normalize_requested_use,
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
