"""
Unit tests for commerce components.
"""

from __future__ import annotations

import logging
import pytest

logging.disable(logging.CRITICAL)


@pytest.fixture(autouse=True)
def _reset():
    from services.x402 import (
        commerce_store as cs,
        idempotency as idem,
        control_plane as cp,
        resources as res,
        facilitators as fac,
        approvals as apv,
        verification as ver,
        settlement as stl,
        entitlements as ent,
        policies as pol,
    )
    cs.reset_commerce_store()
    idem.reset_idempotency_store()
    cp.reset_control_plane()
    res._registry = None
    fac._facilitator_registry = None
    fac._asset_registry = None
    apv._service = None
    ver._engine = None
    stl._tracker = None
    ent._service = None
    pol._engine = None
    yield


# ─── Idempotency store ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotency_record_and_lookup():
    from services.x402.idempotency import IdempotencyStore

    store = IdempotencyStore(ttl_seconds=60)
    await store.record("t1", "pay_123", {"ok": True})
    assert await store.lookup("t1", "pay_123") == {"ok": True}
    assert await store.lookup("t1", "pay_456") is None
    assert await store.lookup("t2", "pay_123") is None  # tenant isolation


@pytest.mark.asyncio
async def test_idempotency_ttl_expiry():
    from services.x402.idempotency import IdempotencyStore

    store = IdempotencyStore(ttl_seconds=-1)  # already expired
    await store.record("t1", "pay_123", {"ok": True})
    assert await store.lookup("t1", "pay_123") is None


# ─── Pricing engine ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pricing_tenant_overrides():
    from services.x402.resources import seed_aether_native_resources
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.pricing import PricingEngine

    resources = await seed_aether_native_resources("t_price")
    await seed_facilitators_and_assets("t_price")
    r = resources[0]

    engine = PricingEngine()
    base = await engine.resolve_price("t_price", r.resource_id)
    pro = await engine.resolve_price("t_price", r.resource_id, plan_code="pro")
    enterprise = await engine.resolve_price("t_price", r.resource_id, plan_code="enterprise")

    assert base["total_usd"] == r.price_usd
    assert pro["total_usd"] < base["total_usd"]
    assert enterprise["total_usd"] < pro["total_usd"]


# ─── Facilitator selection ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_facilitator_selection():
    from services.x402.facilitators import (
        get_facilitator_registry,
        seed_facilitators_and_assets,
    )

    await seed_facilitators_and_assets("t_fac")
    registry = get_facilitator_registry()

    fac = await registry.select_for("t_fac", "USDC", "eip155:8453")
    assert fac is not None
    assert "USDC" in fac.supported_assets
    assert "eip155:8453" in fac.supported_chains

    # Unknown asset
    fac2 = await registry.select_for("t_fac", "DOGE", "eip155:8453")
    assert fac2 is None


# ─── Approval service ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_cannot_decide_after_finalized():
    from services.x402.approvals import get_approval_service
    from services.x402.commerce_models import ApprovalPriority

    service = get_approval_service()
    a = await service.request(
        tenant_id="t_dup",
        challenge_id="chg_x",
        resource_id="res_x",
        requester_id="agent_x",
        requester_type="agent",
        amount_usd=1.0,
        asset_symbol="USDC",
        chain="eip155:8453",
        priority=ApprovalPriority.NORMAL,
    )
    await service.decide("t_dup", a.approval_id, "approve", "user_1", "ok")
    with pytest.raises(ValueError):
        await service.decide("t_dup", a.approval_id, "reject", "user_2", "too late")


@pytest.mark.asyncio
async def test_approval_queue_sorted_by_priority():
    from services.x402.approvals import get_approval_service
    from services.x402.commerce_models import ApprovalPriority

    service = get_approval_service()
    for pr in [ApprovalPriority.LOW, ApprovalPriority.CRITICAL, ApprovalPriority.NORMAL]:
        await service.request(
            tenant_id="t_sort",
            challenge_id=f"chg_{pr.value}",
            resource_id="res_x",
            requester_id="a",
            requester_type="agent",
            amount_usd=1.0,
            asset_symbol="USDC",
            chain="eip155:8453",
            priority=pr,
        )
    queue = await service.list_queue("t_sort")
    assert queue[0].priority == ApprovalPriority.CRITICAL
    assert queue[-1].priority == ApprovalPriority.LOW


# ─── Policy engine ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_policy_approval_required_all_day1_default():
    from services.x402.policies import get_policy_engine
    from services.x402.resources import seed_aether_native_resources
    from services.x402.facilitators import seed_facilitators_and_assets

    resources = await seed_aether_native_resources("t_pol")
    await seed_facilitators_and_assets("t_pol")
    engine = get_policy_engine()

    decision = await engine.evaluate(
        tenant_id="t_pol",
        challenge_id="chg_y",
        resource=resources[0],
        requester_id="agent_1",
        amount_usd=resources[0].price_usd,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    assert decision.requires_approval is True
    assert "mandatory_approval_all_spend_classes" in decision.active_rules


# ─── Entitlement expiry ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_entitlement_auto_expires():
    from datetime import datetime, timezone
    from services.x402.entitlements import get_entitlement_service
    from services.x402.commerce_models import Entitlement, Settlement, SettlementState
    from services.x402.commerce_store import get_commerce_store
    from services.x402.resources import seed_aether_native_resources
    from services.x402.facilitators import seed_facilitators_and_assets

    resources = await seed_aether_native_resources("t_exp")
    await seed_facilitators_and_assets("t_exp")
    store = get_commerce_store()
    service = get_entitlement_service()

    # Craft an entitlement that's already expired
    expired_iso = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    e = Entitlement(
        tenant_id="t_exp",
        holder_id="agent_1",
        resource_id=resources[0].resource_id,
        settlement_id="dummy",
        expires_at=expired_iso,
    )
    await store.put_entitlement(e)

    result = await service.lookup("t_exp", "agent_1", resources[0].resource_id)
    assert result is None  # expired entitlement returns None


# ─── Protected resource registry ──────────────────────────────────────

@pytest.mark.asyncio
async def test_resource_find_by_path():
    from services.x402.resources import seed_aether_native_resources, get_resource_registry

    await seed_aether_native_resources("t_find")
    registry = get_resource_registry()

    r = await registry.find_by_path("t_find", "/v1/ml/predict")
    assert r is not None
    assert r.path_pattern == "/v1/ml/predict"


@pytest.mark.asyncio
async def test_resource_registry_rejects_negative_price():
    from services.x402.resources import get_resource_registry, ProtectedResource, ResourceClass

    registry = get_resource_registry()
    bad = ProtectedResource(
        tenant_id="t_bad",
        name="Bad Resource",
        resource_class=ResourceClass.API,
        path_pattern="/v1/bad",
        owner_service="x",
        description="",
        price_usd=-1.0,
    )
    with pytest.raises(ValueError):
        await registry.register(bad)
