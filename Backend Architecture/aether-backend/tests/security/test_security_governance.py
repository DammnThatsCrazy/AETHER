"""Tests for the Security & Governance control plane."""
from __future__ import annotations

import json

import pytest

from repositories.repos import reset_in_memory_stores

from services.security import audit_ledger as audit_mod
from services.security import integration_security as integ_mod
from services.security.access_control import ROLE_GRANTS, access_control, build_role_grants
from services.security.audit_ledger import AuditLedger, audit_ledger
from services.security.break_glass import BreakGlassService
from services.security.contracts import sanitize_metadata
from services.security.evidence_packs import EvidencePackService
from services.security.integration_security import (
    IntegrationSecurity,
    redact_config,
    sign_payload,
    verify_signature,
)
from services.security.isolation_verifier import TenantIsolationVerifier
from services.security.policy_engine import PolicyEngine
from services.security.repositories import SecurityAuditEventRepository
from services.security.retention import DataRetentionService

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    audit_mod._TENANT_TAIL.clear()
    audit_mod._TENANT_SEQ.clear()
    integ_mod._SEEN_IDEMPOTENCY.clear()
    integ_mod._FAILURE_COUNTS.clear()


# ── Access control: role→permission mapping + allow/deny ─────────────────────

async def test_role_to_permission_mapping_is_populated():
    grants = build_role_grants('tenant_owner')
    assert grants, "tenant_owner should have grants"
    assert all(g.scope == 'own_tenant' for g in grants)
    assert ROLE_GRANTS['olympus_admin'][0].scope == 'all_tenants_admin'


async def test_access_allowed_for_owner_on_own_tenant():
    d = await access_control.evaluate(
        actor_id="u1", actor_type='tenant_user', roles=['tenant_owner'],
        domain='decisions', action='approve', actor_tenant='t1', target_tenant='t1',
    )
    assert d.allowed is True


async def test_access_denied_cross_tenant_for_viewer():
    d = await access_control.evaluate(
        actor_id="u1", actor_type='tenant_user', roles=['tenant_viewer'],
        domain='decisions', action='read', actor_tenant='t1', target_tenant='t2',
    )
    assert d.allowed is False
    assert d.severity == 'block'


async def test_aggregate_scope_cannot_target_single_tenant():
    d = await access_control.evaluate(
        actor_id="op1", actor_type='olympus_operator', roles=['olympus_revops'],
        domain='billing', action='read', target_tenant='t9',
    )
    assert d.allowed is False


async def test_sensitive_allowed_access_is_audited():
    repo = SecurityAuditEventRepository()
    before = len(await repo.list_all(limit=1000))
    await access_control.evaluate(
        actor_id="u1", actor_type='tenant_user', roles=['tenant_owner'],
        domain='audit_exports', action='export', actor_tenant='t1', target_tenant='t1',
    )
    after = len(await repo.list_all(limit=1000))
    assert after == before + 1


# ── Policy engine ─────────────────────────────────────────────────────────────

async def test_dispatch_blocked_when_decision_not_approved():
    eng = PolicyEngine()
    d = await eng.check_action_dispatch(
        actor_id="u1", actor_type='tenant_user', tenant_id='t1',
        decision_status='proposed', action_id='a1',
    )
    assert d.allowed is False and d.policy_key == 'action.dispatch'


async def test_elevated_dispatch_requires_approval_id():
    eng = PolicyEngine()
    d = await eng.check_action_dispatch(
        actor_id="u1", actor_type='tenant_user', tenant_id='t1',
        decision_status='approved', is_elevated=True, approval_id=None,
    )
    assert d.allowed is False and d.policy_key == 'action.elevated_dispatch'
    ok = await eng.check_action_dispatch(
        actor_id="u1", actor_type='tenant_user', tenant_id='t1',
        decision_status='approved', is_elevated=True, approval_id='appr_1',
    )
    assert ok.allowed is True


async def test_cross_tenant_access_denied():
    eng = PolicyEngine()
    d = await eng.check_cross_tenant(
        actor_id="u1", actor_type='tenant_user', actor_tenant='t1',
        target_tenant='t2', resource_type='decision',
    )
    assert d.allowed is False


async def test_audit_export_requires_permission():
    eng = PolicyEngine()
    d = await eng.check_audit_export(
        actor_id="u1", actor_type='tenant_user', tenant_id='t1', has_export_permission=False,
    )
    assert d.allowed is False


async def test_webhook_dispatch_blocks_private_destination():
    eng = PolicyEngine()
    d = await eng.check_integration_dispatch(
        actor_id="u1", actor_type='tenant_user', tenant_id='t1',
        integration_enabled=True, destination_url='https://127.0.0.1/hook',
    )
    assert d.allowed is False


async def test_data_deletion_blocks_audit_log():
    eng = PolicyEngine()
    d = await eng.check_data_deletion(
        actor_id="u1", actor_type='tenant_user', tenant_id='t1', resource_type='audit_log',
    )
    assert d.allowed is False


# ── Audit ledger integrity ────────────────────────────────────────────────────

async def test_audit_chain_is_verifiable():
    ledger = AuditLedger()
    for i in range(3):
        await ledger.record(
            actor_id="u1", actor_type='tenant_user', event_type="t", resource_type="r",
            action="read", outcome='allowed', tenant_id='t1',
        )
    result = await ledger.verify_chain('t1')
    assert result["chain_intact"] is True
    assert result["events_checked"] == 3


async def test_global_chain_verifies_per_tenant():
    # Codex P2: a global (tenant_id omitted) verification must track a separate
    # previous hash per tenant; otherwise the second tenant's first event is
    # falsely flagged as broken.
    ledger = AuditLedger()
    for tid in ("t1", "t2", "t1", "t2"):
        await ledger.record(
            actor_id="u", actor_type='tenant_user', event_type="t", resource_type="r",
            action="read", outcome='allowed', tenant_id=tid,
        )
    result = await ledger.verify_chain()  # global
    assert result["chain_intact"] is True
    assert result["chains_verified"] == 2
    assert result["broken_event_ids"] == []


async def test_audit_metadata_tampering_is_detected():
    # Codex P2: metadata/ip/user_agent are part of the tamper-evident record.
    ledger = AuditLedger()
    ev = await ledger.record(
        actor_id="u1", actor_type='tenant_user', event_type="t", resource_type="r",
        action="read", outcome='allowed', tenant_id='t1',
        metadata={"target": "tenant-a"}, ip_address="10.0.0.9",
    )
    repo = ledger._repo
    raw = await repo.find_by_id(ev.audit_event_id)
    raw["metadata"] = {"target": "tenant-b"}  # tamper after the fact
    await repo.update(ev.audit_event_id, raw)
    result = await ledger.verify_chain('t1')
    assert result["chain_intact"] is False
    assert ev.audit_event_id in result["broken_event_ids"]


# ── Break-glass lifecycle ─────────────────────────────────────────────────────

async def test_break_glass_request_approve_revoke():
    svc = BreakGlassService()
    req = await svc.request(tenant_id='t1', requested_by='op1', reason='incident', requested_scope='read')
    assert req.status == 'requested'
    approved = await svc.approve(request_id=req.request_id, approved_by='op2')
    assert approved.status == 'approved' and approved.expires_at
    assert await svc.has_active_grant('t1', 'op1') is True
    revoked = await svc.revoke(request_id=req.request_id, revoked_by='op2')
    assert revoked.status == 'revoked'
    assert await svc.has_active_grant('t1', 'op1') is False


async def test_break_glass_requires_different_approver():
    # Codex P1: the requester may not approve their own break-glass grant.
    svc = BreakGlassService()
    req = await svc.request(tenant_id='t1', requested_by='op1', reason='incident', requested_scope='read')
    with pytest.raises(Exception):
        await svc.approve(request_id=req.request_id, approved_by='op1')
    # Request stays un-approved, so no active grant is created.
    assert await svc.has_active_grant('t1', 'op1') is False
    # A different operator can still approve.
    approved = await svc.approve(request_id=req.request_id, approved_by='op2')
    assert approved.status == 'approved'


async def test_break_glass_requires_reason():
    svc = BreakGlassService()
    with pytest.raises(Exception):
        await svc.request(tenant_id='t1', requested_by='op1', reason='  ', requested_scope='read')


async def test_break_glass_expires():
    svc = BreakGlassService()
    req = await svc.request(tenant_id='t1', requested_by='op1', reason='x', requested_scope='read', window_hours=1)
    row = await svc._repo.find_by_id(req.request_id)
    await svc.approve(request_id=req.request_id, approved_by='op2')
    # Force expiry by rewinding expires_at.
    row = await svc._repo.find_by_id(req.request_id)
    row["expires_at"] = "2000-01-01T00:00:00+00:00"
    await svc._repo.update(req.request_id, row)
    assert await svc.has_active_grant('t1', 'op1') is False
    after = await svc._repo.find_by_id(req.request_id)
    assert after["status"] == 'expired'


# ── Data retention + data requests ────────────────────────────────────────────

async def test_retention_policy_creation_blocks_hard_delete_of_audit_log():
    svc = DataRetentionService()
    with pytest.raises(Exception):
        await svc.create_policy(tenant_id='t1', resource_type='audit_log', retention_days=30, delete_behavior='hard_delete')
    pol = await svc.create_policy(tenant_id='t1', resource_type='event', retention_days=30, delete_behavior='anonymize')
    assert pol.resource_type == 'event'


async def test_data_request_lifecycle():
    svc = DataRetentionService()
    req = await svc.create_request(tenant_id='t1', request_type='export', requested_by='u1')
    assert req.status == 'requested'
    processed = await svc.process_request(req.data_request_id, status='completed', result_summary='done')
    assert processed["status"] == 'completed' and processed["completed_at"]


async def test_data_request_delete_audit_log_denied():
    svc = DataRetentionService()
    req = await svc.create_request(
        tenant_id='t1', request_type='delete_entity', requested_by='u1',
        target_resource_type='audit_log',
    )
    assert req.status == 'denied'


async def test_default_policies_seeded_and_audit_log_preserved():
    svc = DataRetentionService()
    policies = await svc.list_policies('t1')
    audit = [p for p in policies if p["resource_type"] == 'audit_log'][0]
    assert audit["delete_behavior"] == 'preserve_audit_stub'


# ── Tenant isolation verifier ─────────────────────────────────────────────────

async def test_isolation_verifier_runs_and_detects_missing_tenant_id():
    from services.security.isolation_verifier import _TableRepo
    repo = _TableRepo("recommendations")
    await repo.insert("rec_ok", {"id": "rec_ok", "tenant_id": "t1"})
    await repo.insert("rec_bad", {"id": "rec_bad"})
    verifier = TenantIsolationVerifier()
    result = await verifier.run()
    rec_check = [c for c in result["checks"] if c["check"] == 'recommendations'][0]
    assert rec_check["status"] == 'fail'
    assert result["overall_status"] == 'fail'


# ── Evidence packs ────────────────────────────────────────────────────────────

async def test_evidence_pack_generation_states_not_certified():
    svc = EvidencePackService()
    pack = await svc.generate(pack_type='access_control', requested_by='op1')
    assert pack.status == 'generated'
    assert pack.integrity_hash
    assert pack.known_gaps
    rows = await svc.list_packs(limit=10)
    assert any("compliance certification" in (r.get("disclaimer") or "") for r in rows)


# ── Secret hygiene ────────────────────────────────────────────────────────────

async def test_sanitize_metadata_strips_secrets():
    cleaned = sanitize_metadata({
        "api_key": "sk_live_abc", "nested": {"password": "p"}, "ok": "value",
        "note": "bearer xyz token",
    })
    assert "api_key" not in cleaned
    assert "password" not in cleaned["nested"]
    assert cleaned["ok"] == "value"
    assert cleaned["note"] == "[redacted]"


async def test_no_secret_reaches_audit_metadata():
    ledger = AuditLedger()
    ev = await ledger.record(
        actor_id="u1", actor_type='tenant_user', event_type="t", resource_type="r",
        action="read", outcome='allowed', tenant_id='t1',
        metadata={"signing_secret": "whsec_x", "fine": "ok"},
    )
    blob = json.dumps(ev.model_dump())
    assert "whsec_x" not in blob and "signing_secret" not in blob
    assert "ok" in blob


async def test_integration_config_redacts_secret_but_signals_presence():
    cfg = redact_config({"url": "https://x", "signing_secret": "whsec_1"})
    assert "signing_secret" not in cfg
    assert cfg["secret_configured"] is True


async def test_webhook_signing_roundtrip():
    secret = "whsec_test"
    payload = b'{"event":"x"}'
    headers = sign_payload(secret, payload)
    assert verify_signature(secret, payload, headers["X-Aether-Timestamp"], headers["X-Aether-Signature"]) is True
    assert verify_signature("wrong", payload, headers["X-Aether-Timestamp"], headers["X-Aether-Signature"]) is False


# ── Integration security dispatch governance ──────────────────────────────────

async def test_integration_dispatch_requires_idempotency_and_dedupes(monkeypatch):
    from services.security import policy_engine as pe_mod
    # Resolve the test hostname to a public IP so the SSRF guard allows it
    # deterministically without real DNS.
    monkeypatch.setattr(pe_mod, "_resolve_host", lambda host: ["93.184.216.34"])
    sec = IntegrationSecurity()
    with pytest.raises(Exception):
        await sec.authorize_dispatch(
            tenant_id='t1', integration_id='i1', actor_id='u1', actor_type='tenant_user',
            integration_enabled=True, destination_url='https://hooks.example.com/x',
        )
    first = await sec.authorize_dispatch(
        tenant_id='t1', integration_id='i1', actor_id='u1', actor_type='tenant_user',
        integration_enabled=True, destination_url='https://hooks.example.com/x',
        idempotency_key='k1',
    )
    assert first["dispatched"] is True
    second = await sec.authorize_dispatch(
        tenant_id='t1', integration_id='i1', actor_id='u1', actor_type='tenant_user',
        integration_enabled=True, destination_url='https://hooks.example.com/x',
        idempotency_key='k1',
    )
    assert second["deduplicated"] is True


async def test_integration_repeated_failures_detected():
    sec = IntegrationSecurity()
    result = {}
    for _ in range(5):
        result = await sec.record_failure(tenant_id='t1', integration_id='i1')
    assert result["repeated_failures_detected"] is True


# ── SSRF: hostnames resolving to private targets ──────────────────────────────

async def test_webhook_blocks_hostname_resolving_to_private(monkeypatch):
    # Codex P2: a hostname that resolves to a private/metadata IP must be blocked,
    # not just literal private IPs.
    from services.security import policy_engine as pe_mod
    monkeypatch.setattr(pe_mod, "_resolve_host", lambda host: ["169.254.169.254"])
    unsafe, why = pe_mod._is_unsafe_destination("https://internal.evil.example/hook")
    assert unsafe is True and "private/reserved" in why


async def test_webhook_blocks_unresolvable_hostname(monkeypatch):
    import socket
    from services.security import policy_engine as pe_mod

    def _boom(host):
        raise socket.gaierror("no address")

    monkeypatch.setattr(pe_mod, "_resolve_host", _boom)
    unsafe, why = pe_mod._is_unsafe_destination("https://does-not-resolve.example/hook")
    assert unsafe is True and "could not be resolved" in why


async def test_webhook_allows_hostname_resolving_to_public(monkeypatch):
    from services.security import policy_engine as pe_mod
    monkeypatch.setattr(pe_mod, "_resolve_host", lambda host: ["93.184.216.34"])
    unsafe, _ = pe_mod._is_unsafe_destination("https://hooks.example.com/x")
    assert unsafe is False


# ── Operator-only Kyber access (no Aether tenant may access Kyber) ─────────────

class _FakeTenant:
    def __init__(self, tenant_id, permissions):
        self.tenant_id = tenant_id
        self.user_id = "u-" + tenant_id
        self.permissions = list(permissions)

    def has_permission(self, perm):
        return perm in self.permissions


async def test_tenant_admin_is_not_a_kyber_operator(monkeypatch):
    from services.security import request_context as rc
    from config.settings import settings
    # A normal Aether tenant — even with the legacy "admin" permission — is denied.
    tenant_admin = _FakeTenant("tenant_001", ["admin", "read", "write", "export"])
    assert rc.is_kyber_operator(tenant_admin) is False
    # An operator holding the dedicated permission is allowed.
    operator = _FakeTenant("olympus_ops", [settings.security_governance.kyber_operator_permission])
    assert rc.is_kyber_operator(operator) is True


async def test_operator_allowlist_recognizes_operator(monkeypatch):
    import dataclasses

    from config.settings import settings
    from services.security import request_context as rc
    patched = dataclasses.replace(
        settings.security_governance, kyber_operator_tenant_ids=["olympus_internal"],
    )
    monkeypatch.setattr(settings, "security_governance", patched)
    assert rc.is_kyber_operator(_FakeTenant("olympus_internal", [])) is True
    assert rc.is_kyber_operator(_FakeTenant("tenant_001", ["admin"])) is False
