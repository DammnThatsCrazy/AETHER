"""Fixtures for the tenant Command Center test suite.

Isolation contract
------------------
``repositories.repos.reset_in_memory_stores`` clears every table-backed
in-memory store the composed sections read from (recommendations,
outcome_observations, campaigns, sdk_health, connectors, tenant_activations,
…). The autouse fixture resets it before and after each test so no seeded row
bleeds across cases — the same guarantee the aggregator itself relies on when it
degrades an empty tenant to ``no_data`` rather than a fabricated value.
"""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from shared.common.common import ForbiddenError
from services.command_center.service import CommandCenterService


class _Tenant:
    """Stand-in for the auth-middleware tenant on ``request.state.tenant``.

    The Command Center route reads the tenant from ``request.state.tenant`` and
    calls ``require_permission(Permissions.READ)`` (``"read"``). The tenant id is
    always taken from here — never a body — which is what tenant isolation relies
    on. ``require_permission`` raises a real ``ForbiddenError`` (an ``AetherError``)
    on a missing permission so the mounted app can map it to a 403.
    """

    def __init__(self, tenant_id: str, permissions=None) -> None:
        self.tenant_id = tenant_id
        self.permissions = set(
            permissions if permissions is not None else {"read", "write", "admin"}
        )

    def require_permission(self, permission) -> None:
        if permission not in self.permissions:
            raise ForbiddenError(f"Missing permission: {permission}")


@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset every in-memory store before and after each test."""
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture
def svc() -> CommandCenterService:
    return CommandCenterService()
