"""HTTP-layer tests for the slot-aware credential-admin API.

The durable CredentialAuthority is well tested at the service layer; its HTTP
surface (`services/providers/credentials/routes.py`) was not. These cover the
route logic the authority tests can't: tenant-admin permission enforcement,
unknown-provider 404, SlotError→400 translation, provider enablement gating, and
the write-only-secret guarantee — plus a full create→test→activate→rotate→
revoke→delete lifecycle through the handlers.

All in-memory (AETHER_ENV=local → local cipher); no network.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.providers.credentials import routes as cred_routes  # noqa: E402
from services.providers.credentials.models import (  # noqa: E402
    SlotActivateRequest,
    SlotRotateRequest,
    SlotValueWrite,
)
from shared.common.common import ForbiddenError  # noqa: E402

pytestmark = pytest.mark.asyncio

_ENV = "sandbox"
_SLOT = "webhook_signing_secret"


class _Tenant:
    def __init__(self, tenant_id: str, permissions: set[str]):
        self.tenant_id = tenant_id
        self.principal_id = f"admin-{tenant_id}"
        self._perms = permissions

    def require_permission(self, permission: str) -> None:
        if permission not in self._perms:
            raise ForbiddenError(f"missing permission: {permission}")


class _Request:
    def __init__(self, tenant_id: str, *, admin: bool = True):
        perms = {"read", "write", "admin"} if admin else {"read"}
        self.state = SimpleNamespace(tenant=_Tenant(tenant_id, perms), request_id="req-1")


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _data(result) -> dict:
    """Unwrap a successful api_response envelope."""
    assert isinstance(result, dict) and "data" in result, result
    return result["data"]


# ── permission + provider guards ──────────────────────────────────────────────

async def test_non_admin_is_forbidden():
    reset_in_memory_stores()
    res = await cred_routes.list_connections(_Request(_tenant(), admin=False))
    assert getattr(res, "status_code", None) == ForbiddenError().code.value  # 403 JSONResponse


async def test_unknown_provider_404():
    reset_in_memory_stores()
    res = await cred_routes.provider_preflight("paypal", _Request(_tenant()))
    assert getattr(res, "status_code", None) == 404


async def test_wrong_slot_400():
    reset_in_memory_stores()
    res = await cred_routes.create_or_replace_slot(
        "coinbase", "not_a_real_slot", SlotValueWrite(value="x"), _Request(_tenant())
    )
    assert getattr(res, "status_code", None) == 400


# ── full lifecycle through the handlers ────────────────────────────────────────

async def test_slot_lifecycle_create_test_activate_rotate_revoke_delete():
    reset_in_memory_stores()
    tenant = _tenant()
    req = _Request(tenant)

    created = _data(await cred_routes.create_or_replace_slot(
        "coinbase", _SLOT, SlotValueWrite(value="whsec_1"), req))
    assert created["state"] == "pending"
    assert "whsec_1" not in str(created)  # write-only: no secret echoed

    tested = _data(await cred_routes.test_slot("coinbase", _SLOT, req))
    assert tested["last_test_result"] == "valid"

    activated = _data(await cred_routes.activate_slot(
        "coinbase", _SLOT, SlotActivateRequest(credential_version=1), req))
    assert activated["state"] == "active"

    # connections now reports the slot configured, still no secret value
    conns = _data(await cred_routes.list_connections(req))
    coinbase = next(c for c in conns if c["provider"] == "coinbase")
    whsec = next(s for s in coinbase["slots"] if s["slot_name"] == _SLOT)
    assert whsec["configured"] is True
    assert "whsec_1" not in str(conns)

    rotated = _data(await cred_routes.rotate_slot(
        "coinbase", _SLOT, SlotRotateRequest(value="whsec_2", expected_active_version=1), req))
    assert rotated["state"] == "active"

    revoked = _data(await cred_routes.revoke_slot("coinbase", _SLOT, req))
    assert revoked  # revoke returns a summary

    deleted = _data(await cred_routes.delete_slot("coinbase", _SLOT, req))
    assert deleted


async def test_enable_gated_on_all_required_slots():
    reset_in_memory_stores()
    tenant = _tenant()
    req = _Request(tenant)
    # Only the webhook slot present → enable must fail (coinbase also needs onramp_api_key).
    await cred_routes.create_or_replace_slot("coinbase", _SLOT, SlotValueWrite(value="w"), req)
    await cred_routes.activate_slot("coinbase", _SLOT, SlotActivateRequest(credential_version=1), req)
    res = await cred_routes.enable_provider("coinbase", req)
    assert getattr(res, "status_code", None) in (400, 409)  # missing required slot → conflict

    # Provision the polling slot too → enable succeeds.
    await cred_routes.create_or_replace_slot("coinbase", "onramp_api_key", SlotValueWrite(value="k"), req)
    await cred_routes.activate_slot("coinbase", "onramp_api_key", SlotActivateRequest(credential_version=1), req)
    enabled = _data(await cred_routes.enable_provider("coinbase", req))
    assert enabled["enabled"] is True
    disabled = _data(await cred_routes.disable_provider("coinbase", req))
    assert disabled["enabled"] is False


async def test_cross_tenant_isolation_via_routes():
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    await cred_routes.create_or_replace_slot(
        "coinbase", _SLOT, SlotValueWrite(value="secretA"), _Request(a))
    await cred_routes.activate_slot(
        "coinbase", _SLOT, SlotActivateRequest(credential_version=1), _Request(a))
    # tenant B sees no configured coinbase slot
    conns_b = _data(await cred_routes.list_connections(_Request(b)))
    coinbase_b = next(c for c in conns_b if c["provider"] == "coinbase")
    whsec_b = next(s for s in coinbase_b["slots"] if s["slot_name"] == _SLOT)
    assert whsec_b["configured"] is False
