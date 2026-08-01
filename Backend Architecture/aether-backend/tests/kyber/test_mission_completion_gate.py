"""The completion gate: `completed` is unreachable while unverified.

A mission may complete only when its verification gate is not required or the
latest decision is ``passed``. Anything else — including a missing or failed
decision — is refused, both by the raising guard and structurally in
``transition`` (which rests the mission in ``verifying``/``awaiting_review``
rather than completing it). This is the mission analogue of the command plane's
``executed_unverified`` discipline: completed must never mean unverified.
"""
from __future__ import annotations

import pytest

from shared.common.common import ForbiddenError

from services.kyber.ops.mission_contracts import (
    Mission,
    MissionResult,
    MissionStatus,
    VerificationGate,
)
from services.kyber.ops.mission_repository import mission_repository
from services.kyber.ops.missions import MissionService

TENANT = "tenant_gate"


def _mission(gate: VerificationGate, *, status: MissionStatus = MissionStatus.MONITORING) -> Mission:
    return Mission(
        tenant_id=TENANT,
        title="gate mission",
        status=status,
        objective_id="obj_gate",
        result=MissionResult(verification_id="ver_1"),
        verification_gate=gate,
    )


async def _save(mission: Mission) -> None:
    await mission_repository.save_or_update(mission.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_assert_refuses_unsatisfied_gate() -> None:
    svc = MissionService()
    for decision in (None, "failed", "inconclusive", "needs_review"):
        with pytest.raises(ForbiddenError):
            svc.assert_verified_before_complete(
                _mission(VerificationGate(required=True, decision=decision))
            )


@pytest.mark.asyncio
async def test_assert_allows_when_gate_satisfied() -> None:
    svc = MissionService()
    # Not required at all.
    svc.assert_verified_before_complete(_mission(VerificationGate(required=False)))
    # Required and passed.
    svc.assert_verified_before_complete(
        _mission(VerificationGate(required=True, decision="passed"))
    )


@pytest.mark.asyncio
async def test_transition_to_completed_rests_when_unverified() -> None:
    svc = MissionService()
    mission = _mission(VerificationGate(required=True, decision="failed"))
    await _save(mission)

    result = await svc.transition(mission.mission_id, MissionStatus.COMPLETED)

    # Structurally forbidden: it comes to rest in verifying, never completes.
    assert result.status == MissionStatus.VERIFYING
    assert result.status != MissionStatus.COMPLETED
    persisted = await mission_repository.get(mission.mission_id)
    assert persisted["status"] == MissionStatus.VERIFYING.value


@pytest.mark.asyncio
async def test_transition_needs_review_rests_in_awaiting_review() -> None:
    svc = MissionService()
    mission = _mission(VerificationGate(required=True, decision="needs_review"))
    await _save(mission)

    result = await svc.transition(mission.mission_id, MissionStatus.COMPLETED)

    assert result.status == MissionStatus.AWAITING_REVIEW
    assert result.status != MissionStatus.COMPLETED


@pytest.mark.asyncio
async def test_transition_completes_once_verified() -> None:
    svc = MissionService()
    mission = _mission(VerificationGate(required=True, decision="passed"))
    await _save(mission)

    result = await svc.transition(mission.mission_id, MissionStatus.COMPLETED)

    assert result.status == MissionStatus.COMPLETED
    persisted = await mission_repository.get(mission.mission_id)
    assert persisted["status"] == MissionStatus.COMPLETED.value
