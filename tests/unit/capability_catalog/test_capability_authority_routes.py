"""Route-level tests for the capability authority + policy APIs (PR 2, Phase B1).

Handlers are called directly with a fake ``Request`` and a recording producer — the
established pattern in this suite (see ``test_capability_catalog_routes.py``) — so the
permission gates and tenant scoping are exercised without standing up the middleware.

The permission split is the point: ``POST /v1/capability-authorizations`` requires
``write`` (it is the authorizing act), while both ``GET /v1/capability-policy/decisions``
and ``POST /v1/capability-policy/evaluate`` require only ``read`` — evaluate mutates no
tenant resource, and gating it on ``write`` would stop read-only enforcement callers from
checking before acting.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError, NotFoundError
from shared.events.events import Topic

import services.agent_access_intelligence.authority_routes as authority_routes
from services.agent_access_intelligence.authority_routes import (
    CapabilityAuthorizationGrant,
    CapabilityInvocationCheck,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service


class FakeProducer:
    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _seed_capability(tenant_id: str = "t1", source_event_id: str = "e1") -> str:
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "srvX",
        "provider": "acme",
        "risk_level": "high",
    })
    return result["capability_id"]


# ── POST /v1/capability-authorizations (write) ────────────────────────────────

async def test_grant_requires_write_permission():
    cap_id = await _seed_capability()
    body = CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id)
    with pytest.raises(ForbiddenError):
        await authority_routes.grant_authorization(
            body, _request("t1", permissions=["read"]), producer=FakeProducer()
        )


async def test_grant_writes_row_and_publishes_delegation_created():
    cap_id = await _seed_capability()
    producer = FakeProducer()
    resp = await authority_routes.grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=producer,
    )
    data = resp["data"]
    assert data["state"] == "active"
    assert data["capability_observed"] is True
    assert data["scope"] == {"actions": ["invoke"], "resources": [f"capability:{cap_id}"]}

    assert len(producer.events) == 1
    event = producer.events[0]
    assert event.topic == Topic.DELEGATION_CREATED
    assert event.payload["authorization_kind"] == "capability"
    assert event.payload["delegation_id"] == data["authorization_id"]

    listed = await authority_routes.list_authorizations(
        _request("t1"), agent_id=None, capability_id=None, state=None, limit=100, offset=0
    )
    assert listed["data"]["count"] == 1


async def test_read_and_revoke_are_fail_closed_cross_tenant():
    cap_id = await _seed_capability()
    granted = await authority_routes.grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=FakeProducer(),
    )
    auth_id = granted["data"]["authorization_id"]

    assert (await authority_routes.read_authorization(auth_id, _request("t1")))[
        "data"
    ]["authorization_id"] == auth_id
    with pytest.raises(NotFoundError):
        await authority_routes.read_authorization(auth_id, _request("t2"))
    with pytest.raises(NotFoundError):
        await authority_routes.revoke_authorization(
            auth_id, _request("t2"), producer=FakeProducer()
        )

    producer = FakeProducer()
    revoked = await authority_routes.revoke_authorization(
        auth_id, _request("t1"), producer=producer
    )
    assert revoked["data"]["state"] == "revoked"
    assert producer.events[0].topic == Topic.DELEGATION_REVOKED


# ── POST /v1/capability-policy/evaluate (read) ────────────────────────────────

async def test_evaluate_requires_only_read_and_denies_without_authorization():
    cap_id = await _seed_capability()
    resp = await authority_routes.evaluate_invocation(
        CapabilityInvocationCheck(capability_id=cap_id, agent_id="agentA"),
        _request("t1", permissions=["read"]),  # deliberately NOT "write"
    )
    decision = resp["data"]["decision"]
    assert decision["allowed"] is False
    assert decision["severity"] == "block"
    assert decision["reason"] == "no active capability authorization"
    assert decision["required_action"] == "grant one via POST /v1/capability-authorizations"
    # Risk is context, not a verdict input.
    assert resp["data"]["context"]["latest_risk_level"] == "high"
    assert resp["data"]["context"]["capability_observed"] is True
    assert resp["data"]["context"]["authorization_id"] is None


async def test_evaluate_allows_after_a_grant_and_the_decision_log_records_it():
    cap_id = await _seed_capability()
    await authority_routes.grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=FakeProducer(),
    )
    resp = await authority_routes.evaluate_invocation(
        CapabilityInvocationCheck(capability_id=cap_id, agent_id="agentA"),
        _request("t1", permissions=["read"]),
    )
    decision = resp["data"]["decision"]
    assert decision["allowed"] is True
    assert decision["severity"] == "info"
    assert decision["reason"] == "active capability authorization"
    assert resp["data"]["context"]["authorization_reason"] == "active_capability_authorization"

    # The ALLOW is in the persisted log — the endpoint is a real record, not a
    # deny-only sample.
    log = await authority_routes.list_capability_decisions(
        _request("t1", permissions=["read"]), limit=100
    )
    assert log["data"]["count"] == 1
    assert log["data"]["items"][0]["decision_id"] == decision["decision_id"]
    assert log["data"]["items"][0]["policy_key"] == "capability.invoke"


async def test_decision_log_requires_read_and_is_tenant_scoped():
    cap_id = await _seed_capability()
    await authority_routes.evaluate_invocation(
        CapabilityInvocationCheck(capability_id=cap_id, agent_id="agentA"), _request("t1")
    )
    with pytest.raises(ForbiddenError):
        await authority_routes.list_capability_decisions(
            _request("t1", permissions=[]), limit=100
        )
    other = await authority_routes.list_capability_decisions(_request("t2"), limit=100)
    assert other["data"]["count"] == 0
