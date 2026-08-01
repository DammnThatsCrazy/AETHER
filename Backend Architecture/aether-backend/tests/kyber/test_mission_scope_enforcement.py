"""Reconstruct enforces the operator's granted tenant scope (isolation).

A workforce operator may only read a mission for the tenant their durable
access scope was granted for. The comparison is against the granted scope
(``context.scope.tenant_id`` at the route), never a client-asserted tenant —
the same rule the scoped graph gateway rests on. A session with no scope, or a
scope for a different tenant, is denied.
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

TENANT = "tenant_scope_owner"


async def _seed_mission() -> Mission:
    mission = Mission(
        tenant_id=TENANT,
        title="scoped mission",
        status=MissionStatus.ACTIVE,
        objective_id="obj_scope",
        result=MissionResult(verification_id="v"),
        verification_gate=VerificationGate(required=False),
    )
    await mission_repository.save_or_update(mission.model_dump(mode="json"))
    return mission


@pytest.mark.asyncio
async def test_no_scope_is_denied() -> None:
    mission = await _seed_mission()
    with pytest.raises(ForbiddenError):
        await MissionService().reconstruct(mission.mission_id, scope_tenant=None)


@pytest.mark.asyncio
async def test_scope_for_other_tenant_is_denied() -> None:
    mission = await _seed_mission()
    with pytest.raises(ForbiddenError):
        await MissionService().reconstruct(
            mission.mission_id, scope_tenant="tenant_intruder"
        )


@pytest.mark.asyncio
async def test_scope_for_owning_tenant_succeeds() -> None:
    mission = await _seed_mission()
    view = await MissionService().reconstruct(mission.mission_id, scope_tenant=TENANT)
    assert view.mission.mission_id == mission.mission_id
    assert view.mission.tenant_id == TENANT
