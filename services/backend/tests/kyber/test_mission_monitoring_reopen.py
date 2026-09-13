"""A persistently-diverging monitoring condition reopens the mission.

When a condition's expected state diverges from the mission's live state past
its escalation threshold, ``check_due`` raises one operator signal (an
exception/incident — the reopen path, since a completed objective has no
reopen), marks the condition ``escalated``, and puts the mission back under
``monitoring``. A matching condition never escalates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.kyber.ops.mission_contracts import (
    Mission,
    MissionResult,
    MissionStatus,
    MonitoringCondition,
    VerificationGate,
)
from services.kyber.ops.mission_repository import (
    mission_repository,
    monitoring_condition_repository,
)
from services.kyber.ops.monitoring_service import MonitoringService
from services.kyber.ops.repository import exception_repository

TENANT = "tenant_monitor"


def _past(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


async def _seed_mission(*, status: MissionStatus, objective_id: str) -> Mission:
    mission = Mission(
        tenant_id=TENANT,
        title="watched mission",
        status=status,
        objective_id=objective_id,
        result=MissionResult(verification_id="v"),
        verification_gate=VerificationGate(required=False),
    )
    await mission_repository.save_or_update(mission.model_dump(mode="json"))
    return mission


async def _seed_condition(mission: Mission, *, expected_state: str) -> MonitoringCondition:
    condition = MonitoringCondition(
        mission_id=mission.mission_id,
        tenant_id=TENANT,
        condition_type="mission_status",
        expected_state=expected_state,
        status="passing",
        failure_count=0,
        next_check_at=_past(),  # due
        escalation_policy={"max_failures": 1},
    )
    await monitoring_condition_repository.save_or_update(condition.model_dump(mode="json"))
    return condition


@pytest.mark.asyncio
async def test_diverging_condition_escalates_and_reopens() -> None:
    mission = await _seed_mission(status=MissionStatus.ACTIVE, objective_id="obj_monitor")
    # Expected 'completed' but the mission is live in 'active' -> divergence.
    condition = await _seed_condition(mission, expected_state=MissionStatus.COMPLETED.value)

    summary = await MonitoringService().check_due()

    assert summary["checked"] == 1
    assert summary["failed"] == 1
    assert summary["escalated"] == 1

    conds = await monitoring_condition_repository.list_for_mission(mission.mission_id)
    assert conds and conds[0]["status"] == "escalated"

    reopened = await mission_repository.get(mission.mission_id)
    assert reopened["status"] == MissionStatus.MONITORING.value

    # The reopen path raised an operator exception for this tenant.
    raised = await exception_repository.find_many(filters={"tenant_id": TENANT})
    assert len(raised) >= 1


@pytest.mark.asyncio
async def test_matching_condition_does_not_escalate() -> None:
    mission = await _seed_mission(status=MissionStatus.ACTIVE, objective_id="obj_ok")
    # Expected 'active' and the mission is 'active' -> no divergence.
    condition = await _seed_condition(mission, expected_state=MissionStatus.ACTIVE.value)

    summary = await MonitoringService().check_due()

    assert summary["escalated"] == 0
    conds = await monitoring_condition_repository.list_for_mission(mission.mission_id)
    assert conds and conds[0]["status"] == "passing"
    unchanged = await mission_repository.get(mission.mission_id)
    assert unchanged["status"] == MissionStatus.ACTIVE.value
