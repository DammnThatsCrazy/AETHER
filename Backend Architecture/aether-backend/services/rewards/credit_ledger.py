"""Internal reward credit ledger — durable double-entry.

Backs the ``internal_credit`` reward rail: a fully in-repo, no-custody credit
system where a reward credit is a double-entry pair (a debit against the
campaign's reward pool, a credit to the recipient's balance) so the ledger
always nets to zero and per-recipient balances are auditable.

Rows live in ``reward_credit_ledger`` (append-only entries) and
``reward_credit_balances`` (one balance row per (tenant, recipient)).
Idempotent by ``idempotency_key``: replaying the same reward credit is a no-op
that returns the existing entry, so a redelivered outbox job never
double-credits.

Money is Decimal end-to-end — never float.
"""

from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal
from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.rewards.credit_ledger")

LEDGER_TABLE = "reward_credit_ledger"
BALANCES_TABLE = "reward_credit_balances"


class _LedgerRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__(LEDGER_TABLE)


class _BalancesRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__(BALANCES_TABLE)


class InternalCreditLedger:
    """Durable double-entry credit ledger for the internal_credit rail."""

    def __init__(
        self,
        ledger: Optional[_LedgerRepo] = None,
        balances: Optional[_BalancesRepo] = None,
    ) -> None:
        self._ledger = ledger or _LedgerRepo()
        self._balances = balances or _BalancesRepo()
        # Per-balance-row locks so concurrent postings to the same
        # (tenant, recipient, currency) balance can't lose an update to a
        # racing read-modify-write, and so a crash-retry racing a fresh
        # replay of the *same* idempotency key can't apply the balance
        # twice. Keyed by the balance row id; created lazily and guarded by
        # `_locks_guard` so two coroutines never create two different Lock
        # objects for the same row.
        self._balance_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @staticmethod
    def _entry_id(tenant_id: str, idempotency_key: str) -> str:
        """Deterministic ledger row id, scoped per tenant.

        The idempotency key is caller-controlled (it comes from the
        campaign/outbox payload), so two different tenants can legitimately
        submit the same key (e.g. both replaying "order-123"). Hashing
        ``tenant_id`` together with the key — rather than using the key
        alone — keeps their ledger rows, and therefore their idempotent-
        replay lookups, fully independent. A NUL-separated digest (instead
        of naive ``f"{tenant_id}:{idempotency_key}"`` concatenation) also
        rules out a crafted key containing the delimiter making two distinct
        (tenant_id, key) pairs hash to the same row.
        """
        digest = hashlib.sha256(
            f"{tenant_id}\x00{idempotency_key}".encode("utf-8")
        ).hexdigest()
        return f"rcl_{digest}"

    async def _lock_for(self, row_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._balance_locks.get(row_id)
            if lock is None:
                lock = asyncio.Lock()
                self._balance_locks[row_id] = lock
            return lock

    async def credit(
        self,
        *,
        tenant_id: str,
        recipient_id: str,
        campaign_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        action_id: Optional[str] = None,
    ) -> dict:
        """Post a double-entry reward credit; idempotent by ``idempotency_key``.

        Idempotency is scoped per tenant (see ``_entry_id``): two tenants
        posting the same ``idempotency_key`` get two independent ledger rows
        and two independent balance credits.

        The ledger insert and the balance increment are not on one atomic
        transaction (``BaseRepository`` exposes no multi-statement
        transaction primitive), so a process/db crash could previously land
        between them: the ledger durably recorded the credit but the
        balance was never incremented, and a retry that found the existing
        ledger entry returned early without ever applying it. Every ledger
        entry now carries a ``balance_applied`` marker that only flips to
        ``True`` after the balance increment commits. The replay path
        checks that marker and, if it is still ``False`` (a prior attempt
        died before applying the balance), re-runs the balance step before
        returning — so a redelivered outbox job always converges on
        "ledger entry exists AND balance reflects it", never a durable
        credit the balance silently omits.
        """
        if amount <= 0:
            raise ValueError("credit amount must be positive")

        entry_id = self._entry_id(tenant_id, idempotency_key)
        existing = await self._ledger.find_by_id(entry_id)
        if existing is not None:
            if existing.get("balance_applied"):
                return existing  # fully-applied idempotent replay
            # Prior attempt inserted the ledger row but crashed/failed
            # before the balance was applied — repair it now.
            return await self._apply_and_mark(entry_id, tenant_id, recipient_id, currency, amount)

        entry = {
            "tenant_id": tenant_id,
            "recipient_id": recipient_id,
            "campaign_id": campaign_id,
            "action_id": action_id,
            "amount": str(amount),          # Decimal serialized as string
            "currency": currency,
            "idempotency_key": idempotency_key,
            # double-entry: debit the campaign pool, credit the recipient
            "legs": [
                {"account": f"campaign_pool:{campaign_id}", "direction": "debit", "amount": str(amount)},
                {"account": f"recipient:{recipient_id}", "direction": "credit", "amount": str(amount)},
            ],
            "posted_at": utc_now().isoformat(),
            "balance_applied": False,
        }
        await self._ledger.insert(entry_id, entry)
        return await self._apply_and_mark(entry_id, tenant_id, recipient_id, currency, amount)

    async def _apply_and_mark(
        self,
        entry_id: str,
        tenant_id: str,
        recipient_id: str,
        currency: str,
        amount: Decimal,
    ) -> dict:
        """Apply the balance delta for ``entry_id`` exactly once, then mark it.

        Serialized on the destination balance row's lock so (a) two
        coroutines racing to repair/finish the *same* ledger entry can't
        both apply it, and (b) unrelated concurrent postings to the *same*
        (tenant, recipient, currency) balance never lose an update to each
        other's read-modify-write. The ledger entry is re-read under the
        lock so the ``balance_applied`` check is against the latest
        committed state, not a possibly-stale value read before the lock
        was acquired.
        """
        row_id = f"{tenant_id}:{recipient_id}:{currency}"
        lock = await self._lock_for(row_id)
        async with lock:
            current = await self._ledger.find_by_id(entry_id)
            if current is not None and current.get("balance_applied"):
                return current  # someone else already finished this entry
            await self._apply_balance(tenant_id, recipient_id, currency, amount)
            updated = await self._ledger.update(entry_id, {"balance_applied": True})
            logger.info(
                "internal_credit posted tenant=%s recipient=%s amount=%s %s",
                tenant_id, recipient_id, amount, currency,
            )
            return updated

    async def _apply_balance(
        self, tenant_id: str, recipient_id: str, currency: str, delta: Decimal
    ) -> None:
        row_id = f"{tenant_id}:{recipient_id}:{currency}"
        row = await self._balances.find_by_id(row_id)
        if row is None:
            await self._balances.insert(row_id, {
                "tenant_id": tenant_id,
                "recipient_id": recipient_id,
                "currency": currency,
                "balance": str(delta),
            })
        else:
            new_balance = Decimal(str(row.get("balance", "0"))) + delta
            await self._balances.update(row_id, {"balance": str(new_balance)})

    async def get_balance(
        self, tenant_id: str, recipient_id: str, currency: str
    ) -> Decimal:
        row = await self._balances.find_by_id(f"{tenant_id}:{recipient_id}:{currency}")
        return Decimal(str(row.get("balance", "0"))) if row else Decimal("0")


_ledger: Optional[InternalCreditLedger] = None


def get_internal_credit_ledger() -> InternalCreditLedger:
    global _ledger
    if _ledger is None:
        _ledger = InternalCreditLedger()
    return _ledger


__all__ = [
    "InternalCreditLedger",
    "get_internal_credit_ledger",
    "LEDGER_TABLE",
    "BALANCES_TABLE",
]
