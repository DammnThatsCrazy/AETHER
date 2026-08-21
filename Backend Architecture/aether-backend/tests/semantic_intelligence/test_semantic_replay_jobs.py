"""Durable semantic replay: jobs-platform execution with a persisted cursor.

Regression tests for the removal of the fire-and-forget
``asyncio.create_task(self._run_replay(...))`` path:

- a real (non-dry-run) replay is durably enqueued as a ``semantic.replay`` job
  and executed by the job worker;
- the runner's Bronze cursor is persisted into the durable job payload at every
  checkpoint;
- after a simulated interruption the handler resumes from the persisted
  cursor — already-processed Bronze rows are NOT reprocessed (not row 0);
- resume-after-pause enqueues a fresh durable job carrying the cursor.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.jobs_repo import get_jobs_repository, reset_jobs_memory
from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores

from services.jobs.handlers import HANDLER_REGISTRY, JobContext
from services.jobs.models import JobStatus
from services.jobs.service import get_jobs_service
from services.jobs.worker import JobWorker
from services.semantic_intelligence import replay as replay_mod
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.jobs import (
    SEMANTIC_REPLAY_JOB_TYPE,
    register_semantic_replay_handler,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

pytestmark = pytest.mark.asyncio

TENANT = "tenant_replay_jobs"
_BASE_TS = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate():
    import dataclasses

    from config.settings import settings

    reset_in_memory_stores()
    reset_jobs_memory()
    # The replay handler is now gated on the semantic.replay kill-switch; these
    # tests exercise the replay machinery, so opt the flag on for their duration.
    original_semantic = settings.semantic
    settings.semantic = dataclasses.replace(settings.semantic, replay_enabled=True)
    register_semantic_replay_handler()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    settings.semantic = original_semantic
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()
    reset_jobs_memory()


def _seed_bronze(index: int) -> str:
    """Seed one Bronze event with a strictly increasing received_at."""
    event_id = f"evt_{index:03d}"
    store = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    store[event_id] = {
        "id": event_id,
        "tenant_id": TENANT,
        "event_id": event_id,
        "event_type": "feedback_submitted",
        "event_family": "outcome",
        "received_at": (_BASE_TS + timedelta(seconds=index)).isoformat(),
        "payload": {
            "event_id": event_id,
            "event_type": "feedback_submitted",
            "user_id": "u1",
            "properties": {"content": f"great product {index}", "product_id": "prod_1"},
        },
    }
    return event_id


async def test_real_replay_is_enqueued_not_fire_and_forget():
    for i in range(3):
        _seed_bronze(i)
    svc = service_mod.get_semantic_service()

    result = await svc.create_replay_job(TENANT, dry_run=False, filters={})
    assert result["status"] == "queued"
    platform_job_id = result["platform_job_id"]

    # Nothing ran in-process: no observations until the durable worker runs.
    assert await get_store().list_semantic(TENANT) == []
    job = await get_jobs_service().get_job(TENANT, platform_job_id)
    assert job["job_type"] == SEMANTIC_REPLAY_JOB_TYPE
    assert job["status"] == JobStatus.QUEUED.value

    assert await JobWorker().run_once() is True
    job = await get_jobs_service().get_job(TENANT, platform_job_id)
    assert job["status"] == JobStatus.SUCCEEDED.value
    assert job["result"]["replayed"] == 3
    assert len(await get_store().list_semantic(TENANT)) == 3

    # The final Bronze cursor was durably persisted into the job payload.
    assert job["payload"]["cursor"]["event_id"] == "evt_002"
    replay_job = await svc.get_replay_job(TENANT, result["job_id"])
    assert replay_job["status"] == "completed"
    assert replay_job["progress"]["cursor"]["event_id"] == "evt_002"


async def test_handler_resumes_from_payload_cursor_not_row_zero(monkeypatch):
    """A retried job with a persisted cursor skips the processed prefix."""
    for i in range(4):
        _seed_bronze(i)
    svc = service_mod.get_semantic_service()
    replay_job = await svc._replay_jobs.create(TENANT, dry_run=False, filters={})

    processed: list[str] = []
    original = replay_mod.SemanticEventConsumer.on_validated_event

    async def _tracking(self, event):
        processed.append(event.payload.get("event_id"))
        return await original(self, event)

    monkeypatch.setattr(replay_mod.SemanticEventConsumer, "on_validated_event", _tracking)

    handler = HANDLER_REGISTRY[SEMANTIC_REPLAY_JOB_TYPE]
    ctx = JobContext(
        job_id="job_manual_resume",
        tenant_id=TENANT,
        correlation_id=replay_job["id"],
        worker_id="test_worker",
        heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )
    cursor = {
        "received_at": (_BASE_TS + timedelta(seconds=1)).isoformat(),
        "event_id": "evt_001",
    }
    outcome = await handler(
        {"replay_job_id": replay_job["id"], "cursor": cursor}, ctx
    )
    assert outcome.status == "succeeded"
    # Only rows AFTER the cursor were replayed — never row 0 again.
    assert processed == ["evt_002", "evt_003"]
    assert outcome.result["replayed"] == 2


async def test_interruption_checkpoint_then_worker_retry_resumes(monkeypatch):
    """Crash mid-run → the payload cursor survives → the worker's re-run
    processes only the unfinished suffix."""
    for i in range(4):
        _seed_bronze(i)
    monkeypatch.setattr(replay_mod, "_BATCH", 1)  # checkpoint every row

    svc = service_mod.get_semantic_service()
    result = await svc.create_replay_job(TENANT, dry_run=False, filters={})
    platform_job_id = result["platform_job_id"]

    processed: list[str] = []
    original = replay_mod.SemanticEventConsumer.on_validated_event

    async def _crashy(self, event):
        event_id = event.payload.get("event_id")
        if event_id == "evt_002":
            raise KeyboardInterrupt("simulated process death")  # not caught per-row
        processed.append(event_id)
        return await original(self, event)

    monkeypatch.setattr(replay_mod.SemanticEventConsumer, "on_validated_event", _crashy)

    handler = HANDLER_REGISTRY[SEMANTIC_REPLAY_JOB_TYPE]
    jobs_repo = get_jobs_repository()
    # M8-B3: the checkpoint write is lease-guarded, so simulate the REAL worker
    # path — claim the job (leased_by=test_worker) before running the handler,
    # exactly as JobWorker does after claim_next. A direct invocation without a
    # claim would now (correctly) have its checkpoint writes refused.
    claimed = await jobs_repo.claim_next(worker_id="test_worker")
    assert claimed is not None and claimed["id"] == platform_job_id
    job = await jobs_repo.get_job_any(platform_job_id)
    ctx = JobContext(
        job_id=platform_job_id,
        tenant_id=TENANT,
        correlation_id=result["job_id"],
        worker_id="test_worker",
        heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )
    with pytest.raises(KeyboardInterrupt):
        await handler(job["payload"], ctx)

    # The last completed row's cursor was durably persisted before the crash.
    job = await get_jobs_repository().get_job_any(platform_job_id)
    assert job["payload"]["cursor"] == {
        "received_at": (_BASE_TS + timedelta(seconds=1)).isoformat(),
        "event_id": "evt_001",
    }
    assert processed == ["evt_000", "evt_001"]

    # Restart: the simulated crash left the job claimed/running with a live
    # lease. Model real recovery — the lease expires, the sweeper reaps it back
    # to retrying, then a fresh worker claims it and the handler reads the
    # persisted cursor back — evt_000/evt_001 are never reprocessed.
    _EXPIRED = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    from repositories.jobs_repo import _MEM_JOBS  # in-memory backend fixture

    _MEM_JOBS[platform_job_id]["lease_expires_at"] = _EXPIRED
    await jobs_repo.sweep_expired_leases()
    monkeypatch.setattr(replay_mod.SemanticEventConsumer, "on_validated_event", _tracking_factory(processed, original))
    assert await JobWorker().run_once() is True

    assert processed == ["evt_000", "evt_001", "evt_002", "evt_003"]
    job = await get_jobs_service().get_job(TENANT, platform_job_id)
    assert job["status"] == JobStatus.SUCCEEDED.value
    assert len(await get_store().list_semantic(TENANT)) == 4


def _tracking_factory(processed: list, original):
    async def _tracking(self, event):
        processed.append(event.payload.get("event_id"))
        return await original(self, event)

    return _tracking


async def test_resume_after_pause_enqueues_fresh_job_with_cursor():
    for i in range(3):
        _seed_bronze(i)
    svc = service_mod.get_semantic_service()
    result = await svc.create_replay_job(TENANT, dry_run=False, filters={})
    replay_job_id = result["job_id"]
    assert await JobWorker().run_once() is True  # completes fully

    # Pause then resume: resume durably enqueues a NEW platform job carrying
    # the persisted cursor (no in-process task).
    await svc.control_replay_job(TENANT, replay_job_id, "pause")
    resumed = await svc.control_replay_job(TENANT, replay_job_id, "resume")
    assert resumed["status"] == "running"

    jobs = await get_jobs_service().list_jobs(
        TENANT, job_type=SEMANTIC_REPLAY_JOB_TYPE
    )
    queued = [j for j in jobs if j["status"] == JobStatus.QUEUED.value]
    assert len(queued) == 1
    assert queued[0]["payload"]["replay_job_id"] == replay_job_id
    assert queued[0]["payload"]["cursor"]["event_id"] == "evt_002"

    # The resumed run replays nothing new (cursor already at the last row).
    assert await JobWorker().run_once() is True
    job = await get_jobs_service().get_job(TENANT, queued[0]["id"])
    assert job["status"] == JobStatus.SUCCEEDED.value
    assert len(await get_store().list_semantic(TENANT)) == 3


async def test_dry_run_still_counts_inline():
    for i in range(2):
        _seed_bronze(i)
    result = await service_mod.get_semantic_service().create_replay_job(
        TENANT, dry_run=True, filters={}
    )
    assert result["dry_run"] is True
    assert result["scanned"] == 2
    assert await get_store().list_semantic(TENANT) == []
    # Dry runs never touch the jobs platform.
    assert await get_jobs_service().list_jobs(TENANT, job_type=SEMANTIC_REPLAY_JOB_TYPE) == []
