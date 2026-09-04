"""Projection-surface adapter — the S1 migration seam for 360 surfaces.

Exploration surfaces whose backing plane is an intelligence projection
(outcome360 / economic360 / infrastructure360 / temporal360 / population360 /
geographic360) run through this adapter: it maps one registered exploration
surface to its projection id (here equal by name) and
executes the projection through the S1 engine
(:class:`ProjectionRuntime <shared.projection_engine.runtime.ProjectionRuntime>`
→ :class:`ProjectionExecutor` → the fail-isolated
:class:`ProviderRegistry <shared.intelligence_projections.registry.ProviderRegistry>`)
for the tenant-scoped subject derived from the exploration context.

ADR-010 posture:

* **Fail-isolated** — a missing projection provider, an invalid lens frame, or
  any engine error degrades to a content-free reason
  (``provider_unavailable`` / ``lens_frame_invalid`` / ``projection_failed``);
  the adapter never raises and never echoes a provider diagnostic. The
  content-free reason keys mirror the fabric's session composition
  (``services/exploration/service.py::_compose_projection``).
* **Read-only** — it only ever runs a projection; it has no write path and the
  projection plane never mutates canonical state.
* **Tenant-scoped end to end** — every request carries ``ctx.tenant_id`` (the
  authenticated scope); the adapter derives no tenant of its own.
* **Never fabricates** — a missing provider yields ``populated=False`` with an
  honest degraded payload, never a placeholder row.

The generic adapter is intentionally NOT registered: only the thin per-surface
subclasses for 360 surfaces that previously had no dedicated exploration adapter
(outcome360 / economic360 / infrastructure360 / temporal360 / population360 /
geographic360) join the surface registry, so an already-owned surface
(profile360, campaign360, geo, ...) is never shadowed.
"""

from __future__ import annotations

from typing import Optional

from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionResult,
)
from shared.projection_engine.conflict import LensConflict, LensNotFound
from shared.projection_engine.lens_registry import (
    lens_registry as default_lens_registry,
)
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.runtime import ProjectionRuntime

from services.exploration.adapters.base import (
    AdapterContext,
    AdapterResult,
    AdapterTruncation,
    SurfaceAdapter,
)
from services.exploration.projection_subject import projection_subject_for

# The read plane this adapter honestly reports in AdapterResult.backend.
_BACKEND = "intelligence_projection"

# Content-free degraded reason keys (mirror service.py::_compose_projection so
# the surface data path and the session-composition summary agree).
_REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
_REASON_LENS_FRAME_INVALID = "lens_frame_invalid"
_REASON_PROJECTION_FAILED = "projection_failed"


class ProjectionSurfaceAdapter(SurfaceAdapter):
    """Execute an intelligence projection for one exploration surface.

    Subclasses declare ``surface_id`` (and optionally ``projection_id`` when the
    exploration surface and the projection id differ — here they are equal by
    name). ``execute`` composes any lens frame / temporal mode the exploration
    context carries and reshapes the engine result into the exploration
    ``AdapterResult`` envelope: projection digest, per-section state and the
    engine degradation summary.
    """

    surface_id = ""
    # Optional explicit projection id; defaults to the surface id (the
    # registered 360 surfaces share their name with their projection row).
    projection_id: Optional[str] = None

    def __init__(self, *, runtime: Optional[ProjectionRuntime] = None) -> None:
        # ``runtime`` is injectable so tests can bind a fresh-registry executor;
        # the default is the module-level engine runtime over the global
        # projection_registry (wired at app mount).
        self._runtime = runtime if runtime is not None else ProjectionRuntime()

    @property
    def resolved_projection_id(self) -> str:
        """The intelligence-projection id this surface projects."""
        return self.projection_id or self.surface_id

    # ── Execution ───────────────────────────────────────────────────────────

    async def execute(self, ctx: AdapterContext) -> AdapterResult:
        """Run the surface's intelligence projection for the tenant scope.

        Fail-isolated: an invalid lens frame, a missing provider, or any engine
        error returns a degraded ``AdapterResult`` (``populated=False``,
        content-free reason) — never an exception, never a provider diagnostic.
        """
        surface = self.surface_id
        projection_id = self.resolved_projection_id
        lens_ids = list(ctx.context.lens_set) if ctx.context.lens_set else None
        temporal_mode = ctx.context.temporal_mode

        # Pre-validate the lens frame so an invalid frame degrades to the same
        # content-free reason as the fabric's session composition (the engine's
        # LensSet.from_request would otherwise raise mid-flight).
        if lens_ids:
            try:
                LensSet.from_request(
                    lens_ids, registry=default_lens_registry
                ).validate(default_lens_registry)
            except (LensConflict, LensNotFound):
                return self._degraded_result(
                    surface, projection_id, _REASON_LENS_FRAME_INVALID
                )

        try:
            request = ProjectionRequest(
                projectionId=projection_id,
                tenantId=ctx.tenant_id,
                subject=projection_subject_for(ctx.context),
                lensIds=lens_ids,
                temporalMode=temporal_mode,
            )
            result = await self._runtime.execute_projection(
                request,
                lens_ids=lens_ids,
                temporal_mode=temporal_mode,
            )
        except (LensConflict, LensNotFound):
            return self._degraded_result(
                surface, projection_id, _REASON_LENS_FRAME_INVALID
            )
        except Exception:  # noqa: BLE001 - fail-isolated projection seam
            return self._degraded_result(
                surface, projection_id, _REASON_PROJECTION_FAILED
            )

        # A result with no sections means the target could not be satisfied
        # (no registered provider / a fail-isolated provider). A real projection
        # always renders at least its registered output sections (typed states).
        if not result.sections:
            return self._degraded_result(
                surface, projection_id, _REASON_PROVIDER_UNAVAILABLE
            )
        return self._result_from(result, surface)

    # ── Result shaping ──────────────────────────────────────────────────────

    def _result_from(
        self, result: ProjectionResult, surface: str
    ) -> AdapterResult:
        """Shape an engine result into the exploration adapter envelope."""
        degradation_state = (
            result.degradation.level if result.degradation is not None else None
        )
        return AdapterResult(
            surface=surface,
            backend=_BACKEND,
            data={
                "projectionId": result.projectionId,
                "tenantId": result.tenantId,
                "available": True,
                "digest": result.digest,
                "asOf": result.asOf,
                "lensIds": result.lensIds,
                "temporalMode": result.temporalMode,
                "degradationState": degradation_state,
                "sections": [
                    {"id": s.id, "state": s.state} for s in result.sections
                ],
                "suppressedSections": result.suppressedSections,
                "dependencyState": [
                    {"projectionId": d.projectionId, "state": d.state}
                    for d in result.dependencyState
                ],
            },
            truncation=AdapterTruncation(returned_count=len(result.sections)),
            populated=any(s.state == "available" for s in result.sections),
        )

    def _degraded_result(
        self, surface: str, projection_id: str, reason: str
    ) -> AdapterResult:
        """A content-free degraded adapter result — never an exception."""
        return AdapterResult(
            surface=surface,
            backend=_BACKEND,
            data={
                "projectionId": projection_id,
                "available": False,
                "reason": reason,
                "sections": [],
            },
            truncation=AdapterTruncation(),
            warnings=[reason],
            populated=False,
        )


# ── Registered 360 projection surfaces (previously adapter-less) ────────────

class Outcome360SurfaceAdapter(ProjectionSurfaceAdapter):
    """outcome360 exploration surface → the outcome360 intelligence projection."""

    surface_id = "outcome360"


class Economic360SurfaceAdapter(ProjectionSurfaceAdapter):
    """economic360 exploration surface → the economic360 intelligence projection."""

    surface_id = "economic360"


class Infrastructure360SurfaceAdapter(ProjectionSurfaceAdapter):
    """infrastructure360 exploration surface → the infrastructure360 projection."""

    surface_id = "infrastructure360"


class Temporal360SurfaceAdapter(ProjectionSurfaceAdapter):
    """temporal360 exploration surface → the temporal360 projection.

    The context-360 time leaf (Phase 2): it owns its own ``temporal360``
    surface rather than shadowing ``timeline`` (a non-projection adapter) or
    ``temporal_observatory`` (owned by other work packages).
    """

    surface_id = "temporal360"


class Population360SurfaceAdapter(ProjectionSurfaceAdapter):
    """population360 exploration surface → the population360 projection.

    The context-360 WHO/SET leaf (Phase 3): it owns its own ``population360``
    surface rather than shadowing ``comparison_workbench`` (deferred, no
    adapter) or ``cluster360`` (already owned by ``ClusterSurfaceAdapter`` —
    an already-owned surface is never shadowed).
    """

    surface_id = "population360"


class Geographic360SurfaceAdapter(ProjectionSurfaceAdapter):
    """geographic360 exploration surface → the geographic360 projection.

    The context-360 WHERE leaf (Phase 4): it owns its own ``geographic360``
    surface rather than shadowing ``geo`` (already owned by the graph-plane
    ``GeoSurfaceAdapter`` — an already-owned surface is never shadowed) or
    ``outcome360`` / ``profile360`` geography (owned elsewhere). ``geo`` keeps
    its country-bucket adapter; ``geographic360`` is the projection-depth WHERE
    surface over canonical location facts (precision never exceeds evidence).
    """

    surface_id = "geographic360"


__all__ = [
    "Economic360SurfaceAdapter",
    "Geographic360SurfaceAdapter",
    "Infrastructure360SurfaceAdapter",
    "Outcome360SurfaceAdapter",
    "Population360SurfaceAdapter",
    "ProjectionSurfaceAdapter",
    "Temporal360SurfaceAdapter",
]
