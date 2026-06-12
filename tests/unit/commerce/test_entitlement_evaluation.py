"""Unit tests for EntitlementService — mint, lookup, reuse, revoke, expire."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-entitlement-test"


@pytest.fixture(autouse=True)
def reset():
    import services.x402.resources as _res_mod
    from services.x402.commerce_store import reset_commerce_store
    reset_commerce_store()
    _res_mod._registry = None
    yield
    reset_commerce_store()
    _res_mod._registry = None


@pytest.fixture()
def svc():
    from services.x402.entitlements import EntitlementService
    return EntitlementService()


async def _make_settlement(tenant_id: str = TENANT):
    """Return a minimal Settlement object (matches Settlement model fields)."""
    from services.x402.commerce_models import Settlement, SettlementState
    return Settlement(
        tenant_id=tenant_id,
        receipt_id="rcpt-001",
        challenge_id="chg-001",
        facilitator_id="fac-001",
        amount_usd=1.0,
        tx_hash="0xabc123",
        chain="eip155:8453",
        state=SettlementState.SETTLED,
    )


async def _seed_resource(tenant_id: str = TENANT, resource_id: str = "res-001", ttl: int = 3600):
    """Register a protected resource in the commerce store."""
    from services.x402.commerce_store import get_commerce_store
    from services.x402.commerce_models import ProtectedResource, ResourceClass
    store = get_commerce_store()
    resource = ProtectedResource(
        tenant_id=tenant_id,
        resource_id=resource_id,
        name="Test Resource",
        resource_class=ResourceClass.API,
        path_pattern="/v1/test/*",
        price_usd=1.0,
        entitlement_ttl_seconds=ttl,
    )
    await store.put_resource(resource)
    return resource


@pytest.mark.asyncio
async def test_mint_creates_active_entitlement(svc):
    await _seed_resource()
    settlement = await _make_settlement()
    from services.x402.commerce_models import EntitlementStatus
    ent = await svc.mint(
        tenant_id=TENANT,
        holder_id="agent-001",
        holder_type="agent",
        resource_id="res-001",
        settlement=settlement,
    )
    assert ent.status == EntitlementStatus.ACTIVE
    assert ent.holder_id == "agent-001"
    assert ent.resource_id == "res-001"
    assert ent.expires_at is not None


@pytest.mark.asyncio
async def test_mint_unknown_resource_raises(svc):
    settlement = await _make_settlement()
    with pytest.raises(ValueError, match="Unknown resource"):
        await svc.mint(
            tenant_id=TENANT,
            holder_id="agent-001",
            holder_type="agent",
            resource_id="res-nonexistent",
            settlement=settlement,
        )


@pytest.mark.asyncio
async def test_lookup_returns_active_entitlement(svc):
    await _seed_resource()
    settlement = await _make_settlement()
    ent = await svc.mint(
        tenant_id=TENANT, holder_id="agent-001",
        holder_type="agent", resource_id="res-001", settlement=settlement,
    )
    found = await svc.lookup(TENANT, "agent-001", "res-001")
    assert found is not None
    assert found.entitlement_id == ent.entitlement_id


@pytest.mark.asyncio
async def test_lookup_returns_none_for_expired(svc):
    """Backdate expires_at directly then lookup() should return None."""
    from services.x402.commerce_store import get_commerce_store
    await _seed_resource(ttl=10)
    settlement = await _make_settlement()
    ent = await svc.mint(
        tenant_id=TENANT, holder_id="agent-002",
        holder_type="agent", resource_id="res-001", settlement=settlement,
    )
    # Manually set expires_at to the past so the entitlement is seen as expired
    store = get_commerce_store()
    past = datetime.now(timezone.utc) - timedelta(seconds=30)
    ent.expires_at = past.isoformat()
    await store.put_entitlement(ent)

    found = await svc.lookup(TENANT, "agent-002", "res-001")
    assert found is None


@pytest.mark.asyncio
async def test_reuse_increments_count(svc):
    await _seed_resource()
    settlement = await _make_settlement()
    ent = await svc.mint(
        tenant_id=TENANT, holder_id="agent-003",
        holder_type="agent", resource_id="res-001", settlement=settlement,
    )
    updated = await svc.reuse(TENANT, ent.entitlement_id)
    assert updated.reuse_count == 1
    updated2 = await svc.reuse(TENANT, ent.entitlement_id)
    assert updated2.reuse_count == 2


@pytest.mark.asyncio
async def test_reuse_expired_raises(svc):
    import services.x402.entitlements as mod
    # Seed resource with 1-second TTL
    await _seed_resource(ttl=1)
    settlement = await _make_settlement()
    # Mint with real clock — expires_at = now + 1s
    ent = await svc.mint(
        tenant_id=TENANT, holder_id="agent-004",
        holder_type="agent", resource_id="res-001", settlement=settlement,
    )
    # Patch _now to 60s in future so _is_expired() sees entitlement as past
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    with patch.object(mod, "_now", lambda: future):
        # _is_expired checks: _now() > datetime.fromisoformat(e.expires_at)
        assert svc._is_expired(ent)
        with pytest.raises(ValueError):
            await svc.reuse(TENANT, ent.entitlement_id)


@pytest.mark.asyncio
async def test_revoke_marks_entitlement_revoked(svc):
    await _seed_resource()
    settlement = await _make_settlement()
    ent = await svc.mint(
        tenant_id=TENANT, holder_id="agent-005",
        holder_type="agent", resource_id="res-001", settlement=settlement,
    )
    from services.x402.commerce_models import EntitlementStatus
    revoked = await svc.revoke(TENANT, ent.entitlement_id, "admin", "policy change")
    assert revoked.status == EntitlementStatus.REVOKED


@pytest.mark.asyncio
async def test_revoke_idempotent(svc):
    await _seed_resource()
    settlement = await _make_settlement()
    ent = await svc.mint(
        tenant_id=TENANT, holder_id="agent-006",
        holder_type="agent", resource_id="res-001", settlement=settlement,
    )
    await svc.revoke(TENANT, ent.entitlement_id, "admin", "first revoke")
    # Second revoke should not raise
    result = await svc.revoke(TENANT, ent.entitlement_id, "admin", "second revoke")
    from services.x402.commerce_models import EntitlementStatus
    assert result.status == EntitlementStatus.REVOKED
