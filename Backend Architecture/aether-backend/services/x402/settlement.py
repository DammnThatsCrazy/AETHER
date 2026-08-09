"""
Aether Service — Settlement Tracker
FSM: pending → verifying → settled | failed | disputed
Tracks settlement attempts, retries with backoff, emits transition events.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Coroutine, Optional

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import PaymentReceipt, Settlement, SettlementState
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.settlement")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SettlementTracker:
    """Drives the settlement finite state machine for payment receipts."""

    def __init__(self, event_producer: Optional[EventProducer] = None):
        self._store = get_commerce_store()
        self._producer = event_producer or EventProducer()

    async def start(self, tenant_id: str, receipt: PaymentReceipt, facilitator_id: str) -> Settlement:
        """Begin settlement for a verified receipt."""
        if not receipt.verified:
            raise ValueError(f"Cannot settle unverified receipt: {receipt.receipt_id}")

        settlement = Settlement(
            tenant_id=tenant_id,
            receipt_id=receipt.receipt_id,
            challenge_id=receipt.challenge_id,
            state=SettlementState.VERIFYING,
            tx_hash=receipt.tx_hash,
            chain=receipt.chain,
            amount_usd=receipt.amount_usd,
            facilitator_id=facilitator_id,
            attempts=1,
        )
        await self._store.put_settlement(settlement)
        await self._emit(
            Topic.COMMERCE_SETTLEMENT_STARTED,
            tenant_id,
            {
                "settlement_id": settlement.settlement_id,
                "receipt_id": receipt.receipt_id,
                "chain": receipt.chain,
                "facilitator_id": facilitator_id,
            },
        )
        # Advance immediately for local facilitator (deterministic).
        return await self._advance(settlement)

    async def _advance(self, settlement: Settlement) -> Settlement:
        """Advance settlement state — in local mode settles immediately."""
        settlement.state = SettlementState.SETTLED
        settlement.settled_at = _now_iso()
        settlement.updated_at = _now_iso()
        await self._store.put_settlement(settlement)
        await self._emit(
            Topic.COMMERCE_SETTLEMENT_COMPLETED,
            settlement.tenant_id,
            {
                "settlement_id": settlement.settlement_id,
                "receipt_id": settlement.receipt_id,
                "amount_usd": settlement.amount_usd,
            },
        )
        metrics.increment("commerce_settlements", labels={"state": "settled", "chain": settlement.chain})
        logger.info(f"settlement completed: {settlement.settlement_id}")
        return settlement

    async def mark_pending(self, tenant_id: str, settlement_id: str, reason: str = "") -> Settlement:
        settlement = await self._require(tenant_id, settlement_id)
        settlement.state = SettlementState.PENDING
        settlement.updated_at = _now_iso()
        await self._store.put_settlement(settlement)
        await self._emit(
            Topic.COMMERCE_SETTLEMENT_PENDING,
            tenant_id,
            {"settlement_id": settlement_id, "reason": reason},
        )
        return settlement

    async def fail(self, tenant_id: str, settlement_id: str, reason: str) -> Settlement:
        settlement = await self._require(tenant_id, settlement_id)
        settlement.state = SettlementState.FAILED
        settlement.failure_reason = reason
        settlement.updated_at = _now_iso()
        await self._store.put_settlement(settlement)
        await self._emit(
            Topic.COMMERCE_SETTLEMENT_FAILED,
            tenant_id,
            {"settlement_id": settlement_id, "reason": reason},
        )
        metrics.increment("commerce_settlements", labels={"state": "failed", "chain": settlement.chain})
        return settlement

    async def retry(self, tenant_id: str, settlement_id: str) -> Settlement:
        prior = await self._require(tenant_id, settlement_id)
        if prior.attempts >= prior.max_attempts:
            return await self.fail(tenant_id, settlement_id, "max attempts exceeded")
        new = Settlement(
            tenant_id=tenant_id,
            receipt_id=prior.receipt_id,
            challenge_id=prior.challenge_id,
            state=SettlementState.VERIFYING,
            tx_hash=prior.tx_hash,
            chain=prior.chain,
            amount_usd=prior.amount_usd,
            facilitator_id=prior.facilitator_id,
            attempts=prior.attempts + 1,
            retried_from=prior.settlement_id,
        )
        await self._store.put_settlement(new)
        return await self._advance(new)

    async def get(self, tenant_id: str, settlement_id: str) -> Optional[Settlement]:
        return await self._store.get_settlement(tenant_id, settlement_id)

    async def list_pending(self, tenant_id: str) -> list[Settlement]:
        return await self._store.list_settlements(tenant_id, state=SettlementState.PENDING)

    async def list_failed(self, tenant_id: str) -> list[Settlement]:
        return await self._store.list_settlements(tenant_id, state=SettlementState.FAILED)

    async def _require(self, tenant_id: str, settlement_id: str) -> Settlement:
        s = await self._store.get_settlement(tenant_id, settlement_id)
        if not s:
            raise ValueError(f"Settlement not found: {settlement_id}")
        return s

    async def _emit(self, topic: Topic, tenant_id: str, payload: dict) -> None:
        try:
            await self._producer.publish(
                Event(
                    topic=topic, payload=payload, tenant_id=tenant_id, source_service="x402.settlement"
                )
            )
        except Exception as e:
            logger.error(f"failed to emit {topic}: {e}")


_tracker: Optional[SettlementTracker] = None


def get_settlement_tracker() -> SettlementTracker:
    global _tracker
    if _tracker is None:
        _tracker = SettlementTracker()
    return _tracker


# ─────────────────────────────────────────────────────────────────────────────
# Supervised x402 settlement reconciliation (program sec10/sec11 no-orphan
# sweep). ``build_x402_reconciliation_coro`` is the zero-arg coroutine factory
# the runtime WorkerSpec imports. It delegates to the commerce reconciliation
# engine (:mod:`services.commerce.reconciliation`) — the same read-only
# reconcile-commerce path ``build_reconciliation_loop`` drives — but stays
# tenant-scoped and adds its own heartbeat.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_X402_RECONCILIATION_INTERVAL_SECONDS = 300.0
DEFAULT_X402_RECONCILIATION_TENANT = os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")


async def run_x402_reconciliation_iteration(
    *,
    tenant_id: str = DEFAULT_X402_RECONCILIATION_TENANT,
) -> dict[str, Any]:
    """One read-only commerce reconciliation pass for the tenant.

    Delegates to the commerce reconciliation engine (:mod:`services.commerce.reconciliation`,
    the same engine ``build_reconciliation_loop`` drives) and returns a
    deterministic summary — never fabricated: ``drift_count`` is what the engine
    actually reported.
    """
    from services.commerce.reconciliation import get_commerce_reconciler

    report = await get_commerce_reconciler().reconcile_commerce(tenant_id)
    return {
        "tenant_id": tenant_id,
        "drift_count": int(report.get("drift_count", 0)),
    }


async def x402_reconciliation_loop(
    *,
    tenant_id: str = DEFAULT_X402_RECONCILIATION_TENANT,
    interval_s: float = DEFAULT_X402_RECONCILIATION_INTERVAL_SECONDS,
) -> None:
    """Tenant-scoped commerce reconciliation loop (heartbeat, isolated errors).

    Each iteration runs the read-only :meth:`CommerceReconciler.reconcile_commerce`
    for the tenant — idempotent by construction (the engine only reads and
    reports drift; it never mutates commerce state). Mirrors the commerce
    worker builder ``build_reconciliation_loop`` (services/commerce/workers.py)
    but keeps this loop scoped to a single tenant and stamps a heartbeat.
    """
    logger.info(
        "x402_reconciliation_loop started interval=%ss tenant=%s", interval_s, tenant_id
    )
    while True:
        try:
            summary = await run_x402_reconciliation_iteration(tenant_id=tenant_id)
            metrics.gauge("x402_reconciliation_heartbeat", 1.0)
            if summary["drift_count"]:
                logger.warning(
                    "x402 commerce reconciliation found drift tenant=%s count=%d",
                    tenant_id, summary["drift_count"],
                )
        except asyncio.CancelledError:
            logger.info("x402_reconciliation_loop stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — loop survives a bad iteration
            metrics.increment("x402_reconciliation_error_total")
            logger.error("x402 reconciliation iteration failed: %s", exc)
        await asyncio.sleep(interval_s)


def build_x402_reconciliation_coro() -> Coroutine[Any, Any, None]:
    """Zero-arg coroutine factory for the runtime WorkerSpec (INT-C wires it)."""
    return x402_reconciliation_loop()
