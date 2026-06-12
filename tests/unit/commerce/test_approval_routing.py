"""
Unit tests for ApprovalService — request, assign, decide, revoke, sweep, evidence_bundle.
Uses in-memory CommerceStore via AETHER_ENV=local.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")

TENANT = "tenant-approval-test"


@contextmanager
def backend_path(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    original = list(sys.path)
    original_mods = set(sys.modules.keys())
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for name in list(sys.modules):
            if name in original_mods:
                continue
            if name.split(".", 1)[0] in _BACKEND_PREFIXES:
                sys.modules.pop(name, None)


@pytest.fixture()
def commerce(monkeypatch):
    with backend_path(monkeypatch):
        from services.x402.commerce_store import reset_commerce_store
        reset_commerce_store()
        from services.x402.approvals import ApprovalService
        from services.x402.commerce_models import ApprovalPriority, ApprovalStatus
        yield ApprovalService(), ApprovalPriority, ApprovalStatus
        reset_commerce_store()


# ── request ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_creates_pending_approval(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-001",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
        priority=Priority.NORMAL,
    )
    assert apr.approval_id.startswith("apr_")
    assert apr.status == Status.PENDING
    assert apr.tenant_id == TENANT
    assert apr.challenge_id == "chg-001"
    assert apr.expires_at != ""


@pytest.mark.asyncio
async def test_request_sets_expiry_based_on_priority(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-high",
        resource_id="res-002",
        requester_id="agent-002",
        requester_type="agent",
        amount_usd=10.0,
        asset_symbol="USDC",
        chain="eip155:8453",
        priority=Priority.HIGH,
    )
    # Expiry should be set and non-empty
    assert apr.expires_at != ""
    assert "T" in apr.expires_at  # ISO format


@pytest.mark.asyncio
async def test_request_stores_default_reason(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-002",
        resource_id="res-002",
        requester_id="agent-002",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert "approval" in apr.reason.lower()


# ── assign ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_pending_approval(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-003",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=2.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assigned = await svc.assign(TENANT, apr.approval_id, "reviewer-001", "admin-001")
    assert assigned.status == Status.ASSIGNED
    assert assigned.assigned_to == "reviewer-001"


@pytest.mark.asyncio
async def test_assign_missing_approval_raises(commerce):
    svc, Priority, Status = commerce
    with pytest.raises(ValueError, match="not found"):
        await svc.assign(TENANT, "nonexistent-apr", "reviewer", "admin")


# ── decide ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decide_approve(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-004",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=3.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    result = await svc.decide(TENANT, apr.approval_id, "approve", "reviewer-001", "Looks good")
    assert result.status == Status.APPROVED
    assert result.decided_by == "reviewer-001"
    assert result.decision_reason == "Looks good"


@pytest.mark.asyncio
async def test_decide_reject(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-005",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=3.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    result = await svc.decide(TENANT, apr.approval_id, "reject", "reviewer-002", "Too expensive")
    assert result.status == Status.REJECTED


@pytest.mark.asyncio
async def test_decide_escalate(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-006",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=3.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    result = await svc.decide(TENANT, apr.approval_id, "escalate", "reviewer-003", "Need higher sign-off")
    assert result.status == Status.ESCALATED
    assert "reviewer-003" in result.escalation_chain


@pytest.mark.asyncio
async def test_decide_already_approved_raises(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-007",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=3.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    await svc.decide(TENANT, apr.approval_id, "approve", "r1", "ok")
    with pytest.raises(ValueError, match="finalized"):
        await svc.decide(TENANT, apr.approval_id, "reject", "r2", "too late")


@pytest.mark.asyncio
async def test_decide_unknown_action_raises(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-008",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    with pytest.raises(ValueError, match="Unknown action"):
        await svc.decide(TENANT, apr.approval_id, "magic", "r1", "bad")


# ── revoke ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revoke_approved_approval(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-009",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    await svc.decide(TENANT, apr.approval_id, "approve", "r1", "ok")
    revoked = await svc.revoke(TENANT, apr.approval_id, "admin-001", "Compliance hold")
    assert revoked.status == Status.REVOKED
    assert revoked.decision_reason == "Compliance hold"


@pytest.mark.asyncio
async def test_revoke_idempotent(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-010",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    await svc.revoke(TENANT, apr.approval_id, "admin", "reason")
    result = await svc.revoke(TENANT, apr.approval_id, "admin", "reason again")
    assert result.status == Status.REVOKED


# ── sweep_expired ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_expired_skips_non_expired(commerce):
    svc, Priority, Status = commerce
    await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-sweep-1",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
        priority=Priority.NORMAL,  # 1h SLA — should not expire in test
    )
    count = await svc.sweep_expired(TENANT)
    assert count == 0


# ── evidence_bundle ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_bundle_contains_approval(commerce):
    svc, Priority, Status = commerce
    apr = await svc.request(
        tenant_id=TENANT,
        challenge_id="chg-evid",
        resource_id="res-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    bundle = await svc.evidence_bundle(TENANT, apr.approval_id)
    assert "approval" in bundle
    assert bundle["approval"]["approval_id"] == apr.approval_id
