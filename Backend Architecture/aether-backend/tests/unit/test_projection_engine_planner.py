"""Projection-engine planner tests (A8): dependency-DAG scheduling.

The planner walks the generated projection dependency graph from the target and
schedules every reachable HARD dependency dependency-first. A dependency with
no registered provider is never scheduled — it is reported in
``dependencies_missing`` (fail-closed; the executor degrades).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionRequest,
    ProjectionSubject,
)
from shared.projection_engine.ir import ProjectionIR  # noqa: E402
from shared.projection_engine.planner import ProjectionPlanner  # noqa: E402
from shared.projection_engine.temporal_modes import TemporalMode  # noqa: E402


def _ir(projection_id: str = "economic360") -> ProjectionIR:
    return ProjectionIR(
        projection_id=projection_id,
        tenant_id="tenant-a",
        subject=ProjectionSubject(kind="campaign", id="camp_1"),
        lens_ids=("standard", "economic"),
        temporal_mode=TemporalMode.LIVE,
    )


def test_plan_dependencies_first() -> None:
    """economic360 depends on profile360, relationship360, outcome360 — all
    scheduled before the target (outcome360/relationship360 transitively depend
    on temporal360, so it must be available for the subtree to schedule)."""
    plan = ProjectionPlanner().plan(
        _ir(),
        available_ids={
            "economic360", "profile360", "relationship360", "outcome360", "temporal360",
        },
    )
    ids = [n.projection_id for n in plan.nodes]
    assert ids[-1] == "economic360"
    assert "profile360" in ids and "relationship360" in ids and "outcome360" in ids
    for dep in ("profile360", "relationship360", "outcome360"):
        assert ids.index(dep) < ids.index("economic360")
    assert plan.dependencies_missing == ()


def test_plan_reports_missing_deps() -> None:
    """Deps without a registered provider are reported, never scheduled.

    outcome360 IS scheduled (it has a provider); its own hard dep temporal360
    and economic360's deps profile360/relationship360 have no provider and are
    reported, never run.
    """
    plan = ProjectionPlanner().plan(
        _ir(),
        available_ids={"economic360", "outcome360"},
    )
    node_ids = [n.projection_id for n in plan.nodes]
    assert "outcome360" in node_ids
    assert "profile360" not in node_ids
    assert "relationship360" not in node_ids
    assert "temporal360" not in node_ids
    assert set(plan.dependencies_missing) == {
        "profile360", "relationship360", "temporal360",
    }


def test_plan_target_missing_is_reported_not_raised() -> None:
    """A target with no provider degrades — the planner never raises for it.

    Nothing is scheduled (deps without the target are wasted work), and every
    reachable hard dep is reported so the executor can name it.
    """
    plan = ProjectionPlanner().plan(_ir(), available_ids=set())
    assert set(plan.dependencies_missing) == {
        "outcome360", "profile360", "relationship360", "temporal360",
    }
    assert plan.target_node is None
    assert plan.nodes == ()


def test_plan_is_deterministic() -> None:
    ids = {"economic360", "profile360", "relationship360", "outcome360"}
    a = ProjectionPlanner().plan(_ir(), available_ids=ids)
    b = ProjectionPlanner().plan(_ir(), available_ids=ids)
    assert [n.projection_id for n in a.nodes] == [n.projection_id for n in b.nodes]
