"""Context operator — ``G @ C`` (A8 projection engine).

The context operator is the pure functional transform that applies a lens set
(and the engine temporal mode) to a request's context, producing a new,
equivalent request — the ``G @ C`` step the composition algebra performs before
execution. It NEVER mutates the caller's request: it returns a fresh
``ProjectionRequest`` each time, and it never widens tenant scope.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.intelligence_projections.contracts import ProjectionRequest
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.temporal_modes import (
    TemporalMode,
    dispatch_temporal_mode,
)


class ContextOperation(enum.Enum):
    """The operations the context operator may apply."""

    SET_TEMPORAL = "set_temporal"  # re-express the engine temporal mode
    SET_SUBJECT = "set_subject"  # rebind the subject (same kind, new id)
    ADD_LENS = "add_lens"  # add an overlay
    REMOVE_LENS = "remove_lens"  # remove an overlay
    SET_PAGE = "set_page"  # set pagination
    SET_SECTIONS = "set_sections"  # restrict rendered sections


@dataclass(frozen=True)
class ContextOperator:
    """Apply ``operation`` with ``params`` to a request, yielding a fresh one."""

    operation: ContextOperation
    params: dict[str, Any] = field(default_factory=dict)

    def apply(
        self,
        request: ProjectionRequest,
        *,
        lens_set: Optional[LensSet] = None,
    ) -> ProjectionRequest:
        """Apply the operator to ``request`` (pure — returns a new request)."""
        tenant_id = request.tenantId  # tenant scope is server-authoritative; never widened

        if self.operation is ContextOperation.SET_TEMPORAL:
            mode = TemporalMode(self.params["temporal_mode"])
            return ProjectionRequest(
                projectionId=request.projectionId,
                tenantId=tenant_id,
                subject=request.subject,
                page=request.page,
                timeRange=request.timeRange,
                includeSections=request.includeSections,
                includeClaims=request.includeClaims,
                lensIds=request.lensIds,
                temporalMode=dispatch_temporal_mode(mode),
            )

        if self.operation is ContextOperation.SET_SUBJECT:
            from shared.intelligence_projections.contracts import ProjectionSubject

            subject = ProjectionSubject(
                kind=request.subject.kind,
                id=self.params["subject_id"],
            )
            return ProjectionRequest(
                projectionId=request.projectionId,
                tenantId=tenant_id,
                subject=subject,
                page=request.page,
                timeRange=request.timeRange,
                includeSections=request.includeSections,
                includeClaims=request.includeClaims,
                lensIds=request.lensIds,
                temporalMode=request.temporalMode,
            )

        if self.operation is ContextOperation.ADD_LENS:
            overlay = self.params["lens_id"]
            base = lens_set.base_lens if lens_set else request.lensIds[0] if request.lensIds else "standard"
            overlays = list(lens_set.overlays if lens_set else (request.lensIds or ())[1:])
            if overlay not in overlays:
                overlays.append(overlay)
            return ProjectionRequest(
                projectionId=request.projectionId,
                tenantId=tenant_id,
                subject=request.subject,
                page=request.page,
                timeRange=request.timeRange,
                includeSections=request.includeSections,
                includeClaims=request.includeClaims,
                lensIds=[base, *overlays],
                temporalMode=request.temporalMode,
            )

        if self.operation is ContextOperation.REMOVE_LENS:
            overlay = self.params["lens_id"]
            base = lens_set.base_lens if lens_set else request.lensIds[0] if request.lensIds else "standard"
            overlays = [
                o
                for o in (lens_set.overlays if lens_set else (request.lensIds or ())[1:])
                if o != overlay
            ]
            return ProjectionRequest(
                projectionId=request.projectionId,
                tenantId=tenant_id,
                subject=request.subject,
                page=request.page,
                timeRange=request.timeRange,
                includeSections=request.includeSections,
                includeClaims=request.includeClaims,
                lensIds=[base, *overlays],
                temporalMode=request.temporalMode,
            )

        if self.operation is ContextOperation.SET_PAGE:
            return ProjectionRequest(
                projectionId=request.projectionId,
                tenantId=tenant_id,
                subject=request.subject,
                page=self.params["page"],
                timeRange=request.timeRange,
                includeSections=request.includeSections,
                includeClaims=request.includeClaims,
                lensIds=request.lensIds,
                temporalMode=request.temporalMode,
            )

        if self.operation is ContextOperation.SET_SECTIONS:
            return ProjectionRequest(
                projectionId=request.projectionId,
                tenantId=tenant_id,
                subject=request.subject,
                page=request.page,
                timeRange=request.timeRange,
                includeSections=list(self.params["sections"]),
                includeClaims=request.includeClaims,
                lensIds=request.lensIds,
                temporalMode=request.temporalMode,
            )

        raise ValueError(f"unknown context operation {self.operation!r}")


__all__ = ["ContextOperation", "ContextOperator"]
