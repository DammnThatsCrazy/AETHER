"""Projection planner (A8 projection engine).

:class:`ProjectionPlanner` turns a compiled :class:`ProjectionIR` into a
:class:`ProjectionPlan` by walking the projection registry's dependency DAG
(from ``generated_registry.PROJECTION_DEPENDENCY_GRAPH``) and scheduling every
reachable HARD projection dependency, dependencies before dependents.

A dependency with no registered provider is never scheduled — it is recorded in
``dependencies_missing`` and the executor degrades the sections it would back.
The plan never runs a provider that is not registered (fail-closed), and never
re-orders a dependency after its dependents (topological order).
"""

from __future__ import annotations

from typing import Optional

from shared.intelligence_projections.generated_registry import (
    PROJECTION_DEPENDENCY_GRAPH,
)
from shared.projection_engine.ir import ProjectionIR
from shared.projection_engine.plan import ProjectionPlan, ProjectionPlanNode


class ProjectionPlanner:
    """Schedule a compiled IR into a dependency-first projection plan."""

    def __init__(
        self,
        *,
        dependency_graph: Optional[dict] = None,
    ) -> None:
        self._graph = dependency_graph or PROJECTION_DEPENDENCY_GRAPH

    def plan(
        self,
        ir: ProjectionIR,
        *,
        available_ids: set[str],
    ) -> ProjectionPlan:
        """Plan the IR. ``available_ids`` is the set of projection ids with a
        registered provider (ProviderRegistry.list ids). Raises nothing for a
        missing target — the executor degrades it.
        """
        reachable = self._reachable(ir.projection_id)
        if ir.projection_id not in available_ids:
            # A missing target degrades — schedule nothing (running its
            # dependencies without the target is wasted work). The reachable
            # hard deps are still reported so the executor can name them.
            missing = sorted(reachable - available_ids - {ir.projection_id})
            return ProjectionPlan(
                target_projection=ir.projection_id,
                nodes=(),
                dependencies_missing=tuple(missing),
            )
        missing = sorted(reachable - available_ids - {ir.projection_id})
        scheduled = sorted(reachable & available_ids)
        ordered = self._topological(scheduled, ir.projection_id)

        nodes: list[ProjectionPlanNode] = []
        for order, projection_id in enumerate(ordered):
            nodes.append(
                ProjectionPlanNode(
                    projection_id=projection_id,
                    role="target" if projection_id == ir.projection_id else "dependency",
                    order=order,
                )
            )
        return ProjectionPlan(
            target_projection=ir.projection_id,
            nodes=tuple(nodes),
            dependencies_missing=tuple(missing),
        )

    def _reachable(self, projection_id: str) -> set[str]:
        """Every projection reachable from ``projection_id`` via hard deps."""
        seen: set[str] = set()

        def visit(pid: str) -> None:
            if pid in seen:
                return
            seen.add(pid)
            for dep in self._graph.get(pid, {}).get("required", ()):
                visit(dep)

        visit(projection_id)
        return seen

    def _topological(self, projection_ids: set[str], target: str) -> list[str]:
        """Dependency-first topological order (deterministic by id tiebreak)."""
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(pid: str) -> None:
            if pid in visited:
                return
            visited.add(pid)
            for dep in sorted(
                self._graph.get(pid, {}).get("required", ())
            ):
                if dep in projection_ids:
                    visit(dep)
            ordered.append(pid)

        for pid in sorted(projection_ids):
            visit(pid)
        # The target must always be LAST (its dependents before it) — a
        # topological order already guarantees this when the graph is a DAG.
        return ordered


__all__ = ["ProjectionPlanner"]
