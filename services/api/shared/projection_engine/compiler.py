"""Projection compiler (A8 projection engine).

:class:`ProjectionCompiler` compiles a ``ProjectionRequest`` + lens set +
engine temporal mode into a :class:`ProjectionIR`. Compilation is the
fail-fast stage: illegal compositions, illegal operator requests and
temporal-mode mismatches surface here as typed :class:`LensConflict` /
``ProjectionError`` findings — before any provider runs.

A lens that cannot honor the requested temporal mode is a recoverable
``TEMPORAL_CONFLICT``: the lens is dropped (degraded) rather than failing the
whole request, and the IR records it in ``incompatible_lenses`` so the
executor can surface the degradation.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.intelligence_projections.contracts import ProjectionRequest
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
)
from shared.projection_engine.conflict import (
    ConflictClass,
    LensConflict,
    LensNotFound,
)
from shared.projection_engine.ir import ProjectionIR
from shared.projection_engine.lens_composition import (
    IncompatibleLens,
    compose_lenses,
)
from shared.projection_engine.lens_registry import LensRegistry
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.operators import OperatorSpec, validate_operators
from shared.projection_engine.temporal_modes import (
    TemporalMode,
    is_simulation_or_playback,
    supported_surface_mode,
)


def _projection_kind(projection_id: str) -> Optional[str]:
    definition = INTELLIGENCE_PROJECTION_DEFINITIONS.get(projection_id)
    if not definition:
        return None
    return definition.get("projectionKind")


class ProjectionCompiler:
    """Compile a request + lens set + temporal mode into a :class:`ProjectionIR`."""

    def __init__(
        self,
        *,
        lens_registry: Optional[LensRegistry] = None,
    ) -> None:
        self._lens_registry = lens_registry or LensRegistry()

    def compile(
        self,
        request: ProjectionRequest,
        *,
        lens_set: Optional[LensSet] = None,
        temporal_mode: Optional[TemporalMode] = None,
        operators: Optional[list[OperatorSpec]] = None,
    ) -> ProjectionIR:
        """Compile one projection run. Raises ``ProjectionError`` on an illegal
        combination (never mutates state, never runs a provider)."""
        set_ = lens_set or LensSet.from_request(
            request.lensIds, registry=self._lens_registry
        )
        mode = temporal_mode or TemporalMode.LIVE

        # 1. Compose the lens set over the request subject kind. Illegal
        #    compositions raise; recoverable conflicts (CAPABILITY_MISSING)
        #    are dropped into ``incompatible``.
        composition = compose_lenses(
            set_,
            subject_kind=request.subject.kind,
            registry=self._lens_registry,
        )
        incompatible = list(composition.incompatible)

        # 2. Temporal-mode fit: drop lenses that cannot honor the requested
        #    mode (TEMPORAL_CONFLICT -> DEGRADE). Simulation/playback modes
        #    require explicit opt-in through the lens set and are never applied
        #    to a measured projection silently.
        compatible_lenses: list[str] = []
        for lens_id in composition.ordered_lens_ids:
            descriptor = self._lens_registry.get(lens_id)
            if not supported_surface_mode(mode, list(descriptor.temporal_modes)):
                incompatible.append(
                    IncompatibleLens(
                        lens_id=lens_id,
                        conflict_class=ConflictClass.TEMPORAL_CONFLICT,
                        reason=(
                            f"lens {lens_id!r} does not support temporal mode "
                            f"{mode.value!r} (dispatches to "
                            f"{_surface(mode)!r})"
                        ),
                    )
                )
            else:
                compatible_lenses.append(lens_id)
        if not compatible_lenses:
            raise LensConflict(
                f"no lens in the set supports temporal mode {mode.value!r}",
                ConflictClass.TEMPORAL_CONFLICT,
            )

        # 3. Operator legality for the target projection kind.
        kind = _projection_kind(request.projectionId)
        op_specs = tuple(operators or ())
        violations = validate_operators(list(op_specs), projection_kind=kind)
        if violations:
            raise LensConflict(
                "; ".join(violations),
                ConflictClass.PARAMETER_CONFLICT,
                projection_id=request.projectionId,
            )

        return ProjectionIR(
            projection_id=request.projectionId,
            tenant_id=request.tenantId,
            subject=request.subject,
            lens_ids=tuple(compatible_lenses),
            temporal_mode=mode,
            operators=op_specs,
            requested_sections=(
                tuple(request.includeSections) if request.includeSections else None
            ),
            requested_claims=bool(request.includeClaims),
            page=request.page,
            time_range=request.timeRange,
            incompatible_lenses=tuple(incompatible),
        )


def _surface(mode: TemporalMode) -> str:
    """Registry-surface mode for a message (import-time safe)."""
    from shared.projection_engine.temporal_modes import dispatch_temporal_mode

    return dispatch_temporal_mode(mode)


__all__ = ["ProjectionCompiler"]
