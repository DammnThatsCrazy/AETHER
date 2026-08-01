"""Customer-session lifecycle and authoritative authorization tests."""
from __future__ import annotations

import pytest

from middleware.middleware import _resolve_session_token
from repositories.repos import AdminRepository, UserRepository, reset_in_memory_stores
from services.auth.sessions.service import SessionService
from shared.auth.auth import PlanTier, Role


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()


async def _principal(*, plan: str = "P2", role: str = "admin", permissions=None):
    await AdminRepository().insert("tenant-a", {
        "status": "active", "plan_tier": plan, "name": "Acme"
    })
    await UserRepository().insert("user-a", {
        "tenant_id": "tenant-a",
        "status": "active",
        "membership_status": "active",
        "role": role,
        "permissions": permissions or ["read", "write", "billing"],
    })


@pytest.mark.asyncio
async def test_session_context_rehydrates_mutable_plan_role_and_permissions():
    await _principal()
    service = SessionService()
    issued = await service.create_session("tenant-a", "user-a")

    context = await _resolve_session_token(issued.token)
    assert context is not None
    assert context.plan_tier is PlanTier.P2_PROFESSIONAL
    assert context.role is Role.ADMIN
    assert context.permissions == ["read", "write", "billing"]

    await AdminRepository().update("tenant-a", {"plan_tier": "P1"})
    await UserRepository().update("user-a", {
        "role": "viewer", "permissions": ["read"]
    })
    changed = await _resolve_session_token(issued.token)
    assert changed is not None
    assert changed.plan_tier is PlanTier.P1_HOBBYIST
    assert changed.role is Role.VIEWER
    assert changed.permissions == ["read"]


@pytest.mark.asyncio
async def test_session_authority_fails_closed_without_plan_or_principal():
    service = SessionService()
    issued = await service.create_session("tenant-missing", "user-missing")
    assert await _resolve_session_token(issued.token) is None


@pytest.mark.asyncio
async def test_session_listing_redacts_hash_and_revocation_is_tenant_scoped():
    service = SessionService()
    first = await service.create_session("tenant-a", "user-a")
    second = await service.create_session("tenant-a", "user-a")
    foreign = await service.create_session("tenant-b", "user-b")

    sessions, total = await service.list_for_tenant("tenant-a", limit=1)
    assert total == 2
    assert len(sessions) == 1
    assert "token_hash" not in sessions[0]
    assert not await service.revoke_for_tenant("tenant-a", foreign.session_id)

    assert await service.revoke_for_tenant("tenant-a", first.session_id)
    assert await service.revoke_other_sessions("tenant-a", first.session_id) == 1
    listed, _ = await service.list_for_tenant("tenant-a")
    assert {record["status"] for record in listed} == {"revoked"}
    assert (await service.list_for_tenant("tenant-b"))[1] == 1
