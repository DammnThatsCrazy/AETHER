"""Capability authority tests (PR 2, Phase B1).

Proves the fail-closed invariants documented in
``services/agent_access_intelligence/authority.py`` against the in-memory backend: a
written authorization never carries an empty/wildcard resource set, ``actions`` is exactly
``["invoke"]``, cross-tenant reads and revokes are indistinguishable from "absent", an
unobserved capability may be pre-authorized but is never upgraded to observed, an
attacker-influenced ``server_key`` is digested rather than interpolated, and a
hand-written ordinary delegation cannot satisfy a capability check. No Postgres required.
"""

from __future__ import annotations

import pytest

from repositories.repos import DelegationRepository
from shared.common.common import BadRequestError, NotFoundError

from services.agent_access_intelligence.authority import (
    AUTHORIZATION_KIND,
    CapabilityAuthorityService,
    authorization_state,
    capability_resource,
    server_ref_for,
    validate_capability_scope,
)
from services.agent_access_intelligence.catalog_service import CapabilityCatalogService

PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2999-01-01T00:00:00+00:00"


def _fact(**over):
    row = {
        "tenant_id": "t1",
        "source_event_id": "e1",
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "srvX",
        "server_url": "https://x.example",
        "provider": "acme",
        "protocol_version": "2025-06-18",
        "risk_level": "low",
        "payload": {},
    }
    row.update(over)
    return row


@pytest.fixture
def svc():
    return CapabilityAuthorityService()


@pytest.fixture
def catalog():
    return CapabilityCatalogService()


async def _seed_capability(catalog: CapabilityCatalogService, **over) -> str:
    return (await catalog.record_from_fact(_fact(**over)))["capability_id"]


# ══════════════════════════════════════════════════════════════════════════════
# A. Fail-closed invariants (one test each)
# ══════════════════════════════════════════════════════════════════════════════

async def test_written_scope_resources_are_never_empty(svc, catalog):
    """An empty resource list is match-EVERYTHING in DelegationEngine."""
    cap_id = await _seed_capability(catalog)
    record = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id=cap_id
    )
    assert record["scope"]["resources"] == [capability_resource(cap_id)]
    assert record["scope"]["resources"]  # non-empty on the written row

    server_wide = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", server_key="srvX"
    )
    assert server_wide["scope"]["resources"]

    # And the storage-boundary validator rejects the empty list outright.
    with pytest.raises(BadRequestError):
        validate_capability_scope({"actions": ["invoke"], "resources": []})
    with pytest.raises(BadRequestError):
        validate_capability_scope({"actions": ["invoke"]})  # key absent entirely


async def test_wildcard_rejected_in_actions_and_resources(svc):
    with pytest.raises(BadRequestError):
        validate_capability_scope({"actions": ["*"], "resources": ["capability:c1"]})
    with pytest.raises(BadRequestError):
        validate_capability_scope({"actions": ["invoke"], "resources": ["capability:*"]})
    with pytest.raises(BadRequestError):
        validate_capability_scope({"actions": ["invoke"], "resources": ["*"]})
    # A caller-supplied capability id can never become a glob.
    with pytest.raises(BadRequestError):
        await svc.grant(
            tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id="cap_*"
        )


async def test_actions_are_exactly_invoke(svc, catalog):
    cap_id = await _seed_capability(catalog)
    record = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id=cap_id
    )
    assert record["scope"]["actions"] == ["invoke"]

    for actions in ([], ["read"], ["invoke", "read"], ["read", "invoke"]):
        with pytest.raises(BadRequestError):
            validate_capability_scope({"actions": actions, "resources": ["capability:c1"]})


async def test_cross_tenant_read_and_revoke_are_not_found(svc, catalog):
    cap_id = await _seed_capability(catalog)
    record = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id=cap_id
    )
    auth_id = record["authorization_id"]

    # Owning tenant resolves it ...
    assert (await svc.get(tenant_id="t1", authorization_id=auth_id))["authorization_id"] == auth_id
    # ... a foreign tenant gets NotFound on BOTH read and revoke (never a different
    # error, which would itself be an existence oracle).
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t2", authorization_id=auth_id)
    with pytest.raises(NotFoundError):
        await svc.revoke(
            tenant_id="t2", authorization_id=auth_id, revoked_by_entity_id="attacker"
        )
    # An absent id is indistinguishable from the foreign one.
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t2", authorization_id="does-not-exist")
    # The foreign revoke did not take effect.
    assert (await svc.get(tenant_id="t1", authorization_id=auth_id))["state"] == "active"


async def test_unobserved_capability_grant_is_allowed_but_never_upgraded(svc, catalog):
    """Pre-authorization is legitimate; fabricating inventory evidence is not."""
    record = await svc.grant(
        tenant_id="t1",
        granted_by_entity_id="u1",
        agent_id="agentA",
        capability_id="cap_neverobserved",
    )
    assert record["capability_observed"] is False
    auth_id = record["authorization_id"]

    # Observing the capability afterwards must not retroactively flip the flag.
    await _seed_capability(catalog)
    later = await svc.get(tenant_id="t1", authorization_id=auth_id)
    assert later["capability_observed"] is False

    # A capability observed by ANOTHER tenant is also not "observed" here.
    other_cap = await _seed_capability(catalog, tenant_id="t2", source_event_id="z1")
    cross = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id=other_cap
    )
    assert cross["capability_observed"] is False


# ══════════════════════════════════════════════════════════════════════════════
# B. Additional authority behaviour
# ══════════════════════════════════════════════════════════════════════════════

async def test_grant_requires_exactly_one_target(svc, catalog):
    cap_id = await _seed_capability(catalog)
    with pytest.raises(BadRequestError):
        await svc.grant(tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA")
    with pytest.raises(BadRequestError):
        await svc.grant(
            tenant_id="t1",
            granted_by_entity_id="u1",
            agent_id="agentA",
            capability_id=cap_id,
            server_key="srvX",
        )
    with pytest.raises(BadRequestError):
        await svc.grant(
            tenant_id="t1", granted_by_entity_id="", agent_id="   ", capability_id=cap_id
        )


async def test_server_key_is_digested_so_a_glob_cannot_widen_scope(svc):
    hostile = "https://evil.example.com/*"
    record = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", server_key=hostile
    )
    resource = record["scope"]["resources"][0]
    assert record["server_ref"] == server_ref_for("t1", hostile)
    assert record["server_ref"].startswith("srv_")
    assert resource == f"capability-server:{record['server_ref']}"
    assert "*" not in resource
    assert "evil.example.com" not in resource
    # A ':' in the key cannot inject a second resource segment either.
    colon = await svc.grant(
        tenant_id="t1",
        granted_by_entity_id="u1",
        agent_id="agentB",
        server_key="capability:cap_other",
    )
    assert colon["scope"]["resources"][0].count(":") == 1
    # The digest is tenant-scoped: the same key in another tenant is a different ref.
    assert server_ref_for("t2", hostile) != server_ref_for("t1", hostile)


async def test_server_wide_authorization_covers_only_that_server(svc, catalog):
    on_x = await _seed_capability(catalog, source_event_id="a", server_name="srvX", tool_name="search")
    on_y = await _seed_capability(catalog, source_event_id="b", server_name="srvY", tool_name="search")
    assert on_x != on_y

    await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", server_key="srvX"
    )

    covered = await svc.resolve(tenant_id="t1", agent_id="agentA", capability_id=on_x)
    assert covered["authorized"] is True
    assert covered["authorization_reason"] == "active_capability_authorization"

    other = await svc.resolve(tenant_id="t1", agent_id="agentA", capability_id=on_y)
    assert other["authorized"] is False
    assert other["authorization_reason"] == "no_active_capability_authorization"


async def test_authorization_state_is_derived_from_the_row(svc, catalog):
    cap_id = await _seed_capability(catalog)

    active = await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id=cap_id
    )
    assert active["state"] == "active"

    expired = await svc.grant(
        tenant_id="t1",
        granted_by_entity_id="u1",
        agent_id="agentExpired",
        capability_id=cap_id,
        ends_at=PAST,
    )
    assert expired["state"] == "expired"
    assert authorization_state({"ends_at": PAST}) == "expired"
    # An expired authorization authorizes nothing.
    facts = await svc.resolve(tenant_id="t1", agent_id="agentExpired", capability_id=cap_id)
    assert facts["authorized"] is False

    pending = await svc.grant(
        tenant_id="t1",
        granted_by_entity_id="u1",
        agent_id="agentPending",
        capability_id=cap_id,
        starts_at=FUTURE,
    )
    assert pending["state"] == "pending"
    assert (
        await svc.resolve(tenant_id="t1", agent_id="agentPending", capability_id=cap_id)
    )["authorized"] is False

    revoked = await svc.revoke(
        tenant_id="t1", authorization_id=active["authorization_id"], revoked_by_entity_id="u1"
    )
    assert revoked["state"] == "revoked"
    # revoked_at wins even when the window is still open.
    assert authorization_state({"revoked_at": "2026-01-01T00:00:00+00:00", "ends_at": FUTURE}) == "revoked"
    assert (
        await svc.resolve(tenant_id="t1", agent_id="agentA", capability_id=cap_id)
    )["authorized"] is False


async def test_hand_written_delegation_cannot_satisfy_a_capability_check(svc, catalog):
    """A matching ordinary delegation lacks ``authorization_kind == "capability"``."""
    cap_id = await _seed_capability(catalog)
    delegations = DelegationRepository()
    row = await delegations.grant(
        delegation_id="hand-written-1",
        tenant_id="t1",
        grantor_entity_id="u1",
        grantee_entity_id="agentA",
        scope={"actions": ["invoke"], "resources": [capability_resource(cap_id)]},
    )
    assert row.get("authorization_kind") is None

    facts = await svc.resolve(tenant_id="t1", agent_id="agentA", capability_id=cap_id)
    assert facts["authorized"] is False
    assert facts["authorization_id"] is None
    assert facts["authorization_reason"] == "no_active_capability_authorization"
    # ... and it is invisible to the capability listing.
    assert await svc.list(tenant_id="t1") == []


async def test_get_on_an_ordinary_delegation_id_is_not_found(svc):
    delegations = DelegationRepository()
    await delegations.grant(
        delegation_id="ordinary-1",
        tenant_id="t1",
        grantor_entity_id="u1",
        grantee_entity_id="agentA",
        scope={"actions": ["transfer"], "resources": ["wallet:*"]},
    )
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t1", authorization_id="ordinary-1")


async def test_resolve_reports_facts_without_an_agent(svc, catalog):
    cap_id = await _seed_capability(catalog, risk_level="high")
    facts = await svc.resolve(tenant_id="t1", agent_id=None, capability_id=cap_id)
    assert facts["capability_observed"] is True
    assert facts["latest_risk_level"] == "high"
    assert facts["authorized"] is False
    assert facts["authorization_reason"] == "no_agent_id"

    # Another tenant's capability is not observed here.
    cross = await svc.resolve(tenant_id="t2", agent_id="agentA", capability_id=cap_id)
    assert cross["capability_observed"] is False


async def test_list_is_tenant_scoped_and_state_filterable(svc, catalog):
    cap_id = await _seed_capability(catalog)
    await svc.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA", capability_id=cap_id
    )
    await svc.grant(
        tenant_id="t1",
        granted_by_entity_id="u1",
        agent_id="agentB",
        capability_id=cap_id,
        ends_at=PAST,
    )
    await svc.grant(
        tenant_id="t2", granted_by_entity_id="u2", agent_id="agentA", capability_id=cap_id
    )

    rows = await svc.list(tenant_id="t1")
    assert len(rows) == 2
    assert {r["authorization_kind"] for r in rows} == {AUTHORIZATION_KIND}
    assert [r["agent_id"] for r in await svc.list(tenant_id="t1", state="active")] == ["agentA"]
    assert [r["agent_id"] for r in await svc.list(tenant_id="t1", state="expired")] == ["agentB"]
    assert len(await svc.list(tenant_id="t2")) == 1
    assert len(await svc.list(tenant_id="t1", agent_id="agentA")) == 1
