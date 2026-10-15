"""Tenant user grants derived from organization membership.

A human session's authority is hydrated on every request from the durable
user record (``middleware._resolve_session_token``): its ``role``,
``permissions`` and ``membership_status``. Organization membership is managed
separately (``account_organization_members``), so every membership change that
alters what a person may do must also be written to the user record, or a
demoted or removed member keeps the grant they were provisioned with.
"""

from __future__ import annotations

from typing import Any, Optional

# Organization role -> tenant user role and permissions.
ROLE_GRANTS: dict[str, tuple[str, list[str]]] = {
    "owner": ("admin", ["read", "write", "ingest", "analytics", "billing", "admin"]),
    "admin": ("admin", ["read", "write", "ingest", "analytics", "billing", "admin"]),
    "member": ("editor", ["read", "write", "ingest", "analytics"]),
    "viewer": ("viewer", ["read", "analytics"]),
}


# Organization roles by privilege, for ordering the two writes of a role change.
_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def grants_for(organization_role: Any) -> tuple[str, list[str]]:
    """The tenant role and permissions for an organization role (viewer if unknown)."""
    role = getattr(organization_role, "value", organization_role)
    tenant_role, permissions = ROLE_GRANTS.get(str(role), ROLE_GRANTS["viewer"])
    return tenant_role, list(permissions)


async def sync_user_grants(
    tenant_id: str,
    user_id: Optional[str],
    organization_role: Any,
    *,
    user_repo: Any = None,
) -> bool:
    """Write the grant for ``organization_role`` to the member's user record.

    ``organization_role=None`` means the membership ended: the user keeps no
    permissions and its ``membership_status`` becomes ``removed``, which the
    route policy denies. Only a user record of the same tenant is touched.
    Returns whether a record was updated.
    """
    if not user_id:
        return False
    if user_repo is None:
        from repositories.repos import UserRepository

        user_repo = UserRepository()
    user = await user_repo.find_by_id(user_id)
    if not user or user.get("tenant_id") != tenant_id:
        return False
    if organization_role is None:
        changes: dict[str, Any] = {
            "role": "viewer", "permissions": [], "membership_status": "removed",
        }
    else:
        role, permissions = grants_for(organization_role)
        changes = {"role": role, "permissions": permissions, "membership_status": "active"}
    await user_repo.update(user_id, changes)
    return True


async def change_member_role(
    repo: Any,
    tenant_id: str,
    member: dict[str, Any],
    new_role: Any,
    *,
    user_repo: Any = None,
) -> dict[str, Any]:
    """Change a member's organization role and its session grant together.

    The two rows cannot share a transaction, so the privilege-raising write
    always goes last and is compensated: a promotion updates the membership,
    then the grant, and restores the old membership role if the grant write
    fails; a demotion lowers the grant first, so a failure part-way leaves
    less privilege, never more, and a retry converges. Membership goes first
    on a promotion because the tenant grant is the broader one (a tenant
    ``admin`` holds every permission): a process death between the writes can
    leave only the organization role raised, which retrying the change
    repairs. Returns the updated member.
    """
    role = str(getattr(new_role, "value", new_role))
    old_role = str(member.get("role") or "viewer")
    user_id = member.get("user_id")
    if _ROLE_RANK.get(role, 0) > _ROLE_RANK.get(old_role, 0):
        updated = await repo.update_member(tenant_id, member["id"], {"role": role})
        try:
            await sync_user_grants(tenant_id, user_id, role, user_repo=user_repo)
        except Exception:
            await repo.update_member(tenant_id, member["id"], {"role": old_role})
            raise
        return updated
    await sync_user_grants(tenant_id, user_id, role, user_repo=user_repo)
    return await repo.update_member(tenant_id, member["id"], {"role": role})


__all__ = ["ROLE_GRANTS", "change_member_role", "grants_for", "sync_user_grants"]
