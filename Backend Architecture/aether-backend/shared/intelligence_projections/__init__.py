"""Intelligence Projection plane (P0.4).

A 360 is an intelligence projection over canonical Aether truth — never a
competing system of record. This package holds the shared request / context /
result contracts (Python twin of ``packages/shared/intelligence-projection.ts``),
the typed error hierarchy, and re-exports the generated registry constants.

Importable as ``from shared.intelligence_projections import ...``.
"""

from __future__ import annotations

from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
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

__all__ = [
    # generated registry
    "GRAPH_MUTATION_POLICIES",
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
    # errors
    "ContractVersionIncompatible",
    "DependencyUnavailable",
    "DuplicateProjection",
    "ProjectionError",
    "ProjectionNotFound",
    "ProjectionNotImplemented",
    # contracts
    "ClaimEnvelope",
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
