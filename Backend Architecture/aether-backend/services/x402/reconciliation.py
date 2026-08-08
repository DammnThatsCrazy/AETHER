"""x402 settlement reconciliation worker.

Outside local, ``SettlementTracker._advance`` parks a verified settlement in
PENDING — SETTLED means confirmed on-chain finality, which only this worker
(or an explicit operator action) may assert. The worker periodically re-checks
each PENDING settlement's payment against the tenant's RPC and, when the
transaction is final, advances it to SETTLED; a settlement whose transaction
reverted or exceeded its attempt budget is failed.

Durable cursor: the worker persists a per-run checkpoint in
``x402_reconciliation_cursor`` (last scan time + counts) so an operator can
inspect progress and lag. It is tenant-isolated (re-scoped per tenant), has a
kill switch (skips SUSPENDED x402 capabilities), and is idempotent (advancing
an already-SETTLED settlement is a no-op).
"""

from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from .commerce_models import SettlementState
from .commerce_store import get_commerce_store
from .settlement import get_settlement_tracker
from .verification import get_verification_engine

logger = get_logger("aether.x402.reconciliation")

CURSOR_TABLE = "x402_reconciliation_cursor"


class X402ReconciliationWorker:
    """Re-checks PENDING settlements against on-chain finality."""

    def __init__(self) -> None:
        self._store = get_commerce_store()
        self._tracker = get_settlement_tracker()
        self._verify = get_verification_engine()

    @property
    def _cursor_repo(self):
        if getattr(self, "_cursor_repo_instance", None) is None:
            from repositories.repos import BaseRepository

            self._cursor_repo_instance = BaseRepository(CURSOR_TABLE)
        return self._cursor_repo_instance

    async def _capability_suspended(self, tenant_id: str) -> bool:
        """Kill switch: skip a tenant whose x402 capability is SUSPENDED."""
        try:
            from services.capabilities.lifecycle import get_lifecycle_authority

            for env in ("live", "sandbox"):
                state = await get_lifecycle_authority().get_state(
                    tenant_id, "x402", env, "commerce"
                )
                if state and state.get("readiness_state") in ("suspended", "disabled"):
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    async def reconcile_tenant(self, tenant_id: str) -> dict:
        """Reconcile all PENDING settlements for one tenant."""
        if await self._capability_suspended(tenant_id):
            metrics.increment("x402_reconciliation_skipped", labels={"reason": "suspended"})
            return {"tenant_id": tenant_id, "skipped": "suspended"}

        pending = await self._store.list_settlements(tenant_id, state=SettlementState.PENDING)
        settled = failed = still_pending = 0
        for s in pending:
            receipt = await self._store.get_receipt(tenant_id, s.receipt_id)
            authorization = await self._store.get_authorization(
                tenant_id, receipt.authorization_id
            ) if receipt else None
            if authorization is None:
                still_pending += 1
                continue
            verified, error = await self._verify._verify_locally(authorization, s.tx_hash)
            if verified:
                await self._tracker.mark_settled_reconciled(tenant_id, s.settlement_id)
                settled += 1
            elif error and error.startswith(("reverted", "amount_below_required", "payer_mismatch")):
                await self._tracker.fail(tenant_id, s.settlement_id, error)
                failed += 1
            else:
                # verification_unavailable / not_finalized → leave PENDING
                still_pending += 1

        await self._write_cursor(tenant_id, settled, failed, still_pending)
        metrics.observe("x402_reconciliation_lag", float(still_pending), labels={"tenant_id": tenant_id})
        return {
            "tenant_id": tenant_id, "settled": settled,
            "failed": failed, "still_pending": still_pending,
        }

    async def _write_cursor(self, tenant_id: str, settled: int, failed: int, pending: int) -> None:
        row_id = f"{tenant_id}"
        record = {
            "tenant_id": tenant_id,
            "last_run_at": utc_now().isoformat(),
            "last_settled": settled,
            "last_failed": failed,
            "last_pending": pending,
        }
        try:
            if await self._cursor_repo.find_by_id(row_id) is None:
                await self._cursor_repo.insert(row_id, record)
            else:
                await self._cursor_repo.update(row_id, record)
        except Exception as exc:  # noqa: BLE001 — cursor is diagnostic, never fatal
            logger.warning("x402 reconciliation cursor write failed: %s", type(exc).__name__)


_worker: Optional[X402ReconciliationWorker] = None


def get_reconciliation_worker() -> X402ReconciliationWorker:
    global _worker
    if _worker is None:
        _worker = X402ReconciliationWorker()
    return _worker


__all__ = ["X402ReconciliationWorker", "get_reconciliation_worker", "CURSOR_TABLE"]
