"""
Aether Service — Settlement Tracker
FSM: pending → verifying → settled | failed | disputed
Tracks settlement attempts, retries with backoff, emits transition events.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import PaymentReceipt, Settlement, SettlementState
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.settlement")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


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
        """Advance settlement state.

        Local environment: settles immediately (deterministic dev loop).
        Everywhere else: parks the settlement in PENDING — SETTLED means
        on-chain finality has been confirmed, which only the reconciliation
        path (or an explicit operator action) may assert. Unconditional
        auto-settlement outside local overstated settlement truth.
        """
        if not _is_local_env():
            settlement.state = SettlementState.PENDING
            settlement.updated_at = _now_iso()
            await self._store.put_settlement(settlement)
            await self._emit(
                Topic.COMMERCE_SETTLEMENT_PENDING,
                settlement.tenant_id,
                {
                    "settlement_id": settlement.settlement_id,
                    "receipt_id": settlement.receipt_id,
                    "reason": "awaiting on-chain finality confirmation",
                },
            )
            metrics.increment(
                "commerce_settlements", labels={"state": "pending", "chain": settlement.chain}
            )
            return settlement

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
