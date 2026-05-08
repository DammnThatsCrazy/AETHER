"""Tests for /v1/admin/tenants/{tenant_id}/billing/subscription mutations."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def billing_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.admin.billing_subscription_routes")
        importlib.reload(mod)
        from shared.billing import stripe_repository
        stripe_repository._reset_in_memory_for_tests()
        yield mod


def make_request(tenant_id: str = "t-001", role: str = "admin"):
    """Build a request whose tenant_id matches the path tenant by default.

    Pass a different `tenant_id` (or set role!="admin") to simulate a
    cross-tenant call that should be rejected by `_enforce_tenant_scope`.
    """
    role_obj = SimpleNamespace(value=role)
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        role=role_obj,
        require_permission=lambda perm: None,
        has_permission=lambda perm: role == "admin",
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


async def seed_account(tenant_id: str = "t-001", **overrides):
    from shared.billing import stripe_repository
    await stripe_repository.upsert_billing_account(
        tenant_id=tenant_id,
        plan_tier=overrides.get("plan_tier", "P1"),
    )
    await stripe_repository.update_customer_mapping(
        tenant_id=tenant_id,
        stripe_customer_id=overrides.get("stripe_customer_id", "cus_test"),
        stripe_subscription_id=overrides.get("stripe_subscription_id", "sub_test"),
    )
    await stripe_repository.update_subscription_state(
        tenant_id=tenant_id,
        subscription_status=overrides.get("subscription_status", "active"),
    )


@pytest.mark.asyncio
async def test_get_subscription_returns_state(billing_routes):
    await seed_account()
    res = await billing_routes.get_subscription("t-001", make_request())
    assert res["data"]["tenant_id"] == "t-001"
    assert res["data"]["plan_tier"] == "P1"
    assert res["data"]["subscription_id"] == "sub_test"
    assert res["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_get_subscription_404(billing_routes):
    with pytest.raises(Exception) as exc:
        await billing_routes.get_subscription("ghost", make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_change_plan_to_valid_tier(billing_routes):
    await seed_account(plan_tier="P1")
    body = billing_routes.ChangePlanRequest(plan_tier="P2")
    res = await billing_routes.change_plan("t-001", body, make_request())
    assert res["data"]["plan_tier"] == "P2"


@pytest.mark.asyncio
async def test_change_plan_invalid_tier(billing_routes):
    await seed_account()
    body = billing_routes.ChangePlanRequest(plan_tier="bogus")
    with pytest.raises(Exception) as exc:
        await billing_routes.change_plan("t-001", body, make_request())
    assert "Invalid plan_tier" in str(exc.value)


@pytest.mark.asyncio
async def test_change_plan_unknown_tenant_404(billing_routes):
    body = billing_routes.ChangePlanRequest(plan_tier="P2")
    with pytest.raises(Exception) as exc:
        await billing_routes.change_plan("ghost", body, make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_cancel_at_period_end(billing_routes):
    await seed_account()
    body = billing_routes.CancelSubscriptionRequest(reason="voluntary", cancel_at_period_end=True)
    res = await billing_routes.cancel_subscription("t-001", body, make_request())
    assert res["data"]["status"] == "canceling"
    assert res["data"]["cancel_at_period_end"] is True

    state = await billing_routes.get_subscription("t-001", make_request())
    assert state["data"]["status"] == "canceling"


@pytest.mark.asyncio
async def test_cancel_immediate(billing_routes):
    await seed_account()
    body = billing_routes.CancelSubscriptionRequest(reason="non_payment", cancel_at_period_end=False)
    res = await billing_routes.cancel_subscription("t-001", body, make_request())
    assert res["data"]["status"] == "canceled"


@pytest.mark.asyncio
async def test_cancel_invalid_reason(billing_routes):
    await seed_account()
    body = billing_routes.CancelSubscriptionRequest(reason="bogus")
    with pytest.raises(Exception) as exc:
        await billing_routes.cancel_subscription("t-001", body, make_request())
    assert "Invalid reason" in str(exc.value)


@pytest.mark.asyncio
async def test_reactivate_canceling_subscription(billing_routes):
    await seed_account(subscription_status="canceling")
    body = billing_routes.ReactivateSubscriptionRequest(note="user requested")
    res = await billing_routes.reactivate_subscription("t-001", body, make_request())
    assert res["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_reactivate_active_subscription_is_noop(billing_routes):
    await seed_account(subscription_status="active")
    body = billing_routes.ReactivateSubscriptionRequest()
    res = await billing_routes.reactivate_subscription("t-001", body, make_request())
    assert res["data"]["noop"] is True
    assert res["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_get_subscription_rejects_cross_tenant_call(billing_routes):
    """Non-admin caller from t-002 cannot read t-001's subscription."""
    await seed_account(tenant_id="t-001")
    cross_tenant_req = make_request(tenant_id="t-002", role="member")
    with pytest.raises(Exception) as exc:
        await billing_routes.get_subscription("t-001", cross_tenant_req)
    assert "denied" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_change_plan_rejects_cross_tenant_call(billing_routes):
    await seed_account(tenant_id="t-001")
    cross_tenant_req = make_request(tenant_id="t-002", role="member")
    body = billing_routes.ChangePlanRequest(plan_tier="P2")
    with pytest.raises(Exception) as exc:
        await billing_routes.change_plan("t-001", body, cross_tenant_req)
    assert "denied" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_cancel_rejects_cross_tenant_call(billing_routes):
    await seed_account(tenant_id="t-001")
    cross_tenant_req = make_request(tenant_id="t-002", role="member")
    body = billing_routes.CancelSubscriptionRequest()
    with pytest.raises(Exception) as exc:
        await billing_routes.cancel_subscription("t-001", body, cross_tenant_req)
    assert "denied" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_admin_role_may_act_cross_tenant(billing_routes):
    """Callers with admin role bypass tenant scoping (matches existing helper)."""
    await seed_account(tenant_id="t-001")
    admin_req = make_request(tenant_id="t-admin", role="admin")
    res = await billing_routes.get_subscription("t-001", admin_req)
    assert res["data"]["tenant_id"] == "t-001"
