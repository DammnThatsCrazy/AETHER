"""Durable tenant-scoped repositories for account organizations.

The runtime uses ``BaseRepository`` so local tests and development share the
same behavior as the asyncpg deployment. The forward migration owns the
physical tables and the JSONB expression indexes that protect active-member
and pending-invitation uniqueness in PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from repositories.repos import BaseRepository
from shared.common.common import ConflictError


ORGANIZATIONS_TABLE = "account_organizations"
MEMBERS_TABLE = "account_organization_members"
INVITATIONS_TABLE = "account_organization_invitations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OrganizationRepository:
    """Repository facade that keeps every lookup explicitly tenant-scoped."""

    def __init__(
        self,
        organizations: Optional[BaseRepository] = None,
        members: Optional[BaseRepository] = None,
        invitations: Optional[BaseRepository] = None,
    ) -> None:
        self.organizations = organizations or BaseRepository(ORGANIZATIONS_TABLE)
        self.members = members or BaseRepository(MEMBERS_TABLE)
        self.invitations = invitations or BaseRepository(INVITATIONS_TABLE)

    async def get_profile(self, tenant_id: str) -> Optional[dict[str, Any]]:
        rows = await self.organizations.find_many({"tenant_id": tenant_id}, limit=1)
        return rows[0] if rows else None

    async def create_profile(
        self,
        tenant_id: str,
        *,
        owner_user_id: Optional[str],
        name: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        existing = await self.get_profile(tenant_id)
        if existing is not None:
            raise ConflictError("An organization already exists for this tenant")
        organization_id = f"org_{uuid4().hex}"
        return await self.organizations.insert(
            organization_id,
            {
                "organization_id": organization_id,
                "tenant_id": tenant_id,
                "name": name,
                "slug": slug,
                "description": description,
                "owner_user_id": owner_user_id,
                "status": "active",
            },
        )

    async def update_profile(self, tenant_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        profile = await self.get_profile(tenant_id)
        if profile is None:
            raise KeyError("organization")
        return await self.organizations.update(profile["id"], changes)

    async def get_member(self, tenant_id: str, member_id: str) -> Optional[dict[str, Any]]:
        member = await self.members.find_by_id(member_id)
        if member is None or member.get("tenant_id") != tenant_id:
            return None
        return member

    async def get_active_member_by_user(
        self, tenant_id: str, user_id: Optional[str]
    ) -> Optional[dict[str, Any]]:
        if not user_id:
            return None
        rows = await self.members.find_many(
            {"tenant_id": tenant_id, "user_id": user_id, "status": "active"},
            limit=1,
        )
        return rows[0] if rows else None

    async def list_members(self, tenant_id: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
        return await self.members.find_many(
            {"tenant_id": tenant_id, "status": "active"},
            limit=limit,
            offset=offset,
            sort_by="created_at",
            sort_order="asc",
        )

    async def count_members(self, tenant_id: str) -> int:
        return await self.members.count({"tenant_id": tenant_id, "status": "active"})

    async def add_member(
        self,
        tenant_id: str,
        *,
        user_id: str,
        role: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> dict[str, Any]:
        existing = await self.get_active_member_by_user(tenant_id, user_id)
        if existing is not None:
            raise ConflictError("User is already an active organization member")
        member_id = f"member_{uuid4().hex}"
        return await self.members.insert(
            member_id,
            {
                "member_id": member_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "role": role,
                "status": "active",
            },
        )

    async def update_member(self, tenant_id: str, member_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        member = await self.get_member(tenant_id, member_id)
        if member is None:
            raise KeyError("member")
        return await self.members.update(member_id, changes)

    async def remove_member(self, tenant_id: str, member_id: str) -> dict[str, Any]:
        return await self.update_member(
            tenant_id,
            member_id,
            {"status": "removed", "removed_at": _now()},
        )

    async def find_pending_invitation(
        self, tenant_id: str, email: str
    ) -> Optional[dict[str, Any]]:
        rows = await self.invitations.find_many(
            {"tenant_id": tenant_id, "email": email, "status": "pending"},
            limit=50,
        )
        return rows[0] if rows else None

    async def list_invitations(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self.invitations.find_many(
            {"tenant_id": tenant_id}, limit=200, sort_by="created_at", sort_order="desc"
        )

    async def get_invitation(self, tenant_id: str, invitation_id: str) -> Optional[dict[str, Any]]:
        invitation = await self.invitations.find_by_id(invitation_id)
        if invitation is None or invitation.get("tenant_id") != tenant_id:
            return None
        return invitation

    async def create_invitation(self, tenant_id: str, record: dict[str, Any]) -> dict[str, Any]:
        invitation_id = record.get("invitation_id") or f"invite_{uuid4().hex}"
        payload = {**record, "invitation_id": invitation_id, "tenant_id": tenant_id}
        return await self.invitations.insert(invitation_id, payload)

    async def update_invitation(
        self, tenant_id: str, invitation_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        invitation = await self.get_invitation(tenant_id, invitation_id)
        if invitation is None:
            raise KeyError("invitation")
        return await self.invitations.update(invitation_id, changes)


__all__ = [
    "INVITATIONS_TABLE",
    "MEMBERS_TABLE",
    "ORGANIZATIONS_TABLE",
    "OrganizationRepository",
]
