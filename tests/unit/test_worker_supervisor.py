"""Unit tests for the runtime worker supervisor.

Covers: crash → backoff restart, restart exhaustion → failed, required
first-start failure semantics per environment, duplicate registration,
stop_all cancellation of running + restarting workers, disabled specs,
and the status() shape.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from config.settings import Environment  # noqa: E402
from services.runtime.supervisor import WorkerSpec, WorkerSupervisor  # noqa: E402


async def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.005) -> None:
    """Poll until predicate() is truthy or fail the test after timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    pytest.fail("condition not reached within timeout")


# ── registration ──────────────────────────────────────────────────────────────


def test_duplicate_name_raises_value_error():
    supervisor = WorkerSupervisor(environment=Environment.LOCAL)

    async def _noop():
        return None

    supervisor.register(WorkerSpec(name="w", factory=_noop))
    with pytest.raises(ValueError):
        supervisor.register(WorkerSpec(name="w", factory=_noop))


# ── crash / restart / backoff ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crash_triggers_backoff_restarts_then_recovers():
    """Worker crashes twice, then runs; supervisor restarts it with backoff."""
    crashes = 2
    calls = {"n": 0}
    running = asyncio.Event()

    async def flaky():
        calls["n"] += 1
        if calls["n"] <= crashes:
            raise RuntimeError(f"boom {calls['n']}")
        running.set()
        await asyncio.Event().wait()  # run forever until cancelled

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(name="flaky", factory=flaky, backoff_base_s=0.001, max_restarts=5)
    )
    await supervisor.start_all()
    try:
        await asyncio.wait_for(running.wait(), timeout=5.0)
        status = supervisor.status()["flaky"]
        assert status["state"] == "running"
        assert status["restarts"] == crashes
        assert "boom" in status["last_error"]
    finally:
        await supervisor.stop_all()
    assert supervisor.status()["flaky"]["state"] == "stopped"


@pytest.mark.asyncio
async def test_exceeding_max_restarts_marks_worker_failed():
    calls = {"n": 0}

    async def always_crashes():
        calls["n"] += 1
        raise RuntimeError("permanent failure")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="doomed", factory=always_crashes, backoff_base_s=0.001, max_restarts=2
        )
    )
    await supervisor.start_all()
    try:
        await _wait_for(lambda: supervisor.status()["doomed"]["state"] == "failed")
    finally:
        await supervisor.stop_all()

    status = supervisor.status()["doomed"]
    assert status["state"] == "failed"  # stop_all must not mask terminal failure
    assert status["restarts"] == 2
    assert calls["n"] == 3  # initial start + 2 restarts
    assert "permanent failure" in status["last_error"]


# ── required worker first-start semantics ────────────────────────────────────


@pytest.mark.asyncio
async def test_required_first_start_failure_raises_in_staging(monkeypatch):
    import config.settings as settings_module

    monkeypatch.setattr(settings_module.settings, "env", Environment.STAGING)

    async def boom():
        raise RuntimeError("cannot start")

    supervisor = WorkerSupervisor()  # env resolved from (monkeypatched) settings
    supervisor.register(
        WorkerSpec(
            name="critical", factory=boom, required=True,
            backoff_base_s=0.001, max_restarts=1,
        )
    )
    with pytest.raises(RuntimeError, match="critical"):
        await supervisor.start_all()
    # start_all aborts cleanly: no guard task left running
    await supervisor.stop_all()


@pytest.mark.asyncio
async def test_required_first_start_failure_does_not_raise_in_local(monkeypatch):
    import config.settings as settings_module

    monkeypatch.setattr(settings_module.settings, "env", Environment.LOCAL)

    async def boom():
        raise RuntimeError("cannot start")

    supervisor = WorkerSupervisor()
    supervisor.register(
        WorkerSpec(
            name="critical", factory=boom, required=True,
            backoff_base_s=0.001, max_restarts=1,
        )
    )
    await supervisor.start_all()  # must NOT raise in local
    try:
        await _wait_for(lambda: supervisor.status()["critical"]["state"] == "failed")
    finally:
        await supervisor.stop_all()


@pytest.mark.asyncio
async def test_healthy_required_worker_does_not_block_staging_startup():
    running = asyncio.Event()

    async def healthy():
        running.set()
        await asyncio.Event().wait()

    supervisor = WorkerSupervisor(
        environment=Environment.STAGING, first_start_grace_s=0.05
    )
    supervisor.register(WorkerSpec(name="healthy", factory=healthy, required=True))
    await supervisor.start_all()
    try:
        assert running.is_set()
        assert supervisor.status()["healthy"]["state"] == "running"
    finally:
        await supervisor.stop_all()


# ── stop_all ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_all_cancels_running_and_restarting_workers():
    started = asyncio.Event()

    async def runs_forever():
        started.set()
        await asyncio.Event().wait()

    async def crashes_once_then_backs_off():
        raise RuntimeError("crash into long backoff")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(WorkerSpec(name="runner", factory=runs_forever))
    supervisor.register(
        WorkerSpec(
            name="backoff",
            factory=crashes_once_then_backs_off,
            backoff_base_s=60.0,  # parks the guard in a long restart sleep
            max_restarts=5,
        )
    )
    await supervisor.start_all()
    await asyncio.wait_for(started.wait(), timeout=5.0)
    await _wait_for(lambda: supervisor.status()["backoff"]["state"] == "restarting")

    await supervisor.stop_all()
    status = supervisor.status()
    assert status["runner"]["state"] == "stopped"
    assert status["backoff"]["state"] == "stopped"
    # idempotent
    await supervisor.stop_all()
    assert supervisor.status()["runner"]["state"] == "stopped"


# ── disabled ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_spec_never_starts():
    calls = {"n": 0}

    async def should_not_run():
        calls["n"] += 1

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(name="off", factory=should_not_run, enabled=lambda: False)
    )
    await supervisor.start_all()
    await asyncio.sleep(0.01)
    assert supervisor.status()["off"]["state"] == "disabled"
    assert calls["n"] == 0
    await supervisor.stop_all()
    assert supervisor.status()["off"]["state"] == "disabled"


# ── status shape ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_shape():
    async def runs_forever():
        await asyncio.Event().wait()

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(WorkerSpec(name="a", factory=runs_forever, required=True))
    supervisor.register(
        WorkerSpec(name="b", factory=runs_forever, enabled=lambda: False)
    )

    # pre-start snapshot
    pre = supervisor.status()
    assert set(pre.keys()) == {"a", "b"}

    await supervisor.start_all()
    try:
        status = supervisor.status()
        for name, info in status.items():
            # This key set is a pinned contract: /v1/ready projects it, so an
            # unannounced addition or removal changes the readiness payload.
            # "role" carries the owning logical worker role so a consolidated
            # execution group stays per-role observable; "" when unattributed.
            # The liveness/backlog fields below exist because a supervisor that
            # only reports "running" cannot distinguish a worker doing work from
            # one wedged holding a lease.
            assert set(info.keys()) == {
                "state",
                "restarts",
                "last_error",
                "required",
                "role",
                "lease_owner",
                "heartbeat_at",
                "heartbeat_age_s",
                "last_success_at",
                "consumer_lag",
                "oldest_pending_age_s",
                "dlq_depth",
                "telemetry_error",
            }
            assert isinstance(info["role"], str)
            assert info["state"] in {"running", "failed", "disabled", "stopped", "restarting"}
            assert isinstance(info["restarts"], int)
            assert info["last_error"] is None or isinstance(info["last_error"], str)
            assert isinstance(info["required"], bool)

            # Absence of a signal must be reported as unknown (None), never as a
            # healthy-looking zero — a zero lag and a lag nobody measured are
            # different facts, and conflating them is how a dead worker reads as
            # idle.
            assert info["lease_owner"] is None or isinstance(info["lease_owner"], str)
            assert info["heartbeat_at"] is None or isinstance(info["heartbeat_at"], str)
            assert info["heartbeat_age_s"] is None or isinstance(info["heartbeat_age_s"], float)
            assert info["last_success_at"] is None or isinstance(info["last_success_at"], str)
            assert info["consumer_lag"] is None or isinstance(info["consumer_lag"], int)
            assert (
                info["oldest_pending_age_s"] is None
                or isinstance(info["oldest_pending_age_s"], float)
            )
            assert info["dlq_depth"] is None or isinstance(info["dlq_depth"], int)
            assert info["telemetry_error"] is None or isinstance(info["telemetry_error"], str)

            # A worker that has never reported a heartbeat has no age to report.
            if info["heartbeat_at"] is None:
                assert info["heartbeat_age_s"] is None

        assert status["a"]["required"] is True
        assert status["b"]["state"] == "disabled"
        # A disabled worker holds no lease — reporting one would make an
        # intentionally-off worker look like a live participant.
        assert status["b"]["lease_owner"] is None
    finally:
        await supervisor.stop_all()
