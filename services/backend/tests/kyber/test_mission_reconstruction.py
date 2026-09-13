"""MissionService.reconstruct composes the view from every plane.

A mission persists almost nothing; the view is assembled at read time from the
agent runtime (objective/plan/steps/worker runs/events/approvals), the jobs
platform (correlated by command id), the mission's own result (evidence +
verification) and the monitoring conditions. These tests seed those planes and
assert the composition — and that the merged timeline comes back ordered.
"""
from __future__ import annotations

import pytest

from services.agent.runtime_repository import get_agent_runtime_repository
from services.kyber.ops.mission_contracts import (
    Mission,
    MissionResult,
    MissionStatus,
    MonitoringCondition,
    VerificationGate,
    now_iso,
)
from services.kyber.ops.mission_repository import (
    mission_repository,
    monitoring_condition_repository,
)
from services.kyber.ops.missions import MissionService

TENANT = "tenant_recon"


async def _seed_runtime(repo, *, goal: str = "Reconcile the ledger") -> str:
    """Seed an objective (+ its plan + founding event) and return its id."""
    objective = await repo.create_objective(
        tenant_id=TENANT,
        goal=goal,
        objective_type="remediation",
        severity="high",
        priority=1,
        payload={"scope": "ledger"},
        opened_by="op_seed",
        idempotency_key="recon-objective-1",
        request_id="req_seed",
    )
    return objective["objective_id"]


@pytest.mark.asyncio
async def test_reconstruct_composes_every_plane_and_orders_timeline() -> None:
    repo = get_agent_runtime_repository()
    objective_id = await _seed_runtime(repo)

    # Steps for the objective.
    await repo.steps.set(
        "step_1",
        {
            "step_id": "step_1",
            "tenant_id": TENANT,
            "objective_id": objective_id,
            "index": 0,
            "status": "completed",
            "created_at": now_iso(),
        },
    )
    await repo.steps.set(
        "step_2",
        {
            "step_id": "step_2",
            "tenant_id": TENANT,
            "objective_id": objective_id,
            "index": 1,
            "status": "completed",
            "created_at": now_iso(),
        },
    )

    # A worker run against the objective.
    await repo.worker_runs.set(
        "run_1",
        {
            "run_id": "run_1",
            "tenant_id": TENANT,
            "objective_id": objective_id,
            "status": "completed",
            "created_at": now_iso(),
        },
    )

    # A review batch (composed as an approval).
    await repo.review_batches.set(
        "batch_1",
        {
            "batch_id": "batch_1",
            "tenant_id": TENANT,
            "objective_id": objective_id,
            "status": "pending",
            "mutation_ids": [],
            "created_at": now_iso(),
        },
    )

    # A couple of extra agent events (create_objective already appended one).
    await repo.append_event(TENANT, "objective.planned", "discovery", {}, objective_id)
    await repo.append_event(TENANT, "objective.verified", "verification", {}, objective_id)

    # A correlated job for one of the mission's commands.
    command_key = "cmd-correlation-1"
    jobs_seeded = False
    try:
        from repositories.jobs_repo import get_jobs_repository

        await get_jobs_repository().enqueue(
            TENANT,
            "kyber_command",
            {"action": "remediate"},
            correlation_id=command_key,
        )
        jobs_seeded = True
    except Exception:  # pragma: no cover - jobs plane not exercisable locally
        jobs_seeded = False

    # The mission root: tied to the objective, carrying evidence + a passed gate.
    mission = Mission(
        tenant_id=TENANT,
        title="Ledger reconciliation mission",
        status=MissionStatus.MONITORING,
        objective_id=objective_id,
        command_ids=[command_key],
        result=MissionResult(
            summary="reconciled",
            evidence_ids=["ev_1", "ev_2"],
            verification_id="ver_1",
        ),
        verification_gate=VerificationGate(required=True, decision="passed"),
    )
    await mission_repository.save_or_update(mission.model_dump(mode="json"))

    # A monitoring condition that has been checked, so it contributes a
    # timeline entry alongside the agent events.
    condition = MonitoringCondition(
        mission_id=mission.mission_id,
        tenant_id=TENANT,
        condition_type="mission_status",
        expected_state="monitoring",
        status="passing",
        last_checked_at=now_iso(),
        next_check_at=None,
    )
    await monitoring_condition_repository.save_or_update(condition.model_dump(mode="json"))

    # Reconstruct under the mission's own tenant scope.
    view = await MissionService().reconstruct(mission.mission_id, scope_tenant=TENANT)

    # Root.
    assert view.mission.mission_id == mission.mission_id
    assert view.mission.command_ids == [command_key]

    # Agent-runtime slices.
    assert view.objective is not None
    assert view.objective["objective_id"] == objective_id
    assert view.objective["goal"] == "Reconcile the ledger"
    assert view.plan is not None
    assert view.plan["objective_id"] == objective_id
    assert {step["step_id"] for step in view.steps} == {"step_1", "step_2"}
    assert [run["run_id"] for run in view.worker_runs] == ["run_1"]
    assert len(view.approvals) == 1
    assert view.approvals[0]["batch_id"] == "batch_1"

    # Events: at least the founding event plus the two we appended.
    assert len(view.tool_calls) >= 3
    event_types = {event.get("event_type") for event in view.tool_calls}
    assert {"objective.created", "objective.planned", "objective.verified"} <= event_types

    # Evidence + verification come off the mission itself.
    assert view.evidence == ["ev_1", "ev_2"]
    assert view.verification["decision"] == "passed"
    assert view.verification["is_satisfied"] is True
    assert view.verification["verification_id"] == "ver_1"

    # Monitoring conditions.
    assert len(view.monitoring_conditions) == 1
    assert view.monitoring_conditions[0].condition_id == condition.condition_id

    # Jobs correlated by command id (only when the jobs plane was seedable).
    if jobs_seeded:
        assert any(
            str(job.get("correlation_id") or "") == command_key for job in view.jobs
        )

    # Timeline is a merged, time-ordered stream of agent events + condition checks.
    timeline = view.timeline
    assert timeline, "timeline should not be empty"
    ats = [entry["at"] for entry in timeline]
    assert ats == sorted(ats), "timeline must be ordered by timestamp"
    sources = {entry["source"] for entry in timeline}
    assert "kyber.mission.monitor" in sources  # the condition check
    assert any(source != "kyber.mission.monitor" for source in sources)  # agent events


@pytest.mark.asyncio
async def test_reconstruct_degrades_when_runtime_has_nothing() -> None:
    """A mission whose objective has no runtime state still composes a view.

    Composition degrades to empty sections rather than failing: the mission
    root, its evidence and verification are always present even when the agent
    runtime contributes nothing.
    """
    mission = Mission(
        tenant_id=TENANT,
        title="Bare mission",
        status=MissionStatus.DETECTED,
        objective_id="obj_nonexistent",
        result=MissionResult(evidence_ids=["ev_only"], verification_id="ver_x"),
        verification_gate=VerificationGate(required=False),
    )
    await mission_repository.save_or_update(mission.model_dump(mode="json"))

    view = await MissionService().reconstruct(mission.mission_id, scope_tenant=TENANT)

    assert view.mission.mission_id == mission.mission_id
    assert view.objective is None
    assert view.plan is None
    assert view.steps == []
    assert view.worker_runs == []
    assert view.evidence == ["ev_only"]
    assert view.verification["is_satisfied"] is True  # gate not required
    assert view.timeline == []
