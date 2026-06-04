from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import BadRequestError, ConflictError  # noqa: E402
from services.agent.routes import (  # noqa: E402
    ControllerHeartbeat,
    DispatchRequest,
    KillSwitchAction,
    ObjectiveAction,
    ObjectiveSubmission,
    ReviewDecision,
    agent_status,
    approve_review_batch,
    cancel_objective,
    controller_health,
    controller_heartbeat,
    controllers_status,
    dispatch_step,
    get_objective,
    list_objectives,
    list_review_batches,
    pause_objective,
    reject_review_batch,
    resume_objective,
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

    # An objective still in awaiting_review is not runnable — dispatch must not
    # bypass the human review gate.
    with pytest.raises(ConflictError):
        await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), tenant_a)

    paused = await pause_objective(objective["objective_id"], ObjectiveAction(reason="operator hold"), tenant_a)
    assert paused["data"]["status"] == "paused"
    # The operator's reason must be preserved on the timeline event.
    pause_events = await timeline_events(tenant_a, objective_id=objective["objective_id"], limit=50)
    assert any(
        e["event_type"] == "objective.paused" and e.get("payload", {}).get("reason") == "operator hold"
        for e in pause_events["data"]["events"]
    )

    # Dispatching a paused objective must be rejected, not silently revived.
    with pytest.raises(ConflictError):
        await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), tenant_a)

    # Resume (only valid from paused), then dispatch the now-active objective.
    resumed = await resume_objective(objective["objective_id"], ObjectiveAction(reason="back to work"), tenant_a)
    assert resumed["data"]["status"] == "active"
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


@pytest.mark.asyncio
async def test_status_kill_switch_is_boolean():
    # Kyber validates /v1/agent/status kill_switch as z.boolean(); the endpoint
    # must keep that shape while exposing the full record separately.
    request = FakeRequest("tenant-status")
    await toggle_kill_switch(KillSwitchAction(action="engage", reason="incident"), request)
    status = await agent_status(request)
    assert status["data"]["kill_switch"] is True
    assert isinstance(status["data"]["kill_switch"], bool)
    assert status["data"]["kill_switch_state"]["enabled"] is True


@pytest.mark.asyncio
async def test_idempotent_objective_retry_does_not_duplicate_review_batches():
    request = FakeRequest("tenant-idem")
    submission = ObjectiveSubmission(
        goal="Stage enrichment once",
        idempotency_key="fixed-key-1",
        payload={"staged_mutations": [{"mutation_class": 2, "operation": "upsert", "target": {"node": "n1"}}]},
    )
    first = await submit_objective(submission, request)
    second = await submit_objective(submission, request)
    assert first["data"]["objective_id"] == second["data"]["objective_id"]
    batches = await list_review_batches(request, status="pending")
    assert batches["data"]["total"] == 1


@pytest.mark.asyncio
async def test_invalid_mutation_class_is_rejected_without_persisting():
    request = FakeRequest("tenant-badclass")
    with pytest.raises(BadRequestError):
        await submit_objective(ObjectiveSubmission(
            goal="Bad mutation class",
            payload={"staged_mutations": [{"mutation_class": 9, "operation": "upsert"}]},
        ), request)
    # The objective must not have been persisted before the validation failure.
    listed = await list_objectives(request)
    assert listed["data"]["total"] == 0


@pytest.mark.asyncio
async def test_objective_advances_out_of_review_after_decision():
    request = FakeRequest("tenant-advance")
    submitted = await submit_objective(ObjectiveSubmission(
        goal="Advance after approval",
        payload={"staged_mutations": [{"mutation_class": 1, "operation": "upsert"}]},
    ), request)
    objective_id = submitted["data"]["objective_id"]
    assert submitted["data"]["status"] == "awaiting_review"
    batch_id = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    await approve_review_batch(batch_id, ReviewDecision(notes="ok"), request)
    detail = await get_objective(objective_id, request)
    assert detail["data"]["objective"]["status"] == "active"

    # A rejection blocks the objective instead.
    rejected = await submit_objective(ObjectiveSubmission(
        goal="Block after rejection",
        payload={"staged_mutations": [{"mutation_class": 1, "operation": "upsert"}]},
    ), request)
    reject_batch = (await list_review_batches(request, status="pending"))["data"]["batches"][0]["batch_id"]
    await reject_review_batch(reject_batch, ReviewDecision(notes="no"), request)
    detail2 = await get_objective(rejected["data"]["objective_id"], request)
    assert detail2["data"]["objective"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_health_queue_depth_sums_routed_controllers():
    request = FakeRequest("tenant-queues")
    # nous routes to the default queue; discovery routes to its own queue.
    await controller_heartbeat(ControllerHeartbeat(controller="nous", status="healthy", queue_depth=3, worker_id="w1"), request)
    await controller_heartbeat(ControllerHeartbeat(controller="discovery", status="healthy", queue_depth=2, worker_id="w2"), request)
    health = await controller_health(request)
    depths = {q["name"]: q["depth"] for q in health["data"]["queues"]}
    assert depths["default"] >= 3  # nous contributes to default
    assert depths["discovery"] == 2


@pytest.mark.asyncio
async def test_cancel_emits_correct_event_and_blocks_resume():
    request = FakeRequest("tenant-cancel")
    submitted = await submit_objective(ObjectiveSubmission(goal="Cancel me"), request)
    oid = submitted["data"]["objective_id"]
    cancelled = await cancel_objective(oid, ObjectiveAction(reason="unsafe"), request)
    assert cancelled["data"]["status"] == "cancelled"
    types = {e["event_type"] for e in (await timeline_events(request, objective_id=oid, limit=50))["data"]["events"]}
    assert "objective.cancelled" in types  # not the misspelled "objective.canceld"
    assert "objective.canceld" not in types
    # Resume must not revive a cancelled (terminal) objective.
    with pytest.raises(ConflictError):
        await resume_objective(oid, ObjectiveAction(reason="oops"), request)


@pytest.mark.asyncio
async def test_controller_status_aggregates_workers_and_status_exposes_them():
    request = FakeRequest("tenant-workers")
    # Two workers heartbeat for the same controller (horizontal scaling).
    await controller_heartbeat(ControllerHeartbeat(controller="discovery", status="healthy", queue_depth=3, worker_id="w1"), request)
    await controller_heartbeat(ControllerHeartbeat(controller="discovery", status="healthy", queue_depth=4, worker_id="w2"), request)
    disc = next(c for c in (await controllers_status(request))["data"]["controllers"] if c["controller"] == "discovery")
    assert disc["worker_count"] == 2
    assert disc["queue_depth"] == 7  # 3 + 4 aggregated, not collapsed to one row
    # /status must surface a workers array for Kyber's Command/Mission views.
    st = await agent_status(request)
    assert "discovery" in {w["worker_type"] for w in st["data"]["workers"]}


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_per_objective_controller():
    request = FakeRequest("tenant-dispatch-idem")
    submitted = await submit_objective(ObjectiveSubmission(goal="Run once"), request)
    oid = submitted["data"]["objective_id"]
    first = await dispatch_step(DispatchRequest(objective_id=oid, controller="nous"), request)
    # A retry / double-click reuses the in-flight run instead of queuing duplicate work.
    second = await dispatch_step(DispatchRequest(objective_id=oid, controller="nous"), request)
    assert first["data"]["run_id"] == second["data"]["run_id"]
