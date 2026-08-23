"""
Aether Backend — Reward Claim Reconciliation (A6)

Automated reconciliation between tenant delivery receipts and on-chain claims.
Binds the durable ledger (``reward_proofs``) to execution receipts
(``reward_execution_receipts``): when a receipt confirms that an on-chain claim
happened, the linked proof is marked ``used`` (single-use — replay protection)
and the action is transitioned to ``delivered``.

Nonce / replay protection lives here:
    guard_and_persist_proof(...)
        Refuses to persist a proof whose nonce is already used — the on-chain
        claim contract cannot be replayed because the same nonce is never
        issued twice.
    reconcile_receipt / reconcile_tenant
        Idempotent: a receipt that is already linked to a used proof is a no-op,
        and a proof is only ever marked ``used`` once.

The reconciler is read-mostly: it mutates only proof status and action status,
never receipt payloads. ``reconcile_loop`` is the supervised worker builder the
integration pass registers as an asyncio task.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger, metrics

from .repositories import (
    RewardActionRepository,
    RewardProofRepository,
    RewardReceiptRepository,
)

logger = get_logger("aether.service.rewards.reconcile")

# Receipt statuses that confirm an on-chain claim actually executed.
_CONFIRMED_STATUSES = frozenset({"success", "delivered", "confirmed", "executed"})

#: Sentinel tenant scope for ``build_reconcile_loop``: enumerate the tenants
#: that own delivery receipts on every pass instead of binding to one tenant.
ALL_TENANTS = "__all__"


class NonceReplayError(ValueError):
    """Raised when a proof nonce is already in use (replay attempt)."""

    def __init__(self, nonce: str) -> None:
        self.nonce = nonce
        super().__init__(f"proof nonce {nonce!r} is already used — replay blocked")


class RewardClaimReconciler:
    """Ties delivery receipts to on-chain claims and marks proofs used."""

    def __init__(
        self,
        proof_repo: Optional[RewardProofRepository] = None,
        action_repo: Optional[RewardActionRepository] = None,
        receipt_repo: Optional[RewardReceiptRepository] = None,
    ) -> None:
        self._proofs = proof_repo or RewardProofRepository()
        self._actions = action_repo or RewardActionRepository()
        self._receipts = receipt_repo or RewardReceiptRepository()

    # ── Nonce / replay guard ─────────────────────────────────────────

    async def is_nonce_available(self, nonce: str) -> bool:
        """True when the nonce has never been used (available to mint a proof)."""
        if not nonce:
            return False
        return not await self._proofs.is_nonce_used(nonce)

    async def guard_and_persist_proof(self, tenant_id: str, data: dict, nonce: str) -> dict:
        """Persist an on-chain claim proof with a nonce/replay guard.

        Raises :class:`NonceReplayError` if the nonce is already used, so the
        on-chain claim contract can never be replayed with the same nonce.
        """
        if not await self.is_nonce_available(nonce):
            raise NonceReplayError(nonce)
        record = await self._proofs.create(tenant_id, {**data, "nonce": nonce})
        metrics.increment("rewards_proofs_persisted_total", labels={"tenant_id": tenant_id})
        return record

    # ── Reconciliation ───────────────────────────────────────────────

    async def reconcile_receipt(self, tenant_id: str, receipt: dict) -> dict:
        """Reconcile a single receipt: mark its proof used, action delivered.

        Idempotent: returns ``{"changed": False}`` when the receipt is not a
        confirmed on-chain claim or its proof is already used.
        """
        status = receipt.get("status") or ""
        if status not in _CONFIRMED_STATUSES:
            return {"changed": False, "reason": "not_confirmed"}
        if receipt.get("rail") not in (None, "", "onchain_claim"):
            # Only on-chain claim receipts own a proof; other rails have no proof to mark.
            return {"changed": False, "reason": "not_onchain_claim"}

        proof_id = receipt.get("proof_id")
        action_id = receipt.get("action_payload_id")

        marked = False
        if proof_id:
            existing = await self._proofs.find_by_id(proof_id)
            if existing is not None and existing.get("tenant_id") == tenant_id:
                if existing.get("status") == "used":
                    return {"changed": False, "reason": "proof_already_used", "proof_id": proof_id}
                await self._proofs.mark_used(proof_id, tenant_id)
                marked = True
        elif action_id:
            # No separate proof row: the proof is embedded in the action payload.
            # ``marked`` is set ONLY when a new proof has been persisted AND
            # marked used — replay protection is the point of this path. An
            # action with no embedded nonce, an already-used nonce, or a proof
            # whose mark_used() failed is an explicit non-change, never a
            # delivered action.
            try:
                action = await self._actions.get(action_id, tenant_id)
            except Exception:
                action = None
            if not action:
                return {"changed": False, "reason": "action_missing", "action_payload_id": action_id}
            payload = action.get("payload") or {}
            embedded = (payload.get("proof") or {}).get("nonce") if payload.get("proof") else None
            if not embedded:
                return {"changed": False, "reason": "no_embedded_nonce", "action_payload_id": action_id}
            if await self._proofs.is_nonce_used(embedded):
                return {"changed": False, "reason": "embedded_nonce_already_used", "action_payload_id": action_id, "nonce": embedded}
            # Note: RewardProofRepository.create pins status to "created",
            # so mark the persisted row used explicitly.
            created = await self._proofs.create(tenant_id, {
                "decision_id": action.get("decision_id"),
                "action_payload_id": action_id,
                "tenant_id": tenant_id,
                "nonce": embedded,
                "user": (payload.get("proof") or {}).get("user"),
            })
            try:
                await self._proofs.mark_used(created["id"], tenant_id)
            except Exception as exc:  # noqa: BLE001 - surface as an explicit non-change
                logger.warning("mark proof used failed pid=%s: %s", created.get("id"), exc)
                return {
                    "changed": False,
                    "reason": "mark_used_failed",
                    "action_payload_id": action_id,
                    "proof_id": created.get("id"),
                }
            marked = True

        if marked and action_id:
            try:
                await self._actions.transition(action_id, tenant_id, "delivered")
            except Exception as exc:
                logger.warning("action transition failed after claim reconcile aid=%s: %s", action_id, exc)

        metrics.increment(
            "rewards_claims_reconciled_total",
            labels={"tenant_id": tenant_id, "changed": str(marked)},
        )
        return {
            "changed": marked,
            "proof_id": proof_id,
            "action_payload_id": action_id,
            "receipt_id": receipt.get("id"),
        }

    async def reconcile_tenant(self, tenant_id: str, limit: int = 200) -> dict:
        """Reconcile every delivery receipt for a tenant. Returns a summary."""
        receipts = await self._receipts.list(tenant_id, limit=limit)
        reconciled = 0
        already = 0
        skipped = 0
        details: list[dict] = []
        for receipt in receipts:
            try:
                result = await self.reconcile_receipt(tenant_id, receipt)
            except Exception as exc:  # noqa: BLE001 - one bad receipt must not block the rest
                logger.warning("receipt reconcile failed rid=%s: %s", receipt.get("id"), exc)
                details.append({"receipt_id": receipt.get("id"), "error": str(exc)})
                continue
            if result.get("changed"):
                reconciled += 1
            elif result.get("reason") == "proof_already_used":
                already += 1
            else:
                skipped += 1
            details.append(result)
        return {
            "tenant_id": tenant_id,
            "receipts_scanned": len(receipts),
            "reconciled": reconciled,
            "already_used": already,
            "skipped": skipped,
            "details": details,
            "reconciled_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }

    async def claim_reconciliation_status(self, tenant_id: str) -> dict:
        """Snapshot of proof vs receipt state for operator diagnostics."""
        proofs = await self._proofs.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        by_status: dict[str, int] = {}
        for p in proofs:
            s = p.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        receipts = await self._receipts.list(tenant_id, limit=1000)
        return {
            "tenant_id": tenant_id,
            "proofs_total": len(proofs),
            "proofs_by_status": by_status,
            "receipts_total": len(receipts),
            "reconcile_ready": sum(
                1 for r in receipts if r.get("status") in _CONFIRMED_STATUSES
            ),
        }

    # ── Supervised worker loop ───────────────────────────────────────

    def build_reconcile_loop(
        self,
        tenant_id: str,
        interval_s: float = 300.0,
    ) -> Callable[[], Awaitable[None]]:
        """Return an async loop that reconciles claims periodically.

        When ``tenant_id == ALL_TENANTS`` the loop discovers the tenants that
        own delivery receipts on every pass and reconciles each — a multi-tenant
        deployment must never bind the worker to one ``DEFAULT_TENANT_ID`` while
        every other tenant's confirmed claims sit unreconciled.
        """

        async def _loop() -> None:
            scope = tenant_id
            logger.info("reward_claim_reconcile_loop started interval=%ss tenant=%s", interval_s, scope)
            while True:
                try:
                    tids = (
                        await self._receipts.distinct_tenant_ids()
                        if scope == ALL_TENANTS
                        else [scope]
                    )
                    for tid in tids:
                        summary = await self.reconcile_tenant(tid)
                        if summary["reconciled"]:
                            logger.info(
                                "reward claim reconcile tenant=%s reconciled=%s scanned=%s",
                                tid, summary["reconciled"], summary["receipts_scanned"],
                            )
                except Exception as exc:  # noqa: BLE001 - loop survives
                    logger.error("reward claim reconcile iteration failed: %s", exc)
                await asyncio.sleep(interval_s)

        return _loop


# ── Module-level singleton ──────────────────────────────────────────────

_reconciler: Optional[RewardClaimReconciler] = None


def get_reward_claim_reconciler() -> RewardClaimReconciler:
    global _reconciler
    if _reconciler is None:
        _reconciler = RewardClaimReconciler()
    return _reconciler


def reset_reward_claim_reconciler() -> None:
    """Reset the reconciler — for tests only."""
    global _reconciler
    _reconciler = None


__all__ = [
    "RewardClaimReconciler",
    "NonceReplayError",
    "get_reward_claim_reconciler",
    "reset_reward_claim_reconciler",
]
