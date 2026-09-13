"""Authenticated /v1/me contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from repositories.repos import reset_in_memory_stores
from services.me.routes import get_my_profile
from shared.auth.auth import TenantContext


class FakeRequest:
    def __init__(self, tenant: TenantContext) -> None:
        self.state = SimpleNamespace(tenant=tenant)


@pytest.fixture(autouse=True)
def isolated_memory() -> None:
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_profile_graph_scope_is_server_owned_and_ignores_spoofed_authority(monkeypatch):
    """URL/client/deployment-shaped values never influence graph authority."""
    monkeypatch.setenv("AETHER_ENV", "staging")
    tenant = TenantContext(tenant_id="tenant-authenticated")
    # A compromised or legacy context must not be able to supply graph scope.
    tenant.graph_scope = {  # type: ignore[attr-defined]
        "tenant_id": "tenant-spoofed",
        "workspace_id": "workspace-spoofed",
        "environment_id": "staging",
    }
    request = FakeRequest(tenant)

    admin_repo = SimpleNamespace(find_by_id=AsyncMock(return_value={}))
    monkeypatch.setattr("repositories.repos.AdminRepository", lambda: admin_repo)
    monkeypatch.setattr("repositories.repos.get_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "shared.billing.stripe_repository.get_billing_account",
        AsyncMock(return_value=None),
    )

    response = await get_my_profile(request)

    assert response["data"]["graph_scope"] == {
        "tenant_id": "tenant-authenticated",
        "workspace_id": "tenant-authenticated",
        "environment_id": "production",
        "scope_model": "single_workspace_tenant_v1",
    }
