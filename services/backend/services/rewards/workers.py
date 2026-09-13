"""Reward-plane maintenance worker loops.

Supervised loop builders for reward/x402/credential reconciliation, repair, and
sweep workers. Each returns a long-running coroutine (for
``services/runtime/specs.py``) that ticks on an interval, is cancellation-safe,
tenant-isolated, and idempotent. None auto-starts — the runtime supervisor owns
their lifecycle. A tick whose dependency is not yet wired logs and no-ops
rather than crashing the supervised loop.
"""

from __future__ import annotations

import asyncio

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.rewards.workers")


async def _run_loop(name: str, tick, interval_seconds: float) -> None:
    logger.info("%s worker started", name)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            logger.info("%s worker stopped", name)
            raise
        except Exception as exc:  # noqa: BLE001 — a loop must never die on one tick
            logger.error("%s worker tick error: %s", name, exc)
            metrics.increment("reward_worker_tick_errors", labels={"worker": name})
        await asyncio.sleep(interval_seconds)


async def build_reward_reservation_release_worker(interval_seconds: float = 300.0) -> None:
    """Release stale budget reservations that were never committed/released."""
    from services.rewards.budget import BudgetReservationService

    svc = BudgetReservationService()

    async def tick() -> None:
        released = await svc.release_stale()
        if released:
            metrics.increment("reward_stale_reservations_released", value=released)

    await _run_loop("reward_reservation_release", tick, interval_seconds)


async def build_reward_dlq_sweeper(interval_seconds: float = 600.0) -> None:
    """Surface dead-lettered reward delivery jobs for operator review (metrics
    only — replay stays an explicit operator action)."""
    from services.rewards.delivery_outbox import RewardDeliveryOutbox

    outbox = RewardDeliveryOutbox()

    async def tick() -> None:
        depth = await outbox.dead_letter_depth()
        metrics.observe("reward_dlq_depth", float(depth))

    await _run_loop("reward_dlq_sweeper", tick, interval_seconds)


async def build_x402_settlement_reconciliation_worker(interval_seconds: float = 120.0) -> None:
    """Advance PENDING x402 settlements to SETTLED on confirmed finality."""
    from services.x402.commerce_store import get_commerce_store
    from services.x402.reconciliation import get_reconciliation_worker

    worker = get_reconciliation_worker()
    store = get_commerce_store()

    async def tick() -> None:
        tenants = await store.tenants_with_pending_settlements()
        for tenant_id in tenants:
            await worker.reconcile_tenant(tenant_id)

    await _run_loop("x402_settlement_reconciliation", tick, interval_seconds)


async def build_credential_expiry_sweep(interval_seconds: float = 3600.0) -> None:
    """Sweep expired credential rotation-overlap windows across tenants."""
    from services.providers.credentials.authority import credential_authority

    async def tick() -> None:
        swept = await credential_authority.sweep_expired_overlaps()
        if swept:
            metrics.increment("credential_overlaps_swept", value=swept)

    await _run_loop("credential_expiry_sweep", tick, interval_seconds)


__all__ = [
    "build_reward_reservation_release_worker",
    "build_reward_dlq_sweeper",
    "build_x402_settlement_reconciliation_worker",
    "build_credential_expiry_sweep",
]
