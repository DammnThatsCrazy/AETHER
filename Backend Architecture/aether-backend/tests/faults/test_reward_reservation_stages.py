"""Stage-boundary failures: reward reservation -> commit -> release.

Pipeline: reserve -> scan (expired, ``reserved``-only) -> enqueue (idempotent
job) -> lease -> resolve (release OR commit) -> audit -> bounded retry ->
dead-letter.

Boundary recovery asserted:

  * reserve: a reservation is idempotent per ``reservation_key`` and a fresh
    reservation is NOT a scan candidate (TTL gate).
  * enqueue: one bad enqueue never stops the scan; the job is durable.
  * release: an abandoned (no delivered action) reservation is released, the
    budget freed exactly once, and a replay never double-releases.
  * commit: a reservation whose action was actually delivered is committed
    (final spend) — never released.
  * retry: a transient release failure retries with backoff and recovers —
    the budget is freed exactly once, no double-release.
  * dead-letter: an exhausting release failure dead-letters the job (bounded,
    visible) instead of silently dropping or losing the reservation.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parents[1] / "adversarial"
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import (  # noqa: E402
    DB_UNAVAILABLE,
    arm,
    make_fault,
)
from services.rewards.budget import BudgetReservationService  # noqa: E402
from services.rewards.repositories import (  # noqa: E402
    RewardActionRepository,
    RewardAuditRepository,
)
from services.rewards.reservation_release import (  # noqa: E402
    ReservationReleaseJobRepository,
    ReservationReleaseService,
    RewardBudgetReservationRepository,
)
from shared.common.common import utc_now  # noqa: E402

TENANT = "t1"
OLD_AT = (utc_now() - timedelta(seconds=7200)).isoformat()


async def _expire(res_id: str, reservation: dict) -> None:
    """Backdate ``reserved_at`` so the TTL scan picks the reservation up."""
    await RewardBudgetReservationRepository().insert(res_id, {
        **reservation,
        "reserved_at": OLD_AT,
    })


async def _reserve(service: BudgetReservationService, key: str, amount: str = "10"):
    reserved = await service.reserve(
        tenant_id=TENANT, campaign_id="camp-1", amount=Decimal(amount),
        cap=Decimal("100"), reservation_key=key,
    )
    assert reserved.ok is True
    return reserved.reservation_id


def _build(budget: BudgetReservationService, *, job_repo=None) -> ReservationReleaseService:
    return ReservationReleaseService(
        budget_service=budget,
        job_repo=job_repo or ReservationReleaseJobRepository(),
        worker_id="worker-test",
    )


# ── reserve boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reserve_boundary_idempotent_and_fresh_is_not_a_scan_candidate():
    budget = BudgetReservationService()
    res_id = await _reserve(budget, "key-fresh")

    # Idempotent reserve per reservation_key: same id, no second outstanding.
    again = await budget.reserve(
        tenant_id=TENANT, campaign_id="camp-1", amount=Decimal("10"),
        cap=Decimal("100"), reservation_key="key-fresh",
    )
    assert again.ok is True and again.reservation_id == res_id

    # A fresh reservation is NOT expired -> the TTL scan finds nothing.
    expired = await RewardBudgetReservationRepository().find_expired(3600)
    assert expired == []

    # Once expired, it is exactly the candidate.
    await _expire(res_id, (await RewardBudgetReservationRepository().find_by_id(res_id)) or {})
    expired = await RewardBudgetReservationRepository().find_expired(3600)
    assert [r["id"] for r in expired] == [res_id]


# ── enqueue boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_boundary_one_bad_enqueue_does_not_stop_scan():
    budget = BudgetReservationService()
    res_id = await _reserve(budget, "key-enq")
    await _expire(res_id, (await RewardBudgetReservationRepository().find_by_id(res_id)) or {})

    service = _build(budget)
    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")
    restore = arm(service._jobs, "ensure_enqueued", injector)

    first = await service.run_once(ttl_seconds=3600)
    # The failed enqueue was caught; the scan still ran (loudly not silent).
    assert first["scanned"] == 1
    assert len(await ReservationReleaseJobRepository().find_many({"tenant_id": TENANT}, limit=100)) == 0

    restore()
    second = await service.run_once(ttl_seconds=3600)
    assert len(await ReservationReleaseJobRepository().find_many({"tenant_id": TENANT}, limit=100)) == 1
    job = (await ReservationReleaseJobRepository().find_many({"tenant_id": TENANT}, limit=10))[0]
    assert job["reservation_id"] == res_id
    # Deterministic job id per reservation -> a re-enqueue from the RESERVATION
    # (not the job) re-arms the SAME job id, never a duplicate runnable job.
    reservation = await RewardBudgetReservationRepository().find_by_id(res_id)
    assert reservation is not None
    again = await service._jobs.ensure_enqueued(reservation, "reservation.ttl_expired")
    assert again["id"] == job["id"]


# ── release boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_release_boundary_abandoned_released_once_no_double_release():
    budget = BudgetReservationService()
    res_id = await _reserve(budget, "key-release")
    await _expire(res_id, (await RewardBudgetReservationRepository().find_by_id(res_id)) or {})

    service = _build(budget)
    summary = await service.run_once(ttl_seconds=3600)
    assert summary["released"] == 1 and summary["committed"] == 0

    reservation = await RewardBudgetReservationRepository().find_by_id(res_id)
    assert reservation["state"] == "released"

    # Replay: nothing to release (not in ``reserved``) -> no double-release.
    replay = await service.run_once(ttl_seconds=3600)
    assert replay["released"] == 0 and replay["committed"] == 0

    audit = await RewardAuditRepository().find_many({"tenant_id": TENANT}, limit=10)
    assert any(a["action"] == "reservation.released_abandoned" for a in audit)


# ── commit boundary ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_commit_boundary_delivered_action_commits_final_spend():
    budget = BudgetReservationService()
    res_id = await _reserve(budget, "key-commit")
    await _expire(res_id, (await RewardBudgetReservationRepository().find_by_id(res_id)) or {})

    # The reward was actually delivered -> final spend, never released.
    await RewardActionRepository().create(TENANT, {
        "reservation_id": res_id,
        "status": "delivered",
        "rail": "test",
    })

    summary = await _build(budget).run_once(ttl_seconds=3600)
    assert summary["committed"] == 1 and summary["released"] == 0

    reservation = await RewardBudgetReservationRepository().find_by_id(res_id)
    assert reservation["state"] == "committed"

    audit = await RewardAuditRepository().find_many({"tenant_id": TENANT}, limit=10)
    assert any(a["action"] == "reservation.committed_recovered" for a in audit)


# ── retry boundary ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_boundary_transient_release_failure_recovers_no_double_release():
    budget = BudgetReservationService()
    res_id = await _reserve(budget, "key-retry")
    await _expire(res_id, (await RewardBudgetReservationRepository().find_by_id(res_id)) or {})

    jobs = ReservationReleaseJobRepository()
    service = _build(budget, job_repo=jobs)

    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")
    restore = arm(budget, "release", injector)

    first = await service.run_once(ttl_seconds=3600)
    # The failing release was scheduled for retry, not dead-lettered/silent.
    assert first["released"] == 0
    job = (await jobs.find_many({"tenant_id": TENANT}, limit=10))[0]
    assert job["state"] == "failed" and job["attempt_count"] == 1

    # Make the retry due, then run once more: release recovers exactly once.
    await jobs.update(job["id"], {"next_attempt_at": utc_now().isoformat()})
    restore()
    second = await service.run_once(ttl_seconds=3600)
    assert second["released"] == 1

    reservation = await RewardBudgetReservationRepository().find_by_id(res_id)
    assert reservation["state"] == "released"
    released_at = reservation["released_at"]

    # A further replay cannot double-release.
    third = await service.run_once(ttl_seconds=3600)
    assert third["released"] == 0
    assert (await RewardBudgetReservationRepository().find_by_id(res_id))["released_at"] == released_at


# ── dead-letter boundary ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dead_letter_boundary_exhausting_release_failure_is_bounded_and_visible(monkeypatch):
    monkeypatch.setenv("REWARD_RESERVATION_RELEASE_MAX_ATTEMPTS", "1")
    budget = BudgetReservationService()
    res_id = await _reserve(budget, "key-dlq")
    await _expire(res_id, (await RewardBudgetReservationRepository().find_by_id(res_id)) or {})

    jobs = ReservationReleaseJobRepository()
    service = _build(budget, job_repo=jobs)

    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="always")
    arm(budget, "release", injector)

    summary = await service.run_once(ttl_seconds=3600)
    assert summary["dead_lettered"] == 1
    job = (await jobs.find_many({"tenant_id": TENANT}, limit=10))[0]
    assert job["state"] == "dead_letter" and job["attempt_count"] == 1
    assert job["last_error"]  # visible failure, never silently dropped

    # The reservation is still durable and reserved — the budget is NOT lost,
    # it is bounded by the dead-letter and visible to operators.
    reservation = await RewardBudgetReservationRepository().find_by_id(res_id)
    assert reservation["state"] == "reserved"
    assert reservation["reserved_at"] == OLD_AT
