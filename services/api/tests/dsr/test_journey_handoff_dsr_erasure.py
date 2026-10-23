"""Journey handoff rows (anonymous-ID keyed) are reachable by a DSR erasure."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from governance.consent.erasure_jobs import ERASURE_JOB_TYPE, register_consent_erasure_handler
from governance.dsr_propagation.service import dsr_propagation_service
from journeys.handoff.service import issue_handoff, list_handoffs, redeem_handoff
from journeys.measurement import privacy as privacy_mod
from repositories import journey_handoff_repo
from repositories.jobs_repo import reset_jobs_memory
from repositories.repos import reset_in_memory_stores
from workers.jobs.handlers import HANDLER_REGISTRY, JobContext

pytestmark = pytest.mark.asyncio

TENANT = "tenant-handoff-dsr"
USER = "subject-to-erase"
ANON = "anon-subject"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    journey_handoff_repo.reset_journey_handoff_memory()
    register_consent_erasure_handler()
    monkeypatch.setattr(
        privacy_mod._touchpoint_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        privacy_mod._conversion_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    from journeys.measurement.engine.journey_compiler import JourneyCompiler

    monkeypatch.setattr(
        JourneyCompiler, "rebuild_affected_by_consent_change", AsyncMock(return_value=None)
    )
    yield
    reset_in_memory_stores()
    reset_jobs_memory()
    journey_handoff_repo.reset_journey_handoff_memory()


def _ctx() -> JobContext:
    return JobContext(
        job_id="job_handoff_dsr", tenant_id=TENANT, correlation_id="corr",
        worker_id="w", heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )


async def _seed():
    """Subject is the source of one handoff and the destination of another."""
    a = await issue_handoff(
        tenant_id=TENANT, app_namespace="app", journey_id="j1", session_id="s-mob",
        anonymous_id=ANON, platform="ios",
    )
    b = await issue_handoff(
        tenant_id=TENANT, app_namespace="app", journey_id="j2", session_id="s-other",
        anonymous_id="anon-someone-else", platform="ios",
    )
    await redeem_handoff(
        tenant_id=TENANT, app_namespace="app", token=b["token"], session_id="s-web",
        anonymous_id=ANON, platform="web",
    )
    await issue_handoff(
        tenant_id=TENANT, app_namespace="app", journey_id="j3", session_id="s-x",
        anonymous_id="anon-bystander", platform="ios",
    )
    return a


async def _run(payload: dict):
    propagation_id = await dsr_propagation_service.open_request(
        TENANT, f"user:{USER}", "erasure"
    )
    outcome = await HANDLER_REGISTRY[ERASURE_JOB_TYPE](
        {"user_id": USER, "propagation_request_id": propagation_id, **payload}, _ctx()
    )
    status = await dsr_propagation_service.status(propagation_id, tenant_id=TENANT)
    return outcome, {c["component"]: c for c in status["components"]}


async def test_anonymous_id_erasure_removes_both_ends_and_reports_real_count():
    await _seed()
    outcome, by_comp = await _run({"anonymous_id": ANON})
    assert outcome.status == "succeeded"
    assert by_comp["journey_handoffs"]["status"] == "completed"
    assert by_comp["journey_handoffs"]["records_impacted"] == 2  # source of j1, destination of j2
    assert await list_handoffs(TENANT, "j1") == []
    assert await list_handoffs(TENANT, "j2") == []
    assert len(await list_handoffs(TENANT, "j3")) == 1, "another subject's row must survive"


async def test_without_an_anonymous_id_nothing_is_guessed():
    await _seed()
    _, by_comp = await _run({})
    assert by_comp["journey_handoffs"]["status"] == "completed"
    assert by_comp["journey_handoffs"]["records_impacted"] == 0
    assert len(await list_handoffs(TENANT, "j1")) == 1


async def test_store_failure_marks_only_this_component_failed(monkeypatch):
    await _seed()
    monkeypatch.setattr(
        journey_handoff_repo.JourneyHandoffRepository, "delete_by_anonymous_id",
        AsyncMock(side_effect=RuntimeError("store down")),
    )
    outcome, by_comp = await _run({"anonymous_id": ANON})
    assert by_comp["journey_handoffs"]["status"] == "failed"
    assert by_comp["continuation_records"]["status"] == "completed"
    assert outcome.status != "succeeded", "a failed store keeps the job retryable"
