"""DSR / erasure propagation for capability authorizations (PR 2, Phase B1).

A capability authorization is a ``delegations`` row, so erasure must reach it. The
standard plan now carries TWO ``delegations`` HARD_DELETE steps — one keyed on
``grantee_entity_id`` and one on ``grantor_entity_id`` — because the data subject may sit
on either side of the grant. This closes a pre-existing gap: ``delegations`` previously
had no erasure step at all, so ordinary delegations survived a DSAR too.

Driven through the real ``DSARRequest.process_erasure``, which is where the
``postgresql:delegations`` adapter is wired.
"""

from __future__ import annotations

import pytest

from repositories.repos import DelegationRepository, reset_in_memory_stores
from shared.common.common import NotFoundError
from shared.privacy.retention import DeletionPlan, DSARRequest

from services.agent_access_intelligence.authority import CapabilityAuthorityService
from services.agent_access_intelligence.catalog_service import CapabilityCatalogService


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture
def svc():
    return CapabilityAuthorityService()


async def _seed_capability(tenant_id: str = "t1") -> str:
    result = await CapabilityCatalogService().record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": "e1",
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "srvX",
        "provider": "acme",
    })
    return result["capability_id"]


def _delegation_steps(plan: DeletionPlan) -> list[dict]:
    return [s for s in plan.steps if s["table"] == "delegations"]


async def test_standard_plan_erases_both_sides_of_a_delegation():
    plan = DeletionPlan(entity_id="agentA", tenant_id="t1")
    plan.build_standard_plan()
    steps = _delegation_steps(plan)

    assert len(steps) == 2
    assert {s["entity_field"] for s in steps} == {"grantee_entity_id", "grantor_entity_id"}
    for step in steps:
        assert step["store"] == "postgresql"
        assert step["behavior"] == "hard_delete"
        assert step["classification"] == "confidential"


async def test_erasure_removes_authorizations_granted_to_the_subject(svc):
    """The subject is the grantee (the agent)."""
    cap_id = await _seed_capability()
    mine = await svc.grant(
        tenant_id="t1", granted_by_entity_id="ownerU", agent_id="agentA", capability_id=cap_id
    )
    other = await svc.grant(
        tenant_id="t1", granted_by_entity_id="ownerU", agent_id="agentB", capability_id=cap_id
    )
    assert len(await svc.list(tenant_id="t1")) == 2

    result = await DSARRequest("erasure", "agentA", "t1").process_erasure()
    assert result["failed"] == 0

    remaining = await svc.list(tenant_id="t1")
    assert [r["authorization_id"] for r in remaining] == [other["authorization_id"]]
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t1", authorization_id=mine["authorization_id"])


async def test_erasure_removes_authorizations_granted_by_the_subject(svc):
    """The subject is the grantor (the human who authorized the agent)."""
    cap_id = await _seed_capability()
    by_subject = await svc.grant(
        tenant_id="t1", granted_by_entity_id="ownerU", agent_id="agentA", capability_id=cap_id
    )
    by_other = await svc.grant(
        tenant_id="t1", granted_by_entity_id="ownerV", agent_id="agentA", capability_id=cap_id
    )

    result = await DSARRequest("erasure", "ownerU", "t1").process_erasure()
    assert result["failed"] == 0

    remaining = await svc.list(tenant_id="t1")
    assert [r["authorization_id"] for r in remaining] == [by_other["authorization_id"]]
    assert by_subject["authorization_id"] not in {r["authorization_id"] for r in remaining}


async def test_erasure_reaches_ordinary_delegations_too(svc):
    """The new steps are a deliberate behavioural change for pre-existing rows."""
    delegations = DelegationRepository()
    await delegations.grant(
        delegation_id="ordinary-grantee",
        tenant_id="t1",
        grantor_entity_id="ownerU",
        grantee_entity_id="subject",
        scope={"actions": ["transfer"], "resources": ["wallet:w1"]},
    )
    await delegations.grant(
        delegation_id="ordinary-grantor",
        tenant_id="t1",
        grantor_entity_id="subject",
        grantee_entity_id="agentZ",
        scope={"actions": ["transfer"], "resources": ["wallet:w2"]},
    )
    await delegations.grant(
        delegation_id="unrelated",
        tenant_id="t1",
        grantor_entity_id="ownerU",
        grantee_entity_id="agentZ",
        scope={"actions": ["transfer"], "resources": ["wallet:w3"]},
    )

    await DSARRequest("erasure", "subject", "t1").process_erasure()

    assert await delegations.find_by_id("ordinary-grantee") is None
    assert await delegations.find_by_id("ordinary-grantor") is None
    assert await delegations.find_by_id("unrelated") is not None


async def test_erasure_reports_both_delegation_steps_as_executed(svc):
    cap_id = await _seed_capability()
    await svc.grant(
        tenant_id="t1", granted_by_entity_id="ownerU", agent_id="agentA", capability_id=cap_id
    )
    request = DSARRequest("erasure", "agentA", "t1")
    await request.process_erasure()

    steps = _delegation_steps(request.deletion_plan)
    assert len(steps) == 2
    by_field = {s["entity_field"]: s for s in steps}
    # Grantee side removed the row; grantor side ran and matched nothing.
    assert by_field["grantee_entity_id"]["records_affected"] == 1
    assert by_field["grantor_entity_id"]["records_affected"] == 0
    for step in steps:
        assert step["status"] == "executed"
        assert "note" not in step  # an adapter WAS configured
