"""Unit tests for the durable jobs control plane (in-memory backend).

Covers, against the exact repository/service/worker semantics:
- idempotent enqueue (replay + failed-row re-queue)
- claim / lease / heartbeat ordering and scheduled_for deferral
- cancel of queued vs running jobs (cancel_requested + JobCancelled)
- retrying → failed with dead-letter (job.dead_lettered event) after max attempts
- partially_succeeded outcomes
- tenant isolation (tenant B can never see/cancel tenant A's jobs)
- retry semantics (failed → queued, attempts reset; non-failed → conflict)
- lease + expiry sweeps

AETHER_ENV=local so JobsRepository selects the in-memory backend.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-jobs-platform-tests")

from shared.common.common import ConflictError, NotFoundError, utc_now  # noqa: E402

from repositories.jobs_repo import (  # noqa: E402
    JobsRepository,
    reset_jobs_memory,
)
from services.jobs import handlers as handlers_mod  # noqa: E402
from services.jobs.handlers import JobOutcome, register_handler  # noqa: E402
from services.jobs.models import JobStatus  # noqa: E402
from services.jobs.service import JobsService  # noqa: E402
from services.jobs.worker import JobCancelled, JobWorker, LeaseSweeper  # noqa: E402

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


@pytest.fixture()
def repo():
    reset_jobs_memory()
    yield JobsRepository()
    reset_jobs_memory()


@pytest.fixture()
def service(repo):
    return JobsService(repo=repo)


@pytest.fixture()
def registry():
    """Snapshot/restore the handler registry around each test."""
    saved_handlers = dict(handlers_mod.HANDLER_REGISTRY)
    saved_invocable = set(handlers_mod.TENANT_INVOCABLE)
    yield handlers_mod
    handlers_mod.HANDLER_REGISTRY.clear()
    handlers_mod.HANDLER_REGISTRY.update(saved_handlers)
    handlers_mod.TENANT_INVOCABLE.clear()
    handlers_mod.TENANT_INVOCABLE.update(saved_invocable)


def _worker(repo, **kw):
    kw.setdefault("backoff_base_seconds", 0)  # retries claimable immediately
    return JobWorker(repo=repo, worker_id=kw.pop("worker_id", "w1"), **kw)


def _event_types(events):
    return [e["event_type"] for e in events]


# ── Idempotent enqueue ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_is_idempotent(service, repo):
    first = await service.enqueue(TENANT_A, "t.echo", {"n": 1}, idempotency_key="k1")
    second = await service.enqueue(TENANT_A, "t.echo", {"n": 2}, idempotency_key="k1")

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["id"] == first["id"]
    assert second["payload"] == {"n": 1}  # original payload wins on replay
    assert first["status"] == JobStatus.QUEUED.value

    # exactly one job row and one job.queued event
    jobs = await service.list_jobs(TENANT_A)
    assert len(jobs) == 1
    events = await repo.list_events(TENANT_A, first["id"])
    assert _event_types(events) == ["job.queued"]


@pytest.mark.asyncio
async def test_enqueue_same_key_different_type_or_tenant_is_new(service):
    a = await service.enqueue(TENANT_A, "t.echo", {}, idempotency_key="k1")
    b = await service.enqueue(TENANT_A, "t.other", {}, idempotency_key="k1")
    c = await service.enqueue(TENANT_B, "t.echo", {}, idempotency_key="k1")
    assert len({a["id"], b["id"], c["id"]}) == 3
    assert not b["replayed"] and not c["replayed"]


@pytest.mark.asyncio
async def test_enqueue_over_failed_row_requeues_it(service, repo):
    job = await service.enqueue(TENANT_A, "t.echo", {"n": 1}, idempotency_key="k1")
    await repo.finish(job["id"], JobStatus.FAILED.value, error="boom")

    again = await service.enqueue(TENANT_A, "t.echo", {"n": 1}, idempotency_key="k1")
    assert again["id"] == job["id"]
    assert again["replayed"] is False  # a fresh logical run, not a replay
    assert again["status"] == JobStatus.QUEUED.value
    assert again["attempts"] == 0
    assert again["error"] is None


# ── Claim / lease / heartbeat ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_sets_lease_and_orders_by_priority(service, repo):
    low = await service.enqueue(TENANT_A, "t.echo", {"which": "low"}, priority=200)
    high = await service.enqueue(TENANT_A, "t.echo", {"which": "high"}, priority=10)

    claimed = await repo.claim_next("w1", lease_seconds=60)
    assert claimed["id"] == high["id"]
    assert claimed["status"] == JobStatus.RUNNING.value
    assert claimed["leased_by"] == "w1"
    assert claimed["attempts"] == 1
    assert claimed["lease_expires_at"] is not None
    assert claimed["started_at"] is not None

    second = await repo.claim_next("w2", lease_seconds=60)
    assert second["id"] == low["id"]
    assert await repo.claim_next("w3") is None  # nothing left


@pytest.mark.asyncio
async def test_scheduled_for_defers_claiming(service, repo):
    future = utc_now() + timedelta(hours=1)
    await service.enqueue(TENANT_A, "t.echo", {}, scheduled_for=future)
    assert await repo.claim_next("w1") is None

    past = utc_now() - timedelta(seconds=1)
    due = await service.enqueue(TENANT_A, "t.echo", {"due": True}, scheduled_for=past)
    claimed = await repo.claim_next("w1")
    assert claimed["id"] == due["id"]


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_and_detects_loss(service, repo):
    job = await service.enqueue(TENANT_A, "t.echo", {})
    claimed = await repo.claim_next("w1", lease_seconds=60)

    assert await repo.heartbeat(claimed["id"], "w1", lease_seconds=120) is True
    refreshed = await repo.get_job(TENANT_A, job["id"])
    assert refreshed["lease_expires_at"] > claimed["lease_expires_at"]

    # wrong worker → lease not held
    assert await repo.heartbeat(claimed["id"], "intruder") is False
    # finished job → lease gone
    await repo.finish(claimed["id"], JobStatus.SUCCEEDED.value, result={})
    assert await repo.heartbeat(claimed["id"], "w1") is False


@pytest.mark.asyncio
async def test_claim_filters_job_types(service, repo):
    await service.enqueue(TENANT_A, "t.alpha", {})
    beta = await service.enqueue(TENANT_A, "t.beta", {})
    claimed = await repo.claim_next("w1", job_types=["t.beta"])
    assert claimed["id"] == beta["id"]
    assert await repo.claim_next("w1", job_types=["t.gamma"]) is None


# ── Cancel: queued vs running ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_queued_job_is_immediate(service, repo):
    job = await service.enqueue(TENANT_A, "t.echo", {})
    cancelled = await service.cancel(TENANT_A, job["id"])
    assert cancelled["status"] == JobStatus.CANCELLED.value
    assert cancelled["completed_at"] is not None
    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert "job.cancelled" in events
    # cancelled jobs are not claimable
    assert await repo.claim_next("w1") is None
    # cancelling again is a conflict (terminal)
    with pytest.raises(ConflictError):
        await service.cancel(TENANT_A, job["id"])


@pytest.mark.asyncio
async def test_cancel_running_job_requests_then_worker_cancels(service, repo, registry):
    hb_results: list = []

    @register_handler("t.cancellable")
    async def cancellable(payload, ctx):
        # first heartbeat: fine; then the operator cancels; next heartbeat raises
        hb_results.append(await ctx.heartbeat())
        await service.cancel(TENANT_A, ctx.job_id)
        await ctx.heartbeat()  # must raise JobCancelled
        return JobOutcome(status="succeeded", result={})  # pragma: no cover

    job = await service.enqueue(TENANT_A, "t.cancellable", {})
    worker = _worker(repo)
    assert await worker.run_once() is True

    final = await service.get_job(TENANT_A, job["id"])
    assert hb_results == [True]
    assert final["status"] == JobStatus.CANCELLED.value
    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert "job.cancel_requested" in events
    assert "job.cancelled" in events


@pytest.mark.asyncio
async def test_cancel_running_status_is_cancel_requested(service, repo):
    job = await service.enqueue(TENANT_A, "t.echo", {})
    await repo.claim_next("w1")
    updated = await service.cancel(TENANT_A, job["id"])
    assert updated["status"] == JobStatus.CANCEL_REQUESTED.value
    # heartbeat now reports loss (repo level: no longer 'running')
    assert await repo.heartbeat(job["id"], "w1") is False
    # duplicate cancel is idempotent, not a conflict
    again = await service.cancel(TENANT_A, job["id"])
    assert again["status"] == JobStatus.CANCEL_REQUESTED.value


# ── Retry → failed → dead letter ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrying_then_dead_letter_after_max_attempts(service, repo, registry):
    calls = {"n": 0}

    @register_handler("t.flaky")
    async def flaky(payload, ctx):
        calls["n"] += 1
        raise RuntimeError(f"boom {calls['n']}")

    job = await service.enqueue(TENANT_A, "t.flaky", {}, max_attempts=3)
    worker = _worker(repo)

    # attempts 1 and 2 → retrying (backoff 0 keeps it claimable)
    assert await worker.run_once() is True
    mid = await service.get_job(TENANT_A, job["id"])
    assert mid["status"] == JobStatus.RETRYING.value
    assert mid["attempts"] == 1
    assert await worker.run_once() is True

    # attempt 3 exhausts max_attempts → failed + dead-lettered
    assert await worker.run_once() is True
    final = await service.get_job(TENANT_A, job["id"])
    assert final["status"] == JobStatus.FAILED.value
    assert final["attempts"] == 3
    assert "boom 3" in final["error"]

    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert events.count("job.retrying") == 2
    assert "job.failed" in events
    assert "job.dead_lettered" in events
    assert calls["n"] == 3
    # nothing left to claim
    assert await worker.run_once() is False


@pytest.mark.asyncio
async def test_handler_declared_failure_also_retries_then_dead_letters(service, repo, registry):
    @register_handler("t.reportsfail")
    async def reports_fail(payload, ctx):
        return JobOutcome(status="failed", result={}, error="declared failure")

    job = await service.enqueue(TENANT_A, "t.reportsfail", {}, max_attempts=1)
    assert await _worker(repo).run_once() is True
    final = await service.get_job(TENANT_A, job["id"])
    assert final["status"] == JobStatus.FAILED.value
    assert "declared failure" in final["error"]
    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert "job.dead_lettered" in events


@pytest.mark.asyncio
async def test_unknown_job_type_fails_terminally(service, repo):
    job = await service.enqueue(TENANT_A, "t.nobody-registered-this", {})
    assert await _worker(repo).run_once() is True
    final = await service.get_job(TENANT_A, job["id"])
    assert final["status"] == JobStatus.FAILED.value
    assert "no handler registered" in final["error"]


# ── Success shapes ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_succeeded_outcome(service, repo, registry):
    @register_handler("t.ok")
    async def ok(payload, ctx):
        await ctx.emit_event("t.progress", {"pct": 50})
        return JobOutcome(status="succeeded", result={"echo": payload})

    job = await service.enqueue(TENANT_A, "t.ok", {"x": 1})
    assert await _worker(repo).run_once() is True
    final = await service.get_job(TENANT_A, job["id"])
    assert final["status"] == JobStatus.SUCCEEDED.value
    assert final["result"] == {"echo": {"x": 1}}
    assert final["completed_at"] is not None
    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert events == ["job.queued", "job.started", "t.progress", "job.succeeded"]


@pytest.mark.asyncio
async def test_partially_succeeded_outcome(service, repo, registry):
    @register_handler("t.partial")
    async def partial(payload, ctx):
        return JobOutcome(
            status="partially_succeeded",
            result={"done": 8, "failed": 2},
            error="2 of 10 rows failed",
        )

    job = await service.enqueue(TENANT_A, "t.partial", {})
    assert await _worker(repo).run_once() is True
    final = await service.get_job(TENANT_A, job["id"])
    assert final["status"] == JobStatus.PARTIALLY_SUCCEEDED.value
    assert final["result"] == {"done": 8, "failed": 2}
    assert final["error"] == "2 of 10 rows failed"
    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert "job.partially_succeeded" in events


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_on_reads_and_writes(service):
    job = await service.enqueue(TENANT_A, "t.echo", {"secret": True})

    assert await service.get_job(TENANT_B, job["id"]) is None
    assert await service.list_jobs(TENANT_B) == []
    with pytest.raises(NotFoundError):
        await service.cancel(TENANT_B, job["id"])
    with pytest.raises(NotFoundError):
        await service.list_events(TENANT_B, job["id"])
    with pytest.raises(NotFoundError):
        await service.retry(TENANT_B, job["id"])

    # tenant A remains untouched by B's attempts
    mine = await service.get_job(TENANT_A, job["id"])
    assert mine["status"] == JobStatus.QUEUED.value
    summary_b = await service.summary(TENANT_B)
    assert summary_b["total"] == 0


# ── Retry semantics ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_resets_failed_job(service, repo):
    job = await service.enqueue(TENANT_A, "t.echo", {})
    await repo.claim_next("w1")
    await repo.finish(job["id"], JobStatus.FAILED.value, error="boom")

    retried = await service.retry(TENANT_A, job["id"])
    assert retried["status"] == JobStatus.QUEUED.value
    assert retried["attempts"] == 0
    assert retried["error"] is None
    assert retried["completed_at"] is None
    events = await repo.list_events(TENANT_A, job["id"])
    assert any(
        e["event_type"] == "job.queued" and e["payload"].get("retried")
        for e in events
    )


@pytest.mark.asyncio
async def test_retry_non_failed_job_conflicts(service):
    job = await service.enqueue(TENANT_A, "t.echo", {})
    with pytest.raises(ConflictError):
        await service.retry(TENANT_A, job["id"])


# ── Sweeps ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_expired_leases_retries_then_fails(service, repo):
    job = await service.enqueue(TENANT_A, "t.echo", {}, max_attempts=2)
    sweeper = LeaseSweeper(repo=repo)

    await repo.claim_next("w1", lease_seconds=-1)  # lease already expired
    counts = await sweeper.sweep_once()
    assert counts["lease_swept"] == 1
    mid = await service.get_job(TENANT_A, job["id"])
    assert mid["status"] == JobStatus.RETRYING.value

    await repo.claim_next("w1", lease_seconds=-1)  # attempt 2, expired again
    await sweeper.sweep_once()
    final = await service.get_job(TENANT_A, job["id"])
    assert final["status"] == JobStatus.FAILED.value
    assert final["error"] == "lease expired"
    events = _event_types(await repo.list_events(TENANT_A, job["id"]))
    assert "job.dead_lettered" in events


@pytest.mark.asyncio
async def test_sweep_expired_jobs(service, repo):
    stale = await service.enqueue(TENANT_A, "t.echo", {})
    # expires_at is repo-level (not exposed via service enqueue contract)
    fresh = await repo.enqueue(TENANT_A, "t.echo", {}, expires_at=utc_now() + timedelta(hours=1))
    doomed = await repo.enqueue(TENANT_A, "t.echo", {}, expires_at=utc_now() - timedelta(seconds=1))

    swept = await repo.sweep_expired_jobs()
    assert [j["id"] for j in swept] == [doomed["id"]]
    assert (await repo.get_job(TENANT_A, doomed["id"]))["status"] == JobStatus.EXPIRED.value
    assert (await repo.get_job(TENANT_A, fresh["id"]))["status"] == JobStatus.QUEUED.value
    assert (await repo.get_job(TENANT_A, stale["id"]))["status"] == JobStatus.QUEUED.value


# ── Handler registry ─────────────────────────────────────────────────────────

def test_register_handler_rejects_duplicates(registry):
    @register_handler("t.unique", tenant_invocable=True)
    async def one(payload, ctx):  # pragma: no cover
        return JobOutcome(status="succeeded", result={})

    assert "t.unique" in handlers_mod.HANDLER_REGISTRY
    assert "t.unique" in handlers_mod.TENANT_INVOCABLE
    with pytest.raises(ValueError):
        @register_handler("t.unique")
        async def two(payload, ctx):  # pragma: no cover
            return JobOutcome(status="succeeded", result={})


def test_job_cancelled_is_an_exception():
    assert issubclass(JobCancelled, Exception)
