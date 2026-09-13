"""Chaos scenario: kill worker mid-loop -> supervisor restarts -> no data loss.

Drives the REAL ``WorkerSupervisor`` (services/runtime/supervisor.py) with a
durable worker whose factory reads a durable checkpoint, processes queued
items into an idempotent results store, then advances the checkpoint. The
worker is injected with a mid-loop crash AFTER processing a few items but
BEFORE persisting the checkpoint. The supervisor's guard task catches the
crash, backoff-restarts the factory, and the restarted worker resumes from the
durable checkpoint — the same items are re-read but idempotent inserts
collapse, so:

  * every item is persisted exactly once (no data loss),
  * no item is persisted twice (no duplication of authoritative records),
  * the checkpoint advances to the true tail (no fabricated success).

No live network, no real broker/DB: the in-memory repositories ARE the durable
state a real restart would read back, which is precisely the resume contract
``WorkerSupervisor`` supervises in production.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parent
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

from config.settings import Environment  # noqa: E402
from repositories.repos import BaseRepository, reset_in_memory_stores  # noqa: E402
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from services.runtime.supervisor import WorkerSpec, WorkerSupervisor  # noqa: E402
from shared.credentials.in_memory import InMemoryCredentialBackend  # noqa: E402

QUEUE_ITEMS = [{"seq": i, "payload": f"item-{i}"} for i in range(1, 6)]


class DurableLoopState:
    """Durable worker state shared across supervisor restarts.

    ``crash_after`` items are processed (and results persisted) before the
    injected crash; the checkpoint is NOT advanced on the crashed run, so the
    restart must re-read from the beginning and let idempotent inserts collapse.
    """

    def __init__(self, queue: BaseRepository, results: BaseRepository) -> None:
        self.queue = queue
        self.results = results
        self.crash_after = 3
        self.crashes_left = 1
        self.processed_total = 0
        self.done = False
        self.last_error: str | None = None

    async def seed(self) -> None:
        # The durable checkpoint row EXISTS before the worker starts, so a
        # restart reads it back and the tail-write after recovery is an update
        # to a live row (the real table owns this row; update() is the
        # authoritative advancement write).
        await self.queue.insert("checkpoint", {"last": 0})
        for item in QUEUE_ITEMS:
            await self.queue.insert(f"q-{item['seq']}", item)


def build_worker(state: DurableLoopState):
    """Factory closure: returns a FRESH coroutine per supervisor restart."""

    async def loop() -> None:
        checkpoint = await state.queue.find_by_id("checkpoint") or {}
        last = int(checkpoint.get("last", 0))
        pending = [item for item in QUEUE_ITEMS if item["seq"] > last]

        for item in pending:
            result = {
                "result_id": f"result-{item['seq']}",
                "seq": item["seq"],
                "payload": item["payload"],
                "idempotency_key": f"idem-{item['seq']}",
            }
            # Idempotent insert: re-processing after a crash collapses.
            await state.results.insert(result["result_id"], result)
            state.processed_total += 1
            # KILLED MID-LOOP: crash before the checkpoint is advanced.
            if state.crashes_left and state.processed_total >= state.crash_after:
                state.crashes_left -= 1
                raise RuntimeError("worker killed mid-loop (chaos injection)")

        await state.queue.update("checkpoint", {"last": max(pending[-1]["seq"], last) if pending else last})
        state.done = True
        # Stay alive so the supervisor observes a live worker until stop_all().
        await asyncio.sleep(3600)

    return loop


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    InMemoryCredentialBackend.reset()
    yield
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    InMemoryCredentialBackend.reset()


async def _wait_until(predicate, timeout_s: float = 15.0) -> None:
    """Poll until ``predicate()`` is truthy or fail after ``timeout_s``."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for deterministic worker state")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_kill_worker_mid_loop_supervisor_restarts_with_no_data_loss():
    queue = BaseRepository("chaos_queue")
    results = BaseRepository("chaos_results")
    state = DurableLoopState(queue, results)
    await state.seed()

    supervisor = WorkerSupervisor(
        environment=Environment.LOCAL,
        first_start_grace_s=0.0,
        watchdog_interval_s=30.0,
    )
    supervisor.register(WorkerSpec(
        name="chaos-durable-worker",
        factory=build_worker(state),
        required=False,
        enabled=lambda: True,
        max_restarts=3,
        backoff_base_s=0.01,
        healthy_run_s=300.0,  # only one injected crash -> the budget never drains
    ))
    await supervisor.start_all()

    try:
        # Wait for the crash + restart to complete and the tail checkpoint to land.
        await _wait_until(lambda: state.done, timeout_s=15.0)
    finally:
        await supervisor.stop_all()

    # The supervisor observed and restarted the worker.
    totals = supervisor.restart_totals()
    assert totals["chaos-durable-worker"] >= 1
    assert state.crashes_left == 0

    # EVERY item persisted exactly once — no loss, no duplication.
    rows = await results.find_many(filters=None, limit=100)
    assert len(rows) == len(QUEUE_ITEMS) == 5
    payloads = [r["payload"] for r in rows]
    assert sorted(payloads) == ["item-1", "item-2", "item-3", "item-4", "item-5"]
    assert len(set(payloads)) == len(payloads)  # no duplicate authoritative records
    seqs = [r["seq"] for r in rows]
    assert sorted(seqs) == [1, 2, 3, 4, 5]

    # The checkpoint advanced to the true tail (no fabricated success).
    checkpoint = await queue.find_by_id("checkpoint")
    assert checkpoint is not None and checkpoint["last"] == 5

    # The supervisor reports the worker as running/live after recovery.
    status = supervisor.status()
    assert status["chaos-durable-worker"]["state"] in ("running", "stopped")
    assert supervisor.unhealthy_roles() == {}


@pytest.mark.asyncio
async def test_supervisor_without_restart_budget_leaves_failed_and_no_loss():
    """Control case: when the restart budget is exhausted the role is marked
    failed, but the items already durably persisted are still present exactly
    once (a crash never erases persisted evidence)."""
    queue = BaseRepository("chaos_queue_ctl")
    results = BaseRepository("chaos_results_ctl")
    state = DurableLoopState(queue, results)
    state.crashes_left = 99  # crash forever
    await state.seed()

    supervisor = WorkerSupervisor(
        environment=Environment.LOCAL,
        first_start_grace_s=0.0,
        watchdog_interval_s=30.0,
    )
    supervisor.register(WorkerSpec(
        name="chaos-permafail-worker",
        factory=build_worker(state),
        required=False,
        enabled=lambda: True,
        max_restarts=1,
        backoff_base_s=0.005,
        # healthy_run_s far above the crash uptime (~0s) -> the budget is never
        # earned back and the restart loop exhausts deterministically.
        healthy_run_s=300.0,
    ))
    await supervisor.start_all()
    try:
        await _wait_until(
            lambda: supervisor.status()["chaos-permafail-worker"]["state"] == "failed",
            timeout_s=15.0,
        )
    finally:
        await supervisor.stop_all()

    status = supervisor.status()["chaos-permafail-worker"]
    assert status["state"] == "failed"
    assert status["restarts"] >= 1
    # The items processed before each crash are still durably present, exactly
    # once (idempotent inserts across the restart loop).
    rows = await results.find_many(filters=None, limit=100)
    assert rows  # nothing persisted was lost
    payloads = [r["payload"] for r in rows]
    assert len(payloads) == len(set(payloads))  # no duplicates
