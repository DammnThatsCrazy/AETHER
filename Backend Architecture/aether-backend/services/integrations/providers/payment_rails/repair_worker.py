"""Payment Rail Observability — supervised canonical-repair worker.

Deterministic canonical delivery can leave gaps that no webhook or poll will
close on its own: a crash between a funding-session write and its canonical
emission, or an outbox-relay outage while the durable path is enabled, strands a
receipt short of ``completed``. Webhook/poll handling never runs on a timer, so
nothing re-drives those deliveries without a periodic sweep.

This supervised worker closes that gap. Each cycle it scans the durable receipt
ledger for incomplete deliveries (grouped by tenant, re-scoped per tenant) and
calls :meth:`PaymentRailsService.run_canonical_repair`, which idempotently
re-drives canonical emission (re-emitting missing canonical events and
re-enqueuing missing outbox rows — the deterministic canonical id dedupes both),
advances the receipt, and dead-letters a delivery that can never complete.

Everything is best-effort and tenant-scoped: a failure for one tenant is logged
and metered, never aborting the cycle or leaking across tenants. Idempotent by
construction — repeated cycles never double-emit or double-bill. Aether observes;
this worker never executes, settles, or custodies.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

from services.integrations.providers.payment_rails.service import (
    PaymentRailsService,
    get_payment_rails_service,
)

logger = get_logger("aether.payment_rails.repair_worker")

# Default cadence. Repair is a safety net behind synchronous emission + the
# supervised outbox relay, so a few sweeps per hour is ample.
PAYMENT_RAIL_REPAIR_INTERVAL_SECONDS = 10 * 60


async def run_repair_cycle(
    *,
    service: Optional[PaymentRailsService] = None,
    limit_per_tenant: int = 500,
) -> dict[str, int]:
    """Run one repair sweep over incomplete receipts across tenants.

    Cross-tenant enumeration is a control-plane sweep (never surfaced to a
    tenant); every read/write is re-scoped to the owning tenant. Returns
    per-cycle counters for logging/tests.
    """
    service = service or get_payment_rails_service()

    receipts = await service.repos.receipts.list_all()
    by_tenant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        tenant_id = receipt.get("tenant_id")
        if tenant_id:
            by_tenant[tenant_id].append(receipt)

    stats = {
        "tenants": 0, "receipts_scanned": 0, "receipts_repaired": 0,
        "receipts_dead_lettered": 0, "sessions_repaired": 0, "events_reemitted": 0,
    }
    for tenant_id in by_tenant:
        stats["tenants"] += 1
        try:
            result = await service.run_canonical_repair(tenant_id, limit=limit_per_tenant)
        except Exception as exc:  # noqa: BLE001 — one tenant must not abort the sweep
            logger.warning(
                "payment_rail_repair failed tenant=%s: %s", tenant_id, exc,
            )
            metrics.increment("payment_rail_repair_error_total", labels={"stage": "tenant"})
            continue
        stats["receipts_scanned"] += result.get("receipts_scanned", 0)
        stats["receipts_repaired"] += result.get("receipts_repaired", 0)
        stats["receipts_dead_lettered"] += result.get("receipts_dead_lettered", 0)
        stats["sessions_repaired"] += result.get("sessions_repaired", 0)
        stats["events_reemitted"] += result.get("events_reemitted", 0)

    metrics.increment("payment_rail_repair_cycle_total")
    metrics.gauge("payment_rail_repair_heartbeat", 1.0)
    # Post-cycle backlog gauges for alerting (canonical backlog, oldest incomplete
    # receipt age). Recomputed from the ledger so a stalled relay/repair surfaces.
    from datetime import datetime, timezone

    from shared.temporal.instant import ensure_aware_utc

    from services.integrations.providers.payment_rails.receipts import (
        COMPLETE_STAGES, TERMINAL_STATES,
    )

    post = await service.repos.receipts.list_all()
    incomplete = [
        r for r in post
        if r.get("current_stage") not in COMPLETE_STAGES
        and r.get("current_stage") not in TERMINAL_STATES
    ]
    metrics.gauge("payment_rail_canonical_backlog", float(len(incomplete)))
    now = datetime.now(timezone.utc)
    oldest_age = 0.0
    for r in incomplete:
        ts = r.get("received_at")
        if not ts:
            continue
        try:
            parsed = ensure_aware_utc(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
            oldest_age = max(oldest_age, (now - parsed).total_seconds())
        except (ValueError, TypeError):
            continue
    metrics.gauge("payment_rail_oldest_incomplete_receipt_seconds", oldest_age)
    if stats["receipts_dead_lettered"]:
        metrics.increment(
            "payment_rail_repair_dead_lettered_total",
            value=stats["receipts_dead_lettered"],
        )
    logger.info(
        "payment_rail_repair cycle complete tenants=%d scanned=%d repaired=%d "
        "dead_lettered=%d events_reemitted=%d",
        stats["tenants"], stats["receipts_scanned"], stats["receipts_repaired"],
        stats["receipts_dead_lettered"], stats["events_reemitted"],
    )
    return stats


async def run_payment_canonical_repair_loop(
    interval_seconds: int = PAYMENT_RAIL_REPAIR_INTERVAL_SECONDS,
) -> None:
    """Supervised periodic canonical-repair sweep."""
    while True:
        try:
            await run_repair_cycle()
        except Exception as exc:  # pragma: no cover — supervisor also guards
            logger.warning("payment_rail_repair cycle failed: %s", exc)
            metrics.increment("payment_rail_repair_error_total", labels={"stage": "cycle"})
        await asyncio.sleep(interval_seconds)


def build_payment_canonical_repair_coro():
    """Fresh coroutine for the WorkerSupervisor (one per (re)start)."""
    return run_payment_canonical_repair_loop()
