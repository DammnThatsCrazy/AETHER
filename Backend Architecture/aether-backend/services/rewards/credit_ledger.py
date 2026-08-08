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

import uuid
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
        """Post a double-entry reward credit; idempotent by ``idempotency_key``."""
        if amount <= 0:
            raise ValueError("credit amount must be positive")

        entry_id = f"rcl_{idempotency_key}"
        existing = await self._ledger.find_by_id(entry_id)
        if existing is not None:
            return existing  # idempotent replay

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
        }
        stored = await self._ledger.insert(entry_id, entry)
        await self._apply_balance(tenant_id, recipient_id, currency, amount)
        logger.info(
            "internal_credit posted tenant=%s recipient=%s amount=%s %s",
            tenant_id, recipient_id, amount, currency,
        )
        return stored

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
