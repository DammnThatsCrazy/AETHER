"""Integration tests for DeliveryWorker — in-memory backend."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.repos import reset_in_memory_stores
from services.delivery.adapters.base import (
    AdapterReceipt,
    ProviderAdapter,
    ProviderAdapterRegistry,
    RetryableProviderError,
    ProviderError,
)
from services.delivery.models import (
    DeliveryChannel,
    DeliveryIntent,
    DeliveryJob,
    DeliveryJobPriority,
    DeliveryJobState,
    DeliveryIntentStatus,
)
from services.delivery.worker import DeliveryWorker
from repositories.delivery_repos import (
    DeliveryIntentRepository,
    DeliveryJobRepository,
    DeliveryAttemptRepository,
    ProviderReceiptRepository,
    ExternalResourceLinkRepository,
)


class SuccessAdapter(ProviderAdapter):
    adapter_name = "success"

    def __init__(self) -> None:
        self.calls = []

    async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
        self.calls.append(payload)
        return AdapterReceipt(
            external_id=f"ext-{len(self.calls)}",
            raw_response={"ok": True},
            http_status=200,
        )


class FailureAdapter(ProviderAdapter):
    adapter_name = "failure"
    call_count = 0

    async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
        self.call_count += 1
        raise ProviderError("provider rejected", http_status=400)


class RetryableAdapter(ProviderAdapter):
    adapter_name = "retryable"
    call_count = 0

    async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
        self.call_count += 1
        raise RetryableProviderError("transient error", http_status=503)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _make_registry(*adapters):
    registry = ProviderAdapterRegistry()
    for a in adapters:
        registry.register(a)
    return registry


async def _create_job(job_repo, intent_repo, provider_adapter: str, max_attempts: int = 5) -> dict:
    intent = DeliveryIntent(
        tenant_id="t1",
        source_type="notification",
        source_id="notif-001",
        channels=[provider_adapter],
    )
    await intent_repo.insert(intent.id, intent.model_dump())

    job = DeliveryJob(
        intent_id=intent.id,
        tenant_id="t1",
        channel=DeliveryChannel.NOTIFICATION,
        provider_adapter=provider_adapter,
        priority=DeliveryJobPriority.P2,
        payload={"title": "Test"},
        max_attempts=max_attempts,
    )
    await job_repo.insert(job.id, job.model_dump())
    return job.model_dump()


@pytest.mark.asyncio
async def test_worker_delivers_job_on_success():
    intent_repo = DeliveryIntentRepository()
    job_repo = DeliveryJobRepository()
    attempt_repo = DeliveryAttemptRepository()
    receipt_repo = ProviderReceiptRepository()
    link_repo = ExternalResourceLinkRepository()

    adapter = SuccessAdapter()
    registry = _make_registry(adapter)

    worker = DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=attempt_repo,
        receipt_repo=receipt_repo,
        resource_link_repo=link_repo,
        adapter_registry=registry,
    )

    job = await _create_job(job_repo, intent_repo, "success")
    await worker._process_job(job)

    updated = await job_repo.find_by_id(job["id"])
    assert updated["state"] == DeliveryJobState.DELIVERED.value
    assert updated["attempt_count"] == 1

    receipts = await receipt_repo.find_for_intent(job["intent_id"])
    assert len(receipts) == 1
    assert receipts[0]["external_id"] == "ext-1"
    assert not receipts[0]["external_id"].startswith("sim-")


@pytest.mark.asyncio
async def test_worker_dead_letters_on_non_retryable_failure():
    intent_repo = DeliveryIntentRepository()
    job_repo = DeliveryJobRepository()
    attempt_repo = DeliveryAttemptRepository()
    receipt_repo = ProviderReceiptRepository()
    link_repo = ExternalResourceLinkRepository()

    adapter = FailureAdapter()
    registry = _make_registry(adapter)

    worker = DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=attempt_repo,
        receipt_repo=receipt_repo,
        resource_link_repo=link_repo,
        adapter_registry=registry,
    )

    job = await _create_job(job_repo, intent_repo, "failure", max_attempts=3)
    await worker._process_job(job)

    updated = await job_repo.find_by_id(job["id"])
    # Non-retryable error → immediate dead-letter
    assert updated["state"] == DeliveryJobState.DEAD_LETTER.value

    receipts = await receipt_repo.find_for_intent(job["intent_id"])
    assert len(receipts) == 0  # No receipt — delivery never confirmed


@pytest.mark.asyncio
async def test_worker_schedules_retry_on_retryable_failure():
    intent_repo = DeliveryIntentRepository()
    job_repo = DeliveryJobRepository()
    attempt_repo = DeliveryAttemptRepository()
    receipt_repo = ProviderReceiptRepository()
    link_repo = ExternalResourceLinkRepository()

    adapter = RetryableAdapter()
    registry = _make_registry(adapter)

    worker = DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=attempt_repo,
        receipt_repo=receipt_repo,
        resource_link_repo=link_repo,
        adapter_registry=registry,
    )

    job = await _create_job(job_repo, intent_repo, "retryable", max_attempts=3)
    await worker._process_job(job)

    updated = await job_repo.find_by_id(job["id"])
    # First retryable failure → back to failed state with next_attempt_at in future
    assert updated["state"] == DeliveryJobState.FAILED.value
    assert updated["next_attempt_at"] > updated["updated_at"]


@pytest.mark.asyncio
async def test_worker_dead_letters_after_max_attempts():
    intent_repo = DeliveryIntentRepository()
    job_repo = DeliveryJobRepository()
    attempt_repo = DeliveryAttemptRepository()
    receipt_repo = ProviderReceiptRepository()
    link_repo = ExternalResourceLinkRepository()

    adapter = RetryableAdapter()
    registry = _make_registry(adapter)

    worker = DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=attempt_repo,
        receipt_repo=receipt_repo,
        resource_link_repo=link_repo,
        adapter_registry=registry,
    )

    job = await _create_job(job_repo, intent_repo, "retryable", max_attempts=1)
    await worker._process_job(job)

    updated = await job_repo.find_by_id(job["id"])
    # max_attempts=1 hit on first attempt → dead-letter
    assert updated["state"] == DeliveryJobState.DEAD_LETTER.value


@pytest.mark.asyncio
async def test_worker_intent_completed_after_all_jobs_delivered():
    intent_repo = DeliveryIntentRepository()
    job_repo = DeliveryJobRepository()
    attempt_repo = DeliveryAttemptRepository()
    receipt_repo = ProviderReceiptRepository()
    link_repo = ExternalResourceLinkRepository()

    adapter = SuccessAdapter()
    registry = _make_registry(adapter)

    worker = DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=attempt_repo,
        receipt_repo=receipt_repo,
        resource_link_repo=link_repo,
        adapter_registry=registry,
    )

    job = await _create_job(job_repo, intent_repo, "success")
    await worker._process_job(job)

    intent = await intent_repo.find_by_id(job["intent_id"])
    assert intent["status"] == DeliveryIntentStatus.DELIVERED.value
