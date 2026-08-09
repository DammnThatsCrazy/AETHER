"""
Unit tests for the abandoned-reservation release worker (A6 / program sec18).

Closes the reservation-leak gap: reservations are released at request time
(reject/cancel/enqueue-failure in routes.py), but a reservation whose action
never reaches a terminal state would leak budget forever. The TTL worker scans
expired ``reserved`` reservations, resolves them (release OR commit on
delivered action), retries with bounded backoff, and dead-letters after
exhaustion.

Covers:
    - TTL scan releases an expired abandoned reservation (budget freed + audit)
    - a reservation whose linked action was delivered is COMMITTED (final spend)
    - bounded retry → dead-letter when the ledger backend keeps failing
    - idempotency: a second scan is a no-op (no double release)
    - build_release_loop returns a supervised async loop
    - only ``reserved`` reservations are candidates (committed/released skipped)

All tests run against the in-memory repo backend (AETHER_ENV=local); the shared
per-table stores are reset before each test.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.rewards.budget import BudgetReservationService, reservation_id
from services.rewards.repositories import RewardAuditRepository
from services.rewards.reservation_release import (
    ReservationReleaseService,
    get_reservation_release_service,
    reset_reservation_release_service,
)
from shared.common.common import utc_now


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    reset_reservation_release_service()
    yield
    reset_in_memory_stores()
    reset_reservation_release_service()


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


TENANT = "tenant_rr_001"
CAMPAIGN = "camp_rr_001"


def _backdate_reservation(res_id: str, seconds: int = 7200) -> None:
    """Force the reservation's reserved_at into the past (past the TTL)."""
    repo = BudgetReservationService()._reservations
    row = repo._store[res_id]
    row["reserved_at"] = (utc_now() - timedelta(seconds=seconds)).isoformat()
    repo._store[res_id] = row


def _reserve(key: str = "k1", amount: str = "40", cap: str = "100") -> dict:
    svc = BudgetReservationService()
    result = _run(svc.reserve(
        tenant_id=TENANT, campaign_id=CAMPAIGN, amount=amount,
        cap=cap, reservation_key=key,
    ))
    assert result.ok, result.reason
    _backdate_reservation(result.reservation_id)
    return result


def _ledger() -> dict:
    return _run(BudgetReservationService().get_ledger(TENANT, CAMPAIGN)) or {}


def _job_state(res_id: str) -> dict:
    from services.rewards.reservation_release import _job_id
    return _run(
        ReservationReleaseService()._jobs.find_by_id(_job_id(res_id))
    ) or {}


# ═══════════════════════════════════════════════════════════════════════════
# TTL release
# ═══════════════════════════════════════════════════════════════════════════

def test_release_expired_abandoned_reservation_frees_budget():
    result = _reserve()
    res_id = result.reservation_id

    summary = _run(ReservationReleaseService().run_once(ttl_seconds=0, batch_size=10))
    assert summary["scanned"] == 1
    assert summary["leased"] == 1
    assert summary["released"] == 1

    # Budget freed: outstanding=0, committed=0 → used=0.
    ledger = _ledger()
    assert ledger["outstanding"] == "0"
    assert ledger["committed"] == "0"

    # Reservation row is now released (not reserved).
    stored = _run(BudgetReservationService()._reservations.find_by_id(res_id))
    assert stored["state"] == "released"
    assert _job_state(res_id).get("state") == "released"

    # Immutable audit trail records the abandonment resolution.
    audit = _run(RewardAuditRepository().find_many(
        filters={"tenant_id": TENANT, "target_id": res_id}, limit=10
    ))
    actions = {a.get("action") for a in audit}
    assert "reservation.released_abandoned" in actions


def test_reservation_with_delivered_action_is_committed():
    result = _reserve()
    res_id = result.reservation_id

    # A delivered reward action is linked to the reservation → final spend.
    from services.rewards.repositories import RewardActionRepository
    action = _run(RewardActionRepository().create(TENANT, {
        "decision_id": "dec_1",
        "rail": "tenant_webhook",
        "reservation_id": res_id,
        "status": "delivered",
    }))
    assert action["id"]

    summary = _run(ReservationReleaseService().run_once(ttl_seconds=0, batch_size=10))
    assert summary["committed"] == 1

    ledger = _ledger()
    assert ledger["committed"] == "40"
    assert ledger["outstanding"] == "0"
    assert _job_state(res_id).get("state") == "committed"

    audit = _run(RewardAuditRepository().find_many(
        filters={"tenant_id": TENANT, "target_id": res_id}, limit=10
    ))
    assert "reservation.committed_recovered" in {a.get("action") for a in audit}


def test_abandoned_action_is_marked_failed():
    result = _reserve()
    res_id = result.reservation_id
    from services.rewards.repositories import RewardActionRepository
    action = _run(RewardActionRepository().create(TENANT, {
        "decision_id": "dec_2",
        "rail": "manual_approval",
        "reservation_id": res_id,
        "status": "pending_approval",
    }))

    summary = _run(ReservationReleaseService().run_once(ttl_seconds=0, batch_size=10))
    assert summary["released"] == 1

    stored = _run(RewardActionRepository().get(action["id"], TENANT))
    assert stored["status"] == "failed"
    assert stored.get("abandoned_reason") == "reservation.ttl_expired"


# ═══════════════════════════════════════════════════════════════════════════
# bounded retry → dead-letter
# ═══════════════════════════════════════════════════════════════════════════

class _FailingBudget:
    """Ledger backend that fails every commit/release → forces retry/DLQ."""

    async def release(self, res_id, *, tenant_id):
        raise RuntimeError("db down")
    async def commit(self, res_id, *, tenant_id):
        raise RuntimeError("db down")


def test_bounded_retry_schedules_with_backoff(monkeypatch):
    monkeypatch.setenv("REWARD_RESERVATION_RELEASE_MAX_ATTEMPTS", "3")
    result = _reserve()
    res_id = result.reservation_id

    svc = ReservationReleaseService(budget_service=_FailingBudget())

    first = _run(svc.run_once(ttl_seconds=0, batch_size=10))
    assert first["leased"] == 1
    job = _job_state(res_id)
    assert job.get("state") == "failed"
    assert job.get("attempt_count") == 1
    # Retry is backed off into the future — the very next scan is a no-op.
    from datetime import datetime
    next_at = datetime.fromisoformat(job.get("next_attempt_at", ""))
    assert next_at > utc_now()
    second = _run(svc.run_once(ttl_seconds=0, batch_size=10))
    assert second["leased"] == 0


def test_exhausted_attempts_dead_letter(monkeypatch):
    monkeypatch.setenv("REWARD_RESERVATION_RELEASE_MAX_ATTEMPTS", "1")
    result = _reserve()
    res_id = result.reservation_id

    svc = ReservationReleaseService(budget_service=_FailingBudget())

    summary = _run(svc.run_once(ttl_seconds=0, batch_size=10))
    assert summary["dead_lettered"] == 1
    job = _job_state(res_id)
    assert job.get("state") == "dead_letter"
    assert job.get("last_error") and "db down" in job.get("last_error", "")


# ═══════════════════════════════════════════════════════════════════════════
# idempotency / state filters
# ═══════════════════════════════════════════════════════════════════════════

def test_second_scan_is_idempotent():
    _reserve()
    svc = ReservationReleaseService()
    first = _run(svc.run_once(ttl_seconds=0, batch_size=10))
    second = _run(svc.run_once(ttl_seconds=0, batch_size=10))
    assert first["released"] == 1
    # Nothing left to release; the already-released reservation is not scanned.
    assert second["scanned"] == 0


def test_only_reserved_reservations_are_candidates():
    # A committed reservation must never be released by the TTL worker.
    result = _reserve()
    _run(BudgetReservationService().commit(result.reservation_id, tenant_id=TENANT))
    summary = _run(ReservationReleaseService().run_once(ttl_seconds=0, batch_size=10))
    assert summary["scanned"] == 0

    # And a request-time-released reservation is equally not a candidate.
    result2 = _reserve(key="k2")
    _run(BudgetReservationService().release(result2.reservation_id, tenant_id=TENANT))
    summary = _run(ReservationReleaseService().run_once(ttl_seconds=0, batch_size=10))
    assert summary["scanned"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# supervised loop builder
# ═══════════════════════════════════════════════════════════════════════════

def test_build_release_loop_returns_supervised_async_loop():
    loop = ReservationReleaseService().build_release_loop(interval_s=3600, ttl_seconds=0)
    assert callable(loop)
    # It is an async coroutine function (awaitable) — suitable for the runtime
    # supervisor which awaits each worker coroutine.
    import inspect
    assert inspect.iscoroutinefunction(loop) or asyncio.iscoroutinefunction(loop)


def test_singleton_reset_cycle():
    get_reservation_release_service()
    reset_reservation_release_service()
    assert get_reservation_release_service() is not None
