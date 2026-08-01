"""Focused account organization tests using only in-process test doubles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.account_organization.models import (
    InvitationCreateRequest,
    MemberRoleUpdate,
    OrganizationProfileUpdate,
    OrganizationRole,
)
from services.account_organization.repository import OrganizationRepository
from services.account_organization.routes import (
    change_organization_member_role,
    create_organization_invitation,
    get_organization_profile,
    list_organization_invitations,
    list_organization_members,
    remove_organization_member,
    revoke_organization_invitation,
    update_organization_profile,
)
from shared.auth.auth import Role, TenantContext
from shared.common.common import ConflictError, ForbiddenError


class FakeRequest:
    def __init__(self, tenant: TenantContext) -> None:
        self.state = SimpleNamespace(tenant=tenant)


@pytest.fixture(autouse=True)
def isolated_memory(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    reset_in_memory_stores()


@pytest.fixture
async def organization():
    repo = OrganizationRepository()
    profile = await repo.create_profile(
        "tenant-a",
        owner_user_id="owner-a",
        name="Acme",
        slug="acme",
    )
    await repo.add_member(
        "tenant-a", user_id="owner-a", role="owner", email="owner@example.com"
    )
    return repo, profile


def request_for(user_id: str | None, role: str = "viewer", tenant_id: str = "tenant-a") -> FakeRequest:
    return FakeRequest(
        TenantContext(
            tenant_id=tenant_id,
            user_id=user_id,
            role=Role.VIEWER,
            permissions=["read"],
            organization_id=None,
        )
        if role == "viewer"
        else TenantContext(
            tenant_id=tenant_id,
            user_id=user_id,
            role=Role.ADMIN if role == "admin" else Role.VIEWER,
            permissions=["read", "write", "admin"],
            organization_id=None,
        )
    )


@pytest.mark.asyncio
async def test_repository_is_durable_and_tenant_scoped():
    repo = OrganizationRepository()
    first = await repo.create_profile("tenant-a", owner_user_id="owner-a", name="A")
    second = await repo.create_profile("tenant-b", owner_user_id="owner-b", name="B")
    await repo.add_member("tenant-a", user_id="a-user", role="member")
    await repo.add_member("tenant-b", user_id="b-user", role="member")

    assert (await repo.get_profile("tenant-a"))["id"] == first["id"]
    assert (await repo.get_profile("tenant-b"))["id"] == second["id"]
    assert {row["user_id"] for row in await repo.list_members("tenant-a", limit=50, offset=0)} == {"a-user"}
    with pytest.raises(ConflictError):
        await repo.create_profile("tenant-a", owner_user_id="other", name="duplicate")


@pytest.mark.asyncio
async def test_member_listing_is_paginated_and_does_not_cross_tenants(organization):
    repo, _ = organization
    for index in range(4):
        await repo.add_member("tenant-a", user_id=f"user-{index}", role="member")
    await repo.create_profile("tenant-b", owner_user_id="owner-b", name="Other")
    await repo.add_member("tenant-b", user_id="other-user", role="member")

    response = await list_organization_members(request_for("owner-a"), limit=2, offset=1)
    assert len(response["data"]) == 2
    assert response["pagination"] == {
        "total": 5,
        "limit": 2,
        "offset": 1,
        "has_more": True,
    }
    assert all(item["tenant_id"] == "tenant-a" for item in response["data"])


@pytest.mark.asyncio
async def test_permissions_are_role_specific(organization):
    repo, _ = organization
    member = await repo.add_member("tenant-a", user_id="member-a", role="member")
    viewer = await repo.add_member("tenant-a", user_id="viewer-a", role="viewer")

    assert (await get_organization_profile(request_for("viewer-a")))["data"]["name"] == "Acme"
    assert (await list_organization_members(request_for("member-a"), limit=10, offset=0))["pagination"]["total"] == 3

    with pytest.raises(ForbiddenError):
        await update_organization_profile(
            request_for("member-a"), OrganizationProfileUpdate(name="Nope")
        )
    with pytest.raises(ForbiddenError):
        await create_organization_invitation(
            request_for("viewer-a"), InvitationCreateRequest(email="new@example.com")
        )

    admin = await repo.add_member("tenant-a", user_id="admin-a", role="admin")
    updated = await update_organization_profile(
        request_for("admin-a"), OrganizationProfileUpdate(description="Updated")
    )
    assert updated["data"]["description"] == "Updated"
    assert member["role"] == "member" and viewer["role"] == "viewer"


@pytest.mark.asyncio
async def test_invitation_lifecycle_redacts_secret_and_expires(organization):
    repo, _ = organization
    created = await create_organization_invitation(
        request_for("owner-a"),
        InvitationCreateRequest(email="Invitee@Example.com", role=OrganizationRole.MEMBER),
    )
    invitation = created["data"]
    assert invitation["email"] == "invitee@example.com"
    assert len(invitation["token"]) > 20
    assert "token_hash" not in invitation

    with pytest.raises(ConflictError):
        await create_organization_invitation(
            request_for("owner-a"), InvitationCreateRequest(email="invitee@example.com")
        )

    listed = await list_organization_invitations(request_for("owner-a"))
    assert "token" not in listed["data"][0]
    assert "token_hash" not in listed["data"][0]
    revoked = await revoke_organization_invitation(request_for("owner-a"), invitation["invitation_id"])
    assert revoked["data"]["status"] == "revoked"

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    expired = await repo.create_invitation(
        "tenant-a",
        {
            "email": "expired@example.com",
            "role": "member",
            "status": "pending",
            "invited_by": "owner-a",
            "expires_at": past,
            "token_hash": "digest-only",
        },
    )
    listed = await list_organization_invitations(request_for("owner-a"))
    expired_row = next(row for row in listed["data"] if row["invitation_id"] == expired["invitation_id"])
    assert expired_row["status"] == "expired"


@pytest.mark.asyncio
async def test_owner_transfer_and_removal_safeguards(organization):
    repo, _ = organization
    target = await repo.add_member("tenant-a", user_id="target-a", role="member")
    owner = await repo.get_active_member_by_user("tenant-a", "owner-a")

    with pytest.raises(ConflictError):
        await change_organization_member_role(
            request_for("owner-a"), owner["id"], MemberRoleUpdate(role=OrganizationRole.VIEWER)
        )
    with pytest.raises(ConflictError):
        await remove_organization_member(request_for("owner-a"), owner["id"])

    transferred = await change_organization_member_role(
        request_for("owner-a"), target["id"], MemberRoleUpdate(role=OrganizationRole.OWNER)
    )
    assert transferred["data"]["role"] == "owner"
    profile = await repo.get_profile("tenant-a")
    assert profile["owner_user_id"] == "target-a"
    assert (await repo.get_active_member_by_user("tenant-a", "owner-a"))["role"] == "admin"

    with pytest.raises(ConflictError):
        await change_organization_member_role(
            request_for("owner-a"), target["id"], MemberRoleUpdate(role=OrganizationRole.VIEWER)
        )
