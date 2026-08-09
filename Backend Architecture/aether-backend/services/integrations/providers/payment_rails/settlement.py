"""Payment Rail Observability — supervised settlement reconciliation worker.

Closes the settlement-state convergence gap: deterministic canonical delivery
can leave incomplete receipts and funding-session emission gaps that no webhook
or poll re-drives on its own. This supervised worker runs the payment-rails
canonical reconciliation/repair seam (:func:`run_repair_cycle`, which drives
:meth:`PaymentRailsService.run_canonical_repair` per tenant) on its own cadence,
idempotently re-emitting missing canonical events and re-enqueuing missing
outbox rows (the deterministic canonical id dedupes both paths) and advancing
stuck receipts.

Everything is best-effort and tenant-scoped: a failure for one tenant is logged
and metered, never aborting the cycle or leaking across tenants. Idempotent by
construction — repeated cycles never double-emit or double-bill. Aether observes;
this worker never executes, settles, or custodies. It deliberately does NOT
duplicate x402 settlement reconciliation (which is owned by
:mod:`services.x402.settlement`).

``build_settlement_reconciliation_coro`` is the zero-arg coroutine factory the
runtime WorkerSpec imports; the loop is supervised-loop-shaped (while True,
per-iteration exception isolation, heartbeat, graceful shutdown).
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.payment_rails.settlement")

DEFAULT_SETTLEMENT_RECONCILIATION_INTERVAL_SECONDS = 10 * 60
DEFAULT_LIMIT_PER_TENANT = 500


async def run_settlement_reconciliation_iteration(
    *,
    service: Any = None,
    limit_per_tenant: int = DEFAULT_LIMIT_PER_TENANT,
) -> dict[str, int]:
    """Run one settlement reconciliation pass over the payment-rails ledger.

    Delegates to :func:`~services.integrations.providers.payment_rails.repair_worker.run_repair_cycle`
    — the canonical repair seam — which scans incomplete receipts and
    funding-session emission gaps across tenants and re-drives canonical
    emission idempotently. Returns the per-cycle counters.
    """
    from services.integrations.providers.payment_rails.repair_worker import (
        run_repair_cycle,
    )

    return await run_repair_cycle(service=service, limit_per_tenant=limit_per_tenant)


async def settlement_reconciliation_loop(
    interval_s: float = DEFAULT_SETTLEMENT_RECONCILIATION_INTERVAL_SECONDS,
) -> None:
    """Supervised settlement reconciliation loop (heartbeat, isolated errors)."""
    logger.info("settlement_reconciliation_loop started interval=%ss", interval_s)
    while True:
        try:
            stats = await run_settlement_reconciliation_iteration()
            metrics.gauge("settlement_reconciliation_heartbeat", 1.0)
            repaired = int(stats.get("receipts_repaired", 0))
            dead_lettered = int(stats.get("receipts_dead_lettered", 0))
            reemitted = int(stats.get("events_reemitted", 0))
            if repaired or dead_lettered:
                logger.info(
                    "settlement reconciliation pass repaired=%d dead_lettered=%d reemitted=%d",
                    repaired, dead_lettered, reemitted,
                )
        except asyncio.CancelledError:
            logger.info("settlement_reconciliation_loop stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — loop survives a bad pass
            metrics.increment("settlement_reconciliation_error_total")
            logger.error("settlement reconciliation iteration failed: %s", exc)
        await asyncio.sleep(interval_s)


def build_settlement_reconciliation_coro() -> Coroutine[Any, Any, None]:
    """Zero-arg coroutine factory for the runtime WorkerSpec (INT-C wires it)."""
    return settlement_reconciliation_loop()


__all__ = [
    "build_settlement_reconciliation_coro",
    "run_settlement_reconciliation_iteration",
    "settlement_reconciliation_loop",
]
