"""Unit tests for the jobs-platform cron scheduler (in-memory backend).

Covers:
- croniter next-run computation across the 2026-03-08 America/New_York
  spring-forward DST transition (02:00 → 03:00 local does not exist)
- misfire policies: fire_once coalesces to a single run, skip drops the run
- overlap policy skip while a previous run is still active
- stable idempotency keys (a replayed tick never double-fires)
- consecutive-failure tracking + auto-disable after 10 failures
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-jobs-platform-tests")

from shared.common.common import BadRequestError  # noqa: E402

from repositories.jobs_repo import JobsRepository, reset_jobs_memory  # noqa: E402
from services.jobs.models import JobStatus  # noqa: E402
from services.jobs.scheduler import (  # noqa: E402
    JobScheduler,
    compute_next_run,
    validate_cron_expression,
    validate_timezone,
)

TENANT = "tenant-sched"
UTC = timezone.utc
NY = ZoneInfo("America/New_York")


@pytest.fixture()
def repo():
    reset_jobs_memory()
    yield JobsRepository()
    reset_jobs_memory()


@pytest.fixture()
def scheduler(repo):
    return JobScheduler(repo=repo)


async def _make_schedule(repo, *, cron="*/30 * * * *", tz="UTC", next_run_at,
                         misfire="fire_once", overlap="skip", job_type="s.job"):
    return await repo.create_schedule(
        TENANT,
        name="test schedule",
        job_type=job_type,
        cron_expression=cron,
        timezone_name=tz,
        misfire_policy=misfire,
        overlap_policy=overlap,
        payload={"from": "schedule"},
        next_run_at=next_run_at,
    )


def _sched_event_types(events):
    return [e["event_type"] for e in events]


# ── DST: 2026-03-08 America/New_York spring forward ─────────────────────────

def test_hourly_cron_skips_nonexistent_two_am_local():
    """On 2026-03-08 clocks jump 02:00→03:00 EST→EDT. The hourly fire after
    01:00 EST (06:00 UTC) is 03:00 EDT (07:00 UTC) — exactly one UTC hour
    later, with no 02:xx local fire."""
    after = datetime(2026, 3, 8, 0, 30, tzinfo=NY)
    first = compute_next_run("0 * * * *", "America/New_York", after)
    second = compute_next_run("0 * * * *", "America/New_York", first)
    third = compute_next_run("0 * * * *", "America/New_York", second)

    assert first == datetime(2026, 3, 8, 6, 0, tzinfo=UTC)   # 01:00 EST
    assert second == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)  # 03:00 EDT (02:00 gap)
    assert third == datetime(2026, 3, 8, 8, 0, tzinfo=UTC)   # 04:00 EDT
    assert second.astimezone(NY).hour == 3  # never 2 AM local


def test_daily_cron_in_dst_gap_rolls_forward_once():
    """A daily 02:30 NY schedule cannot fire at 02:30 on 2026-03-08 (the time
    does not exist); croniter rolls it to 03:00 EDT, then returns to 02:30
    local the following day."""
    after = datetime(2026, 3, 7, 12, 0, tzinfo=NY)
    gap_day = compute_next_run("30 2 * * *", "America/New_York", after)
    next_day = compute_next_run("30 2 * * *", "America/New_York", gap_day)

    assert gap_day == datetime(2026, 3, 8, 3, 0, tzinfo=NY).astimezone(UTC)
    assert next_day.astimezone(NY) == datetime(2026, 3, 9, 2, 30, tzinfo=NY)
    # UTC offsets differ across the jump: EST fire is -5, EDT fire is -4
    assert next_day - gap_day == timedelta(hours=23, minutes=30)


def test_compute_next_run_accepts_naive_after_as_utc():
    naive = datetime(2026, 3, 8, 6, 30)  # treated as UTC
    result = compute_next_run("0 * * * *", "America/New_York", naive)
    assert result == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)


def test_cron_and_timezone_validation():
    validate_cron_expression("*/5 * * * *")
    validate_timezone("America/New_York")
    with pytest.raises(BadRequestError):
        validate_cron_expression("not a cron")
    with pytest.raises(BadRequestError):
        validate_timezone("Mars/Olympus_Mons")


# ── Normal firing + stable idempotency key ───────────────────────────────────

@pytest.mark.asyncio
async def test_due_schedule_fires_once_with_stable_idempotency_key(repo, scheduler):
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    # overlap=allow so the replayed tick reaches the enqueue path — proving it
    # is the STABLE idempotency key (not the overlap guard) that deduplicates.
    sched = await _make_schedule(repo, next_run_at=due, overlap="allow")
    now = due + timedelta(seconds=10)

    actions = await scheduler.tick(now=now)
    assert [a["action"] for a in actions] == ["fired"]
    jobs = await repo.list_jobs(TENANT)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["idempotency_key"] == f"{sched['id']}:{due.isoformat()}"
    assert job["schedule_id"] == sched["id"]
    assert job["payload"] == {"from": "schedule"}
    assert job["requested_by"] == "scheduler"

    updated = await repo.get_schedule(TENANT, sched["id"])
    assert updated["last_job_id"] == job["id"]
    assert updated["last_run_status"] == "fired"
    assert updated["consecutive_failures"] == 0
    # next_run_at advanced beyond now
    assert updated["next_run_at"] > now.isoformat()

    # Replayed tick for the SAME fire time (e.g. crash before mark_fired):
    # the stable idempotency key collapses it onto the existing job.
    await repo.update_schedule(TENANT, sched["id"], {"next_run_at": due})
    again = await scheduler.tick(now=now)
    assert [a["action"] for a in again] == ["fired"]
    jobs = await repo.list_jobs(TENANT)
    assert len(jobs) == 1  # still exactly one job


@pytest.mark.asyncio
async def test_not_due_schedule_does_not_fire(repo, scheduler):
    await _make_schedule(repo, next_run_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC))
    actions = await scheduler.tick(now=datetime(2026, 7, 10, 11, 59, tzinfo=UTC))
    assert actions == []
    assert await repo.list_jobs(TENANT) == []


# ── Misfire policies ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_misfire_fire_once_coalesces_missed_fires_into_one_run(repo, scheduler):
    # */30 cron, due 3 hours ago → 6 missed fires; fire_once coalesces to ONE.
    due = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due, misfire="fire_once")

    actions = await scheduler.tick(now=now)
    assert [a["action"] for a in actions] == ["fired"]
    jobs = await repo.list_jobs(TENANT)
    assert len(jobs) == 1
    assert jobs[0]["idempotency_key"] == f"{sched['id']}:{due.isoformat()}"

    events = _sched_event_types(await repo.list_events(TENANT, sched["id"]))
    assert "schedule.misfired" in events
    assert "schedule.fired" in events
    updated = await repo.get_schedule(TENANT, sched["id"])
    assert updated["next_run_at"] == datetime(2026, 7, 10, 12, 30, tzinfo=UTC).isoformat()


@pytest.mark.asyncio
async def test_misfire_skip_drops_run_and_advances(repo, scheduler):
    due = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due, misfire="skip")

    actions = await scheduler.tick(now=now)
    assert [a["action"] for a in actions] == ["misfire_skipped"]
    assert await repo.list_jobs(TENANT) == []  # nothing enqueued

    events = _sched_event_types(await repo.list_events(TENANT, sched["id"]))
    assert "schedule.misfired" in events
    assert "schedule.fired" not in events
    updated = await repo.get_schedule(TENANT, sched["id"])
    assert updated["last_run_status"] == "misfired"
    assert updated["next_run_at"] > now.isoformat()


@pytest.mark.asyncio
async def test_one_interval_late_is_not_a_misfire(repo, scheduler):
    """Being late by less than one interval (normal tick jitter) fires
    normally without a misfire event."""
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due, misfire="skip")
    actions = await scheduler.tick(now=due + timedelta(minutes=5))
    assert [a["action"] for a in actions] == ["fired"]
    events = _sched_event_types(await repo.list_events(TENANT, sched["id"]))
    assert "schedule.misfired" not in events


# ── Overlap policy ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overlap_skip_while_previous_run_active(repo, scheduler):
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due, overlap="skip")

    # A previous run for this schedule is still active.
    await repo.enqueue(TENANT, "s.job", {}, schedule_id=sched["id"])

    actions = await scheduler.tick(now=due + timedelta(seconds=5))
    assert [a["action"] for a in actions] == ["skipped_overlap"]
    jobs = await repo.list_jobs(TENANT)
    assert len(jobs) == 1  # only the pre-existing active job

    events = _sched_event_types(await repo.list_events(TENANT, sched["id"]))
    assert "schedule.skipped" in events
    updated = await repo.get_schedule(TENANT, sched["id"])
    assert updated["last_run_status"] == "skipped"
    assert updated["next_run_at"] > due.isoformat()


@pytest.mark.asyncio
async def test_overlap_allow_fires_alongside_active_run(repo, scheduler):
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due, overlap="allow")
    await repo.enqueue(TENANT, "s.job", {}, schedule_id=sched["id"])

    actions = await scheduler.tick(now=due + timedelta(seconds=5))
    assert [a["action"] for a in actions] == ["fired"]
    assert len(await repo.list_jobs(TENANT)) == 2


# ── Failure tracking + auto-disable ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_consecutive_failures_auto_disable_after_ten(repo, scheduler, monkeypatch):
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due)

    async def exploding_enqueue(*args, **kwargs):
        raise RuntimeError("enqueue backend down")

    monkeypatch.setattr(repo, "enqueue", exploding_enqueue)

    now = due
    for expected_failures in range(1, 10):
        now = now + timedelta(minutes=31)
        # keep the schedule due for the next tick despite advancement
        await repo.update_schedule(TENANT, sched["id"], {"next_run_at": now})
        actions = await scheduler.tick(now=now + timedelta(seconds=1))
        assert [a["action"] for a in actions] == ["error"]
        current = await repo.get_schedule(TENANT, sched["id"])
        assert current["consecutive_failures"] == expected_failures
        assert current["enabled"] is True
        assert current["last_run_status"] == "error"

    # 10th consecutive failure → auto-disabled
    now = now + timedelta(minutes=31)
    await repo.update_schedule(TENANT, sched["id"], {"next_run_at": now})
    actions = await scheduler.tick(now=now + timedelta(seconds=1))
    assert [a["action"] for a in actions] == ["disabled"]
    final = await repo.get_schedule(TENANT, sched["id"])
    assert final["enabled"] is False
    assert final["consecutive_failures"] == 10
    events = _sched_event_types(await repo.list_events(TENANT, sched["id"]))
    assert "schedule.disabled" in events

    # disabled schedules never fire again
    assert await scheduler.tick(now=now + timedelta(hours=2)) == []


@pytest.mark.asyncio
async def test_successful_fire_resets_consecutive_failures(repo, scheduler):
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    sched = await _make_schedule(repo, next_run_at=due)
    await repo.update_schedule(TENANT, sched["id"], {"consecutive_failures": 7})

    await scheduler.tick(now=due + timedelta(seconds=1))
    updated = await repo.get_schedule(TENANT, sched["id"])
    assert updated["consecutive_failures"] == 0
    assert updated["last_run_status"] == "fired"


@pytest.mark.asyncio
async def test_scheduled_jobs_flow_to_worker(repo, scheduler):
    """End-to-end within local mode: schedule → tick → claimable job."""
    due = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    await _make_schedule(repo, next_run_at=due)
    await scheduler.tick(now=due + timedelta(seconds=1))
    claimed = await repo.claim_next("w1")
    assert claimed is not None
    assert claimed["job_type"] == "s.job"
    assert claimed["status"] == JobStatus.RUNNING.value
