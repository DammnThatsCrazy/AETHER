"""Route-level tests for the capability catalog (PR 2, Phase A).

Handlers are called directly with a fake ``Request`` (the established pattern — see
``tests/unit/product_catalog/test_routes.py``) so the tenant gate and fail-closed reads are
exercised without standing up the middleware. The Kyber operator gate is tested against
``require_kyber_operator`` directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.settings import get_settings
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError, NotFoundError

import services.agent_access_intelligence.routes as aai_routes
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.security.request_context import require_kyber_operator

OPERATOR_PERM = get_settings().security_governance.kyber_operator_permission


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read"],
    )
    # `.client`/`.headers` are needed when the operator gate builds an ActorContext.
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


async def _seed(tenant_id: str, source_event_id: str = "e1"):
    return await capability_catalog_service.record_from_fact(
        {
            "tenant_id": tenant_id,
            "source_event_id": source_event_id,
            "event_name": "agent_tool_invocation_observed",
            "occurred_at": "2026-07-24T00:00:00Z",
            "agent_id": "agentA",
            "tool_name": "search",
            "server_name": "srvX",
            "provider": "acme",
        }
    )


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def test_list_returns_tenant_inventory():
    await _seed("t1")
    resp = await aai_routes.list_capabilities(_request("t1"), provider=None, server_name=None, tool_name=None, limit=100, offset=0)
    assert resp["data"]["count"] == 1
    assert resp["data"]["items"][0]["tool_name"] == "search"


async def test_get_capability_fail_closed_cross_tenant():
    seeded = await _seed("t1")
    cap_id = seeded["capability_id"]
    # correct tenant resolves
    ok = await aai_routes.get_capability(cap_id, _request("t1"))
    assert ok["data"]["capability_id"] == cap_id
    # foreign tenant is denied (fail-closed)
    with pytest.raises(NotFoundError):
        await aai_routes.get_capability(cap_id, _request("t2"))


async def test_read_requires_read_permission():
    await _seed("t1")
    with pytest.raises(ForbiddenError):
        await aai_routes.list_capabilities(_request("t1", permissions=[]), provider=None, server_name=None, tool_name=None, limit=100, offset=0)


async def test_installations_list_and_detail():
    await _seed("t1")
    resp = await aai_routes.list_installations(_request("t1"), agent_id=None, provider=None, limit=100, offset=0)
    assert resp["data"]["count"] == 1
    inst_id = resp["data"]["items"][0]["installation_id"]
    detail = await aai_routes.get_installation(inst_id, _request("t1"))
    assert detail["data"]["agent_id"] == "agentA"
    with pytest.raises(NotFoundError):
        await aai_routes.get_installation(inst_id, _request("t2"))


async def test_kyber_gate_rejects_normal_tenant_even_admin():
    # Role-admin permission must NOT pass the operator-only gate (raw-permission check).
    with pytest.raises(ForbiddenError):
        require_kyber_operator(_request("t1", permissions=["admin", "read", "write"]))


async def test_kyber_gate_allows_operator_and_handler_aggregates():
    actor = require_kyber_operator(_request("op-tenant", permissions=[OPERATOR_PERM]))
    assert actor is not None
    # seed two tenants; operator health aggregates across them
    await _seed("t1", "a")
    await _seed("t2", "b")
    resp = await aai_routes.catalog_health(_request("op-tenant", permissions=[OPERATOR_PERM]))
    assert resp["data"]["total_capabilities"] == 2
    assert resp["data"]["tenant_count"] == 2
