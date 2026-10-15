"""Projection plan (A8 projection engine).

A :class:`ProjectionPlan` is the scheduled unit of execution: the target
projection plus every reachable hard projection dependency, each as a
:class:`ProjectionPlanNode` ordered dependency-first (a node's dependencies
run before the node). Nodes whose provider is absent are NOT scheduled — they
are reported in ``dependencies_missing`` and the executor degrades the
sections they would have backed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProjectionPlanNode:
    """One projection to run as part of a plan."""

    projection_id: str
    role: str  # "target" | "dependency"
    order: int  # topological execution order (dependencies first)
    lens_id: Optional[str] = None  # the composed lens applied at this node


@dataclass(frozen=True)
class ProjectionPlan:
    """The full scheduled plan for one projection run."""

    target_projection: str
    nodes: tuple[ProjectionPlanNode, ...] = field(default_factory=tuple)
    dependencies_missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def target_node(self) -> Optional[ProjectionPlanNode]:
        for node in self.nodes:
            if node.role == "target":
                return node
        return None

    @property
    def dependency_ids(self) -> tuple[str, ...]:
        return tuple(node.projection_id for node in self.nodes if node.role == "dependency")


__all__ = ["ProjectionPlan", "ProjectionPlanNode"]
