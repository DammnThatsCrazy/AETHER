"""Kyber/Aether boundary gate: every kyber-scoped route must carry the operator guard.

Kyber is the internal Olympus operator console. `require_kyber_operator`
(services/security/request_context.py) fails closed — a tenant Role.ADMIN is
NOT an operator. This test enforces that every route whose mounted path
contains ``/kyber`` is guarded either declaratively (a `Depends` on the guard
anywhere in its dependency tree) or imperatively (the handler source calls the
guard). Zero exceptions: there is no allowlist, so a new unguarded kyber
route fails CI immediately.
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi.routing import APIRoute  # noqa: E402

_GUARD_NAMES = (
    "require_kyber_operator",
    "is_kyber_operator",
    # The workforce plane's canonical gate and its helpers. Strictly stronger
    # than require_kyber_operator: it does everything that gate does (deny every
    # Aether tenant, fail closed without a session) and additionally enforces
    # principal status, device approval, session/device binding, capability,
    # environment, action class, tenant scope, disclosure and step-up.
    "require_kyber_access",
    "require_kyber_presence",
    "resolve_access_context",
    "require_kyber_capability",
    "require_kyber_tenant_scope",
)

# Routes that establish identity in the first place, and therefore cannot
# require an established operator session without being unreachable. This is
# NOT a general allowlist: each entry is an exact (method, path) pair, each one
# is the documented entry point of an authentication flow, and each carries its
# own fail-closed control listed below. Anything else under /kyber must name a
# guard from _GUARD_NAMES.
_PREAUTH_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/v1/kyber/auth/login"): (
        "starts the Google OIDC redirect; issues no authority and sets only a "
        "single-use state/nonce/PKCE transaction"
    ),
    ("GET", "/v1/kyber/auth/callback"): (
        "completes the OIDC exchange; gated by issuer/audience/state/nonce/"
        "email_verified/hosted-domain validation and an existing active "
        "workforce principal — an unknown Google subject is denied"
    ),
    ("POST", "/v1/kyber/workforce/invitations/accept"): (
        "gated by a single-use sha256-hashed invitation token bound to a "
        "verified Google identity and email"
    ),
    ("POST", "/v1/kyber/auth/bootstrap"): (
        "one-time founder bootstrap; gated by an explicit env flag, a "
        "configured founder identity, and a hard refusal when any workforce "
        "principal already exists"
    ),
}


def iter_api_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    yield inner


#: The one module allowed to mint Kyber authorization dependencies. Matching on
#: module identity rather than a name substring keeps the check precise: a
#: helper that merely happens to be called `_require` elsewhere does not count.
_GATE_MODULE = "services.kyber.access.dependencies"


def _is_guard_callable(call) -> bool:
    """True when a resolved dependency is one of the canonical Kyber gates.

    `require_kyber_access(...)` is a factory, and the dependency it returns is
    named `require_kyber_access[<capability>]`, so an exact-name match misses
    it. Accept either the canonical gate module or a name that starts with a
    known guard.
    """
    if call is None:
        return False
    if getattr(call, "__module__", "") == _GATE_MODULE:
        return True
    name = getattr(call, "__name__", "") or ""
    return any(name.startswith(guard) for guard in _GUARD_NAMES)


def _has_guard_dependency(route: APIRoute) -> bool:
    stack = [route.dependant]
    while stack:
        dependant = stack.pop()
        if _is_guard_callable(getattr(dependant, "call", None)):
            return True
        stack.extend(dependant.dependencies or [])
    return False


def _has_guard_in_source(endpoint) -> bool:
    try:
        source = inspect.getsource(endpoint)
    except (OSError, TypeError):
        return False
    return any(f"{name}(" in source for name in _GUARD_NAMES)


def test_every_kyber_route_requires_operator():
    import main

    unguarded = []
    total = 0
    seen_preauth: set[tuple[str, str]] = set()
    for route in iter_api_routes(main.app):
        if "/kyber" not in route.path:
            continue
        total += 1
        methods = sorted(route.methods or [])
        preauth_keys = {(m, route.path) for m in methods} & set(_PREAUTH_ROUTES)
        if preauth_keys:
            seen_preauth |= preauth_keys
            continue
        if _has_guard_dependency(route) or _has_guard_in_source(route.endpoint):
            continue
        unguarded.append(
            (route.path, methods,
             f"{route.endpoint.__module__}.{route.endpoint.__name__}")
        )
    assert total > 0, "no kyber routes found — enumeration is broken"

    # A pre-auth entry that no longer corresponds to a mounted route is stale
    # permission. Fail rather than let the exemption outlive its route.
    stale = set(_PREAUTH_ROUTES) - seen_preauth
    assert not stale, (
        f"pre-authentication exemption(s) no longer match any mounted route: "
        f"{sorted(stale)} — remove them from _PREAUTH_ROUTES"
    )
    assert not unguarded, (
        f"{len(unguarded)} kyber route(s) lack require_kyber_operator — a "
        f"tenant admin could reach internal operator surfaces:\n"
        + "\n".join(str(u) for u in sorted(unguarded))
    )


class _Req:
    def __init__(self, tenant):
        self.state = type("S", (), {})()
        self.state.tenant = tenant
        self.state.request_id = "req-boundary-test"
        self.headers = {}
        self.client = None


def test_tenant_admin_context_is_rejected_by_guard():
    """A tenant Role.ADMIN is NOT an operator — the guard must fail closed."""
    import pytest

    from services.security.request_context import require_kyber_operator
    from shared.auth.auth import Role, TenantContext

    tenant_admin = TenantContext(
        tenant_id="tenant-a",
        role=Role.ADMIN,
        permissions=["read", "write", "admin"],
    )
    # Match on the exception class NAME, not identity: the full suite's
    # sys.modules surgery (pop-and-reimport in many suites) can leave two
    # `shared.common.common` modules loaded → two distinct ForbiddenError
    # classes, so `pytest.raises(ForbiddenError)` can miss the raised one even
    # though the guard fired correctly. The behavior under test (a role-admin
    # tenant is rejected) is exactly what a raised ForbiddenError proves.
    with pytest.raises(Exception) as exc_info:
        require_kyber_operator(_Req(tenant_admin))
    assert type(exc_info.value).__name__ == "ForbiddenError"


def test_no_kyber_route_classifies_as_public():
    """A Kyber route may never be reachable without an operator identity."""
    import main

    from services.security.route_registry import classify

    public_kyber = []
    for route in iter_api_routes(main.app):
        if "/kyber" not in route.path:
            continue
        policy = classify(route.path)
        if policy is None or policy.public or not policy.requires_auth:
            public_kyber.append(route.path)
    assert not public_kyber, f"kyber routes must never classify as public: {sorted(set(public_kyber))}"


def test_operator_permission_passes_guard():
    """The configured kyber operator permission grants access."""
    from config.settings import get_settings
    from services.security.request_context import require_kyber_operator
    from shared.auth.auth import Role, TenantContext

    operator_perm = get_settings().security_governance.kyber_operator_permission
    operator = TenantContext(
        tenant_id="olympus-ops",
        role=Role.ADMIN,
        permissions=["read", "write", "admin", operator_perm],
    )
    actor = require_kyber_operator(_Req(operator))
    assert actor is not None
