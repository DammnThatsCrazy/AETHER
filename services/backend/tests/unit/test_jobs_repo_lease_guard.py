"""M8-B3: durable job lease ownership guard on finish() and update_payload().

The jobs platform claims a job with ``claim_next`` (leased_by + lease
expiry), and the sweeper reaps expired leases back to 'retrying'. A stale
worker whose lease was reaped and whose job was re-claimed by a NEW worker
must NOT be able to finish() the job (clobbering the new owner's active
running state) or update_payload() its checkpoint (overwriting the new
owner's durable cursor). These tests exercise the in-memory backend, which
must enforce the identical invariant as the Postgres path.

Scenario (matches the failure that motivated M8-B3):
  1. Worker A claims job J (leased_by='A', status='running').
  2. A's lease expires; sweep_expired_leases() reclaims J ('retrying',
     leased_by=None).
  3. Worker B claims J (leased_by='B', status='running').
  4. A (stale) calls finish(J, ...) / update_payload(J, ...).
  5. Both must return None and leave J owned by B, untouched.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from shared.common.common import utc_now

from repositories.jobs_repo import (
    get_jobs_repository,
    reset_jobs_memory,
)
from services.jobs.models import JobStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_jobs_memory():
    reset_jobs_memory()
    yield
    reset_jobs_memory()


async def _claim_stale_and_reclaim(repo) -> tuple[dict, dict]:
    """Run the A-stalls->sweep->B-reclaims scenario and return (job, b_row)."""
    job = await repo.enqueue("t1", "replay", {"n": 1}, max_attempts=5)
    await repo.claim_next(worker_id="A", lease_seconds=60)
    # Expire A's lease, then let the sweeper reclaim the job.
    await repo.sweep_expired_leases()  # no-op while the lease is live
    row_a = await repo.get_job_any(job["id"])
    assert row_a["leased_by"] == "A", "setup: A holds the fresh lease"
    assert row_a["status"] == JobStatus.RUNNING.value
    # Backdate the lease so the sweeper reaps it, then reclaim by B.
    from repositories.jobs_repo import _MEM_JOBS  # in-memory backend fixture

    rec = _MEM_JOBS[job["id"]]
    rec["lease_expires_at"] = (utc_now() - timedelta(seconds=1)).isoformat()
    await repo.sweep_expired_leases()
    row_swept = await repo.get_job_any(job["id"])
    assert row_swept["leased_by"] is None, "setup: sweeper released the lease"
    assert row_swept["status"] == JobStatus.RETRYING.value
    b_row = await repo.claim_next(worker_id="B", lease_seconds=60)
    assert b_row["leased_by"] == "B", "setup: B now owns the job"
    assert b_row["status"] == JobStatus.RUNNING.value
    return job, b_row


async def test_stale_worker_cannot_finish_after_lease_reclaimed():
    repo = get_jobs_repository()
    job, b_row = await _claim_stale_and_reclaim(repo)

    # Stale worker A tries to record success for a job B now owns.
    outcome = await repo.finish(
        job["id"], JobStatus.SUCCEEDED.value, result={"ok": True}, worker_id="A"
    )
    assert outcome is None, "stale worker finish() must be a no-op"
    current = await repo.get_job_any(job["id"])
    assert current["leased_by"] == "B", "lease must still belong to the current owner"
    assert current["status"] == JobStatus.RUNNING.value, "status must be untouched"
    assert current.get("result") is None, "no stale result may be recorded"


async def test_current_owner_finish_releases_lease():
    repo = get_jobs_repository()
    job, _ = await _claim_stale_and_reclaim(repo)

    # The actual owner B still finishes normally and releases the lease.
    outcome = await repo.finish(
        job["id"], JobStatus.SUCCEEDED.value, result={"ok": True}, worker_id="B"
    )
    assert outcome is not None, "current owner's finish() must transition the job"
    assert outcome["status"] == JobStatus.SUCCEEDED.value
    assert outcome["leased_by"] is None, "the owner's finish() releases the lease"
    assert outcome["completed_at"] is not None


async def test_stale_worker_cannot_update_payload():
    repo = get_jobs_repository()
    job, _ = await _claim_stale_and_reclaim(repo)

    # Stale worker A writes a checkpoint; B's durable cursor must be safe.
    outcome = await repo.update_payload(
        job["id"], {"cursor": {"stale": True}}, worker_id="A"
    )
    assert outcome is None, "stale worker checkpoint must be a no-op"
    current = await repo.get_job_any(job["id"])
    assert current["leased_by"] == "B"
    assert current["status"] == JobStatus.RUNNING.value


async def test_heartbeat_ownership_guard_is_preserved():
    """Regression: the heartbeat invariant finish/update_payload now match."""
    repo = get_jobs_repository()
    job, _ = await _claim_stale_and_reclaim(repo)

    assert await repo.heartbeat(job["id"], "A") is False, "non-owner cannot heartbeat"
    assert await repo.heartbeat(job["id"], "B") is True, "owner still heartbeats"


async def test_guard_defaults_off_when_no_worker_id():
    """A caller that predates the guard (no worker_id) keeps its old behavior."""
    repo = get_jobs_repository()
    job, _ = await _claim_stale_and_reclaim(repo)

    outcome = await repo.finish(
        job["id"], JobStatus.FAILED.value, error="legacy caller"
    )
    assert outcome is not None, "legacy finish() without worker_id still applies"
    assert outcome["status"] == JobStatus.FAILED.value
    assert outcome["leased_by"] is None
