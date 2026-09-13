"""Worker execution bridge: envelope contract, exactly-once enqueue,
lifecycle/kill-switch guards, hosted fail-closed and local fail-open."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import ConflictError  # noqa: E402
from services.agent import worker_bridge  # noqa: E402
from services.agent.routes import (  # noqa: E402
    DispatchRequest,
    KillSwitchAction,
    ObjectiveAction,
    ObjectiveSubmission,
    _runtime_repo,
    dispatch_step,
    pause_objective,
    submit_objective,
    toggle_kill_switch,
)
from services.agent.worker_bridge import (  # noqa: E402
    BridgeUnavailableError,
    build_dispatch_envelope,
    dispatch_to_worker,
)

# The backend tests/ root is intentionally not a package; this suite's package
# root is one_person_ops (repo-root tests/ owns the "tests" package name).
from one_person_ops.conftest import FakeRequest, tenant_id  # noqa: E402

pytestmark = pytest.mark.asyncio


def _run(tenant: str = "t", **overrides) -> dict:
    run = {
        "run_id": "run_1",
        "tenant_id": tenant,
        "objective_id": "obj_1",
        "controller": "nous",
        "queue": "default",
        "idempotency_key": "idem-1",
        "attempt": 1,
        "created_at": "2026-07-10T00:00:00+00:00",
    }
    run.update(overrides)
    return run


def _full_envelope(tenant: str = "t") -> dict:
    return build_dispatch_envelope(_run(tenant), request_id="req-1", payload={"k": "v"})


class BridgeRecorder:
    def __init__(self, result=None, exc=None):
        self.calls: list[dict] = []
        self.result = result or {"dispatched": True, "task_id": "task-1", "queue": "default"}
        self.exc = exc

    def __call__(self, envelope: dict) -> dict:
        self.calls.append(envelope)
        if self.exc is not None:
            raise self.exc
        return self.result


# ── Envelope contract ──────────────────────────────────────────────────────

async def test_envelope_has_mandated_shape():
    envelope = build_dispatch_envelope(
        _run("t-env"), request_id="req-9", payload={"goal": "x"}, plan_id="plan_1", step_id="step_1"
    )
    for key in ("tenant_id", "objective_id", "run_id", "controller", "queue",
                "idempotency_key", "attempt", "payload", "created_at", "request_id"):
        assert key in envelope, f"missing envelope key: {key}"
    assert envelope["tenant_id"] == "t-env"
    assert envelope["payload"] == {"goal": "x"}
    assert envelope["attempt"] == 1
    assert envelope["plan_id"] == "plan_1"
    assert envelope["step_id"] == "step_1"


async def test_envelope_optional_keys_omitted_when_empty():
    envelope = build_dispatch_envelope(_run(), request_id="req-1")
    assert "plan_id" not in envelope
    assert "step_id" not in envelope


async def test_dispatch_rejects_incomplete_envelope():
    with pytest.raises(ValueError):
        dispatch_to_worker({"run_id": "run_1"})


# ── Exactly-once enqueue via the dispatch route ────────────────────────────

async def test_dispatch_enqueues_exactly_once_per_idempotency_key(bridge_enabled, monkeypatch):
    recorder = BridgeRecorder()
    monkeypatch.setattr(worker_bridge, "dispatch_to_worker", recorder)
    request = FakeRequest(tenant_id())
    objective = (await submit_objective(ObjectiveSubmission(goal="Bridge me once"), request))["data"]
    first = await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), request)
    second = await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), request)
    # Same idempotency key → the in-flight run is reused and the broker sees ONE task.
    assert first["data"]["run_id"] == second["data"]["run_id"]
    assert len(recorder.calls) == 1
    envelope = recorder.calls[0]
    assert envelope["run_id"] == first["data"]["run_id"]
    assert envelope["idempotency_key"] == first["data"]["idempotency_key"]
    assert first["data"]["bridge"]["dispatched"] is True


async def test_bridge_not_called_when_flag_off(monkeypatch):
    recorder = BridgeRecorder()
    monkeypatch.setattr(worker_bridge, "dispatch_to_worker", recorder)
    request = FakeRequest(tenant_id())
    objective = (await submit_objective(ObjectiveSubmission(goal="No bridge"), request))["data"]
    run = await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), request)
    assert recorder.calls == []
    assert "bridge" not in run["data"]


async def test_kill_switch_blocks_dispatch_and_bridge(bridge_enabled, monkeypatch):
    recorder = BridgeRecorder()
    monkeypatch.setattr(worker_bridge, "dispatch_to_worker", recorder)
    request = FakeRequest(tenant_id())
    objective = (await submit_objective(ObjectiveSubmission(goal="Blocked by kill switch"), request))["data"]
    await toggle_kill_switch(KillSwitchAction(action="engage", reason="incident"), request)
    with pytest.raises(ConflictError):
        await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), request)
    assert recorder.calls == []


async def test_non_runnable_objective_states_cannot_dispatch(bridge_enabled, monkeypatch):
    recorder = BridgeRecorder()
    monkeypatch.setattr(worker_bridge, "dispatch_to_worker", recorder)
    request = FakeRequest(tenant_id())
    # awaiting_review must not bypass the human gate.
    awaiting = (await submit_objective(ObjectiveSubmission(
        goal="Awaiting review",
        payload={"staged_mutations": [{"mutation_class": 1, "operation": "upsert"}]},
    ), request))["data"]
    with pytest.raises(ConflictError):
        await dispatch_step(DispatchRequest(objective_id=awaiting["objective_id"], controller="nous"), request)
    # paused must not silently revive.
    paused = (await submit_objective(ObjectiveSubmission(goal="Paused work"), request))["data"]
    await pause_objective(paused["objective_id"], ObjectiveAction(reason="hold"), request)
    with pytest.raises(ConflictError):
        await dispatch_step(DispatchRequest(objective_id=paused["objective_id"], controller="nous"), request)
    assert recorder.calls == []


# ── Environment failure semantics ──────────────────────────────────────────

def _clear_broker_env(monkeypatch):
    for var in ("AGENT_LAYER_BROKER_URL", "CELERY_BROKER_URL", "REDIS_URL", "REDIS_HOST"):
        monkeypatch.delenv(var, raising=False)


async def test_local_env_fails_open_without_broker(monkeypatch):
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "local")
    result = dispatch_to_worker(_full_envelope())
    assert result == {"dispatched": False, "reason": "broker_not_configured"}


async def test_hosted_env_fails_closed_without_broker(monkeypatch):
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "staging")
    with pytest.raises(BridgeUnavailableError) as excinfo:
        dispatch_to_worker(_full_envelope())
    assert excinfo.value.reason == "broker_not_configured"


async def test_hosted_env_fails_closed_when_publish_fails(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("AGENT_LAYER_BROKER_URL", "redis://broker.internal:6379/0")

    class ExplodingClient:
        def send_task(self, *args, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(worker_bridge, "_get_celery_client", lambda url: ExplodingClient())
    with pytest.raises(BridgeUnavailableError) as excinfo:
        dispatch_to_worker(_full_envelope())
    assert "broker_unreachable" in excinfo.value.reason


async def test_local_env_fails_open_when_celery_missing(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("AGENT_LAYER_BROKER_URL", "redis://broker.internal:6379/0")

    def _no_celery(url):
        raise ImportError("celery not installed")

    monkeypatch.setattr(worker_bridge, "_get_celery_client", _no_celery)
    result = dispatch_to_worker(_full_envelope())
    assert result["dispatched"] is False
    assert result["reason"] == "celery_not_installed"


async def test_successful_publish_sends_task_by_name_with_queue_and_idempotency(monkeypatch):
    monkeypatch.setenv("AGENT_LAYER_BROKER_URL", "redis://broker.internal:6379/0")
    sent = {}

    class FakeAsyncResult:
        id = "celery-task-1"

    class FakeClient:
        def send_task(self, name, kwargs=None, queue=None, headers=None):
            sent.update({"name": name, "kwargs": kwargs, "queue": queue, "headers": headers})
            return FakeAsyncResult()

    monkeypatch.setattr(worker_bridge, "_get_celery_client", lambda url: FakeClient())
    envelope = build_dispatch_envelope(_run(queue="discovery", controller="discovery"), request_id="req-1")
    result = dispatch_to_worker(envelope)
    assert result == {"dispatched": True, "task_id": "celery-task-1", "queue": "discovery"}
    assert sent["name"] == "aether.agent.execute_objective_step"
    assert sent["queue"] == "discovery"
    assert sent["headers"] == {"idempotency_key": "idem-1"}
    assert sent["kwargs"] == {"envelope": envelope}


async def test_hosted_bridge_failure_marks_run_dispatch_failed(bridge_enabled, monkeypatch):
    request = FakeRequest(tenant_id())
    tenant = request.state.tenant.tenant_id
    objective = (await submit_objective(ObjectiveSubmission(goal="Fail closed"), request))["data"]
    # Connect the event producer while still in local mode so the publish that
    # precedes the bridge keeps its in-memory transport after the env flips.
    from services.agent import routes as agent_routes
    await agent_routes._producer.connect()
    _clear_broker_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "staging")
    with pytest.raises(BridgeUnavailableError):
        await dispatch_step(DispatchRequest(objective_id=objective["objective_id"], controller="nous"), request)
    failed = await _runtime_repo.list_runs(tenant, status="dispatch_failed")
    assert len(failed) == 1
    assert failed[0]["objective_id"] == objective["objective_id"]
    assert failed[0]["error"] == "broker_not_configured"
    events = await _runtime_repo.events_for_tenant(tenant, limit=50, objective_id=objective["objective_id"])
    assert any(e["event_type"] == "run.dispatch_failed" for e in events)
