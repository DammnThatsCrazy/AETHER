"""``capability.invoke`` policy tests (PR 2, Phase B1).

Proves the deny ladder fires in the documented order with the exact operator-facing
strings, that the allow path is ``info``/allowed, that the decision is persisted even
when ALLOWED (``capability.invoke`` is a sensitive key — this is what makes
``GET /v1/capability-policy/decisions`` a real log rather than a deny-only sample), that
``latest_risk_level`` is reported in audit metadata but never silently enforced, and that
``list_decisions(policy_key=...)`` filters in the query rather than after the page.
"""

from __future__ import annotations

import pytest

from services.security.contracts import PolicyDecision
from services.security.policy_engine import PolicyEngine, _SENSITIVE_KEYS
from services.security.repositories import (
    PolicyDecisionRepository,
    SecurityAuditEventRepository,
)

TENANT = "t1"
CAP = "cap_abc123"


@pytest.fixture
def engine():
    return PolicyEngine()


async def _check(engine: PolicyEngine, **over):
    kwargs = {
        "actor_id": "u1",
        "actor_type": "tenant_user",
        "tenant_id": TENANT,
        "capability_id": CAP,
        "agent_id": "agentA",
        "capability_observed": True,
        "has_active_authorization": True,
    }
    kwargs.update(over)
    return await engine.check_capability_invocation(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# C. Deny ladder / allow path
# ══════════════════════════════════════════════════════════════════════════════

async def test_capability_invoke_is_a_sensitive_policy_key():
    assert "capability.invoke" in _SENSITIVE_KEYS


async def test_unobserved_capability_is_denied_first(engine):
    """Fires ahead of the agent and authorization rules."""
    d = await _check(
        engine, capability_observed=False, agent_id=None, has_active_authorization=False
    )
    assert d.allowed is False
    assert d.severity == "block"
    assert d.policy_key == "capability.invoke"
    assert d.action == "invoke"
    assert d.resource_type == "capability"
    assert d.resource_id == CAP
    assert d.reason == "capability not in tenant inventory"
    assert d.required_action == "observe or authorize it explicitly before invocation"


async def test_unidentified_agent_is_denied_second(engine):
    d = await _check(engine, agent_id=None, has_active_authorization=False)
    assert d.allowed is False
    assert d.severity == "block"
    assert d.reason == "invoking agent is unidentified"
    assert d.required_action == "attribute the invocation to an agent"


async def test_missing_authorization_is_denied_third(engine):
    d = await _check(engine, has_active_authorization=False)
    assert d.allowed is False
    assert d.severity == "block"
    assert d.reason == "no active capability authorization"
    assert d.required_action == "grant one via POST /v1/capability-authorizations"


async def test_allow_path(engine):
    d = await _check(engine, authorization_id="auth-1")
    assert d.allowed is True
    assert d.severity == "info"
    assert d.reason == "active capability authorization"
    assert d.required_action is None


async def test_allowed_decision_is_still_persisted_and_listable(engine):
    """The load-bearing assertion behind the decision-log endpoint."""
    d = await _check(engine, authorization_id="auth-1")
    assert d.allowed is True

    rows = await engine.list_decisions(tenant_id=TENANT, policy_key="capability.invoke")
    assert [r["decision_id"] for r in rows] == [d.decision_id]
    assert rows[0]["allowed"] is True
    assert rows[0]["reason"] == "active capability authorization"

    # ... and the audit ledger recorded the allow too.
    events = await SecurityAuditEventRepository().list_for_tenant(TENANT, limit=10)
    assert [e["event_type"] for e in events] == ["policy.capability.invoke"]
    assert events[0]["outcome"] == "allowed"
    assert events[0]["policy_decision_id"] == d.decision_id


async def test_denied_decision_is_persisted_too(engine):
    d = await _check(engine, capability_observed=False)
    rows = await engine.list_decisions(tenant_id=TENANT, policy_key="capability.invoke")
    assert [r["decision_id"] for r in rows] == [d.decision_id]
    assert rows[0]["allowed"] is False
    events = await SecurityAuditEventRepository().list_for_tenant(TENANT, limit=10)
    assert events[0]["outcome"] == "blocked"


async def test_critical_risk_is_reported_not_enforced(engine):
    """Risk travels in audit metadata; inventing a threshold here would be a
    fabricated control operators would believe is enforced."""
    d = await _check(engine, authorization_id="auth-1", latest_risk_level="critical")
    assert d.allowed is True
    assert d.severity == "info"
    assert d.reason == "active capability authorization"

    events = await SecurityAuditEventRepository().list_for_tenant(TENANT, limit=10)
    meta = events[0]["metadata"]
    assert meta["latest_risk_level"] == "critical"
    assert meta["capability_id"] == CAP
    assert meta["agent_id"] == "agentA"
    assert meta["capability_observed"] is True


async def test_the_permitting_grant_reaches_the_audit_ledger(engine):
    """``contracts.SECRET_RE`` matches the substring ``authorization`` and
    ``sanitize_metadata`` DROPS any key it matches, so a metadata key literally named
    ``authorization_id`` would silently vanish and the ledger would never record *which*
    grant permitted the invocation. The sanitizer is not weakened — the key is named
    ``capability_grant_id``. This test fails if it is ever renamed back."""
    await _check(engine, authorization_id="auth-1")
    events = await SecurityAuditEventRepository().list_for_tenant(TENANT, limit=10)
    meta = events[0]["metadata"]
    assert meta["capability_grant_id"] == "auth-1"
    assert "authorization_id" not in meta
    # The evidence lives in the audit ledger: PolicyDecision itself carries no metadata.
    assert not hasattr(PolicyDecision(
        actor_id="u1", actor_type="tenant_user", policy_key="capability.invoke",
        resource_type="capability", action="invoke", allowed=True, reason="x",
    ), "metadata")


async def test_a_key_named_authorization_id_really_would_be_dropped(engine):
    """Guards the reason for the rename above: if SECRET_RE ever stops matching
    ``authorization``, this test fails and the rename can be revisited deliberately."""
    from services.security.contracts import sanitize_metadata

    assert sanitize_metadata({"authorization_id": "auth-1"}) == {}
    assert sanitize_metadata({"capability_grant_id": "auth-1"}) == {
        "capability_grant_id": "auth-1"
    }


async def test_critical_risk_does_not_rescue_a_denied_invocation(engine):
    d = await _check(engine, has_active_authorization=False, latest_risk_level="critical")
    assert d.allowed is False
    assert d.reason == "no active capability authorization"


async def test_decisions_are_tenant_scoped(engine):
    mine = await _check(engine, authorization_id="auth-1")
    await _check(engine, tenant_id="t2", authorization_id="auth-2")
    rows = await engine.list_decisions(tenant_id=TENANT, policy_key="capability.invoke")
    assert [r["decision_id"] for r in rows] == [mine.decision_id]


async def test_policy_key_filter_applies_in_the_query_not_after_the_page(engine):
    """A post-filter over a `limit`-sized page would return an empty log whenever the
    tenant's most recent decisions belong to other policy keys."""
    repo = PolicyDecisionRepository()
    d = await _check(engine, authorization_id="auth-1")
    # Make the capability decision the OLDEST row so a naive
    # "take the newest `limit`, then filter" implementation would drop it.
    await repo.update(d.decision_id, {"created_at": "2000-01-01T00:00:00+00:00"})

    limit = 3
    noise_ids = []
    for i in range(limit + 3):
        other = PolicyDecision(
            tenant_id=TENANT,
            actor_id="u1",
            actor_type="tenant_user",
            policy_key="action.dispatch",
            resource_type="action",
            action="dispatch",
            allowed=True,
            reason="unrelated policy traffic",
        )
        await repo.insert(other.decision_id, other.model_dump())
        await repo.update(other.decision_id, {"created_at": f"2026-07-2{i}T00:00:00+00:00"})
        noise_ids.append(other.decision_id)

    # The newest `limit` decisions are all the other policy key ...
    unfiltered = await engine.list_decisions(tenant_id=TENANT, limit=limit)
    assert len(unfiltered) == limit
    assert d.decision_id not in {r["decision_id"] for r in unfiltered}
    assert set(unfiltered[0].keys()) >= {"policy_key", "decision_id"}

    # ... yet the capability log still returns it.
    rows = await engine.list_decisions(
        tenant_id=TENANT, limit=limit, policy_key="capability.invoke"
    )
    assert [r["decision_id"] for r in rows] == [d.decision_id]
    assert not ({r["decision_id"] for r in rows} & set(noise_ids))
