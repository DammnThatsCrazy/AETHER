"""POST /v1/profile/resolve: identifier in the body, same authority as GET."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

os.environ.setdefault("AETHER_ENV", "local")

import identity.profile.routes as routes  # noqa: E402
from shared.common.common import NotFoundError  # noqa: E402


class _Tenant:
    tenant_id = "tenant-r"

    def __init__(self):
        self.checked = []

    def require_permission(self, permission):
        self.checked.append(permission)


class _Resolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _request():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.fixture(autouse=True)
def _no_metering(monkeypatch):
    async def _meter(*_a, **_k):
        return None

    monkeypatch.setattr(routes, "meter_family_usage", _meter)


@pytest.mark.parametrize("payload", [{}, {"email": "a@b.c", "wallet": "0xabc"}, {"phone": "1"}])
def test_body_requires_exactly_one_known_identifier(payload):
    with pytest.raises(ValidationError):
        routes.ResolveIdentifierBody(**payload)


@pytest.mark.asyncio
async def test_resolves_with_read_permission_for_authenticated_tenant():
    request = _request()
    resolver = _Resolver("ent-1")
    body = routes.ResolveIdentifierBody(email="person@example.com")
    result = await routes.resolve_identifier_body(body, request, resolver=resolver)
    assert result["data"] == {"resolved_user_id": "ent-1"}
    assert request.state.tenant.checked == ["read"]
    assert resolver.calls[0]["tenant_id"] == "tenant-r"
    assert resolver.calls[0]["email"] == "person@example.com"
    assert resolver.calls[0]["wallet_address"] is None


@pytest.mark.asyncio
async def test_unresolvable_identifier_is_404():
    with pytest.raises(NotFoundError):
        await routes.resolve_identifier_body(
            routes.ResolveIdentifierBody(customer="c-404"), _request(), resolver=_Resolver(None),
        )
