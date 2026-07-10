"""Worker run lifecycle: callback permissions, transitions, sanitization,
stuck detection/sweep, replay, retention, health visibility, flag gating."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import BadRequestError, ConflictError, ForbiddenError, NotFoundError  # noqa: E402
from services.agent import worker_bridge  # noqa: E402
from services.agent.routes import (  # noqa: E402
    DispatchRequest,
    ObjectiveSubmission,
    _runtime_repo,
    controller_health,
    dispatch_step,
    submit_objective,
)
from services.agent.worker_routes import (  # noqa: E402
    RunStatusUpdate,
    get_run,
    list_runs,
    list_stuck_runs,
    update_run_status,
)

from one_person_ops.conftest import FakeRequest, tenant_id  # noqa: E402

pytestmark = pytest.mark.asyncio

OPERATOR_ONLY = {"agent:manage", "agent:dispatch", "agent:pause", "agent:approve"}
WORKER_CRED = {"agent:run_update"}


async def _dispatched_run(request: FakeRequest, monkeypatch) -> dict:
    monkeypatch.setattr(
        worker_bridge, "dispatch_to_worker",
        lambda envelope: {"dispatched": True, "task_id": "task-1", "queue": envelope["queue"]},
    )
    objective = (await submit_objective(ObjectiveSubmission(goal="Lifecycle run"), request))["data"]
    run = (await dispatch_step(
        DispatchRequest(objective_id=objective["objective_id"], controller="nous"), request
    ))["data"]
    return run


def _age(run: dict, seconds: int) -> dict:
    """Backdate a run's progress signals past the stale threshold."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    run["heartbeat_at"] = old
    run["updated_at"] = old
    run["created_at"] = old
    return run


# ── Callback permission boundary ───────────────────────────────────────────

async def test_operator_token_cannot_spoof_worker_updates(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    with pytest.raises(ForbiddenError):
        await update_run_status(run["run_id"], RunStatusUpdate(status="completed"), operator)
    # The run is untouched by the rejected update.
    stored = await _runtime_repo.get_run(tenant, run["run_id"])
    assert stored["status"] == "queued"


async def test_worker_credential_can_update_run(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    started = await update_run_status(
        run["run_id"], RunStatusUpdate(status="running", worker_id="w-1"), worker
    )
    assert started["data"]["status"] == "running"
    assert started["data"]["worker_id"] == "w-1"


async def test_worker_credential_cannot_read_operator_views(bridge_enabled):
    worker = FakeRequest(tenant_id(), permissions=WORKER_CRED)
    with pytest.raises(ForbiddenError):
        await list_runs(worker)


# ── Lifecycle transitions ──────────────────────────────────────────────────

async def test_run_completes_with_sanitized_output_and_timeline(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    completed = await update_run_status(
        run["run_id"],
        RunStatusUpdate(status="completed", output={"result": "ok", "api_key": "leak-me"}),
        worker,
    )
    assert completed["data"]["status"] == "completed"
    assert completed["data"]["output"]["api_key"] == "[redacted]"
    assert completed["data"]["output"]["result"] == "ok"
    assert completed["data"]["completed_at"]
    events = await _runtime_repo.events_for_tenant(tenant, limit=50, objective_id=run["objective_id"])
    types = {e["event_type"] for e in events}
    assert {"step.dispatched", "run.started", "run.completed"} <= types
    assert "leak-me" not in str(events)


async def test_failed_run_records_bounded_error(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    failed = await update_run_status(
        run["run_id"], RunStatusUpdate(status="failed", error="boom " * 1000), worker
    )
    assert failed["data"]["status"] == "failed"
    assert len(failed["data"]["error"]) <= 2000
    assert failed["data"]["failed_at"]


async def test_retry_increments_attempt_then_can_run_again(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    retried = await update_run_status(
        run["run_id"], RunStatusUpdate(status="retry", error="transient"), worker
    )
    assert retried["data"]["status"] == "retry"
    assert retried["data"]["attempt"] == 2
    # retry → running → completed is a legal path.
    again = await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    assert again["data"]["status"] == "running"


async def test_illegal_transition_conflicts(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    await update_run_status(run["run_id"], RunStatusUpdate(status="failed", error="x"), worker)
    with pytest.raises(ConflictError):
        await update_run_status(run["run_id"], RunStatusUpdate(status="completed"), worker)


async def test_duplicate_completion_is_idempotent(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    first = await update_run_status(run["run_id"], RunStatusUpdate(status="completed"), worker)
    second = await update_run_status(run["run_id"], RunStatusUpdate(status="completed"), worker)
    assert second["data"]["completed_at"] == first["data"]["completed_at"]


# ── Tenant isolation ───────────────────────────────────────────────────────

async def test_cross_tenant_run_access_is_not_found(bridge_enabled, monkeypatch):
    tenant_a = tenant_id()
    operator_a = FakeRequest(tenant_a, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator_a, monkeypatch)
    other = FakeRequest(tenant_id(), permissions=OPERATOR_ONLY | WORKER_CRED)
    with pytest.raises(NotFoundError):
        await get_run(run["run_id"], other)
    with pytest.raises(NotFoundError):
        await update_run_status(run["run_id"], RunStatusUpdate(status="running"), other)
    listed = await list_runs(other)
    assert all(r["tenant_id"] != tenant_a for r in listed["data"]["runs"])


# ── Stuck-run detection, sweep, replay, retention ──────────────────────────

async def test_stuck_run_detection_and_sweep(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    fresh = await _dispatched_run_second(operator, monkeypatch)
    stored = await _runtime_repo.get_run(tenant, run["run_id"])
    await _runtime_repo.worker_runs.set(run["run_id"], _age(stored, 3600))
    stuck_route = await list_stuck_runs(operator)
    stuck_ids = {r["run_id"] for r in stuck_route["data"]["runs"]}
    assert run["run_id"] in stuck_ids
    assert fresh["run_id"] not in stuck_ids

    swept = await _runtime_repo.sweep_stale_runs(tenant)
    assert [r["run_id"] for r in swept] == [run["run_id"]]
    assert (await _runtime_repo.get_run(tenant, run["run_id"]))["status"] == "stale"
    assert await _runtime_repo.list_stuck_runs(tenant) == []
    events = await _runtime_repo.events_for_tenant(tenant, limit=100, objective_id=run["objective_id"])
    assert any(e["event_type"] == "run.stale" for e in events)


async def _dispatched_run_second(request: FakeRequest, monkeypatch) -> dict:
    monkeypatch.setattr(
        worker_bridge, "dispatch_to_worker",
        lambda envelope: {"dispatched": True, "task_id": "task-2", "queue": envelope["queue"]},
    )
    objective = (await submit_objective(ObjectiveSubmission(goal="Fresh healthy run"), request))["data"]
    return (await dispatch_step(
        DispatchRequest(objective_id=objective["objective_id"], controller="discovery"), request
    ))["data"]


async def test_replay_produces_new_queued_run_with_fresh_idempotency(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    stored = await _runtime_repo.get_run(tenant, run["run_id"])
    await _runtime_repo.worker_runs.set(run["run_id"], _age(stored, 3600))
    await _runtime_repo.sweep_stale_runs(tenant)

    replay = await _runtime_repo.replay_run(tenant, run["run_id"], actor_id="operator")
    assert replay["run_id"] != run["run_id"]
    assert replay["status"] == "queued"
    assert replay["replay_of"] == run["run_id"]
    assert replay["idempotency_key"].startswith(f"{run['idempotency_key']}:replay:")
    assert replay["controller"] == run["controller"]
    assert replay["queue"] == run["queue"]


async def test_replay_of_active_run_conflicts(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    with pytest.raises(ConflictError):
        await _runtime_repo.replay_run(tenant, run["run_id"])


async def test_prune_runs_keeps_active_and_recent(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    old_run = await _dispatched_run(operator, monkeypatch)
    await update_run_status(old_run["run_id"], RunStatusUpdate(status="running"), worker)
    await update_run_status(old_run["run_id"], RunStatusUpdate(status="completed"), worker)
    stored = await _runtime_repo.get_run(tenant, old_run["run_id"])
    stored["created_at"] = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    await _runtime_repo.worker_runs.set(old_run["run_id"], stored)
    active_run = await _dispatched_run_second(operator, monkeypatch)

    pruned = await _runtime_repo.prune_runs(tenant, keep_days=30)
    assert pruned == 1
    assert await _runtime_repo.get_run(tenant, old_run["run_id"]) is None
    assert await _runtime_repo.get_run(tenant, active_run["run_id"]) is not None


# ── Health visibility ──────────────────────────────────────────────────────

async def test_health_exposes_queue_depth_runs_and_worker_freshness(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    health = (await controller_health(operator))["data"]
    assert health["queue_depth"] >= 1
    assert health["runs"]["queued"] >= 1
    assert set(health["runs"]) == {
        "queued", "running", "completed", "failed", "retry", "stale", "dispatch_failed", "stuck",
    }
    assert health["workers"]["count"] == 0
    assert health["workers"]["stale"] == 0
    # Existing keys are preserved (additive change only).
    assert "kill_switch" in health and "controllers" in health and "queues" in health
    worker = FakeRequest(tenant, permissions=WORKER_CRED)
    await update_run_status(run["run_id"], RunStatusUpdate(status="running"), worker)
    health2 = (await controller_health(operator))["data"]
    assert health2["runs"]["running"] >= 1


# ── Filters and flag gating ────────────────────────────────────────────────

async def test_list_runs_filters_by_status_and_objective(bridge_enabled, monkeypatch):
    tenant = tenant_id()
    operator = FakeRequest(tenant, permissions=OPERATOR_ONLY)
    run = await _dispatched_run(operator, monkeypatch)
    by_obj = await list_runs(operator, objective_id=run["objective_id"])
    assert [r["run_id"] for r in by_obj["data"]["runs"]] == [run["run_id"]]
    queued = await list_runs(operator, status="queued")
    assert run["run_id"] in {r["run_id"] for r in queued["data"]["runs"]}
    with pytest.raises(BadRequestError):
        await list_runs(operator, status="bogus")


async def test_worker_routes_gated_off_by_default():
    operator = FakeRequest(tenant_id())
    with pytest.raises(BadRequestError):
        await list_runs(operator)
    with pytest.raises(BadRequestError):
        await list_stuck_runs(operator)
    with pytest.raises(BadRequestError):
        await get_run("run_x", operator)
    with pytest.raises(BadRequestError):
        await update_run_status("run_x", RunStatusUpdate(status="running"), operator)
