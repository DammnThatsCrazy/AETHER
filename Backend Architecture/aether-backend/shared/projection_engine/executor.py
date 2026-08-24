"""Projection executor (A8 projection engine).

:class:`ProjectionExecutor` runs a compiled, planned projection through the P0
runtime (``ProviderRegistry.project``), inheriting its fail-isolation, and
re-assembles the engine-level result: composed lens ids, dispatched temporal
mode, engine degradation summary, suppressed sections and a deterministic
content digest.

The executor is the FIRST place a provider result is wrapped. It never echoes a
provider diagnostic (degraded results keep content-free ``degradedReasons``)
and it never mutates canonical state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from shared.intelligence_projections.contracts import (
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionResult,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import (
    ProviderRegistry,
    projection_registry,
)
from shared.projection_engine.compiler import ProjectionCompiler
from shared.projection_engine.degradation import summarize_degradation
from shared.projection_engine.digest import compute_projection_digest
from shared.projection_engine.ir import ProjectionIR
from shared.projection_engine.lens_composition import IncompatibleLens
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.operators import OperatorSpec
from shared.projection_engine.plan import ProjectionPlan
from shared.projection_engine.planner import ProjectionPlanner
from shared.projection_engine.temporal_modes import (
    TemporalMode,
    dispatch_temporal_mode,
)

logger = logging.getLogger(__name__)


class ProjectionExecutor:
    """Compile → plan → run one projection through the fail-isolated runtime."""

    def __init__(
        self,
        *,
        registry: Optional[ProviderRegistry] = None,
        compiler: Optional[ProjectionCompiler] = None,
        planner: Optional[ProjectionPlanner] = None,
    ) -> None:
        self._registry = registry or projection_registry
        self._compiler = compiler or ProjectionCompiler()
        self._planner = planner or ProjectionPlanner()

    async def execute(
        self,
        request: ProjectionRequest,
        *,
        lens_set: Optional[LensSet] = None,
        temporal_mode: Optional[TemporalMode] = None,
        operators: Optional[list[OperatorSpec]] = None,
    ) -> ProjectionResult:
        """Run one projection with the engine's composition + degradation.

        Compiles the request (raising on an ILLEGAL combination), plans it
        against the registered providers, runs each scheduled node through the
        fail-isolated runtime, and reassembles the engine-level result. A
        missing target provider yields a fully-degraded result — never an
        exception.
        """
        ir = self._compiler.compile(
            request,
            lens_set=lens_set,
            temporal_mode=temporal_mode,
            operators=operators,
        )
        available_ids = {p.projection_id for p in self._registry.list()}
        plan = self._planner.plan(ir, available_ids=available_ids)

        results: dict[str, ProjectionResult] = {}
        for node in plan.nodes:
            sub_request = self._build_request(ir, node)
            results[node.projection_id] = await self._registry.project(
                node.projection_id, sub_request
            )

        target = results.get(ir.projection_id)
        if target is None:
            return self._fully_degraded(ir, plan, request)

        return self._assemble(ir, plan, target, request, results)

    # ── Node scheduling ─────────────────────────────────────────────────────

    def _build_request(self, ir: ProjectionIR, node) -> ProjectionRequest:
        """Build the sub-request for one plan node.

        Only the TARGET node carries the composed lens ids and the dispatched
        engine temporal mode; dependency nodes run with the same tenant-scoped
        subject but no lens frame (their providers do not consume lenses yet).
        """
        return ProjectionRequest(
            projectionId=node.projection_id,
            tenantId=ir.tenant_id,
            subject=ir.subject,
            page=ir.page,
            timeRange=ir.time_range,
            includeSections=list(ir.requested_sections) if ir.requested_sections else None,
            includeClaims=ir.requested_claims or None,
            lensIds=list(ir.lens_ids) if node.role == "target" else None,
            temporalMode=dispatch_temporal_mode(ir.temporal_mode)
            if node.role == "target"
            else None,
        )

    # ── Result assembly ─────────────────────────────────────────────────────

    def _assemble(
        self,
        ir: ProjectionIR,
        plan: ProjectionPlan,
        target: ProjectionResult,
        request: ProjectionRequest,
        results: dict[str, ProjectionResult],
    ) -> ProjectionResult:
        reasons: list[str] = []
        conflicted_lenses: list[str] = []
        for incompatible in ir.incompatible_lenses:
            if isinstance(incompatible, IncompatibleLens):
                conflicted_lenses.append(incompatible.lens_id)
                reasons.append(incompatible.reason)

        missing_deps = list(plan.dependencies_missing)
        degraded_count = sum(
            1 for s in target.sections if s.state in ("degraded", "missing", "stale")
        )
        suppressed = self._suppressed_sections(ir, target)
        suppression_reason = (
            "lens composition suppressed sections under the requested lens set"
            if suppressed
            else ""
        )
        if suppression_reason:
            reasons.append(suppression_reason)

        # A provider-degraded target already carries content-free reasons —
        # pass them through unchanged.
        degraded_reasons = list(target.degradedReasons)

        degradation = summarize_degradation(
            reasons=reasons + degraded_reasons,
            conflicted_lenses=conflicted_lenses or None,
            missing_dependencies=missing_deps or None,
            suppressed_count=len(suppressed),
            degraded_count=degraded_count,
            total_sections=len(target.sections),
        )

        digest = compute_projection_digest(
            projection_id=ir.projection_id,
            tenant_id=ir.tenant_id,
            subject=_subject_dict(ir.subject),
            as_of=target.asOf,
            sections=[s.model_dump(exclude_none=True) for s in target.sections],
            claims=[c.model_dump(exclude_none=True) for c in target.claims],
            dependency_state=[
                d.model_dump(exclude_none=True) for d in target.dependencyState
            ],
            lens_ids=list(ir.lens_ids),
            temporal_mode=dispatch_temporal_mode(ir.temporal_mode),
        )

        return ProjectionResult(
            projectionId=ir.projection_id,
            tenantId=ir.tenant_id,
            contractVersion=target.contractVersion,
            sections=target.sections,
            claims=target.claims,
            dependencyState=target.dependencyState,
            asOf=target.asOf,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            page=target.page,
            degradedReasons=degraded_reasons,
            digest=digest,
            lensIds=list(ir.lens_ids),
            temporalMode=dispatch_temporal_mode(ir.temporal_mode),
            degradation=degradation,
            suppressedSections=suppressed or None,
        )

    def _suppressed_sections(self, ir: ProjectionIR, target: ProjectionResult) -> list[str]:
        """Sections the composition suppressed (currently: none day-1).

        Composition may drop lenses (CAPABILITY_MISSING / TEMPORAL_CONFLICT)
        but those degrade rather than suppress. A suppression is the
        HARD_CONFLICT / POLICY_CONFLICT resolution; it is surfaced through the
        result's ``suppressedSections`` whenever a future composition applies
        it. This helper keeps the executor's section-surgery in ONE place.
        """
        return []

    def _fully_degraded(
        self,
        ir: ProjectionIR,
        plan: ProjectionPlan,
        request: ProjectionRequest,
    ) -> ProjectionResult:
        """The target has no registered provider — a fully-degraded result."""
        reason = f"no provider registered for target projection {ir.projection_id!r}"
        dependency_state = [
            ProjectionDependencyState(
                projectionId=dep,
                state="missing",
                reason="no provider registered",
            )
            for dep in plan.dependencies_missing
        ]
        degradation = summarize_degradation(
            reasons=[reason],
            conflicted_lenses=[
                l.lens_id for l in ir.incompatible_lenses if isinstance(l, IncompatibleLens)
            ]
            or None,
            missing_dependencies=list(plan.dependencies_missing) or None,
            suppressed_count=0,
            degraded_count=0,
            total_sections=0,
        )
        return ProjectionResult(
            projectionId=ir.projection_id,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=dependency_state,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=[reason],
            digest=None,
            lensIds=list(ir.lens_ids),
            temporalMode=dispatch_temporal_mode(ir.temporal_mode),
            degradation=degradation,
            suppressedSections=None,
        )


def _subject_dict(subject) -> dict:
    return {"kind": subject.kind, "id": subject.id}


__all__ = ["ProjectionExecutor"]
