"""Legacy resolution graph routes stay unavailable until tenant-safe."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.resolution import routes


class _Tenant:
    tenant_id = "tenant-a"

    def __init__(self) -> None:
        self.permissions: list[str] = []

    def require_permission(self, permission: str) -> None:
        self.permissions.append(permission)


def _request(tenant: _Tenant) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.mark.asyncio
async def test_cluster_route_fails_closed_before_profile_or_graph_reads() -> None:
    with pytest.raises(HTTPException) as exc:
        await routes.get_cluster("user-1", _request(_Tenant()))

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_batch_route_preserves_write_auth_then_fails_closed() -> None:
    tenant = _Tenant()

    with pytest.raises(HTTPException) as exc:
        await routes.trigger_batch_job(_request(tenant))

    assert tenant.permissions == ["write"]
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_approval_route_preserves_write_auth_without_mutating_decision() -> None:
    tenant = _Tenant()

    with pytest.raises(HTTPException) as exc:
        await routes.approve_resolution("decision-1", _request(tenant))

    assert tenant.permissions == ["write"]
    assert exc.value.status_code == 503
