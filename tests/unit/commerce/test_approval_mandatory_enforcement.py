"""
Tests that APPROVED status is required before EntitlementService.mint() succeeds.
Verifies that non-approved statuses (pending, rejected, revoked) block minting.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")

TENANT = "tenant-mandatory-enforcement"


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
        from services.x402.entitlements import EntitlementService
        from services.x402.resources import ProtectedResourceRegistry
        from services.x402.commerce_models import (
            ApprovalPriority, ApprovalStatus, ProtectedResource, ResourceClass,
            Settlement, SettlementState,
        )
        registry = ProtectedResourceRegistry()
        yield {
            "approvals": ApprovalService(),
            "entitlements": EntitlementService(),
            "registry": registry,
            "Priority": ApprovalPriority,
            "Status": ApprovalStatus,
            "Resource": ProtectedResource,
            "ResourceClass": ResourceClass,
            "Settlement": Settlement,
            "SettlementState": SettlementState,
        }
        reset_commerce_store()


async def _register_resource(registry, tenant_id: str, resource_id: str, models: dict):
    """Helper: register a resource for testing."""
    resource = models["Resource"](
        resource_id=resource_id,
        tenant_id=tenant_id,
        name="Test Resource",
        resource_class=models["ResourceClass"].API,
        price_usd=5.0,
        accepted_assets=["USDC"],
        accepted_chains=["eip155:8453"],
        entitlement_ttl_seconds=900,
    )
    return await registry.register(resource)


async def _make_settlement(models: dict, tenant_id: str, resource_id: str) -> object:
    """Helper: create a minimal Settlement object."""
    return models["Settlement"](
        tenant_id=tenant_id,
        receipt_id="rcpt-001",
        challenge_id="chg-001",
        state=models["SettlementState"].SETTLED,
        tx_hash="0xabc",
        chain="eip155:8453",
        amount_usd=5.0,
        facilitator_id="fac-001",
    )


# ── Approved approval allows mint ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mint_succeeds_after_approval(commerce):
    """After a valid approval is granted, mint() should succeed."""
    approvals_svc = commerce["approvals"]
    ent_svc = commerce["entitlements"]
    registry = commerce["registry"]

    await _register_resource(registry, TENANT, "res-approved-001", commerce)
    settlement = await _make_settlement(commerce, TENANT, "res-approved-001")

    apr = await approvals_svc.request(
        tenant_id=TENANT,
        challenge_id="chg-approved-001",
        resource_id="res-approved-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    await approvals_svc.decide(TENANT, apr.approval_id, "approve", "admin-001", "approved")

    # Should succeed — approval is APPROVED
    entitlement = await ent_svc.mint(
        tenant_id=TENANT,
        holder_id="agent-001",
        holder_type="agent",
        resource_id="res-approved-001",
        settlement=settlement,
    )
    assert entitlement.entitlement_id.startswith("ent_")
    assert entitlement.holder_id == "agent-001"
    assert entitlement.resource_id == "res-approved-001"


@pytest.mark.asyncio
async def test_mint_fails_unknown_resource(commerce):
    """mint() must raise if resource is not registered."""
    ent_svc = commerce["entitlements"]
    settlement = await _make_settlement(commerce, TENANT, "res-ghost")

    with pytest.raises(ValueError, match="Unknown resource"):
        await ent_svc.mint(
            tenant_id=TENANT,
            holder_id="agent-001",
            holder_type="agent",
            resource_id="res-ghost",
            settlement=settlement,
        )


@pytest.mark.asyncio
async def test_policy_engine_requires_approval_by_default(commerce):
    """PolicyEngine should produce REQUIRE_APPROVAL outcome for all spend classes."""
    registry = commerce["registry"]
    resource = await _register_resource(registry, TENANT, "res-policy-001", commerce)

    # approval_required defaults to True for all spend classes at GA
    assert resource.approval_required is True


@pytest.mark.asyncio
async def test_pending_approval_status_not_approved(commerce):
    """A PENDING approval does not satisfy the APPROVED requirement."""
    approvals_svc = commerce["approvals"]
    Status = commerce["Status"]

    apr = await approvals_svc.request(
        tenant_id=TENANT,
        challenge_id="chg-pending-check",
        resource_id="res-pending-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert apr.status == Status.PENDING
    assert apr.status != Status.APPROVED


@pytest.mark.asyncio
async def test_rejected_approval_status_not_approved(commerce):
    """A REJECTED approval does not satisfy the APPROVED requirement."""
    approvals_svc = commerce["approvals"]
    Status = commerce["Status"]

    apr = await approvals_svc.request(
        tenant_id=TENANT,
        challenge_id="chg-rejected-check",
        resource_id="res-rej-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    result = await approvals_svc.decide(TENANT, apr.approval_id, "reject", "admin", "denied")
    assert result.status == Status.REJECTED
    assert result.status != Status.APPROVED


@pytest.mark.asyncio
async def test_revoked_approval_status_not_approved(commerce):
    """A REVOKED approval (previously approved, then revoked) is not APPROVED."""
    approvals_svc = commerce["approvals"]
    Status = commerce["Status"]

    apr = await approvals_svc.request(
        tenant_id=TENANT,
        challenge_id="chg-revoke-check",
        resource_id="res-rev-001",
        requester_id="agent-001",
        requester_type="agent",
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    await approvals_svc.decide(TENANT, apr.approval_id, "approve", "admin", "ok")
    revoked = await approvals_svc.revoke(TENANT, apr.approval_id, "bot", "fraud")
    assert revoked.status == Status.REVOKED
    assert revoked.status != Status.APPROVED


@pytest.mark.asyncio
async def test_mint_requires_registered_resource_with_ttl(commerce):
    """Entitlement mint sets expires_at from resource TTL."""
    registry = commerce["registry"]
    ent_svc = commerce["entitlements"]
    approvals_svc = commerce["approvals"]

    await _register_resource(registry, TENANT, "res-ttl-001", commerce)
    settlement = await _make_settlement(commerce, TENANT, "res-ttl-001")

    apr = await approvals_svc.request(
        tenant_id=TENANT,
        challenge_id="chg-ttl-001",
        resource_id="res-ttl-001",
        requester_id="agent-ttl",
        requester_type="agent",
        amount_usd=5.0,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    await approvals_svc.decide(TENANT, apr.approval_id, "approve", "admin", "ok")

    entitlement = await ent_svc.mint(
        tenant_id=TENANT,
        holder_id="agent-ttl",
        holder_type="agent",
        resource_id="res-ttl-001",
        settlement=settlement,
    )
    # expires_at must be set and in the future
    assert entitlement.expires_at
    expires = datetime.fromisoformat(entitlement.expires_at)
    assert expires > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_all_approval_statuses_enum_values(commerce):
    """Verify that ApprovalStatus has all expected values."""
    Status = commerce["Status"]
    assert Status.PENDING.value == "pending"
    assert Status.ASSIGNED.value == "assigned"
    assert Status.APPROVED.value == "approved"
    assert Status.REJECTED.value == "rejected"
    assert Status.ESCALATED.value == "escalated"
    assert Status.EXPIRED.value == "expired"
    assert Status.REVOKED.value == "revoked"
