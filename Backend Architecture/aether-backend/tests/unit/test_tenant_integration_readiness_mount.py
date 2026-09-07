"""Wiring lock for the tenant-contextual integration-readiness router.

The WS-4 joined readiness router
(``services.readiness_graph.tenant_integration_readiness_routes``) is developed
and exercised in isolation by
``tests/integrations/test_tenant_integration_readiness_projection.py``, which
mounts it into its own synthetic app. This file locks the **real** wiring: the
router must be mounted in ``main.py`` under the connectors feature gate, and must
stay unmounted when connectors are disabled (the default), so the running service
serves ``/v1/tenant/integration-readiness`` exactly when the flag is on.

Test strategy
-------------
* Positive gate: source-text assertion (the repo's established idiom for
  main.py mount checks — see ``test_deferred_attribution.py`` and
  ``test_source_classification_kyber_contracts.py``). Unlike a bare substring
  check, the assertions are scoped to the body of ``if
  settings.connectors.enabled:`` so a future move of the import/include to module
  top level (un-gated) or into the ``else`` branch fails loudly. This avoids any
  dependence on mutating global settings, which sibling suites share.
* Negative gate: the live app built by importing ``main`` under default settings
  (connectors disabled) must NOT expose the path — inspected the same way as
  ``tests/unit/test_main_router_mounts.py``.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("AETHER_ENV", "local")

import main  # noqa: E402  (requires AETHER_ENV=local before settings load)


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MAIN_SOURCE = (_BACKEND_ROOT / "main.py").read_text(encoding="utf-8")

#: The mounted route path produced by the router's own prefix + ``@router.get("")``.
_TENANT_READINESS_PATH = "/v1/tenant/integration-readiness"


def _connectors_gate_body(main_source: str) -> str:
    """The source of the ``if settings.connectors.enabled:`` branch in main.py.

    Returns the text from the gate's ``if`` line up to (not including) its
    matching ``else:`` line. The connectors gate is the first ``else:`` after the
    ``if`` (the nested ``settings.connectors.kyber_connector_health_enabled``
    conditional has no ``else``).
    """
    gate_if = "if settings.connectors.enabled:"
    lines = main_source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == gate_if)
    end = next(
        i
        for i in range(start + 1, len(lines))
        if lines[i].strip() == "else:"
    )
    return "\n".join(lines[start:end])


def _route_paths(app) -> set[str]:
    """Flatten every mounted route path, descending into included routers."""
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


def test_router_is_mounted_under_connectors_gate() -> None:
    """main.py lazy-imports and includes the router inside the gate branch."""
    body = _connectors_gate_body(_MAIN_SOURCE)

    assert (
        "from services.readiness_graph.tenant_integration_readiness_routes import "
        "router as tenant_integration_readiness_router"
    ) in body, "lazy import must live inside the connectors-enabled branch"
    assert (
        "app.include_router(tenant_integration_readiness_router)" in body
    ), "include_router call must live inside the connectors-enabled branch"

    # No prefix is passed at mount: the router declares its own
    # /v1/tenant/integration-readiness prefix.
    assert "app.include_router(tenant_integration_readiness_router, prefix=" not in _MAIN_SOURCE


def test_route_absent_when_connectors_disabled() -> None:
    """Default settings (connectors OFF) must not expose the path in the app."""
    assert _TENANT_READINESS_PATH not in _route_paths(main.app)


def test_router_prefix_matches_mounted_path() -> None:
    """The router under test actually serves the path we lock on."""
    from services.readiness_graph.tenant_integration_readiness_routes import (
        router as tenant_integration_readiness_router,
    )

    paths = {
        route.path
        for route in tenant_integration_readiness_router.routes
    }
    assert _TENANT_READINESS_PATH in paths
