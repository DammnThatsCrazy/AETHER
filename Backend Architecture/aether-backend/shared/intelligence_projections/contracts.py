"""Shared intelligence-projection request/context/result contracts (P0.4).

Python twin of ``packages/shared/intelligence-projection.ts``. A 360 is an
intelligence projection over canonical Aether truth — never a competing system
of record. These models are the stable boundary the projection runtime (P0.5)
and future 360 providers implement against.

Reuse, never redefine: ``ContractModel``, ``EntityRef``, ``EvidenceRef``,
``PageRequest``, ``PageInfo`` and ``TimeRangeFilter`` are the canonical
operational-intelligence primitives imported from
``services/operational_intelligence/models.py`` (single-monolith reuse). The
``SectionState`` / ``ProjectionId`` vocabularies are derived from the generated
registry (``shared/intelligence_projections/generated_registry.py``) so the
typed vocabulary can never drift from the canonical JSON.

Timestamp convention: ``asOf`` / ``generatedAt`` are ISO-8601 UTC strings,
matching the repo's operational-intelligence models (e.g. ``computedAt``).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import Field

# Generated registry vocab — never hand-maintained here (derived below).
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_SECTION_STATES,
)

# Reused canonical primitives (single-monolith reuse — never redefined here).
from services.operational_intelligence.models import (
    ContractModel,
    EntityRef,
    EvidenceRef,
    PageInfo,
    PageRequest,
    TimeRangeFilter,
)

# Deriving a typing.Literal from the generated tuple keeps the vocabulary in
# lockstep with the registry JSON (the TS twin derives the same union from
# `typeof intelligenceProjectionSectionStates[number]`).
SectionState = Literal[tuple(PROJECTION_SECTION_STATES)]
ProjectionId = Literal[tuple(INTELLIGENCE_PROJECTION_IDS)]


class ProjectionRequest(ContractModel):
    """Request to run an intelligence projection over canonical Aether truth."""

    projectionId: ProjectionId
    tenantId: str
    subject: EntityRef
    page: Optional[PageRequest] = None
    timeRange: Optional[TimeRangeFilter] = None
    includeSections: Optional[list[str]] = None
    includeClaims: Optional[bool] = None


class ProjectionDependencyState(ContractModel):
    """Dependency state of a sibling projection this projection depends on."""

    projectionId: ProjectionId
    state: SectionState
    reason: Optional[str] = None


class ProjectionContext(ContractModel):
    """Build-time context the runtime computes for a projection request."""

    projectionId: ProjectionId
    tenantId: str
    registryState: str
    dependencyState: list[ProjectionDependencyState] = Field(default_factory=list)
    asOf: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class ProjectionSection(ContractModel):
    """One rendered section of a projection result."""

    id: str
    state: SectionState
    title: Optional[str] = None
    content: Optional[Any] = None
    warnings: Optional[list[str]] = None


class ClaimEnvelope(ContractModel):
    """One claim a projection makes about its subject, backed by evidence refs."""

    id: str
    kind: str
    subject: EntityRef
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class ProjectionResult(ContractModel):
    """The result of running a projection over canonical Aether truth."""

    projectionId: ProjectionId
    tenantId: str
    contractVersion: str
    sections: list[ProjectionSection] = Field(default_factory=list)
    claims: list[ClaimEnvelope] = Field(default_factory=list)
    dependencyState: list[ProjectionDependencyState] = Field(default_factory=list)
    asOf: Optional[str] = None
    generatedAt: str  # ISO-8601 UTC string (repo timestamp convention)
    page: Optional[PageInfo] = None
    degradedReasons: list[str] = Field(default_factory=list)


__all__ = [
    "ClaimEnvelope",
    "ProjectionContext",
    "ProjectionDependencyState",
    "ProjectionId",
    "ProjectionRequest",
    "ProjectionResult",
    "ProjectionSection",
    "SectionState",
]
