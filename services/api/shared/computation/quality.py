"""Structured, multi-dimensional quality for a computed result.

Quality is never collapsed into one opaque number. A result carries a set of
named quality dimensions, each with its own state, optional score, reason,
evidence, and threshold. A single top-level classification MAY be derived, but
only as the worst of the visible dimensions (worst-wins), reusing the precedence
ordering from ``shared/dimension_state``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.dimension_state import worst_state


class QualityDimensionName(str, Enum):
    COMPLETENESS = "completeness"
    COVERAGE = "coverage"
    FRESHNESS = "freshness"
    VALIDITY = "validity"
    CONSISTENCY = "consistency"
    UNIQUENESS = "uniqueness"
    RECONCILIATION = "reconciliation"
    SAMPLE_SUFFICIENCY = "sample_sufficiency"
    IDENTITY_STABILITY = "identity_stability"
    SOURCE_AVAILABILITY = "source_availability"
    TRUNCATION = "truncation"
    FINALITY = "finality"
    VALUATION_CONFIDENCE = "valuation_confidence"
    ALLOCATION_CONFIDENCE = "allocation_confidence"


# A quality dimension reuses the canonical dimension-state vocabulary so a
# result's quality rolls up with the same worst-wins semantics used everywhere
# else in the platform. ("ready" == this dimension is fine.)
QUALITY_DIMENSION_STATES: tuple[str, ...] = (
    "ready",
    "not_applicable",
    "empty",
    "pending",
    "partial",
    "insufficient_data",
    "stale",
    "suppressed",
    "degraded",
    "error",
)


class QualityDimension(BaseModel):
    """One visible facet of a result's trustworthiness."""

    name: QualityDimensionName
    state: str = "ready"
    score: Optional[float] = None
    reason: Optional[str] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    threshold: Optional[float] = None
    source: Optional[str] = None


class Quality(BaseModel):
    """The full quality picture for a result: many dimensions + a derived rollup."""

    dimensions: list[QualityDimension] = Field(default_factory=list)

    def overall_state(self) -> str:
        """Worst state across all visible dimensions (empty set -> ``ready``)."""
        return worst_state([d.state for d in self.dimensions])

    def dimension(self, name: QualityDimensionName) -> Optional[QualityDimension]:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None

    def with_dimension(
        self,
        name: QualityDimensionName,
        *,
        state: str = "ready",
        score: Optional[float] = None,
        reason: Optional[str] = None,
        evidence: Optional[dict[str, Any]] = None,
        threshold: Optional[float] = None,
        source: Optional[str] = None,
    ) -> "Quality":
        """Return a copy with one dimension added/replaced (immutable-style build)."""
        others = [d for d in self.dimensions if d.name != name]
        others.append(
            QualityDimension(
                name=name,
                state=state,
                score=score,
                reason=reason,
                evidence=evidence or {},
                threshold=threshold,
                source=source,
            )
        )
        return Quality(dimensions=others)


__all__ = [
    "QualityDimensionName",
    "QUALITY_DIMENSION_STATES",
    "QualityDimension",
    "Quality",
]
