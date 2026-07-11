"""PR-A — central consent PolicyDecision engine.

Every sensitive path gets an explainable decision (policy_decision_id); denials
and explicit-opt-in purposes are persisted + audited; there is no broad-consent
fallback (exact required purpose from the signal-use matrix / purpose).
"""
import pytest

from repositories.repos import reset_in_memory_stores
from services.policy.engine import ConsentPolicyEngine
from services.policy import signal_use_matrix as matrix
import services.security.audit_ledger as audit_mod

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    audit_mod._TENANT_TAIL.clear()
    audit_mod._TENANT_SEQ.clear()
    yield
    reset_in_memory_stores()


async def test_allow_with_consent_persists_sensitive_decision():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="render_profile360",
        resource_type="profile360.web2", purpose="credit",
        granted_purposes=["credit"], subject_ref="ent1",
    )
    assert d.allowed is True
    assert d.required_purposes == ["credit"]
    assert d.missing_purposes == []
    assert d.policy_decision_id.startswith("cpd_")
    # credit is explicit opt-in => evidence persisted even when allowed.
    stored = await eng.list_decisions("t1")
    assert any(x["policy_decision_id"] == d.policy_decision_id for x in stored)


async def test_deny_records_reason_and_redacted_fields():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="render_profile360",
        resource_type="profile360.web2", purpose="credit",
        granted_purposes=["analytics"], subject_ref="ent1",
        redactable_fields=["credit_signals", "bank_accounts"],
    )
    assert d.allowed is False
    assert d.denied_reason == "missing_consent:credit"
    assert d.redacted_fields == ["bank_accounts", "credit_signals"]
    stored = await eng.list_decisions("t1")
    assert len(stored) == 1


async def test_signal_type_resolves_exact_purpose_from_matrix():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="link_identity",
        resource_type="identity", signal_type="device_fingerprint",
        granted_purposes=["analytics"],
    )
    # Fingerprint requires personalization (not a broad OR); denied here.
    assert d.required_purposes == ["personalization"]
    assert d.allowed is False
    # And fingerprint-only never links, per the matrix.
    assert matrix.allows("device_fingerprint", "allow_identity_linking") is False


async def test_non_sensitive_allow_is_not_persisted():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="collect_event",
        resource_type="event", purpose="analytics",
        granted_purposes=["analytics"],
    )
    assert d.allowed is True
    # analytics is not explicit opt-in and collect_event is not always-persist.
    assert await eng.list_decisions("t1") == []


async def test_no_broad_consent_fallback_for_sensitive():
    eng = ConsentPolicyEngine()
    # Having analytics/marketing must NOT satisfy a credit requirement.
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="export_data",
        resource_type="export", purpose="credit",
        granted_purposes=["analytics", "marketing", "web3", "agent", "commerce"],
    )
    assert d.allowed is False
    assert "credit" in d.missing_purposes


async def test_denial_joins_audit_ledger():
    eng = ConsentPolicyEngine()
    d = await eng.decide(
        tenant_id="t1", actor_id="u1", action="serve_inference",
        resource_type="model", purpose="location", granted_purposes=[],
    )
    events = await audit_mod.audit_ledger._repo.list_for_tenant("t1")
    assert any(e.get("policy_decision_id") == d.policy_decision_id for e in events)
