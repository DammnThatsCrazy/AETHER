from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.agent.routes import (  # noqa: E402
    ControllerHeartbeat,
    DispatchRequest,
    KillSwitchAction,
    ObjectiveAction,
    ObjectiveSubmission,
    ReviewDecision,
    approve_review_batch,
    controller_heartbeat,
    controllers_status,
    dispatch_step,
    get_objective,
    list_objectives,
    list_review_batches,
    submit_objective,
    timeline_events,
    toggle_kill_switch,
)


class FakeTenant:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.permissions = permissions or {"agent:manage", "agent:dispatch", "agent:pause", "agent:approve", "agent:heartbeat", "admin"}

    def require_permission(self, permission: str) -> None:
        assert permission in self.permissions or "admin" in self.permissions

    def require_any_permission(self, *permissions: str) -> None:
        assert any(permission in self.permissions for permission in permissions) or "admin" in self.permissions


class FakeRequest:
    def __init__(self, tenant_id: str):
        self.state = SimpleNamespace(tenant=FakeTenant(tenant_id), request_id=f"req-{tenant_id}")
        self.headers = {}


@pytest.mark.asyncio
async def test_objective_lifecycle_review_and_tenant_isolation():
    tenant_a = FakeRequest("tenant-a")
    tenant_b = FakeRequest("tenant-b")
    response = await submit_objective(ObjectiveSubmission(
        goal="Verify staged enrichment before graph commit",
        payload={
            "secret_token": "do-not-persist",
            "staged_mutations": [{"mutation_class": 3, "operation": "upsert", "target": {"node": "n1"}, "diff": {"api_key": "hidden"}}],
        },
    ), tenant_a)
    objective = response["data"]
    assert objective["status"] == "awaiting_review"
    assert objective["payload"]["secret_token"] == "[redacted]"

    listed = await list_objectives(tenant_a)
    assert listed["data"]["total"] >= 1
    isolated = await list_objectives(tenant_b)
    assert all(row["tenant_id"] == "tenant-b" for row in isolated["data"]["objectives"])

    detail = await get_objective(objective["objective_id"], tenant_a)
    assert detail["data"]["objective"]["objective_id"] == objective["objective_id"]

    paused = await __import__("services.agent.routes", fromlist=["pause_objective"]).pause_objective(objective["objective_id"], ObjectiveAction(reason="operator hold"), tenant_a)
    assert paused["data"]["status"] == "paused"

    run = await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), tenant_a)
    assert run["data"]["queue"] == "default"

    batches = await list_review_batches(tenant_a, status="pending")
    assert batches["data"]["total"] == 1
    batch_id = batches["data"]["batches"][0]["batch_id"]
    decision = await approve_review_batch(batch_id, ReviewDecision(notes="approved by test"), tenant_a)
    assert decision["data"]["status"] == "approved"

    events = await timeline_events(tenant_a, limit=50)
    assert any(event["event_type"] == "mutation.approved" for event in events["data"]["events"])
    assert "hidden" not in str(events)


@pytest.mark.asyncio
async def test_controller_heartbeat_and_kill_switch():
    request = FakeRequest("tenant-control")
    heartbeat = await controller_heartbeat(ControllerHeartbeat(controller="catalyst", status="healthy", queue_depth=4, worker_id="worker-1"), request)
    assert heartbeat["data"]["queue_depth"] == 4
    status = await controllers_status(request)
    assert any(controller["controller"] == "catalyst" and controller["queue_depth"] == 4 for controller in status["data"]["controllers"])

    engaged = await toggle_kill_switch(KillSwitchAction(action="engage", reason="incident"), request)
    assert engaged["data"]["kill_switch"] is True
    released = await toggle_kill_switch(KillSwitchAction(action="release", reason="recovered"), request)
    assert released["data"]["kill_switch"] is False
