"""Helpers to derive governance actor context from a FastAPI request.

Bridges the existing auth `TenantContext` (legacy Role + permissions) to the new
AccessRole model without removing any existing permission checks.

``is_kyber_operator`` / ``require_kyber_operator`` are the *compatibility
adapter* for the Kyber workforce identity plane. Roughly 158 call sites across
37 modules call them, so their names, signatures and exception types are frozen.
What changed underneath is the order of resolution:

1. a Kyber **workforce session** (Google SSO principal + trusted device +
   role templates) is authoritative when one is present;
2. otherwise the **legacy** tenant-permission / tenant-id allowlist path runs,
   but only while ``KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED`` is true;
3. otherwise access is denied.

Step 2 is the rollback lever: flipping the flag off retires legacy operator
identity without touching a single call site, and flipping it back on restores
the previous behaviour exactly.
"""
from __future__ import annotations

import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional

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


#: The in-flight request, bound by the authorization middleware. Service-layer
#: code that must authorize against the Kyber workforce plane but is not handed
#: a ``Request`` (Noesis takes only a ``TenantContext``) reads it from here. It
#: lives on the request's own task context, so it never leaks across requests.
_CURRENT_REQUEST: ContextVar[Optional[Request]] = ContextVar(
    "aether_current_request", default=None
)


def bind_current_request(request: Optional[Request]) -> None:
    """Bind the in-flight request for the current task context."""
    _CURRENT_REQUEST.set(request)


def current_request() -> Optional[Request]:
    """The in-flight request, or ``None`` outside a bound request."""
    return _CURRENT_REQUEST.get()


def kyber_access_context(request: Optional[Request]) -> Optional[Any]:
    """The request's Kyber workforce access context, or ``None``.

    Worker-owned module ``services.kyber.access.dependencies`` is imported
    lazily and every failure mode — the module not existing yet, raising, or
    handing back a coroutine we cannot await from synchronous code — resolves to
    ``None``, i.e. "no workforce session", which callers treat as deny.
    """
    if request is None or not settings.kyber_workforce.workforce_identity_enabled:
        return None
    state = getattr(request, "state", None)
    cached = getattr(state, "kyber_access_context", None)
    if cached is not None:
        return cached
    try:
        from services.kyber.access.dependencies import current_kyber_context
    except Exception:
        return None
    try:
        ctx = current_kyber_context(request)
    except Exception:
        return None
    if inspect.isawaitable(ctx):
        # A synchronous gate cannot await; treat an unresolved session as absent
        # rather than blocking or fabricating authority.
        try:
            ctx.close()  # type: ignore[union-attr]
        except Exception:
            pass
        return None
    return ctx


def _workforce_session_valid(ctx: Any) -> bool:
    """True when a resolved workforce context represents a live principal."""
    if ctx is None:
        return False
    for attr in ("authenticated", "is_authenticated", "active", "session_active"):
        value = getattr(ctx, attr, None)
        if value is False:
            return False
    return bool(_workforce_actor_id(ctx))


def _workforce_actor_id(ctx: Any) -> Optional[str]:
    for attr in ("operator_id", "principal_id", "workforce_principal_id", "actor_id"):
        value = getattr(ctx, attr, None)
        if value:
            return str(value)
    return None


def _workforce_roles(ctx: Any) -> list[AccessRole]:
    """Map the context's role templates to governance AccessRoles.

    Falls back to the least-privileged operator role when the context exposes no
    templates, so an authenticated principal is never silently upgraded.
    """
    templates: Any = None
    for attr in ("role_template_ids", "role_templates", "roles"):
        templates = getattr(ctx, attr, None)
        if templates:
            break
    if templates:
        try:
            from services.kyber.access.roles import access_roles_for

            resolved = access_roles_for(list(templates))
            if resolved:
                return list(resolved)
        except Exception:
            pass
    return ['olympus_operator']


def _workforce_actor(ctx: Any, request: Optional[Request]) -> ActorContext:
    """Build an ActorContext from a workforce principal (never tenant-scoped)."""
    ip, ua = _client_meta(request) if request is not None else (None, None)
    return ActorContext(
        actor_id=_workforce_actor_id(ctx) or "unknown-operator",
        actor_type='olympus_operator',
        tenant_id=None,
        roles=_workforce_roles(ctx),
        ip_address=ip, user_agent=ua,
    )


def _legacy_operator(tenant) -> bool:  # noqa: ANN001
    """The pre-workforce operator test: explicit grant or tenant-id allowlist.

    Inspects the RAW permission list (not ``has_permission()``, which returns
    True for every permission when ``role == Role.ADMIN``) so a role-admin Aether
    tenant cannot pass this operator-only gate.
    """
    cfg = settings.security_governance
    if tenant is None:
        return False
    raw_permissions = getattr(tenant, "permissions", None) or []
    if cfg.kyber_operator_permission in raw_permissions:
        return True
    tenant_id = getattr(tenant, "tenant_id", None)
    return bool(tenant_id) and tenant_id in cfg.kyber_operator_tenant_ids


def is_kyber_operator(tenant, request: Optional[Request] = None) -> bool:  # noqa: ANN001
    """True only for Olympus operators. No Aether tenant may access Kyber.

    ``tenant`` keeps its positional contract (a ``TenantContext``, or ``None``)
    so every existing caller is unaffected. Passing ``request`` additionally
    admits a Kyber workforce session, which needs no tenant at all.

    A regular Aether tenant — even one with ``Role.ADMIN`` — is NOT an operator.
    """
    if _workforce_session_valid(kyber_access_context(request)):
        return True
    if not settings.kyber_workforce.legacy_operator_identity_allowed:
        return False
    return _legacy_operator(tenant)


def require_kyber_operator(request: Request):  # noqa: ANN201
    """Fail-closed gate for Kyber security routes. Denies all Aether tenants.

    Returns an :class:`ActorContext` exactly as before. Raises
    ``UnauthorizedError`` when nothing identifies the caller and
    ``ForbiddenError`` when the caller is identified but not an operator — the
    two exception types the existing call sites and tests depend on.
    """
    ctx = kyber_access_context(request)
    if _workforce_session_valid(ctx):
        return _workforce_actor(ctx, request)

    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    if not settings.kyber_workforce.legacy_operator_identity_allowed:
        raise ForbiddenError(
            "Kyber operator access required; legacy_identity_disabled — "
            "sign in with a Kyber workforce session"
        )
    if not _legacy_operator(tenant):
        raise ForbiddenError(
            "Kyber operator access required; Aether tenants may not access Kyber"
        )
    return operator_actor(request)


def context_capabilities(ctx: Any) -> frozenset[str]:
    """Capability ids held by a resolved Kyber access context."""
    raw = getattr(ctx, "capabilities", None)
    if raw is None:
        raw = getattr(ctx, "capability_ids", None)
    if raw is None:
        return frozenset()
    try:
        return frozenset(str(c) for c in raw)
    except TypeError:
        return frozenset()


def context_has_capability(ctx: Any, capability: str) -> bool:
    """True when the context grants ``capability``."""
    checker = getattr(ctx, "has_capability", None)
    if callable(checker):
        try:
            return bool(checker(capability))
        except Exception:
            return False
    return capability in context_capabilities(ctx)


def context_max_action_class(ctx: Any) -> int:
    """The principal's action-class ceiling; 0 (read-only) when unknown."""
    for attr in ("max_action_class", "action_class_ceiling"):
        value = getattr(ctx, attr, None)
        if isinstance(value, int):
            return value
    templates = getattr(ctx, "role_template_ids", None) or getattr(ctx, "role_templates", None)
    if templates:
        try:
            from services.kyber.access.roles import max_action_class_for

            return int(max_action_class_for(list(templates)))
        except Exception:
            return 0
    return 0


def context_max_disclosure(ctx: Any) -> int:
    """The principal's disclosure ceiling as an int; D0 when unknown.

    Falls back to deriving it from the bound role templates so a context that
    predates the field still yields a real ceiling rather than silently
    resolving to "everything".
    """
    templates = getattr(ctx, "role_template_ids", None) or getattr(ctx, "role_templates", None)
    if templates:
        try:
            from services.kyber.access.roles import max_disclosure_for

            return int(max_disclosure_for(list(templates)))
        except Exception:
            return 0
    # No bound templates: fall back to the level this request was actually
    # granted, which the access dependency already computed as the minimum
    # across role, capability, scope and request. Falling back to 0 instead
    # would deny a legitimately-resolved context that simply carries the
    # decision rather than the inputs.
    granted = getattr(ctx, "granted_disclosure", None)
    if isinstance(granted, int):
        return int(granted)
    return 0


def context_is_stepped_up(ctx: Any) -> bool:
    """True when the session holds a live step-up elevation."""
    return bool(getattr(ctx, "stepped_up", False))


def context_has_tenant_scope(ctx: Any, tenant_id: Optional[str]) -> bool:
    """True when the principal holds an active access scope for ``tenant_id``.

    ``tenant_id=None`` asks the weaker question "is ANY tenant scope active",
    which is all a caller that has not yet resolved its target can require.
    """
    checker = getattr(ctx, "has_tenant_scope", None)
    if callable(checker) and tenant_id:
        try:
            return bool(checker(tenant_id))
        except Exception:
            return False
    scopes = None
    for attr in ("active_tenant_scopes", "tenant_scopes", "scopes"):
        scopes = getattr(ctx, attr, None)
        if scopes:
            break
    if not scopes:
        return False
    scoped: set[str] = set()
    try:
        for scope in scopes:
            value = getattr(scope, "tenant_id", scope)
            if value:
                scoped.add(str(value))
    except TypeError:
        return False
    if not scoped:
        return False
    return True if tenant_id is None else tenant_id in scoped


def has_kyber_capability(
    capability: str, request: Optional[Request] = None, *, tenant: Any = None,
) -> bool:
    """True when the caller holds ``capability`` on the Kyber workforce plane.

    Falls back to the legacy operator test while
    ``KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED`` is on: a legacy operator has no
    capability grants at all, so treating a verified one as holding the
    capability is what keeps local/dev and the existing suites working. Turning
    the flag off makes capability possession strictly required.
    """
    request = request if request is not None else current_request()
    ctx = kyber_access_context(request)
    if _workforce_session_valid(ctx):
        return context_has_capability(ctx, capability)
    if not settings.kyber_workforce.legacy_operator_identity_allowed:
        return False
    if tenant is None and request is not None:
        tenant = getattr(getattr(request, "state", None), "tenant", None)
    return _legacy_operator(tenant)


def require_kyber_capability(
    capability: str, request: Optional[Request] = None, *, tenant: Any = None,
) -> None:
    """Raise ``ForbiddenError`` unless the caller holds ``capability``."""
    if not has_kyber_capability(capability, request, tenant=tenant):
        raise ForbiddenError(f"Kyber capability required: {capability}")


def require_kyber_tenant_scope(
    tenant_id: str, request: Optional[Request] = None, *, tenant: Any = None,
) -> None:
    """Raise unless the caller may reach ``tenant_id``'s records.

    A workforce principal needs an active, purpose-bound access scope naming
    that tenant. A legacy operator (no workforce session, legacy identity still
    permitted) passes on the operator gate alone — scopes do not exist on that
    path, and inventing a check it can never satisfy would simply break the
    documented operator flow instead of tightening it.
    """
    request = request if request is not None else current_request()
    ctx = kyber_access_context(request)
    if _workforce_session_valid(ctx):
        if not context_has_tenant_scope(ctx, tenant_id):
            raise ForbiddenError(
                f"no active Kyber tenant access scope for tenant {tenant_id!r}"
            )
        return
    if tenant is None and request is not None:
        tenant = getattr(getattr(request, "state", None), "tenant", None)
    if settings.kyber_workforce.legacy_operator_identity_allowed and _legacy_operator(tenant):
        return
    raise ForbiddenError(
        f"no active Kyber tenant access scope for tenant {tenant_id!r}"
    )


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
