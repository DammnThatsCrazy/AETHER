"""Intelligence Projection plane (P0.4).

A 360 is an intelligence projection over canonical Aether truth — never a
competing system of record. This package holds the shared request / context /
result contracts (Python twin of ``packages/shared/intelligence-projection.ts``),
the typed error hierarchy, the re-exported generated registry constants, and
the hand-written PRESENTATION-ONLY readiness mapping (implementationState is
repo metadata, NOT readiness).

Importable as ``from shared.intelligence_projections import ...``.
"""

from __future__ import annotations

from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    EXPERIENCE_360_FRAME_STATES,
    PRODUCT_360_SURFACE_IDS,
    Experience360ActorAttribution,
    Experience360ActorParty,
    Experience360AuthorityDecision,
    Experience360Delegation,
    Experience360DriverScore,
    Experience360Frame,
    Experience360FrameRequest,
    Experience360FrameSlot,
    Experience360FrameState,
    Experience360Freshness,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    Experience360ProjectionProvenance,
    Experience360Quality,
    Experience360SlotState,
    Experience360SurfaceId,
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionId,
    ProjectionRegistryState,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProjectionSubjectKind,
    SectionState,
)
from shared.intelligence_projections.composition import compose_experience360_frame
from shared.intelligence_projections.errors import (
    ContractVersionIncompatible,
    DependencyUnavailable,
    DuplicateProjection,
    ProjectionError,
    ProjectionNotFound,
    ProjectionNotImplemented,
)
from shared.intelligence_projections.generated_registry import (
    GRAPH_MUTATION_POLICIES,
    PRODUCT_360_SURFACE_CATALOG_VERSION,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTION_IDS,
    PENDING_AUTHORITIES,
    PENDING_REFERENCES,
    PROJECTION_CAPABILITY_MAP,
    PROJECTION_DEPENDENCY_GRAPH,
    PROJECTION_IMPLEMENTATION_STATES,
    PROJECTION_KINDS,
    PROJECTION_SECTION_STATES,
    PROJECTION_SURFACE_MAP,
)
from shared.intelligence_projections import generated_registry as _generated_registry

# Product definitions are emitted by the canonical contract generator. Keep a
# safe empty mapping for checkouts where generation has not yet added the
# product catalog, while the public type contracts remain importable.
PRODUCT_360_SURFACE_DEFINITIONS = getattr(
    _generated_registry, "PRODUCT_360_SURFACE_DEFINITIONS", {}
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.readiness import (
    IMPLEMENTATION_STATE_PRESENTATION,
    PRESENTATION_TOKENS,
    presentation_token,
)
from shared.intelligence_projections.registry import (
    ProviderRegistry,
    projection_registry,
    registry,
)

__all__ = [
    # generated registry
    "GRAPH_MUTATION_POLICIES",
    "PRODUCT_360_SURFACE_CATALOG_VERSION",
    "EXPERIENCE_360_FRAME_STATES",
    "INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION",
    "INTELLIGENCE_PROJECTION_DEFINITIONS",
    "INTELLIGENCE_PROJECTION_IDS",
    "PENDING_AUTHORITIES",
    "PENDING_REFERENCES",
    "PROJECTION_CAPABILITY_MAP",
    "PROJECTION_DEPENDENCY_GRAPH",
    "PROJECTION_IMPLEMENTATION_STATES",
    "PROJECTION_KINDS",
    "PROJECTION_SECTION_STATES",
    "PROJECTION_SURFACE_MAP",
    "PRODUCT_360_SURFACE_DEFINITIONS",
    "PRODUCT_360_SURFACE_IDS",
    # provider protocol
    "IntelligenceProjectionProvider",
    # runtime provider registry
    "ProviderRegistry",
    "projection_registry",
    "registry",
    # capability / readiness join (presentation-only)
    "IMPLEMENTATION_STATE_PRESENTATION",
    "PRESENTATION_TOKENS",
    "presentation_token",
    # errors
    "ContractVersionIncompatible",
    "DependencyUnavailable",
    "DuplicateProjection",
    "ProjectionError",
    "ProjectionNotFound",
    "ProjectionNotImplemented",
    # contracts
    "ClaimEnvelope",
    "compose_experience360_frame",
    "build_experience360_frame",
    "Experience360PolicyEvaluator",
    "Experience360ActorAttribution",
    "Experience360ActorParty",
    "Experience360AuthorityDecision",
    "Experience360Delegation",
    "Experience360DriverScore",
    "Experience360Frame",
    "Experience360FrameRequest",
    "Experience360FrameSlot",
    "Experience360FrameState",
    "Experience360Freshness",
    "Experience360PolicyDisposition",
    "Experience360PolicyEvaluation",
    "Experience360ProjectionProvenance",
    "Experience360Quality",
    "Experience360SlotState",
    "Experience360SurfaceId",
    "ProjectionContext",
    "ProjectionDependencyState",
    "ProjectionId",
    "ProjectionRegistryState",
    "ProjectionRequest",
    "ProjectionResult",
    "ProjectionSection",
    "ProjectionSubject",
    "ProjectionSubjectKind",
    "SectionState",
]


def __getattr__(name: str):
    """Load runtime exports lazily to keep projection-engine imports acyclic.

    The engine imports the projection contract package while it is initializing.
    Eagerly importing ``frame_runtime`` here would re-enter the partially
    initialized engine package. Callers can still import these names from the
    public package barrel once the contract package has loaded.
    """

    if name in {"Experience360PolicyEvaluator", "build_experience360_frame"}:
        from importlib import import_module

        frame_runtime = import_module("shared.intelligence_projections.frame_runtime")
        return getattr(frame_runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
