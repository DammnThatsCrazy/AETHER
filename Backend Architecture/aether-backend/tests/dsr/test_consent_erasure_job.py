"""Durable DSR erasure: route → jobs platform → dsr_propagation evidence.

Regression tests for the removal of the fire-and-forget
``asyncio.create_task(handle_erasure_background(...))`` path:

- submitting an erasure DSR durably enqueues a ``consent.erasure`` job and
  opens a dsr_propagation record (no in-process task to lose on crash);
- the job worker executes the erasure and marks the measurement component's
  step with that store's own evidence (tombstone counts + job id receipt);
- re-running the handler (worker retry after a crash) is idempotent;
- per-store failures mark the step failed and fail the attempt so the worker
  retries instead of silently dropping the erasure.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.jobs_repo import reset_jobs_memory
from repositories.repos import ConsentRepository, reset_in_memory_stores

from services.consent.erasure_jobs import (
    ERASURE_JOB_TYPE,
    MEASUREMENT_COMPONENT,
    register_consent_erasure_handler,
)
from services.consent.routes import DataSubjectRequest, submit_dsr
from services.dsr_propagation.models import DSR_COMPONENTS
from services.dsr_propagation.service import DSRPropagationService
from services.jobs.handlers import HANDLER_REGISTRY, JobContext
from services.jobs.models import JobStatus
from services.jobs.service import get_jobs_service
from services.jobs.worker import JobWorker
from services.measurement import privacy as privacy_mod

pytestmark = pytest.mark.asyncio

TENANT = "tenant-erasure-test"
USER = "user-to-erase"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    register_consent_erasure_handler()
    # The measurement stores' own receipts: 3 touchpoints + 2 conversions.
    monkeypatch.setattr(
        privacy_mod._touchpoint_repo, "tombstone_for_profile", AsyncMock(return_value=3)
    )
    monkeypatch.setattr(
        privacy_mod._conversion_repo, "tombstone_for_profile", AsyncMock(return_value=2)
    )
    from services.measurement.engine.journey_compiler import JourneyCompiler

    monkeypatch.setattr(
        JourneyCompiler, "rebuild_affected_by_consent_change", AsyncMock(return_value=None)
    )
    yield
    reset_in_memory_stores()
    reset_jobs_memory()


class _Producer:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


def _request(tenant_id: str = TENANT) -> MagicMock:
    req = MagicMock()
    req.state.tenant.tenant_id = tenant_id
    req.state.tenant.require_permission = MagicMock()
    return req


async def _submit_erasure() -> dict:
    body = DataSubjectRequest(user_id=USER, request_type="erasure", details="erase me")
    response = await submit_dsr(body, _request(), producer=_Producer())
    return response["data"]


async def test_erasure_enqueues_durable_job_and_opens_propagation():
    dsr = await _submit_erasure()

    # The route persisted the durable linkage — no fire-and-forget task.
    assert dsr["status"] == "queued"
    job_id = dsr["erasure_job_id"]
    propagation_id = dsr["propagation_request_id"]
    assert job_id and propagation_id

    job = await get_jobs_service().get_job(TENANT, job_id)
    assert job is not None
    assert job["job_type"] == ERASURE_JOB_TYPE
    assert job["status"] == JobStatus.QUEUED.value
    assert job["payload"]["user_id"] == USER
    assert job["payload"]["propagation_request_id"] == propagation_id

    # The propagation record is seeded with every component pending.
    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT)
    assert [c["component"] for c in status["components"]] == list(DSR_COMPONENTS)
    assert all(c["status"] == "pending" for c in status["components"])
    assert status["overall"] == "pending"


async def test_worker_executes_erasure_and_marks_step_with_evidence():
    dsr = await _submit_erasure()
    job_id = dsr["erasure_job_id"]
    propagation_id = dsr["propagation_request_id"]

    claimed = await JobWorker().run_once()
    assert claimed is True

    job = await get_jobs_service().get_job(TENANT, job_id)
    assert job["status"] == JobStatus.SUCCEEDED.value
    assert job["result"]["touchpoints_tombstoned"] == 3
    assert job["result"]["conversions_tombstoned"] == 2

    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT)
    step = next(
        c for c in status["components"] if c["component"] == MEASUREMENT_COMPONENT
    )
    # Completed WITH the store's own evidence: counts + durable job receipt.
    assert step["status"] == "completed"
    assert step["records_impacted"] == 5
    assert step["audit_event_id"] == job_id
    assert step["requires_recompute"] is False
    # Only the store this handler actually erased was marked.
    others = [c for c in status["components"] if c["component"] != MEASUREMENT_COMPONENT]
    assert all(c["status"] == "pending" for c in others)

    # The DSR record reflects real completion state.
    record = await ConsentRepository().find_by_id(f"dsr_{dsr['dsr_id']}")
    assert record["status"] == "completed"
    assert record["erasure_result"]["touchpoints_tombstoned"] == 3


async def test_handler_rerun_is_idempotent():
    """Simulate a worker crash + retry: re-running the handler re-marks the
    same step and leaves a consistent completed record (no duplication)."""
    dsr = await _submit_erasure()
    propagation_id = dsr["propagation_request_id"]
    assert await JobWorker().run_once() is True

    handler = HANDLER_REGISTRY[ERASURE_JOB_TYPE]
    ctx = JobContext(
        job_id=dsr["erasure_job_id"],
        tenant_id=TENANT,
        correlation_id=dsr["dsr_id"],
        heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )
    outcome = await handler(
        {
            "dsr_id": dsr["dsr_id"],
            "user_id": USER,
            "propagation_request_id": propagation_id,
        },
        ctx,
    )
    assert outcome.status == "succeeded"

    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT)
    steps = [c for c in status["components"] if c["component"] == MEASUREMENT_COMPONENT]
    assert len(steps) == 1  # re-run re-marked, never duplicated
    assert steps[0]["status"] == "completed"
    assert steps[0]["records_impacted"] == 5


async def test_store_failure_marks_step_failed_and_retries(monkeypatch):
    monkeypatch.setattr(
        privacy_mod._conversion_repo,
        "tombstone_for_profile",
        AsyncMock(side_effect=RuntimeError("conversion store down")),
    )
    dsr = await _submit_erasure()
    propagation_id = dsr["propagation_request_id"]

    assert await JobWorker().run_once() is True

    # The attempt failed → worker schedules a retry (attempts < max_attempts).
    job = await get_jobs_service().get_job(TENANT, dsr["erasure_job_id"])
    assert job["status"] == JobStatus.RETRYING.value
    assert "conversion" in (job["error"] or "")

    # The step honestly records the partial store state, never a silent pass.
    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT)
    step = next(
        c for c in status["components"] if c["component"] == MEASUREMENT_COMPONENT
    )
    assert step["status"] == "failed"
    assert step["records_impacted"] == 3  # touchpoints succeeded before the failure
    assert status["overall"] == "failed"


async def test_non_erasure_dsr_enqueues_nothing():
    body = DataSubjectRequest(user_id=USER, request_type="access")
    response = await submit_dsr(body, _request(), producer=_Producer())
    data = response["data"]
    assert "erasure_job_id" not in data
    jobs = await get_jobs_service().list_jobs(TENANT, job_type=ERASURE_JOB_TYPE)
    assert jobs == []
