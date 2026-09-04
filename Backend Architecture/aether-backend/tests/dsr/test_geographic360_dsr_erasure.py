"""Geographic-plane DSR erasure (geographic360 G4.5-C3).

Before G4.5 none of the dsr_propagation components touched the canonical
``location_facts`` store, so a data subject's recorded location facts silently
survived an erasure the DSR record reported as ``completed``. G4.5-C3 appends
the ``location_facts`` component (30 total) and teaches the durable
``consent.erasure`` handler to actually erase them.

The erasure is a *governed soft-revoke*, not a hard delete: every ACTIVE
location fact of the subject transitions ``lifecycle_state`` ``active`` ->
``revoked`` (with ``revoked_by`` / ``revoke_reason`` / ``revoked_at`` stamps)
through ``services.geo.location_facts``, so the fact stays audit-visible while
becoming invisible to every geographic360 read. The component receipt is the
store's OWN revoke count, tenant-scoped and fail-closed across tenants.

Suites pin: (1) the plane helper is tenant-scoped and returns the store's own
governed-revoke count; (2) the durable erasure job end-to-end marks the
``location_facts`` component with the store's OWN real receipt and soft-revokes
the subject's facts; (3) a plane failure marks the component ``failed`` and
keeps the job retryable.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.jobs_repo import reset_jobs_memory
from repositories.repos import reset_in_memory_stores

from services.consent import erasure_jobs
from services.consent.authority import ConsentReceiptRepository
from services.consent.erasure_jobs import (
    LOCATION_FACT_ERASURE_ACTOR,
    LOCATION_FACT_ERASURE_REASON,
    LOCATION_FACTS_COMPONENT,
    register_consent_erasure_handler,
)
from services.consent.routes import DataSubjectRequest, submit_dsr
from services.dsr_propagation.service import DSRPropagationService
from services.geo.location_facts import (
    LOCATION_FACT_REVOKED,
    location_fact_repo,
)
from services.jobs.models import JobStatus
from services.jobs.service import get_jobs_service
from services.jobs.worker import JobWorker
from services.measurement import privacy as privacy_mod

from shared.geo.models import LocationFact, Region

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant-geo-dsr-a"
TENANT_B = "tenant-geo-dsr-b"
USER = "user-to-erase"

_NOW = datetime.now(timezone.utc)


def _days_ago(days: int) -> datetime:
    return _NOW - timedelta(days=days)


def _fact(
    location_id: str,
    *,
    tenant_id: str = TENANT_A,
    subject_id: str = USER,
    observed_at: datetime = _days_ago(1),
) -> LocationFact:
    return LocationFact(
        location_id=location_id,
        tenant_id=tenant_id,
        subject_type="entity",
        subject_id=subject_id,
        role="primary_residence",
        precision_class="city",
        region=Region(
            region_id=f"region:{location_id}",
            region_type="city",
            name="Portland",
            country_code="US",
            geo_reference="OR",
        ),
        observed_at=observed_at,
        provider="geoip",
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    register_consent_erasure_handler()
    # The measurement stores' own receipts (the durable handler always runs the
    # measurement plane first, even for a location-only subject).
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


async def _grant(entity_id: str, tenant_id: str = TENANT_A) -> None:
    """Seed a server consent receipt so erasure submission is accepted."""
    await ConsentReceiptRepository().record(
        receipt_id=f"rcpt_{tenant_id}_{entity_id}",
        tenant_id=tenant_id,
        purpose="analytics",
        state="granted",
        subject_id=entity_id,
    )


class _Producer:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


def _request(tenant_id: str = TENANT_A) -> MagicMock:
    req = MagicMock()
    req.state.tenant.tenant_id = tenant_id
    req.state.tenant.require_permission = MagicMock()
    return req


async def _submit_erasure(tenant_id: str = TENANT_A) -> dict:
    body = DataSubjectRequest(user_id=USER, request_type="erasure", details="erase me")
    response = await submit_dsr(body, _request(tenant_id), producer=_Producer())
    return response["data"]


# ── 1. Direct plane helper: tenant-scoped governed soft-revoke ─────────────────


async def test_erase_location_plane_is_tenant_scoped_and_soft_revokes():
    await location_fact_repo.record(_fact("loc-a-1", observed_at=_days_ago(5)))
    await location_fact_repo.record(_fact("loc-a-2", observed_at=_days_ago(1)))
    # Another tenant's fact for the SAME subject, and another A subject.
    await location_fact_repo.record(_fact("loc-b", tenant_id=TENANT_B))
    await location_fact_repo.record(_fact("loc-other", subject_id="user_other"))

    receipts = await erasure_jobs._erase_location_plane(TENANT_A, USER)

    # The component carries the store's OWN real revoke count (A's two facts).
    assert receipts == {LOCATION_FACTS_COMPONENT: 2}

    # USER's tenant-A facts are revoked (invisible to reads); B's row and A's
    # OTHER subject are untouched (never erased across tenants or subjects).
    assert await location_fact_repo.active_facts_for_subject(TENANT_A, "entity", USER) == []
    assert [
        r["location_id"]
        for r in await location_fact_repo.active_facts_for_subject(TENANT_B, "entity", USER)
    ] == ["loc-b"]
    assert [
        r["location_id"]
        for r in await location_fact_repo.active_facts_for_subject(
            TENANT_A, "entity", "user_other"
        )
    ] == ["loc-other"]

    # Soft-revoke, never a hard delete: the rows persist with a governed envelope.
    revoked = await location_fact_repo.find_by_id("loc-a-1")
    assert revoked["lifecycle_state"] == LOCATION_FACT_REVOKED
    assert revoked["revoked_by"] == LOCATION_FACT_ERASURE_ACTOR
    assert revoked["revoke_reason"] == LOCATION_FACT_ERASURE_REASON
    assert revoked["revoked_at"]


# ── 2. Durable erasure job end-to-end ──────────────────────────────────────────


async def test_dsr_erasure_marks_location_step_and_soft_revokes():
    await _grant(USER)
    await location_fact_repo.record(_fact("loc-a-1", observed_at=_days_ago(10)))
    await location_fact_repo.record(_fact("loc-a-2", observed_at=_days_ago(5)))
    await location_fact_repo.record(_fact("loc-a-3", observed_at=_days_ago(1)))
    await location_fact_repo.record(_fact("loc-other", subject_id="user_other"))

    dsr = await _submit_erasure()
    job_id = dsr["erasure_job_id"]
    propagation_id = dsr["propagation_request_id"]
    assert await JobWorker().run_once() is True

    # The durable job succeeded.
    job = await get_jobs_service().get_job(TENANT_A, job_id)
    assert job["status"] == JobStatus.SUCCEEDED.value

    # The location_facts component is marked completed with the store's OWN
    # receipt (3 governed soft-revokes) and the durable job id as audit pointer.
    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT_A)
    location_step = next(
        c for c in status["components"] if c["component"] == LOCATION_FACTS_COMPONENT
    )
    assert location_step["status"] == "completed"
    assert location_step["records_impacted"] == 3
    assert location_step["audit_event_id"] == job_id

    # Governed soft-revoke: the erased subject's facts are invisible to reads,
    # still present as revoked rows, and the other subject is untouched.
    assert await location_fact_repo.active_facts_for_subject(TENANT_A, "entity", USER) == []
    for location_id in ("loc-a-1", "loc-a-2", "loc-a-3"):
        row = await location_fact_repo.find_by_id(location_id)
        assert row["lifecycle_state"] == LOCATION_FACT_REVOKED
        assert row["revoke_reason"] == "dsr_erasure"
    assert [
        r["location_id"]
        for r in await location_fact_repo.active_facts_for_subject(
            TENANT_A, "entity", "user_other"
        )
    ] == ["loc-other"]

    # The DSR record reflects the real completion state.
    from repositories.repos import ConsentRepository

    record = await ConsentRepository().find_by_id(f"dsr_{dsr['dsr_id']}")
    assert record["status"] == "completed"


# ── 3. Plane failure is honest and retryable ───────────────────────────────────


async def test_location_plane_failure_marks_component_failed_and_retries(monkeypatch):
    await _grant(USER)
    await location_fact_repo.record(_fact("loc-a-1"))

    monkeypatch.setattr(
        erasure_jobs,
        "_erase_location_plane",
        AsyncMock(side_effect=RuntimeError("geographic store down")),
    )
    dsr = await _submit_erasure()
    propagation_id = dsr["propagation_request_id"]

    assert await JobWorker().run_once() is True

    # The attempt failed -> worker schedules a retry, never a silent pass.
    job = await get_jobs_service().get_job(TENANT_A, dsr["erasure_job_id"])
    assert job["status"] == JobStatus.RETRYING.value
    assert "geographic" in (job["error"] or "")

    # The location_facts component honestly records the plane failure.
    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT_A)
    location_step = next(
        c for c in status["components"] if c["component"] == LOCATION_FACTS_COMPONENT
    )
    assert location_step["status"] == "failed"
    assert status["overall"] == "failed"
