"""Aether Runtime — supervised dead-letter requeue sweeper.

Drains the platform's durable dead-letter stores so operator attention is the
only thing a stuck delivery needs, and nothing is silently dropped:

- **Rewards DLQ** (``reward_delivery_jobs`` in ``dead_letter`` state) —
  requeued to ``queued`` through the delivery-job repository, so the supervised
  reward outbox worker re-leases them with a fresh (bounded) attempt budget.
- **Payment dead-lettered receipts** (``ReceiptStage.DEAD_LETTERED``) — a tenant
  with dead-lettered receipts gets ONE idempotent canonical-repair pass
  (:meth:`PaymentRailsService.run_canonical_repair`), re-driving every
  recoverable (non-terminal) delivery under that tenant so stuck work actually
  progresses. Dead-lettered receipts themselves are parked for MANUAL operator
  replay on main (the payment-rails alert surface raises on the backlog); the
  branch's automatic un-dead-letter ``replay_dead_lettered`` is not re-ported.
- **Interop dead letters** (provider-checkpoint ``runtime.dead_letter_count``) —
  observation-only. There is no durable interop requeue seam, so the sweeper
  reports the accumulated depth and never fabricates a drain.

Design rules:

* **Never fabricates success.** Every requeue/replay is a real mutation routed
  through the owning system's idempotent entry points; anything that fails is
  counted and logged, never claimed drained.
* **Supervised-loop-shaped.** ``while True``, per-store and per-item exception
  isolation, a heartbeat gauge per iteration, and graceful shutdown on
  ``asyncio.CancelledError``.
* **Bounded per pass.** Each pass drains a bounded batch so a single saturated
  DLQ cannot monopolise the loop; subsequent passes continue where the batch
  ended (the stores' own leases / deterministic ids keep everything idempotent).

``build_dead_letter_sweeper_coro`` is the zero-arg coroutine factory the runtime
WorkerSpec imports.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.runtime.dead_letter_sweeper")

DEFAULT_SWEEP_INTERVAL_SECONDS = 600.0
DEFAULT_DLQ_BATCH = 25


def _now_iso() -> str:
    return utc_now().isoformat()


# ── per-store drain helpers ────────────────────────────────────────────────


async def _requeue_rewards_dlq(limit: int) -> dict[str, int]:
    """Requeue dead-lettered reward delivery jobs (bounded, idempotent)."""
    from services.rewards.delivery_outbox import RewardDeliveryJobRepository

    repo = RewardDeliveryJobRepository()
    dead = await repo.find_many(filters={"state": "dead_letter"}, limit=limit)
    requeued = 0
    errors = 0
    for job in dead:
        job_id = job.get("id")
        if not job_id:
            continue
        try:
            # Requeue to ``queued`` with an immediate next attempt; the reward
            # outbox worker's own lease/release cycle re-applies a bounded retry
            # budget from here. A re-scan of the SAME job after a failed requeue
            # is safe — the state transition is forward-only and idempotent.
            await repo.update(job_id, {
                "state": "queued",
                "next_attempt_at": _now_iso(),
                "leased_by": None,
                "lease_expires_at": None,
            })
            requeued += 1
        except Exception as exc:  # noqa: BLE001 — one job must not abort the drain
            errors += 1
            logger.warning("rewards DLQ requeue failed job=%s: %s", job_id, exc)
    return {"scanned": len(dead), "requeued": requeued, "errors": errors}


async def _replay_payment_dead_letters(limit: int) -> dict[str, int]:
    """Re-drive recoverable payment deliveries for tenants with dead letters.

    Main's canonical recovery for a dead-lettered payment receipt is a manual
    operator replay (the payment-rails alert surface raises on the dead-letter
    backlog); the branch's automatic un-dead-letter path
    (``PaymentRailsService.replay_dead_lettered``) is not part of main and is not
    re-ported. What the sweeper does instead for each tenant with dead-lettered
    receipts is run main's canonical repair pass
    (:meth:`PaymentRailsService.run_canonical_repair`) — the same idempotent
    pass the supervised ``payment_canonical_repair`` worker runs — which
    re-drives every recoverable (non-terminal) delivery under that tenant so
    stuck work progresses while unrecoverable receipts stay parked.
    """
    from services.integrations.providers.payment_rails.service import (
        get_payment_rails_service,
    )

    service = get_payment_rails_service()
    receipts = await service.repos.receipts.list_all()
    tenants_with_dead: set[str] = set()
    for receipt in receipts:
        if receipt.get("current_stage") == "dead_lettered":
            tenant_id = receipt.get("tenant_id")
            if tenant_id:
                tenants_with_dead.add(str(tenant_id))

    replayed = 0
    errors = 0
    per_tenant_limit = max(1, min(limit, 2000))
    for tenant_id in sorted(tenants_with_dead)[: max(1, limit)]:
        try:
            result = await service.run_canonical_repair(
                tenant_id, limit=per_tenant_limit
            )
            replayed += int(result.get("receipts_repaired", 0))
        except Exception as exc:  # noqa: BLE001 — one tenant must not abort the drain
            errors += 1
            logger.warning("payment DLQ replay failed tenant=%s: %s", tenant_id, exc)
    return {
        "tenants": len(tenants_with_dead),
        "replayed": replayed,
        "errors": errors,
    }


async def _interop_dead_letter_depth() -> int:
    """Accumulated interop dead-letter depth across provider checkpoints.

    Observation-only: interop quarantined observations have no durable requeue
    seam (the scan worker records ``dead_letter_count`` on the provider
    checkpoint's runtime evidence and restarts from its persisted cursor), so
    this reports the depth and never claims a drain.
    """
    from repositories.interop_repos import InteropProviderCheckpointRepo

    repo = InteropProviderCheckpointRepo()
    rows = await repo.find_many({}, limit=10000)
    depth = 0
    for row in rows:
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            continue
        runtime = evidence.get("runtime")
        if not isinstance(runtime, dict):
            continue
        try:
            depth += int(runtime.get("dead_letter_count", 0) or 0)
        except (TypeError, ValueError):  # pragma: no cover — defensive
            continue
    return depth


# ── one iteration ──────────────────────────────────────────────────────────


async def run_dead_letter_sweep_iteration(
    *,
    limit: int = DEFAULT_DLQ_BATCH,
    include_interop_depth: bool = True,
) -> dict[str, Any]:
    """Run one dead-letter drain pass. Returns a deterministic summary dict."""
    summary: dict[str, Any] = {
        "rewards_dlq": {"scanned": 0, "requeued": 0, "errors": 0},
        "payment_dlq": {"tenants": 0, "replayed": 0, "errors": 0},
        "interop_dead_letter_depth": 0,
    }
    # Rewards DLQ.
    try:
        summary["rewards_dlq"] = await _requeue_rewards_dlq(limit)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a store failure must not abort the pass
        logger.error("rewards DLQ drain failed: %s", exc)
        summary["rewards_dlq"]["errors"] += 1
    # Payment dead-lettered receipts.
    try:
        summary["payment_dlq"] = await _replay_payment_dead_letters(limit)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("payment DLQ drain failed: %s", exc)
        summary["payment_dlq"]["errors"] += 1
    # Interop depth (observation-only).
    if include_interop_depth:
        try:
            summary["interop_dead_letter_depth"] = await _interop_dead_letter_depth()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("interop dead-letter depth read failed: %s", exc)
    return summary


# ── supervised loop ────────────────────────────────────────────────────────


async def dead_letter_sweeper_loop(
    interval_s: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Supervised dead-letter drain loop (heartbeat, isolated errors)."""
    logger.info("dead_letter_sweeper_loop started interval=%ss", interval_s)
    while True:
        try:
            summary = await run_dead_letter_sweep_iteration()
            metrics.gauge("dead_letter_sweeper_heartbeat", 1.0)
            requeued = summary["rewards_dlq"]["requeued"]
            replayed = summary["payment_dlq"]["replayed"]
            depth = summary["interop_dead_letter_depth"]
            metrics.gauge("dead_letter_sweeper_interop_depth", float(depth))
            if requeued or replayed:
                logger.info(
                    "dead-letter drain pass requeued=%d replayed=%d interop_depth=%d",
                    requeued, replayed, depth,
                )
            elif depth:
                logger.debug("dead-letter drain pass no-op interop_depth=%d", depth)
        except asyncio.CancelledError:
            logger.info("dead_letter_sweeper_loop stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — loop survives a bad pass
            metrics.increment("dead_letter_sweeper_error_total")
            logger.error("dead-letter sweep iteration failed: %s", exc)
        await asyncio.sleep(interval_s)


def build_dead_letter_sweeper_coro() -> Coroutine[Any, Any, None]:
    """Zero-arg coroutine factory for the runtime WorkerSpec (INT-C wires it)."""
    return dead_letter_sweeper_loop()


__all__ = [
    "build_dead_letter_sweeper_coro",
    "dead_letter_sweeper_loop",
    "run_dead_letter_sweep_iteration",
]
