"""Shared intelligence-projection request/context/result contracts (P0.4).

Python twin of ``packages/shared/intelligence-projection.ts``. A 360 is an
intelligence projection over canonical Aether truth — never a competing system
of record. These models are the stable boundary the projection runtime (P0.5)
and future 360 providers implement against.

Reuse, never redefine: ``ContractModel``, ``EvidenceRef``, ``PageRequest``,
``PageInfo`` and ``TimeRangeFilter`` are the canonical operational-intelligence
primitives imported from ``services/operational_intelligence/models.py``
(single-monolith reuse). The ``SectionState`` / ``ProjectionId`` /
``ProjectionSubjectKind`` / ``ProjectionRegistryState`` vocabularies are derived
from the generated registry (``shared/intelligence_projections/generated_registry.py``)
so the typed vocabulary can never drift from the canonical JSON.

All models inherit :class:`ProjectionContract` (``extra="forbid"``) so a
misspelled field raises instead of silently passing — the canonical primitives
(``ContractModel``) stay tolerant, the projection plane fails closed.

Timestamp convention: ``asOf`` / ``generatedAt`` are ISO-8601 UTC strings,
matching the repo's operational-intelligence models (e.g. ``computedAt``).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ConfigDict, Field

# Generated registry vocab — never hand-maintained here (derived below).
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_IMPLEMENTATION_STATES,
    PROJECTION_SECTION_STATES,
)

# Reused canonical primitives (single-monolith reuse — never redefined here).
from services.operational_intelligence.models import (
    ContractModel,
    EvidenceRef,
    PageInfo,
    PageRequest,
    TimeRangeFilter,
)

# Deriving typing.Literal from the generated tuples keeps the vocabulary in
# lockstep with the registry JSON (the TS twin derives the same unions from
# `typeof intelligenceProjectionSectionStates[number]` & friends).
SectionState = Literal[tuple(PROJECTION_SECTION_STATES)]
ProjectionId = Literal[tuple(INTELLIGENCE_PROJECTION_IDS)]
ProjectionRegistryState = Literal[tuple(PROJECTION_IMPLEMENTATION_STATES)]

# Union of every subject kind any registered projection declares. Distinct from
# EntityKind by design: projections are asked about campaigns, episodes,
# populations, sources, connections, clusters and relationships too.
ProjectionSubjectKind = Literal[
    tuple(
        sorted(
            {
                kind
                for definition in INTELLIGENCE_PROJECTION_DEFINITIONS.values()
                for kind in definition["subjectKinds"]
            }
        )
    )
]


class ProjectionContract(ContractModel):
    """Projection-plane contract base — fails closed on unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ProjectionSubject(ProjectionContract):
    """The subject a projection is asked about.

    ``kind`` is the projection-plane subject vocabulary derived from the
    generated registry — intentionally broader than ``EntityRef.kind``.
    """

    kind: ProjectionSubjectKind
    id: str


class ProjectionRequest(ProjectionContract):
    """Request to run an intelligence projection over canonical Aether truth."""

    projectionId: ProjectionId
    tenantId: str
    subject: ProjectionSubject
    page: Optional[PageRequest] = None
    timeRange: Optional[TimeRangeFilter] = None
    includeSections: Optional[list[str]] = None
    includeClaims: Optional[bool] = None


class ProjectionDependencyState(ProjectionContract):
    """Dependency state of a sibling projection this projection depends on."""

    projectionId: ProjectionId
    state: SectionState
    reason: Optional[str] = None


class ProjectionContext(ProjectionContract):
    """Build-time context the runtime computes for a projection request."""

    projectionId: ProjectionId
    tenantId: str
    registryState: ProjectionRegistryState
    dependencyState: list[ProjectionDependencyState]
    asOf: Optional[str] = None
    warnings: list[str]


class ProjectionSection(ProjectionContract):
    """One rendered section of a projection result."""

    id: str
    state: SectionState
    title: Optional[str] = None
    content: Optional[Any] = None
    warnings: Optional[list[str]] = None


class ClaimEnvelope(ProjectionContract):
    """One claim a projection makes about its subject, backed by evidence refs."""

    id: str
    kind: str
    subject: ProjectionSubject
    evidenceRefs: list[EvidenceRef]
    claims: list[str]
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class ProjectionResult(ProjectionContract):
    """The result of running a projection over canonical Aether truth."""

    projectionId: ProjectionId
    tenantId: str
    contractVersion: str
    sections: list[ProjectionSection]
    claims: list[ClaimEnvelope]
    dependencyState: list[ProjectionDependencyState]
    asOf: Optional[str] = None
    generatedAt: str  # ISO-8601 UTC string (repo timestamp convention)
    page: Optional[PageInfo] = None
    degradedReasons: list[str]


__all__ = [
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
