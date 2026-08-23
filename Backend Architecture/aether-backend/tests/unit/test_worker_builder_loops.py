"""Supervised-loop-shape tests for the credential-turnkey builder wave.

Each builder authored during the integration pass must be supervised-loop-shaped:
a zero-arg coroutine factory returning a FRESH coroutine, a ``while True`` loop
with per-iteration exception isolation, a heartbeat, graceful shutdown on
cancellation, and a deterministic per-iteration summary that never fabricates
success.

Covered builders (all registered by the runtime WorkerSpec in
``services/runtime/specs.py``):

- ``build_stablecoin_polling_loop``   (services/stablecoins/polling.py)
- ``build_venue_sweep_coro``          (services/derivatives/multi_venue.py)
- ``build_dead_letter_sweeper_coro``  (services/runtime/dead_letter_sweeper.py)

PORT-ADAPT: main's canonical x402 settlement reconciliation loop is
``services.rewards.workers.build_x402_settlement_reconciliation_worker`` (the
``x402_settlement_reconciliation`` spec), so it is NOT re-tested here — the
worker-topology suite pins its registration, and this suite pins the loop shape
for the sweep/poll builders that live in their domain modules.

The no-orphan / module-registration proof lives in ``test_worker_topology.py``;
this suite pins the loop *shape* for the same workers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Optional

import pytest

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinPollingCheckpointRepository
from repositories.typed_repo import reset_typed_in_memory_stores
from shared.store import reset_in_memory_stores as reset_shared_in_memory_stores
from services.rewards.delivery_outbox import RewardDeliveryJobRepository
from services.runtime import dead_letter_sweeper as dls
from services.derivatives import multi_venue as multi_venue
from services.stablecoins import polling as stable_polling


class _MetricsRecorder:
    """Capture stand-in for shared.logger.logger.metrics."""

    def __init__(self) -> None:
        self.increments: list[tuple[str, int, Optional[dict]]] = []
        self.gauges: list[tuple[str, float, Optional[dict]]] = []

    def increment(self, name: str, value: int = 1, labels: Optional[dict] = None) -> None:
        self.increments.append((name, value, labels))

    def gauge(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        self.gauges.append((name, value, labels))


async def _fast_summary(**overrides) -> dict:
    return {"ok": True, **overrides}


async def _assert_survives_and_cancels(loop_coro: object) -> None:
    """The loop must keep running after an iteration crash, then cancel cleanly."""
    task = asyncio.create_task(loop_coro)  # type: ignore[arg-type]
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), 0.15)
    # Still alive (the exception was isolated) -> cancel for graceful shutdown.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── factory shape: zero-arg, returns a fresh coroutine ─────────────────────


@pytest.mark.parametrize(
    "factory",
    [
        stable_polling.build_stablecoin_polling_loop,
        multi_venue.build_venue_sweep_coro,
        dls.build_dead_letter_sweeper_coro,
    ],
)
def test_factory_returns_fresh_coroutine(factory):
    first = factory()
    second = factory()
    assert asyncio.iscoroutine(first)
    assert asyncio.iscoroutine(second)
    assert first is not second, "factory must return a FRESH coroutine per call"
    first.close()
    second.close()


# ── stablecoin provider polling loop ───────────────────────────────────────


def test_stablecoin_iteration_returns_deterministic_summary():
    class _FakeResult:
        def __init__(self, *, status="healthy", scanned=0):
            self.status = status
            self.scanned = scanned

    class _FakeScheduler:
        def __init__(self) -> None:
            self.provider_calls = 0
            self.finality_calls = 0
            # The supervised loop reads the durable polling checkpoint before
            # each provider pass, so the double needs a real checkpoint repo.
            self.checkpoints = StablecoinPollingCheckpointRepository()

        async def poll_provider(self, **kwargs):
            self.provider_calls += 1
            return _FakeResult(status="healthy")

        async def poll_finality(self, **kwargs):
            self.finality_calls += 1
            return _FakeResult(status="healthy", scanned=3)

    deployment = SimpleNamespace(
        chain_id="1", token_standard="ERC-20", contract_or_mint="0xabc"
    )
    # Mirrors StablecoinConnectorRegistry: .deployments is a
    # StablecoinDeploymentRegistry whose own .deployments is the id -> deployment
    # dict (see services/stablecoins/registry.py).
    registry = SimpleNamespace(
        deployments=SimpleNamespace(deployments={"usdc:eth": deployment}),
        build_ingestion_connector=lambda deployment_id: SimpleNamespace(
            provider="usdc", source_manifest_id="manifest"
        ),
    )
    scheduler = _FakeScheduler()

    summary = asyncio.run(stable_polling.run_stablecoin_poll_iteration(
        tenant_id="tenant-test",
        scheduler=scheduler,
        connector_registry=registry,
        provider_cooldown_seconds=0,
        finality_cooldown_seconds=0,
    ))

    assert summary["tenant_id"] == "tenant-test"
    assert summary["deployments"] == 1
    assert summary["providers_polled"] == 1
    assert summary["denied"] == 0
    assert summary["finality_scanned"] == 3
    assert summary["errors"] == []
    assert scheduler.provider_calls == 1
    assert scheduler.finality_calls == 1


def test_stablecoin_loop_survives_iteration_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(stable_polling, "run_stablecoin_poll_iteration", boom)
    asyncio.run(_assert_survives_and_cancels(
        stable_polling.stablecoin_polling_loop(interval_s=0.001)
    ))


def test_stablecoin_loop_graceful_shutdown_and_heartbeat(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(stable_polling, "metrics", recorder)
    monkeypatch.setattr(
        stable_polling, "run_stablecoin_poll_iteration",
        lambda **kwargs: _fast_summary(
            providers_polled=0, denied=0, finality_scanned=0, errors=[],
        ),
    )

    async def _drive():
        task = asyncio.create_task(stable_polling.stablecoin_polling_loop(interval_s=0.001))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert any(name == "stablecoin_provider_polling_heartbeat" for name, *_ in recorder.gauges)


def test_stablecoin_iteration_resumes_from_persisted_cursor():
    """A connector that paginates beyond its first page must resume from the
    durable polling checkpoint on the next supervised pass — not re-fetch page
    one forever with the default empty cursor."""
    reset_in_memory_stores()

    class _PaginatingConnector:
        provider = "usdc"
        source_manifest_id = "manifest"

        def __init__(self):
            self.received_cursors: list[str] = []

        async def fetch_observations(self, *, tenant_id, cursor="", limit=100):
            self.received_cursors.append(cursor)
            if not cursor:
                return ["page1-obs"], "page-2"
            return ["page2-obs"], ""

    class _FakeRunner:
        async def run_execution(self, **kwargs):
            rows = list(kwargs.get("observations") or [])
            return SimpleNamespace(
                health_status="healthy",
                rows_observed=len(rows),
                rows_accepted=len(rows),
                rows_rejected=0,
            )

        async def record_provider_failure(self, **kwargs):
            return None

    connector = _PaginatingConnector()
    deployment = SimpleNamespace(chain_id="", token_standard="ERC-20")
    registry = SimpleNamespace(
        deployments=SimpleNamespace(deployments={"usdc:eth": deployment}),
        build_ingestion_connector=lambda deployment_id: connector,
    )
    scheduler = stable_polling.StablecoinPollingScheduler(
        runner=_FakeRunner(),
        evm_verifier=SimpleNamespace(),
        solana_verifier=SimpleNamespace(),
    )
    kwargs = dict(
        tenant_id="tenant-test",
        scheduler=scheduler,
        connector_registry=registry,
        provider_cooldown_seconds=0,
        finality_cooldown_seconds=0,
    )

    summary = asyncio.run(stable_polling.run_stablecoin_poll_iteration(**kwargs))
    assert summary["providers_polled"] == 1
    assert summary["errors"] == []
    assert connector.received_cursors == [""]  # first pass starts fresh

    summary2 = asyncio.run(stable_polling.run_stablecoin_poll_iteration(**kwargs))
    assert summary2["providers_polled"] == 1
    assert summary2["errors"] == []
    # The second pass resumed at page 2 from the persisted checkpoint cursor.
    assert connector.received_cursors == ["", "page-2"]

    reset_in_memory_stores()


# ── derivatives venue sweep loop ───────────────────────────────────────────


def test_venue_sweep_iteration_summary(monkeypatch):
    class _FakeResult:
        completed = True

    class _FakeWorker:
        def __init__(self, *args, **kwargs):
            pass

        async def run_once(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr(
        "services.derivatives.sequence.SupervisedStreamWorker", _FakeWorker
    )
    monkeypatch.setattr(
        "services.derivatives.adapters.get_adapter",
        lambda venue_id: SimpleNamespace(venue_id=venue_id),
    )

    summary = asyncio.run(multi_venue.run_venue_sweep_iteration(
        tenant_id="tenant-test", venue_ids=("dydx", "gmx"),
    ))
    assert summary["tenant_id"] == "tenant-test"
    assert summary["venues_targeted"] == 2
    assert summary["venues_scanned"] == 2
    assert summary["completed"] == 2
    assert summary["skipped"] == 0
    assert summary["errors"] == []


def test_venue_sweep_iteration_skips_unregistered_venue(monkeypatch):
    monkeypatch.setattr(
        "services.derivatives.adapters.get_adapter", lambda venue_id: None
    )
    summary = asyncio.run(multi_venue.run_venue_sweep_iteration(
        tenant_id="tenant-test", venue_ids=("hyperliquid",),
    ))
    assert summary["venues_scanned"] == 0
    assert summary["skipped"] == 1


def test_venue_sweep_loop_survives_iteration_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(multi_venue, "run_venue_sweep_iteration", boom)
    asyncio.run(_assert_survives_and_cancels(
        multi_venue.venue_sweep_loop(interval_s=0.001)
    ))


def test_venue_sweep_loop_graceful_shutdown_and_heartbeat(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(multi_venue, "metrics", recorder)
    monkeypatch.setattr(
        multi_venue, "run_venue_sweep_iteration",
        lambda **kwargs: _fast_summary(
            venues_scanned=0, skipped=0, completed=0, errors=[],
        ),
    )

    async def _drive():
        task = asyncio.create_task(multi_venue.venue_sweep_loop(interval_s=0.001))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert any(name == "derivatives_venue_sweep_heartbeat" for name, *_ in recorder.gauges)


def test_venue_sweep_covers_every_persisted_checkpoint_tenant(monkeypatch):
    """The sweep loop must discover every tenant that holds a durable
    connector checkpoint — not bind to the local-dev default tenant."""
    from repositories.derivatives_repos import ConnectorCheckpointRepo
    from services.derivatives.durable_cursor import persist_connector_checkpoint

    reset_typed_in_memory_stores()

    async def _seed():
        repo = ConnectorCheckpointRepo()
        for tid, connector in (("tenant-alpha", "dydx"), ("tenant-beta", "gmx")):
            await persist_connector_checkpoint(
                repo,
                tenant_id=tid,
                connector_id=connector,
                checkpoint_value='{"stream": 1}',
                state="ok",
            )

    asyncio.run(_seed())

    seen: list[str] = []

    async def _spy(*, tenant_id, venue_ids=None, **kwargs):
        seen.append(tenant_id)
        return {
            "tenant_id": tenant_id,
            "venues_targeted": 0,
            "venues_scanned": 0,
            "completed": 0,
            "skipped": 0,
            "errors": [],
        }

    monkeypatch.setattr(multi_venue, "run_venue_sweep_iteration", _spy)

    async def _drive():
        task = asyncio.create_task(multi_venue.venue_sweep_loop(interval_s=0.001))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert "tenant-alpha" in seen and "tenant-beta" in seen
    reset_typed_in_memory_stores()


# ── dead-letter sweeper loop ───────────────────────────────────────────────


def test_dead_letter_sweep_iteration_returns_deterministic_summary():
    # The summary asserts ABSOLUTE zero counts across the rewards DLQ (repos.py
    # registry) and the payment dead-letter receipts (shared.store registry).
    # Reset both registries so a sibling test that dead-lettered a payment
    # receipt on the same xdist worker cannot bleed rows into this assertion.
    reset_in_memory_stores()
    reset_shared_in_memory_stores()
    summary = asyncio.run(dls.run_dead_letter_sweep_iteration(
        limit=1, include_interop_depth=False,
    ))
    assert set(summary) == {"rewards_dlq", "payment_dlq", "interop_dead_letter_depth"}
    assert summary["rewards_dlq"]["scanned"] == 0
    assert summary["payment_dlq"]["tenants"] == 0
    assert summary["interop_dead_letter_depth"] == 0


def test_dead_letter_sweeper_loop_survives_iteration_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(dls, "run_dead_letter_sweep_iteration", boom)
    asyncio.run(_assert_survives_and_cancels(
        dls.dead_letter_sweeper_loop(interval_s=0.001)
    ))


def test_dead_letter_sweeper_loop_graceful_shutdown_and_heartbeat(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(dls, "metrics", recorder)
    monkeypatch.setattr(
        dls, "run_dead_letter_sweep_iteration",
        lambda **kwargs: _fast_summary(
            rewards_dlq={"scanned": 0, "requeued": 0, "errors": 0},
            payment_dlq={"tenants": 0, "replayed": 0, "errors": 0},
            interop_dead_letter_depth=0,
        ),
    )

    async def _drive():
        task = asyncio.create_task(dls.dead_letter_sweeper_loop(interval_s=0.001))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert any(name == "dead_letter_sweeper_heartbeat" for name, *_ in recorder.gauges)


# ── rewards DLQ: explicit replay eligibility ───────────────────────────────

def _dead_letter_job(job_id: str, **extra) -> dict:
    """A terminal reward delivery job row in the ``dead_letter`` state."""
    from datetime import datetime, timedelta, timezone
    job = {
        "tenant_id": "tenant_dlq",
        "state": "dead_letter",
        "provider_adapter": "tenant_webhook",
        "channel": "webhook",
        "payload": {"event": "reward.action.ready"},
        "attempt_count": 6,
        "max_attempts": 6,
        "last_error": "terminal failure",
    }
    job.update(extra)
    return job


def test_rewards_dlq_requeue_parks_jobs_without_replay_authorization():
    reset_in_memory_stores()
    repo = RewardDeliveryJobRepository()
    asyncio.run(repo.insert("dlq-parked-1", _dead_letter_job("dlq-parked-1")))

    summary = asyncio.run(dls._requeue_rewards_dlq(limit=25))
    assert summary["scanned"] == 1
    assert summary["requeued"] == 0
    assert summary["parked"] == 1

    # The job stays parked in dead_letter — no every-pass auto-requeue.
    after = asyncio.run(repo.find_by_id("dlq-parked-1"))
    assert after["state"] == "dead_letter"
    assert after["attempt_count"] == 6
    reset_in_memory_stores()


def test_rewards_dlq_requeues_replay_requested_job_with_reset_budget():
    reset_in_memory_stores()
    repo = RewardDeliveryJobRepository()
    asyncio.run(repo.insert(
        "dlq-replay-1", _dead_letter_job("dlq-replay-1", replay_requested=True)
    ))

    summary = asyncio.run(dls._requeue_rewards_dlq(limit=25))
    assert summary["requeued"] == 1
    assert summary["parked"] == 0

    after = asyncio.run(repo.find_by_id("dlq-replay-1"))
    assert after["state"] == "queued"
    assert after["attempt_count"] == 0  # fresh bounded retry budget
    assert after.get("replay_requested") is False  # marker cleared
    reset_in_memory_stores()


def test_rewards_dlq_requeues_replay_at_due_job_and_parks_future():
    from datetime import datetime, timedelta, timezone
    reset_in_memory_stores()
    repo = RewardDeliveryJobRepository()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    asyncio.run(repo.insert("dlq-sched-future", _dead_letter_job("dlq-sched-future", replay_at=future)))
    asyncio.run(repo.insert("dlq-sched-due", _dead_letter_job("dlq-sched-due", replay_at=past)))

    summary = asyncio.run(dls._requeue_rewards_dlq(limit=25))
    assert summary["scanned"] == 2
    assert summary["requeued"] == 1
    assert summary["parked"] == 1

    assert asyncio.run(repo.find_by_id("dlq-sched-future"))["state"] == "dead_letter"
    due = asyncio.run(repo.find_by_id("dlq-sched-due"))
    assert due["state"] == "queued"
    assert due["attempt_count"] == 0
    assert due.get("replay_at") is None  # marker cleared
    reset_in_memory_stores()
