"""
Aether Backend — Concurrency-safe durable budget reservation.

Replaces the old *observational* budget gate (a racy, non-reserving
``count * per_reward >= cap`` estimate) with a durable
**reserve → commit / release** ledger so concurrent eligibility evaluations can
never oversubscribe a campaign's recorded budget.

Model
-----
* **Ledger row** — table ``reward_budget_ledger``, id ``{tenant_id}:{campaign_id}``.
  Tracks the exact ``cap`` plus ``outstanding`` (reserved-but-not-final) and
  ``committed`` totals as exact ``Decimal`` strings. Budget *used* is
  ``committed + outstanding``.
* **Reservation row** — table ``reward_budget_reservations``, id derived
  deterministically from ``(tenant_id, campaign_id, reservation_key)`` so a
  retry with the same key is idempotent (never double-counts).

Operations
----------
* ``reserve()`` — atomically checks ``used + amount <= cap`` and, on success,
  bumps ``outstanding`` and appends a ``reserved`` reservation row.
    - PostgreSQL: ``SELECT ... FOR UPDATE`` on the ledger row inside a
      transaction serializes concurrent reservers.
    - In-memory: a per-account :class:`asyncio.Lock` serializes concurrent
      reservers in-process.
  Either way, a budget of ``K`` units yields **at most ``K``** successful
  reservations regardless of how many evaluations race.
* ``commit()`` — ``reserved → committed`` (``outstanding -= amount``,
  ``committed += amount``). Budget usage is unchanged but the spend is final.
  Called on confirmed delivery / receipt.
* ``release()`` — ``reserved → released`` (``outstanding -= amount``), freeing
  the budget for other evaluations. Called on reject / expiry / delivery
  failure.

All arithmetic is exact ``Decimal`` — never binary ``float``.
"""

from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from repositories.repos import BaseRepository
from services.rewards.policy_engine import _amount_to_decimal
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.budget")


# Per-account in-memory locks (single-process backend only). Keyed by ledger id
# so distinct campaigns reserve concurrently while the same campaign serializes.
_ACCOUNT_LOCKS: dict[str, asyncio.Lock] = {}


def _account_lock(account_id: str) -> asyncio.Lock:
    lock = _ACCOUNT_LOCKS.get(account_id)
    if lock is None:
        lock = asyncio.Lock()
        _ACCOUNT_LOCKS[account_id] = lock
    return lock


def _account_id(tenant_id: str, campaign_id: str) -> str:
    return f"{tenant_id}:{campaign_id}"


def reservation_id(tenant_id: str, campaign_id: str, reservation_key: str) -> str:
    """Deterministic reservation row id → idempotency by (tenant, campaign, key)."""
    raw = f"{tenant_id}:{campaign_id}:{reservation_key}"
    return "res_" + hashlib.sha256(raw.encode()).hexdigest()[:40]


class ReservationResult(BaseModel):
    ok: bool
    reservation_id: Optional[str] = None
    state: Optional[str] = None          # reserved | committed | released
    reason: Optional[str] = None
    used: str = "0"                      # committed + outstanding after the op
    cap: Optional[str] = None
    idempotent: bool = False             # True if an existing reservation was returned


class _LedgerRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reward_budget_ledger")


class _ReservationRepo(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reward_budget_reservations")


class BudgetReservationService:
    """Durable, concurrency-safe campaign budget reservations."""

    def __init__(
        self,
        ledger_repo: Optional[BaseRepository] = None,
        reservation_repo: Optional[BaseRepository] = None,
    ) -> None:
        self._ledger = ledger_repo or _LedgerRepo()
        self._reservations = reservation_repo or _ReservationRepo()

    # ── public API ────────────────────────────────────────────────────────

    async def reserve(
        self,
        *,
        tenant_id: str,
        campaign_id: str,
        amount,
        cap,
        reservation_key: str,
        decision_id: Optional[str] = None,
    ) -> ReservationResult:
        """Atomically reserve ``amount`` against a campaign budget ``cap``.

        Returns ``ok=True`` with a ``reservation_id`` on success, ``ok=False``
        with ``reason='budget_exceeded'`` when the reservation would push
        ``committed + outstanding`` past ``cap``. Idempotent per
        ``reservation_key``.
        """
        amt = _amount_to_decimal(amount)
        if amt < 0:
            raise ValueError(f"reservation amount must be non-negative, got {amount!r}")
        cap_dec = _amount_to_decimal(cap)
        acct_id = _account_id(tenant_id, campaign_id)
        res_id = reservation_id(tenant_id, campaign_id, reservation_key)

        pool = await self._ledger._ensure_pool()
        if pool is None:
            return await self._reserve_in_memory(
                acct_id, res_id, tenant_id, campaign_id, amt, cap_dec, decision_id
            )
        return await self._reserve_postgres(
            pool, acct_id, res_id, tenant_id, campaign_id, amt, cap_dec, decision_id
        )

    async def commit(self, res_id: str, *, tenant_id: str) -> ReservationResult:
        """Finalize a reservation: ``reserved → committed`` (usage unchanged)."""
        return await self._transition(res_id, tenant_id, "committed")

    async def release(self, res_id: str, *, tenant_id: str) -> ReservationResult:
        """Release a reservation: ``reserved → released`` (frees the budget)."""
        return await self._transition(res_id, tenant_id, "released")

    async def get_ledger(self, tenant_id: str, campaign_id: str) -> Optional[dict]:
        return await self._ledger.find_by_id(_account_id(tenant_id, campaign_id))

    # ── in-memory backend ─────────────────────────────────────────────────

    async def _reserve_in_memory(
        self, acct_id, res_id, tenant_id, campaign_id, amt: Decimal, cap: Decimal, decision_id,
    ) -> ReservationResult:
        async with _account_lock(acct_id):
            existing = await self._reservations.find_by_id(res_id)
            if existing and existing.get("state") in ("reserved", "committed"):
                ledger = await self._ledger.find_by_id(acct_id) or {}
                return ReservationResult(
                    ok=True, reservation_id=res_id, state=existing.get("state"),
                    used=self._used(ledger), cap=str(cap), idempotent=True,
                )

            ledger = await self._ledger.find_by_id(acct_id)
            outstanding = Decimal(ledger["outstanding"]) if ledger else Decimal(0)
            committed = Decimal(ledger["committed"]) if ledger else Decimal(0)
            used = committed + outstanding
            if used + amt > cap:
                metrics.increment("rewards_budget_blocked", labels={"tenant_id": tenant_id})
                return ReservationResult(
                    ok=False, reason="budget_exceeded", used=str(used), cap=str(cap),
                )
            new_outstanding = outstanding + amt
            await self._upsert_ledger(acct_id, tenant_id, campaign_id, cap, new_outstanding, committed)
            await self._reservations.insert(res_id, {
                "tenant_id": tenant_id,
                "campaign_id": campaign_id,
                "decision_id": decision_id,
                "amount": str(amt),
                "state": "reserved",
                "reserved_at": utc_now().isoformat(),
            })
            metrics.increment("rewards_budget_reserved", labels={"tenant_id": tenant_id})
            return ReservationResult(
                ok=True, reservation_id=res_id, state="reserved",
                used=str(committed + new_outstanding), cap=str(cap),
            )

    # ── postgres backend ──────────────────────────────────────────────────

    async def _reserve_postgres(
        self, pool, acct_id, res_id, tenant_id, campaign_id, amt: Decimal, cap: Decimal, decision_id,
    ) -> ReservationResult:
        await self._ledger._ensure_table()
        await self._reservations._ensure_table()
        import json

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Ensure the ledger row exists so FOR UPDATE has a row to lock.
                seed = {
                    "id": acct_id, "tenant_id": tenant_id, "campaign_id": campaign_id,
                    "cap": str(cap), "outstanding": "0", "committed": "0",
                    "created_at": utc_now().isoformat(), "updated_at": utc_now().isoformat(),
                }
                await conn.execute(
                    """INSERT INTO reward_budget_ledger (id, data, tenant_id, created_at, updated_at)
                       VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                       ON CONFLICT (id) DO NOTHING""",
                    acct_id, json.dumps(seed), tenant_id,
                )
                row = await conn.fetchrow(
                    "SELECT data FROM reward_budget_ledger WHERE id=$1 FOR UPDATE", acct_id
                )
                ledger = json.loads(row["data"])

                res_row = await conn.fetchrow(
                    "SELECT data FROM reward_budget_reservations WHERE id=$1", res_id
                )
                if res_row is not None:
                    existing = json.loads(res_row["data"])
                    if existing.get("state") in ("reserved", "committed"):
                        return ReservationResult(
                            ok=True, reservation_id=res_id, state=existing.get("state"),
                            used=self._used(ledger), cap=str(cap), idempotent=True,
                        )

                outstanding = Decimal(ledger.get("outstanding", "0"))
                committed = Decimal(ledger.get("committed", "0"))
                # Honor a cap already recorded on the ledger if larger data drift; use call cap.
                if used_exceeds(committed + outstanding, amt, cap):
                    metrics.increment("rewards_budget_blocked", labels={"tenant_id": tenant_id})
                    return ReservationResult(
                        ok=False, reason="budget_exceeded",
                        used=str(committed + outstanding), cap=str(cap),
                    )
                new_outstanding = outstanding + amt
                ledger.update({
                    "cap": str(cap), "outstanding": str(new_outstanding),
                    "committed": str(committed), "updated_at": utc_now().isoformat(),
                })
                await conn.execute(
                    "UPDATE reward_budget_ledger SET data=$1::jsonb, updated_at=NOW() WHERE id=$2",
                    json.dumps(ledger), acct_id,
                )
                res_data = {
                    "id": res_id, "tenant_id": tenant_id, "campaign_id": campaign_id,
                    "decision_id": decision_id, "amount": str(amt), "state": "reserved",
                    "reserved_at": utc_now().isoformat(),
                    "created_at": utc_now().isoformat(), "updated_at": utc_now().isoformat(),
                }
                await conn.execute(
                    """INSERT INTO reward_budget_reservations (id, data, tenant_id, created_at, updated_at)
                       VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                       ON CONFLICT (id) DO NOTHING""",
                    res_id, json.dumps(res_data), tenant_id,
                )
                metrics.increment("rewards_budget_reserved", labels={"tenant_id": tenant_id})
                return ReservationResult(
                    ok=True, reservation_id=res_id, state="reserved",
                    used=str(committed + new_outstanding), cap=str(cap),
                )

    # ── shared transition (commit / release) ──────────────────────────────

    async def _transition(self, res_id: str, tenant_id: str, target: str) -> ReservationResult:
        assert target in ("committed", "released")
        reservation = await self._reservations.find_by_id(res_id)
        if reservation is None:
            return ReservationResult(ok=False, reason="reservation_not_found")
        if reservation.get("tenant_id") != tenant_id:
            return ReservationResult(ok=False, reason="forbidden")
        current = reservation.get("state")
        if current == target:
            return ReservationResult(ok=True, reservation_id=res_id, state=target, idempotent=True)
        if current != "reserved":
            # Only an outstanding reservation can be committed/released.
            return ReservationResult(ok=False, reason=f"invalid_state:{current}", state=current)

        campaign_id = reservation.get("campaign_id", "")
        acct_id = _account_id(tenant_id, campaign_id)
        amt = _amount_to_decimal(reservation.get("amount", "0"))

        pool = await self._ledger._ensure_pool()
        if pool is None:
            async with _account_lock(acct_id):
                ledger = await self._ledger.find_by_id(acct_id) or {
                    "cap": "0", "outstanding": "0", "committed": "0",
                }
                outstanding = Decimal(ledger.get("outstanding", "0")) - amt
                if outstanding < 0:
                    outstanding = Decimal(0)
                committed = Decimal(ledger.get("committed", "0"))
                if target == "committed":
                    committed = committed + amt
                await self._upsert_ledger(
                    acct_id, tenant_id, campaign_id,
                    _amount_to_decimal(ledger.get("cap", "0")), outstanding, committed,
                )
                await self._reservations.update(res_id, {
                    "state": target, f"{target}_at": utc_now().isoformat(),
                })
                self._emit_transition_metric(target, tenant_id)
                return ReservationResult(
                    ok=True, reservation_id=res_id, state=target,
                    used=str(committed + outstanding), cap=str(ledger.get("cap", "0")),
                )

        import json
        await self._ledger._ensure_table()
        async with pool.acquire() as conn:
            async with conn.transaction():
                res_row = await conn.fetchrow(
                    "SELECT data FROM reward_budget_reservations WHERE id=$1 FOR UPDATE", res_id
                )
                if res_row is None:
                    return ReservationResult(ok=False, reason="reservation_not_found")
                reservation = json.loads(res_row["data"])
                current = reservation.get("state")
                if current == target:
                    return ReservationResult(ok=True, reservation_id=res_id, state=target, idempotent=True)
                if current != "reserved":
                    return ReservationResult(ok=False, reason=f"invalid_state:{current}", state=current)
                row = await conn.fetchrow(
                    "SELECT data FROM reward_budget_ledger WHERE id=$1 FOR UPDATE", acct_id
                )
                ledger = json.loads(row["data"]) if row else {"cap": "0", "outstanding": "0", "committed": "0"}
                outstanding = Decimal(ledger.get("outstanding", "0")) - amt
                if outstanding < 0:
                    outstanding = Decimal(0)
                committed = Decimal(ledger.get("committed", "0"))
                if target == "committed":
                    committed = committed + amt
                ledger.update({
                    "outstanding": str(outstanding), "committed": str(committed),
                    "updated_at": utc_now().isoformat(),
                })
                await conn.execute(
                    "UPDATE reward_budget_ledger SET data=$1::jsonb, updated_at=NOW() WHERE id=$2",
                    json.dumps(ledger), acct_id,
                )
                reservation.update({"state": target, f"{target}_at": utc_now().isoformat(),
                                    "updated_at": utc_now().isoformat()})
                await conn.execute(
                    "UPDATE reward_budget_reservations SET data=$1::jsonb, updated_at=NOW() WHERE id=$2",
                    json.dumps(reservation), res_id,
                )
                self._emit_transition_metric(target, tenant_id)
                return ReservationResult(
                    ok=True, reservation_id=res_id, state=target,
                    used=str(committed + outstanding), cap=str(ledger.get("cap", "0")),
                )

    # ── helpers ───────────────────────────────────────────────────────────

    async def _upsert_ledger(self, acct_id, tenant_id, campaign_id, cap: Decimal, outstanding: Decimal, committed: Decimal) -> None:
        existing = await self._ledger.find_by_id(acct_id)
        data = {
            "tenant_id": tenant_id, "campaign_id": campaign_id, "cap": str(cap),
            "outstanding": str(outstanding), "committed": str(committed),
        }
        if existing:
            await self._ledger.update(acct_id, data)
        else:
            await self._ledger.insert(acct_id, data)

    @staticmethod
    def _used(ledger: dict) -> str:
        outstanding = Decimal(ledger.get("outstanding", "0")) if ledger else Decimal(0)
        committed = Decimal(ledger.get("committed", "0")) if ledger else Decimal(0)
        return str(committed + outstanding)

    @staticmethod
    def _emit_transition_metric(target: str, tenant_id: str) -> None:
        if target == "committed":
            metrics.increment("rewards_budget_committed", labels={"tenant_id": tenant_id})
        else:
            metrics.increment("rewards_budget_released", labels={"tenant_id": tenant_id})


def used_exceeds(current_used: Decimal, amount: Decimal, cap: Decimal) -> bool:
    """True when reserving ``amount`` on top of ``current_used`` would exceed ``cap``."""
    return current_used + amount > cap
