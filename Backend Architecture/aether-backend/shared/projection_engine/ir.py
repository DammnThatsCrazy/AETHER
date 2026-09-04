"""Projection intermediate representation (A8 projection engine).

:class:`ProjectionIR` is the immutable, compiled representation of one
projection run: the target projection, the tenant-scoped subject, the composed
lens sequence, the engine temporal mode, the requested operators, and the
requested sections/claims. Compilation produces an IR; planning turns the IR
into a :class:`ProjectionPlan`; execution runs the plan.

The IR reuses the plane's canonical primitives directly — :class:`ProjectionSubject`
from the projection contracts, and :class:`PageRequest` / :class:`TimeRangeFilter`
from ``services/operational_intelligence/models.py``. It never re-declares them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.operational_intelligence.models import PageRequest, TimeRangeFilter
from shared.intelligence_projections.contracts import ProjectionSubject
from shared.projection_engine.operators import OperatorSpec
from shared.projection_engine.temporal_modes import TemporalMode


@dataclass(frozen=True)
class ProjectionIR:
    """The compiled, immutable representation of one projection run."""

    projection_id: str
    tenant_id: str
    subject: ProjectionSubject
    lens_ids: tuple[str, ...]  # composed base+overlays, in application order
    temporal_mode: Optional[TemporalMode]
    operators: tuple[OperatorSpec, ...] = field(default_factory=tuple)
    requested_sections: Optional[tuple[str, ...]] = None
    requested_claims: bool = False
    page: Optional[PageRequest] = None
    time_range: Optional[TimeRangeFilter] = None
    incompatible_lenses: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def base_lens(self) -> str:
        return self.lens_ids[0] if self.lens_ids else "standard"


__all__ = ["ProjectionIR"]
