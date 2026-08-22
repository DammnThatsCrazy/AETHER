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

    async def _capability_suspended(self, tenant_id: str, environment: str) -> bool:
        """Kill switch, scoped to ONE settlement environment.

        Each settlement carries its own environment, so suspending sandbox must
        not halt live reconciliation (or vice versa). Only the matching
        environment's lifecycle state gates a settlement.
        """
        try:
            from services.capabilities.lifecycle import get_lifecycle_authority

            state = await get_lifecycle_authority().get_state(
                tenant_id, "x402", environment, "commerce"
            )
            if state and state.get("readiness_state") in ("suspended", "disabled"):
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    async def reconcile_tenant(self, tenant_id: str) -> dict:
        """Reconcile all PENDING settlements for one tenant.

        The kill switch is evaluated per settlement ENVIRONMENT: a settlement in
        a suspended environment is skipped, while settlements in a still-active
        environment continue to reconcile in the same pass.
        """
        pending = await self._store.list_settlements(tenant_id, state=SettlementState.PENDING)
        settled = failed = still_pending = skipped = 0
        suspended_by_env: dict[str, bool] = {}
        for s in pending:
            env = getattr(s, "environment", None) or "sandbox"
            if env not in suspended_by_env:
                suspended_by_env[env] = await self._capability_suspended(tenant_id, env)
            if suspended_by_env[env]:
                skipped += 1
                metrics.increment(
                    "x402_reconciliation_skipped",
                    labels={"reason": "suspended", "environment": env},
                )
                continue
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
                # Finality is now confirmed → mint the entitlement that
                # verify_and_settle deferred for this PENDING settlement.
                try:
                    from services.x402.control_plane import get_control_plane

                    await get_control_plane().finalize_settlement_entitlement(
                        tenant_id, s.settlement_id
                    )
                except Exception:  # noqa: BLE001 — settlement still advanced; retried next tick
                    logger.warning(
                        "entitlement finalize failed for settlement %s",
                        s.settlement_id, exc_info=True,
                    )
                settled += 1
            else:
                # Reserve PENDING for RETRYABLE verdicts only (not_finalized /
                # verification_unavailable — a later tick can still confirm).
                # EVERY other verdict is terminal (reverted, payer_mismatch,
                # amount_below_required, no_matching_transfer, malformed,
                # unsupported asset/contract, …): the transaction's logs can
                # never later acquire a matching transfer, so leaving it PENDING
                # loops forever. Use the verification engine's terminal-verdict
                # classification rather than a hand-listed prefix set.
                from .verification import is_terminal_verdict

                verdict_token = (error or "").split(":", 1)[0].split()[0] if error else ""
                if verdict_token and is_terminal_verdict(verdict_token):
                    await self._tracker.fail(tenant_id, s.settlement_id, error)
                    failed += 1
                else:
                    still_pending += 1

        await self._write_cursor(tenant_id, settled, failed, still_pending)
        metrics.observe("x402_reconciliation_lag", float(still_pending), labels={"tenant_id": tenant_id})
        return {
            "tenant_id": tenant_id, "settled": settled,
            "failed": failed, "still_pending": still_pending, "skipped": skipped,
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
