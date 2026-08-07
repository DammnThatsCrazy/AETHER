"""Mobile-gateway route handlers over the in-memory installation repository."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.installation_repo import reset_installation_memory
from shared.common.common import NotFoundError
from services.mobile import routes as mobile_routes
from services.mobile.routes import RegistrationRequest, SubscriptionRequest


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    reset_installation_memory()
    monkeypatch.setattr(mobile_routes, "_require_enabled", lambda: None)
    yield
    reset_installation_memory()


def _reg(**over):
    base = dict(platform="ios", bundle_id="com.aether.app", environment="production")
    base.update(over)
    return RegistrationRequest(**base)


def test_register_forces_aether_and_mints_id():
    data = _run(mobile_routes.register_installation(_req(), _reg(device_name="iPhone"))).data
    assert data["installation"]["app_kind"] == "aether"
    assert data["installation"]["id"].startswith("inst_")
    assert data["subscription"] is None


def test_register_with_push_creates_subscription():
    data = _run(mobile_routes.register_installation(
        _req(), _reg(installation_id="dev-1", push_token="raw-token", push_provider="apns")
    )).data
    assert data["subscription"] is not None
    # Only the hash is stored, never the raw token.
    assert data["subscription"]["token_hash"] != "raw-token"
    assert data["subscription"]["provider"] == "apns"


def test_list_and_get():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    listed = _run(mobile_routes.list_installations(_req())).data
    assert any(i["id"] == "dev-1" for i in listed["installations"])
    got = _run(mobile_routes.get_installation(_req(), installation_id="dev-1")).data
    assert got["id"] == "dev-1"


def test_get_absent_404():
    with pytest.raises(NotFoundError):
        _run(mobile_routes.get_installation(_req(), installation_id="nope"))


def test_revoke():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    out = _run(mobile_routes.revoke_installation(_req(), installation_id="dev-1")).data
    assert out["trust_state"] == "revoked"
    with pytest.raises(NotFoundError):
        _run(mobile_routes.revoke_installation(_req(), installation_id="dev-1-missing"))


def test_add_subscription_requires_installation():
    with pytest.raises(NotFoundError):
        _run(mobile_routes.add_subscription(
            _req(),
            SubscriptionRequest(platform="ios", provider="apns", push_token="t", environment="production"),
            installation_id="nope",
        ))


def test_add_subscription_ok():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    sub = _run(mobile_routes.add_subscription(
        _req(),
        SubscriptionRequest(platform="ios", provider="fcm", push_token="tok", environment="production"),
        installation_id="dev-1",
    )).data
    assert sub["provider"] == "fcm"


# ── Intra-tenant ownership isolation (A2 IDOR remediation) ────────────────────
#
# A second tenant user must never read / revoke / configure / subscribe a device
# registered by another principal. Absent and foreign installations read
# identically as 404 — no existence leak, no 403 (which would reveal the row).

class _OtherTenant(_Tenant):
    user_id = "user-2"


def _other_req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_OtherTenant()))


def test_foreign_principal_get_installation_404():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    with pytest.raises(NotFoundError):
        _run(mobile_routes.get_installation(_other_req(), installation_id="dev-1"))
    # The owner can still read it — the probe never touched the row.
    got = _run(mobile_routes.get_installation(_req(), installation_id="dev-1")).data
    assert got["id"] == "dev-1"


def test_foreign_principal_revoke_404():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    with pytest.raises(NotFoundError):
        _run(mobile_routes.revoke_installation(_other_req(), installation_id="dev-1"))
    # Owner's installation survives the foreign revoke attempt, still active.
    got = _run(mobile_routes.get_installation(_req(), installation_id="dev-1")).data
    assert got["trust_state"] != "revoked"


def test_foreign_principal_get_config_404():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    with pytest.raises(NotFoundError):
        _run(mobile_routes.get_mobile_config(_other_req(), installation_id="dev-1"))
    # The owner still gets a typed config.
    cfg = _run(mobile_routes.get_mobile_config(_req(), installation_id="dev-1")).data
    assert cfg["app_kind"] == "aether"


def test_foreign_principal_add_subscription_404():
    _run(mobile_routes.register_installation(_req(), _reg(installation_id="dev-1")))
    with pytest.raises(NotFoundError):
        _run(mobile_routes.add_subscription(
            _other_req(),
            SubscriptionRequest(platform="ios", provider="apns", push_token="foreign-token", environment="production"),
            installation_id="dev-1",
        ))
