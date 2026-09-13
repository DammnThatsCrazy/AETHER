"""Smoke tests for the app-level router/middleware wiring closed by the
credential-turnkey review findings:

* Finding #12 (P1) — mount the card-linked graph-projection operator router,
  the capability readiness-graph routers, and the rewards operator router.
* Finding #16 (P2) — register the observability trace middleware AFTER the
  auth middleware so the automatic writer observes authenticated requests.

These assert the real ``main`` application: a route-inventory descent into
included routers plus the middleware-chain ordering contract. All three routers
are mounted unconditionally, so the assertions are feature-flag independent.
"""
from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest

import main  # noqa: E402  (requires AETHER_ENV=local before settings load)
from services.diagnostics.observability_middleware import (  # noqa: E402
    ObservabilityTraceMiddleware,
)


@pytest.fixture(scope="module")
def app():
    return main.app


def _route_paths(app) -> set[str]:
    """Flatten every mounted route path, descending into included routers.

    FastAPI mounts included routers as ``_IncludedRouter`` entries that have no
    ``path`` of their own; their routes live on ``original_router``.
    """
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(inner.routes)
    return paths


def _middleware_names(app) -> list[str]:
    return [m.cls.__name__ for m in app.user_middleware]


# ── Finding #12: the three newly added routers are actually mounted ─────────


def test_card_linked_graph_projection_operator_router_is_mounted(app):
    """POST /v1/kyber/card-linked/graph-projection/{drain,repair} + GET reconcile."""
    paths = _route_paths(app)
    for expected in (
        "/v1/kyber/card-linked/graph-projection/drain",
        "/v1/kyber/card-linked/graph-projection/reconcile",
        "/v1/kyber/card-linked/graph-projection/repair",
    ):
        assert expected in paths, f"missing mounted route {expected}"


def test_readiness_graph_routers_are_mounted(app):
    """Tenant surface + Kyber operator surface for the readiness graph."""
    paths = _route_paths(app)
    assert "/v1/tenant/readiness-graph/{capability}" in paths
    assert "/v1/kyber/readiness-graph/{capability}" in paths


def test_rewards_operator_router_is_mounted(app):
    """Kyber UI reward-health + tenant-scoped read surfaces."""
    paths = _route_paths(app)
    assert "/v1/admin/kyber/rewards/health" in paths
    for suffix in ("campaigns", "decisions", "actions", "audit"):
        assert (
            f"/v1/admin/kyber/tenants/{{tenant_id}}/{suffix}" in paths
        ), f"missing mounted route /v1/admin/kyber/tenants/{{tenant_id}}/{suffix}"


# ── Finding #16: the observability middleware is installed after auth ───────


def test_observability_middleware_is_installed(app):
    """The auto-record trace middleware is on the production middleware chain."""
    names = _middleware_names(app)
    assert ObservabilityTraceMiddleware.__name__ in names


def test_observability_middleware_runs_after_auth(app):
    """The trace middleware must dispatch AFTER the auth middleware.

    Starlette's ``add_middleware`` inserts at the FRONT of the chain, so the
    last-added middleware is outermost (runs first). ``request_lifecycle``
    (auth, registered by ``register_middleware``) must be OUTERMOST relative to
    the trace middleware so ``request.state.tenant`` is populated before the
    trace middleware's dispatch reads it.
    """
    names = _middleware_names(app)
    auth_index = names.index("BaseHTTPMiddleware")  # request_lifecycle wrapper
    obs_index = names.index(ObservabilityTraceMiddleware.__name__)
    assert obs_index > auth_index, (
        "observability middleware must run AFTER the auth middleware "
        f"(auth at index {auth_index}, observability at {obs_index})"
    )
