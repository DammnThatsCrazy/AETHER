"""Helpers to derive governance actor context from a FastAPI request.

Bridges the existing auth `TenantContext` (legacy Role + permissions) to the new
AccessRole model without removing any existing permission checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from shared.auth.auth import Role
from shared.common.common import UnauthorizedError

from .contracts import AccessRole, ActorType


@dataclass
class ActorContext:
    actor_id: str
    actor_type: ActorType
    tenant_id: Optional[str]
    roles: list[AccessRole]
    ip_address: Optional[str]
    user_agent: Optional[str]

    def has_export_permission(self, tenant) -> bool:  # noqa: ANN001
        return tenant.has_permission("export") or tenant.has_permission("admin")


def _client_meta(request: Request) -> tuple[Optional[str], Optional[str]]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


def tenant_roles_from_context(tenant) -> list[AccessRole]:  # noqa: ANN001
    """Map a tenant user's legacy Role + permissions to governance AccessRoles."""
    roles: list[AccessRole] = []
    if tenant.role == Role.ADMIN:
        roles.append('tenant_owner')
    elif tenant.role == Role.EDITOR:
        roles.append('tenant_operator')
    else:
        roles.append('tenant_viewer')
    if "billing" in tenant.permissions:
        roles.append('tenant_billing_admin')
    if "security" in tenant.permissions or tenant.role == Role.ADMIN:
        roles.append('tenant_security_admin')
    return roles


def tenant_actor(request: Request) -> ActorContext:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    ip, ua = _client_meta(request)
    return ActorContext(
        actor_id=tenant.user_id or tenant.tenant_id,
        actor_type='tenant_user',
        tenant_id=tenant.tenant_id,
        roles=tenant_roles_from_context(tenant),
        ip_address=ip, user_agent=ua,
    )


def operator_actor(request: Request) -> ActorContext:
    """Olympus operator context. Routes still call require_permission('admin')
    before using this — it does not replace that gate."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    ip, ua = _client_meta(request)
    # An admin-permissioned principal on a Kyber route is treated as olympus_admin
    # for aggregate access; finer operator roles are assigned via future provisioning.
    roles: list[AccessRole] = ['olympus_admin'] if tenant.has_permission("admin") else ['olympus_operator']
    return ActorContext(
        actor_id=tenant.user_id or tenant.tenant_id,
        actor_type='olympus_operator',
        tenant_id=None,
        roles=roles,
        ip_address=ip, user_agent=ua,
    )
