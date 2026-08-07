"""
Unit tests for the delivery-lease release guard (B7).

The delivery worker and the rewards outbox release a leased job (DELIVERED /
FAILED / DEAD_LETTER) through a plain update-by-id with NO ``leased_by``
ownership check. If a worker's lease expires and another worker re-claims the
batch, the stale worker's release would overwrite the new owner's active job —
the split-brain that double-delivers in the rewards/delivery fan-out.

These tests prove the ``release_job`` guard added to DeliveryJobRepository and
RewardDeliveryJobRepository:
  * a stale worker's release is a NO-OP (returns None, mutates nothing) when
    the job is now leased by a different worker;
  * the current owner's release still succeeds;
  * an unleased job (direct-dispatch path) is still releasable.
All scenarios run against the in-memory backend (AETHER_ENV=local).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from repositories.delivery_repos import (
    DeliveryAttemptRepository,
    DeliveryIntentRepository,
    DeliveryJobRepository,
    ExternalResourceLinkRepository,
    ProviderReceiptRepository,
)
from services.delivery.adapters.base import (
    AdapterReceipt,
    ProviderAdapter,
    ProviderAdapterRegistry,
)
from services.delivery.models import (
    DeliveryChannel,
    DeliveryIntent,
    DeliveryJob,
    DeliveryJobPriority,
    DeliveryJobState,
)
from services.delivery.worker import DeliveryWorker
from services.rewards.delivery_outbox import (
    RewardDeliveryJobRepository,
    RewardDeliveryOutbox,
    SenderResult,
)


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _expire(job: dict) -> None:
    """Force a leased job's lease to be expired (in-memory backend)."""
    job["lease_expires_at"] = "2000-01-01T00:00:00+00:00"


async def _insert_platform_job(job_repo: DeliveryJobRepository, **overrides: object) -> dict:
    job = {
        "id": "job-b7",
        "tenant_id": "t-b7",
        "state": "queued",
        "provider_adapter": "success",
        "payload": {"title": "B7"},
        "provider_config": {},
        "attempt_count": 0,
        "max_attempts": 5,
        "next_attempt_at": "2000-01-01T00:00:00+00:00",
        "leased_by": None,
        "lease_expires_at": None,
    }
    job.update(overrides)
    await job_repo.insert(job["id"], job)
    return dict(job)


async def _insert_reward_job(job_repo: RewardDeliveryJobRepository, **overrides: object) -> dict:
    job = {
        "id": "reward-job-b7",
        "tenant_id": "t-b7",
        "state": "queued",
        "provider_adapter": "tenant_webhook",
        "payload": {},
        "provider_config": {},
        "attempt_count": 0,
        "max_attempts": 6,
        "next_attempt_at": "2000-01-01T00:00:00+00:00",
        "leased_by": None,
        "lease_expires_at": None,
    }
    job.update(overrides)
    await job_repo.insert(job["id"], job)
    return dict(job)


# ═══════════════════════════════════════════════════════════════════════════
# DeliveryJobRepository.release_job
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delivery_stale_worker_release_is_noop_after_lease_reclaimed():
    """A worker whose lease expired (and whose batch was re-claimed) cannot
    overwrite the new owner's active job."""
    jobs = DeliveryJobRepository()
    job = await _insert_platform_job(jobs)

    # Worker A claims the batch.
    claimed_a = await jobs.lease_next_batch(worker_id="worker-a", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_a] == [job["id"]]

    # A's lease expires; worker B re-claims the same job.
    _expire(await jobs.find_by_id(job["id"]))
    claimed_b = await jobs.lease_next_batch(worker_id="worker-b", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_b] == [job["id"]]

    # Stale worker A tries to mark the job DELIVERED — must be a no-op.
    result = await jobs.release_job(job["id"], "worker-a", {
        "state": DeliveryJobState.DELIVERED.value,
        "attempt_count": 1,
        "leased_by": None,
        "lease_expires_at": None,
    })
    after = await jobs.find_by_id(job["id"])
    assert result is None
    assert after["state"] == "leased"           # not overwritten to DELIVERED
    assert after["leased_by"] == "worker-b"     # still the new owner's batch
    assert after["attempt_count"] == 0


@pytest.mark.asyncio
async def test_delivery_current_owner_release_still_succeeds():
    """The actual lease holder can still release (DELIVERED) exactly as before."""
    jobs = DeliveryJobRepository()
    job = await _insert_platform_job(jobs)
    await jobs.lease_next_batch(worker_id="worker-a", batch_size=10, lease_seconds=120)

    result = await jobs.release_job(job["id"], "worker-a", {
        "state": DeliveryJobState.DELIVERED.value,
        "attempt_count": 1,
        "leased_by": None,
        "lease_expires_at": None,
    })
    after = await jobs.find_by_id(job["id"])
    assert result is not None
    assert result["state"] == DeliveryJobState.DELIVERED.value
    assert after["state"] == DeliveryJobState.DELIVERED.value
    assert after["attempt_count"] == 1
    assert after["leased_by"] is None


@pytest.mark.asyncio
async def test_delivery_stale_retry_release_is_noop():
    """A stale worker's retry scheduling (FAILED) must also be a no-op."""
    jobs = DeliveryJobRepository()
    job = await _insert_platform_job(jobs)
    await jobs.lease_next_batch(worker_id="worker-a", batch_size=10, lease_seconds=120)
    _expire(await jobs.find_by_id(job["id"]))
    await jobs.lease_next_batch(worker_id="worker-b", batch_size=10, lease_seconds=120)

    result = await jobs.release_job(job["id"], "worker-a", {
        "state": DeliveryJobState.FAILED.value,
        "attempt_count": 1,
        "next_attempt_at": "2099-01-01T00:00:00+00:00",
        "leased_by": None,
        "lease_expires_at": None,
    })
    after = await jobs.find_by_id(job["id"])
    assert result is None
    assert after["state"] == "leased"
    assert after["leased_by"] == "worker-b"


@pytest.mark.asyncio
async def test_delivery_unleased_job_release_remains_allowed():
    """Direct-dispatch path: a job that was never leased stays releasable."""
    jobs = DeliveryJobRepository()
    job = await _insert_platform_job(jobs)  # no lease ever taken

    result = await jobs.release_job(job["id"], "worker-a", {
        "state": DeliveryJobState.DEAD_LETTER.value,
        "attempt_count": 1,
        "leased_by": None,
        "lease_expires_at": None,
    })
    after = await jobs.find_by_id(job["id"])
    assert result is not None
    assert after["state"] == DeliveryJobState.DEAD_LETTER.value


# ═══════════════════════════════════════════════════════════════════════════
# RewardDeliveryJobRepository.release_job
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reward_outbox_stale_worker_release_is_noop_after_lease_reclaimed():
    """Same stale-worker split-brain, on the rewards-owned job table."""
    jobs = RewardDeliveryJobRepository()
    job = await _insert_reward_job(jobs)

    claimed_a = await jobs.lease_next_batch(worker_id="outbox-a", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_a] == [job["id"]]

    _expire(await jobs.find_by_id(job["id"]))
    claimed_b = await jobs.lease_next_batch(worker_id="outbox-b", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_b] == [job["id"]]

    result = await jobs.release_job(job["id"], "outbox-a", {
        "state": "delivered",
        "attempt_count": 1,
        "leased_by": None,
        "lease_expires_at": None,
    })
    after = await jobs.find_by_id(job["id"])
    assert result is None
    assert after["state"] == "leased"
    assert after["leased_by"] == "outbox-b"


@pytest.mark.asyncio
async def test_reward_outbox_current_owner_release_succeeds():
    jobs = RewardDeliveryJobRepository()
    job = await _insert_reward_job(jobs)
    await jobs.lease_next_batch(worker_id="outbox-a", batch_size=10, lease_seconds=120)

    result = await jobs.release_job(job["id"], "outbox-a", {
        "state": "delivered",
        "attempt_count": 1,
        "leased_by": None,
        "lease_expires_at": None,
    })
    after = await jobs.find_by_id(job["id"])
    assert result is not None
    assert result["state"] == "delivered"
    assert after["state"] == "delivered"
    assert after["leased_by"] is None


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: the worker / outbox release path is wired to the guard
# ═══════════════════════════════════════════════════════════════════════════

class _SuccessAdapter(ProviderAdapter):
    adapter_name = "success"

    def __init__(self) -> None:
        self.calls = []

    async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
        self.calls.append(payload)
        return AdapterReceipt(
            external_id="ext-b7-1",
            raw_response={"ok": True},
            http_status=200,
        )


class _ScriptedSender:
    def __init__(self, *results: SenderResult) -> None:
        self._results = list(results)
        self.calls = 0

    async def send(self, job):
        r = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return r


def _worker(job_repo, intent_repo, attempt_repo, receipt_repo, link_repo, adapter, *, worker_id):
    registry = ProviderAdapterRegistry()
    registry.register(adapter)
    return DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=attempt_repo,
        receipt_repo=receipt_repo,
        resource_link_repo=link_repo,
        adapter_registry=registry,
        worker_id=worker_id,
    )


@pytest.mark.asyncio
async def test_delivery_worker_stale_process_job_does_not_overwrite_new_owner():
    """Full path: stale worker A finishes its (already-sent) provider call and
    releases AFTER worker B re-claimed the batch — the job row must survive."""
    job_repo = DeliveryJobRepository()
    intent_repo = DeliveryIntentRepository()
    attempt_repo = DeliveryAttemptRepository()
    receipt_repo = ProviderReceiptRepository()
    link_repo = ExternalResourceLinkRepository()
    adapter = _SuccessAdapter()

    worker_a = _worker(job_repo, intent_repo, attempt_repo, receipt_repo, link_repo,
                       adapter, worker_id="worker-a")
    worker_b = _worker(job_repo, intent_repo, attempt_repo, receipt_repo, link_repo,
                       adapter, worker_id="worker-b")

    intent = DeliveryIntent(
        tenant_id="t-b7", source_type="notification", source_id="notif-b7",
        channels=["success"],
    )
    await intent_repo.insert(intent.id, intent.model_dump())
    job = DeliveryJob(
        intent_id=intent.id,
        tenant_id="t-b7",
        channel=DeliveryChannel.NOTIFICATION,
        provider_adapter="success",
        priority=DeliveryJobPriority.P2,
        payload={"title": "B7 stale"},
    )
    await job_repo.insert(job.id, job.model_dump())

    # Worker A claims the job and starts its (slow) provider call.
    claimed_a = await job_repo.lease_next_batch(worker_id="worker-a", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_a] == [job.id]

    # A's lease expires; worker B re-claims the same job.
    _expire(await job_repo.find_by_id(job.id))
    claimed_b = await job_repo.lease_next_batch(worker_id="worker-b", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_b] == [job.id]

    # A's provider call returns; A releases with its OWN identity → no-op.
    await worker_a._process_job(claimed_a[0])

    after = await job_repo.find_by_id(job.id)
    assert after["state"] != DeliveryJobState.DELIVERED.value  # A did not mark it delivered
    assert after["leased_by"] == "worker-b"                    # B's batch untouched


@pytest.mark.asyncio
async def test_reward_outbox_stale_process_job_does_not_overwrite_new_owner():
    """Full path: stale reward outbox worker A releases after B re-claimed —
    the reward job row must survive."""
    jobs = RewardDeliveryJobRepository()
    receipts = ProviderReceiptRepository()
    sender = _ScriptedSender(SenderResult("success", external_id="ext-b7-reward", response_code=200))

    outbox_a = RewardDeliveryOutbox(
        job_repo=jobs, receipt_repo=receipts, sender=sender, worker_id="outbox-a",
    )
    outbox_b = RewardDeliveryOutbox(
        job_repo=jobs, receipt_repo=receipts, sender=sender, worker_id="outbox-b",
    )

    action = {"id": None, "payload": {"idempotency_key": "b7-idem", "tenant_id": "t-b7"}}
    job = await outbox_a.enqueue(action, {"webhook_url": "http://127.0.0.1:9/b7-hook"}, "t-b7")

    claimed_a = await jobs.lease_next_batch(worker_id="outbox-a", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_a] == [job["id"]]

    _expire(await jobs.find_by_id(job["id"]))
    claimed_b = await jobs.lease_next_batch(worker_id="outbox-b", batch_size=10, lease_seconds=120)
    assert [j["id"] for j in claimed_b] == [job["id"]]

    await outbox_a._process_job(claimed_a[0])

    after = await jobs.find_by_id(job["id"])
    assert after["state"] != "delivered"
    assert after["leased_by"] == "outbox-b"
