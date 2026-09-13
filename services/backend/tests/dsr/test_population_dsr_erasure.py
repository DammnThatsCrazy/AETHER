"""Population-plane DSR erasure (population360 P3.3).

Before P3.3 none of the 26 dsr_propagation components touched the population
tables, so a data subject's cohort memberships silently survived an erasure the
DSR record reported as ``completed``. P3.3 appends three components —
``population_memberships`` / ``population_snapshots`` / ``populations`` (29
total) — and teaches the durable ``consent.erasure`` handler to actually erase
them.

The erasure is a *governed leave*, not a bulk delete: every active membership of
the subject is revoked through ``PopulationMembershipGovernor.remove_membership``
(``MEMBER_OF`` edge soft-revoked, membership row -> ``left``, never hard
deleted), and each affected population's materialised ``member_count`` is
recomputed from active memberships. Snapshots (subject-less aggregates) and
population objects (tenant artifacts) receive honest zero receipts.

Suites pin: (1) the plane helper is tenant-scoped and recomputes counts;
(2) the durable erasure job end-to-end marks the three components with the
membership store's OWN real receipt and transitions the member to ``left``;
(3) a plane failure marks all three components ``failed`` and keeps the job
retryable.

Note on graph backends: local-mode ``GraphClient`` backends are per-instance,
so this suite asserts the *materialised current state* reads surface (the
membership row, member counts, DSR step evidence). The edge-level revocation
contract itself is pinned in ``test_population_governed_membership`` P3.1
(``test_leave_revokes_edge_and_transitions_row``) — the same
``remove_membership`` the erasure plane calls.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.jobs_repo import reset_jobs_memory
from repositories.repos import reset_in_memory_stores

from services.consent import erasure_jobs
from services.consent.authority import ConsentReceiptRepository
from services.consent.erasure_jobs import (
    ERASURE_JOB_TYPE,
    POPULATION_MEMBERSHIP_COMPONENT,
    POPULATION_RECORDS_COMPONENT,
    POPULATION_SNAPSHOT_COMPONENT,
    register_consent_erasure_handler,
)
from services.consent.routes import DataSubjectRequest, submit_dsr
from services.dsr_propagation.service import DSRPropagationService
from services.jobs.models import JobStatus
from services.jobs.service import get_jobs_service
from services.jobs.worker import JobWorker
from services.measurement import privacy as privacy_mod
from services.population.governance import (
    _membership_row_id,
    PopulationMembershipGovernor,
)
from services.population.models import MembershipState, PopulationType
from services.population.registry import membership_repo, population_repo

from shared.graph.graph import GraphClient

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant-pop-dsr-a"
TENANT_B = "tenant-pop-dsr-b"
USER = "user-to-erase"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    register_consent_erasure_handler()
    # The measurement stores' own receipts (the durable handler always runs the
    # measurement plane first, even for a population-only subject).
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
    """Seed a server consent receipt so a governed join is allowed."""
    await ConsentReceiptRepository().record(
        receipt_id=f"rcpt_{tenant_id}_{entity_id}",
        tenant_id=tenant_id,
        purpose="analytics",
        state="granted",
        subject_id=entity_id,
    )


async def _population(tenant_id: str, name: str = "High-value cohort") -> dict:
    return await population_repo.create_population(
        name=name,
        population_type=PopulationType.SEGMENT,
        definition={"filters": [{"field": "lifetime_value", "op": "gt", "value": 100}]},
        source_tag="p3_dsr_test",
        tenant_id=tenant_id,
    )


async def _join(pop: dict, entity_id: str, tenant_id: str) -> None:
    governor = PopulationMembershipGovernor(graph_client=await _graph())
    await governor.add_membership(
        population=pop,
        entity_id=entity_id,
        tenant_id=tenant_id,
        reason="rule_match",
        source_tag="p3_dsr_test",
    )


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


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


# ── 1. Direct plane helper: tenant scope + recompute ──────────────────────────


async def test_erase_population_plane_is_tenant_scoped_and_recomputes():
    pop_a = await _population(TENANT_A, "A cohort")
    pop_b = await _population(TENANT_B, "B cohort")
    await _grant(USER, TENANT_A)
    await _grant(USER, TENANT_B)
    await _join(pop_a, USER, TENANT_A)
    await _join(pop_b, USER, TENANT_B)
    # A second subject in A that the erasure must NOT touch.
    await _grant("user_other", TENANT_A)
    await _join(pop_a, "user_other", TENANT_A)
    await population_repo.update(pop_a["id"], {"member_count": 2})
    await population_repo.update(pop_b["id"], {"member_count": 1})

    receipts = await erasure_jobs._erase_population_plane(TENANT_A, USER)

    # Each component carries the store's OWN real receipt.
    assert receipts == {
        POPULATION_MEMBERSHIP_COMPONENT: 1,
        POPULATION_SNAPSHOT_COMPONENT: 0,
        POPULATION_RECORDS_COMPONENT: 0,
    }

    # USER's tenant-A membership transitioned to left (row present, not active);
    # tenant-B membership is untouched (never erased across tenants).
    assert await membership_repo.active_memberships_for_subject(TENANT_A, USER) == []
    assert await membership_repo.active_memberships_for_subject(TENANT_B, USER) != []
    row_a = await membership_repo.find_by_id(_membership_row_id(pop_a["id"], USER))
    assert row_a["membership_state"] == MembershipState.LEFT.value

    # Other subject still active; member_count recomputed from ACTIVE rows only.
    assert [m["entity_id"] for m in await membership_repo.get_members(pop_a["id"])] == [
        "user_other"
    ]
    assert (await population_repo.find_by_id(pop_a["id"]))["member_count"] == 1
    assert (await population_repo.find_by_id(pop_b["id"]))["member_count"] == 1


# ── 2. Durable erasure job end-to-end ─────────────────────────────────────────


async def test_dsr_erasure_marks_population_steps_and_governed_leaves():
    pop = await _population(TENANT_A)
    await _grant(USER)
    await _grant("user_other")
    await _join(pop, USER, TENANT_A)
    await _join(pop, "user_other", TENANT_A)
    await population_repo.update(pop["id"], {"member_count": 2})

    dsr = await _submit_erasure()
    job_id = dsr["erasure_job_id"]
    propagation_id = dsr["propagation_request_id"]
    assert await JobWorker().run_once() is True

    # The durable job succeeded.
    job = await get_jobs_service().get_job(TENANT_A, job_id)
    assert job["status"] == JobStatus.SUCCEEDED.value

    # The three population components are marked completed with the membership
    # store's OWN receipt (1 governed leave) and honest zero receipts.
    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT_A)
    membership_step = next(
        c for c in status["components"] if c["component"] == POPULATION_MEMBERSHIP_COMPONENT
    )
    assert membership_step["status"] == "completed"
    assert membership_step["records_impacted"] == 1
    assert membership_step["audit_event_id"] == job_id
    for component in (POPULATION_SNAPSHOT_COMPONENT, POPULATION_RECORDS_COMPONENT):
        step = next(c for c in status["components"] if c["component"] == component)
        assert step["status"] == "completed"
        assert step["records_impacted"] == 0
        assert step["audit_event_id"] == job_id

    # Governed leave: the erased subject is no longer an active member, the row
    # is still present (left, not hard-deleted), and the count is recomputed.
    assert await membership_repo.active_memberships_for_subject(TENANT_A, USER) == []
    row = await membership_repo.find_by_id(_membership_row_id(pop["id"], USER))
    assert row["membership_state"] == MembershipState.LEFT.value
    assert row["leave_reason"] == "dsr_erasure"
    assert (await population_repo.find_by_id(pop["id"]))["member_count"] == 1
    # The other member is untouched.
    assert [m["entity_id"] for m in await membership_repo.get_members(pop["id"])] == [
        "user_other"
    ]

    # The DSR record reflects the real completion state.
    from repositories.repos import ConsentRepository

    record = await ConsentRepository().find_by_id(f"dsr_{dsr['dsr_id']}")
    assert record["status"] == "completed"


# ── 3. Plane failure is honest and retryable ──────────────────────────────────


async def test_population_plane_failure_marks_components_failed_and_retries(
    monkeypatch,
):
    pop = await _population(TENANT_A)
    await _grant(USER)
    await _join(pop, USER, TENANT_A)
    await population_repo.update(pop["id"], {"member_count": 1})

    monkeypatch.setattr(
        erasure_jobs,
        "_erase_population_plane",
        AsyncMock(side_effect=RuntimeError("population store down")),
    )
    dsr = await _submit_erasure()
    propagation_id = dsr["propagation_request_id"]

    assert await JobWorker().run_once() is True

    # The attempt failed -> worker schedules a retry, never a silent pass.
    job = await get_jobs_service().get_job(TENANT_A, dsr["erasure_job_id"])
    assert job["status"] == JobStatus.RETRYING.value
    assert "population" in (job["error"] or "")

    # All three population components honestly record the plane failure.
    status = await DSRPropagationService().status(propagation_id, tenant_id=TENANT_A)
    for component in (
        POPULATION_MEMBERSHIP_COMPONENT,
        POPULATION_SNAPSHOT_COMPONENT,
        POPULATION_RECORDS_COMPONENT,
    ):
        step = next(c for c in status["components"] if c["component"] == component)
        assert step["status"] == "failed"
    assert status["overall"] == "failed"
