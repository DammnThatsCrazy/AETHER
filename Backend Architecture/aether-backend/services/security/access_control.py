"""Centralized Access Control Service.

Maps AccessRoles to PermissionGrants and evaluates domain/action/scope access
checks. Emits audit events for denied access and sensitive allowed access.

This is additive: existing `tenant.require_permission(...)` checks are NOT
removed. Routes call `require_access(...)` which keeps the legacy gate and layers
role evaluation + audit emission on top.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from shared.common.common import ForbiddenError
from shared.logger.logger import get_logger

from .audit_ledger import audit_ledger
from .break_glass import break_glass_service
from .contracts import (
    AccessRole,
    ActorType,
    GovernanceDomain,
    PermissionAction,
    PermissionGrant,
    PermissionScope,
    PolicyDecision,
)

logger = get_logger("aether.security.access_control")

ALL_DOMAINS: tuple[GovernanceDomain, ...] = (
    'profile', 'graph', 'recommendations', 'decisions', 'actions', 'dispatches',
    'outcomes', 'playbooks', 'integrations', 'audit_exports', 'billing',
    'onboarding', 'customer_success', 'kyber_admin', 'security', 'governance',
    'reliability', 'data_quality',
)
TENANT_DOMAINS: tuple[GovernanceDomain, ...] = tuple(
    d for d in ALL_DOMAINS if d != 'kyber_admin'
)

# Grant tuples: (domains, actions, scope). '*' expands to ALL_DOMAINS.
_GrantSpec = tuple[Iterable[GovernanceDomain] | str, Iterable[PermissionAction], PermissionScope]

ROLE_SPECS: dict[AccessRole, list[_GrantSpec]] = {
    'tenant_owner': [
        (TENANT_DOMAINS, ('read', 'write', 'approve', 'dispatch', 'export', 'configure', 'delete', 'admin'), 'own_tenant'),
    ],
    'tenant_admin': [
        (TENANT_DOMAINS, ('read', 'write', 'approve', 'dispatch', 'configure'), 'own_tenant'),
        (('audit_exports',), ('export',), 'own_tenant'),
    ],
    'tenant_operator': [
        (('profile', 'graph', 'recommendations', 'decisions', 'actions', 'dispatches', 'outcomes', 'playbooks', 'integrations'), ('read', 'write', 'dispatch'), 'own_tenant'),
    ],
    'tenant_analyst': [
        (('profile', 'graph', 'recommendations', 'decisions', 'outcomes', 'playbooks', 'customer_success'), ('read', 'write'), 'own_tenant'),
    ],
    'tenant_viewer': [
        (TENANT_DOMAINS, ('read',), 'own_tenant'),
    ],
    'tenant_billing_admin': [
        (('billing',), ('read', 'write', 'configure', 'admin'), 'own_tenant'),
        (('profile',), ('read',), 'own_tenant'),
    ],
    'tenant_security_admin': [
        (('security', 'governance', 'audit_exports'), ('read', 'write', 'configure', 'export', 'admin'), 'own_tenant'),
        (TENANT_DOMAINS, ('read',), 'own_tenant'),
    ],
    'olympus_operator': [
        (TENANT_DOMAINS, ('read',), 'assigned_tenant'),
        (('kyber_admin', 'security', 'governance'), ('read',), 'all_tenants_aggregate'),
    ],
    'olympus_support': [
        (('profile', 'onboarding', 'customer_success', 'billing'), ('read',), 'assigned_tenant'),
    ],
    'olympus_admin': [
        ('*', ('read', 'write', 'approve', 'dispatch', 'export', 'configure', 'delete', 'admin'), 'all_tenants_admin'),
    ],
    'olympus_security': [
        (('security', 'governance', 'audit_exports', 'integrations'), ('read', 'write', 'configure', 'export', 'admin'), 'all_tenants_admin'),
        (('kyber_admin',), ('read',), 'all_tenants_aggregate'),
    ],
    'olympus_revops': [
        (('billing', 'kyber_admin'), ('read',), 'all_tenants_aggregate'),
    ],
    'auditor': [
        (('security', 'governance', 'audit_exports'), ('read', 'export'), 'all_tenants_aggregate'),
    ],
}

# Domains/actions whose ALLOWED outcomes are still worth an audit event.
_SENSITIVE_DOMAINS: frozenset[GovernanceDomain] = frozenset(
    {'security', 'governance', 'audit_exports', 'billing', 'kyber_admin', 'integrations', 'dispatches'}
)
_SENSITIVE_ACTIONS: frozenset[PermissionAction] = frozenset(
    {'approve', 'dispatch', 'export', 'delete', 'admin', 'configure'}
)


def _expand(spec: _GrantSpec) -> list[tuple[GovernanceDomain, PermissionAction, PermissionScope]]:
    domains, actions, scope = spec
    dom_list = ALL_DOMAINS if domains == '*' else tuple(domains)  # type: ignore[arg-type]
    return [(d, a, scope) for d in dom_list for a in actions]


def build_role_grants(role: AccessRole) -> list[PermissionGrant]:
    grants: list[PermissionGrant] = []
    for spec in ROLE_SPECS.get(role, []):
        for domain, action, scope in _expand(spec):
            grants.append(PermissionGrant(role=role, domain=domain, action=action, scope=scope))
    return grants


# Pre-build all grants once.
ROLE_GRANTS: dict[AccessRole, list[PermissionGrant]] = {
    role: build_role_grants(role) for role in ROLE_SPECS
}


class AccessControlService:
    """Evaluates whether an actor with given roles may act on a domain."""

    def grants_for_roles(self, roles: Iterable[AccessRole]) -> list[PermissionGrant]:
        out: list[PermissionGrant] = []
        for role in roles:
            out.extend(ROLE_GRANTS.get(role, []))
        return out

    def _scope_satisfies(
        self, grant_scope: PermissionScope, actor_tenant: Optional[str],
        target_tenant: Optional[str], assigned_tenants: Iterable[str],
    ) -> bool:
        if grant_scope == 'own_tenant':
            return target_tenant is not None and target_tenant == actor_tenant
        if grant_scope == 'assigned_tenant':
            return target_tenant is not None and target_tenant in set(assigned_tenants)
        if grant_scope == 'all_tenants_aggregate':
            # Aggregate scope can only authorize reads/exports of aggregate views,
            # never a single specific tenant's private records.
            return target_tenant is None
        if grant_scope == 'all_tenants_admin':
            return True
        return False

    async def evaluate(
        self,
        *,
        actor_id: str,
        actor_type: ActorType,
        roles: Iterable[AccessRole],
        domain: GovernanceDomain,
        action: PermissionAction,
        actor_tenant: Optional[str] = None,
        target_tenant: Optional[str] = None,
        assigned_tenants: Optional[Iterable[str]] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> PolicyDecision:
        roles = list(roles)
        assigned = set(assigned_tenants or [])

        # Break-glass can grant temporary assigned-tenant access for operators.
        if target_tenant and actor_type == 'olympus_operator':
            if await break_glass_service.has_active_grant(target_tenant, actor_id):
                assigned.add(target_tenant)

        allowed = False
        matched_scope: Optional[PermissionScope] = None
        for grant in self.grants_for_roles(roles):
            if grant.domain != domain or grant.action != action:
                continue
            if self._scope_satisfies(grant.scope, actor_tenant, target_tenant, assigned):
                allowed = True
                matched_scope = grant.scope
                break

        reason = (
            f"role(s) {roles} grant {action}:{domain} via scope {matched_scope}"
            if allowed else
            f"no grant for {action}:{domain} on target_tenant={target_tenant} for roles {roles}"
        )
        decision = PolicyDecision(
            tenant_id=target_tenant or actor_tenant,
            actor_id=actor_id,
            actor_type=actor_type,
            policy_key="access_control.evaluate",
            resource_type=resource_type or domain,
            resource_id=resource_id,
            action=action,
            allowed=allowed,
            reason=reason,
            severity='info' if allowed else 'block',
            required_action=None if allowed else "request appropriate role or break-glass",
        )

        sensitive = domain in _SENSITIVE_DOMAINS or action in _SENSITIVE_ACTIONS
        if not allowed or sensitive:
            await audit_ledger.record(
                actor_id=actor_id, actor_type=actor_type,
                event_type="access_check", resource_type=decision.resource_type,
                action=action, outcome='allowed' if allowed else 'blocked',
                tenant_id=decision.tenant_id, resource_id=resource_id,
                policy_decision_id=decision.decision_id,
                ip_address=ip_address, user_agent=user_agent,
                metadata={"domain": domain, "scope": matched_scope, "roles": roles},
            )
        return decision

    async def require_access(
        self, *, actor_id: str, actor_type: ActorType, roles: Iterable[AccessRole],
        domain: GovernanceDomain, action: PermissionAction, **kwargs: Any,
    ) -> PolicyDecision:
        decision = await self.evaluate(
            actor_id=actor_id, actor_type=actor_type, roles=roles,
            domain=domain, action=action, **kwargs,
        )
        if not decision.allowed:
            raise ForbiddenError(decision.reason)
        return decision


access_control = AccessControlService()
