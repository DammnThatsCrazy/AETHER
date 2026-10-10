"""Projection runtime facade (A8 projection engine).

:class:`ProjectionRuntime` is the single entry point callers use to run a
projection with the engine's composition: ``compile → plan → execute`` behind
one method. It wires the default compiler / planner / executor over the shared
``projection_registry`` and exposes the engine's temporal-mode and lens-set
helpers so consumers never touch the machinery directly.
"""

from __future__ import annotations

from typing import Optional

from shared.intelligence_projections.contracts import ProjectionRequest, ProjectionResult
from shared.projection_engine.executor import ProjectionExecutor
from shared.projection_engine.lens_registry import lens_registry as default_lens_registry
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.operators import OperatorSpec
from shared.projection_engine.temporal_modes import (
    TemporalMode,
    parse_temporal_mode,
)

# The default engine lens frame: the registry's default base lens, no overlays
# (the identity element of lens composition).
DEFAULT_LENS_SET: LensSet = LensSet(base_lens="standard", overlays=())


class ProjectionRuntime:
    """Compile → plan → execute one projection through the engine."""

    def __init__(self, *, executor: Optional[ProjectionExecutor] = None) -> None:
        self._executor = executor or ProjectionExecutor()

    async def execute_projection(
        self,
        request: ProjectionRequest,
        *,
        lens_ids: Optional[list[str]] = None,
        temporal_mode: Optional[TemporalMode | str] = None,
        operators: Optional[list[OperatorSpec]] = None,
    ) -> ProjectionResult:
        """Run one projection.

        ``lens_ids`` — the lens frame; ``None`` means the default base lens.
        ``temporal_mode`` — an engine :class:`TemporalMode` (or its string
        value); ``None`` means :attr:`TemporalMode.LIVE`.
        """
        mode = temporal_mode
        if isinstance(mode, str):
            mode = parse_temporal_mode(mode) or TemporalMode.LIVE
        lens_set = LensSet.from_request(lens_ids, registry=default_lens_registry)
        return await self._executor.execute(
            request,
            lens_set=lens_set,
            temporal_mode=mode or TemporalMode.LIVE,
            operators=operators,
        )

    # ── Introspection helpers ───────────────────────────────────────────────

    def available_projection_ids(self) -> set[str]:
        """Projection ids with a registered provider (planning input)."""
        return {p.projection_id for p in self._executor._registry.list()}

    @staticmethod
    def parse_temporal_mode(value: Optional[str]) -> Optional[TemporalMode]:
        return parse_temporal_mode(value)

    @staticmethod
    def resolve_lens_ids(lens_ids: Optional[list[str]]) -> tuple[str, ...]:
        return LensSet.from_request(lens_ids, registry=default_lens_registry).lens_ids()


# Module-level singleton shared by the service layer.
runtime = ProjectionRuntime()


__all__ = ["DEFAULT_LENS_SET", "ProjectionRuntime", "runtime"]
