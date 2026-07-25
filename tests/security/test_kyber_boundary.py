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

_GUARD_NAMES = ("require_kyber_operator", "is_kyber_operator")


def iter_api_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    yield inner


def _has_guard_dependency(route: APIRoute) -> bool:
    stack = [route.dependant]
    while stack:
        dependant = stack.pop()
        call = getattr(dependant, "call", None)
        if call is not None and getattr(call, "__name__", "") in _GUARD_NAMES:
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
    for route in iter_api_routes(main.app):
        if "/kyber" not in route.path:
            continue
        total += 1
        if _has_guard_dependency(route) or _has_guard_in_source(route.endpoint):
            continue
        unguarded.append(
            (route.path, sorted(route.methods or []),
             f"{route.endpoint.__module__}.{route.endpoint.__name__}")
        )
    assert total > 0, "no kyber routes found — enumeration is broken"
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
