"""Helpers to derive governance actor context from a FastAPI request.

Bridges the existing auth `TenantContext` (legacy Role + permissions) to the new
AccessRole model without removing any existing permission checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from config.settings import settings
from shared.auth.auth import Role
from shared.common.common import ForbiddenError, UnauthorizedError

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


def is_kyber_operator(tenant) -> bool:  # noqa: ANN001
    """True only for Olympus operators. No Aether tenant may access Kyber.

    A regular Aether tenant — even one with ``Role.ADMIN`` — is NOT an operator.
    We deliberately inspect the RAW permission list (not ``has_permission()``,
    which returns True for every permission when ``role == Role.ADMIN``) so a
    role-admin tenant cannot pass this operator-only gate. An operator is
    recognised only by the configured ``kyber:operator`` permission grant or
    membership in the operator tenant-id allowlist.
    """
    cfg = settings.security_governance
    if tenant is None:
        return False
    raw_permissions = getattr(tenant, "permissions", None) or []
    if cfg.kyber_operator_permission in raw_permissions:
        return True
    tenant_id = getattr(tenant, "tenant_id", None)
    return bool(tenant_id) and tenant_id in cfg.kyber_operator_tenant_ids


def require_kyber_operator(request: Request):  # noqa: ANN201
    """Fail-closed gate for Kyber security routes. Denies all Aether tenants."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    if not is_kyber_operator(tenant):
        raise ForbiddenError(
            "Kyber operator access required; Aether tenants may not access Kyber"
        )
    return operator_actor(request)


def operator_actor(request: Request) -> ActorContext:
    """Olympus operator context. Callers MUST gate with require_kyber_operator()
    first — this builds the context but does not itself authorize access."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    ip, ua = _client_meta(request)
    # A verified operator with the legacy admin permission gets olympus_admin
    # (all-tenant admin); other verified operators get olympus_operator.
    roles: list[AccessRole] = ['olympus_admin'] if tenant.has_permission("admin") else ['olympus_operator']
    return ActorContext(
        actor_id=tenant.user_id or tenant.tenant_id,
        actor_type='olympus_operator',
        tenant_id=None,
        roles=roles,
        ip_address=ip, user_agent=ua,
    )
