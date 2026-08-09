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
- ``build_x402_reconciliation_coro``  (services/x402/settlement.py)
- ``build_dead_letter_sweeper_coro``  (services/runtime/dead_letter_sweeper.py)
- ``build_settlement_reconciliation_coro`` (services/integrations/providers/
  payment_rails/settlement.py)

The no-orphan / module-registration proof lives in ``test_worker_topology.py``;
this suite pins the loop *shape* for the same workers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Optional

import pytest

from services.integrations.providers.payment_rails import settlement as pr_settlement
from services.runtime import dead_letter_sweeper as dls
from services.derivatives import multi_venue as multi_venue
from services.stablecoins import polling as stable_polling
from services.x402 import settlement as x402_settlement


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
        x402_settlement.build_x402_reconciliation_coro,
        dls.build_dead_letter_sweeper_coro,
        pr_settlement.build_settlement_reconciliation_coro,
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


# ── x402 settlement reconciliation loop ────────────────────────────────────


def test_x402_iteration_returns_deterministic_summary(monkeypatch):
    class _FakeReconciler:
        async def reconcile_commerce(self, tenant_id: str) -> dict:
            return {"tenant_id": tenant_id, "drift_count": 2}

    monkeypatch.setattr(
        "services.commerce.reconciliation.get_commerce_reconciler",
        lambda: _FakeReconciler(),
    )
    summary = asyncio.run(x402_settlement.run_x402_reconciliation_iteration(
        tenant_id="tenant-test",
    ))
    assert summary == {"tenant_id": "tenant-test", "drift_count": 2}


def test_x402_loop_survives_iteration_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(x402_settlement, "run_x402_reconciliation_iteration", boom)
    asyncio.run(_assert_survives_and_cancels(
        x402_settlement.x402_reconciliation_loop(interval_s=0.001)
    ))


def test_x402_loop_graceful_shutdown_and_heartbeat(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(x402_settlement, "metrics", recorder)
    monkeypatch.setattr(
        x402_settlement, "run_x402_reconciliation_iteration",
        lambda **kwargs: _fast_summary(drift_count=0),
    )

    async def _drive():
        task = asyncio.create_task(
            x402_settlement.x402_reconciliation_loop(interval_s=0.001)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert any(name == "x402_reconciliation_heartbeat" for name, *_ in recorder.gauges)


# ── dead-letter sweeper loop ───────────────────────────────────────────────


def test_dead_letter_sweep_iteration_returns_deterministic_summary():
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


# ── payment-rails settlement reconciliation loop ───────────────────────────


def test_settlement_iteration_returns_deterministic_summary():
    summary = asyncio.run(pr_settlement.run_settlement_reconciliation_iteration(
        limit_per_tenant=10,
    ))
    assert isinstance(summary, dict)
    assert summary["receipts_scanned"] == 0
    assert summary["receipts_repaired"] == 0
    assert summary["receipts_dead_lettered"] == 0


def test_settlement_loop_survives_iteration_error(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pr_settlement, "run_settlement_reconciliation_iteration", boom)
    asyncio.run(_assert_survives_and_cancels(
        pr_settlement.settlement_reconciliation_loop(interval_s=0.001)
    ))


def test_settlement_loop_graceful_shutdown_and_heartbeat(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(pr_settlement, "metrics", recorder)
    monkeypatch.setattr(
        pr_settlement, "run_settlement_reconciliation_iteration",
        _fast_summary,
    )

    async def _drive():
        task = asyncio.create_task(
            pr_settlement.settlement_reconciliation_loop(interval_s=0.001)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert any(
        name == "settlement_reconciliation_heartbeat" for name, *_ in recorder.gauges
    )
