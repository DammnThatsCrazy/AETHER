"""Mount/import smoke for the Rights Authority tenant surface.

Proves:
* ``services.rights_authority.routes:router`` imports cleanly and registers the
  three authoritative paths under the ``/v1/rights`` prefix.
* The real ``main`` app factory imports without error after the router is
  mounted and the three paths are actually reachable in the mounted app (an
  app-level mount smoke, mirroring tests/unit/test_main_router_mounts.py — no
  heavyweight TestClient/fixtures required).

The surface is deliberately additive and mounted unconditionally like sibling
governance routers (dsr_propagation precedent).
"""
from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from services.rights_authority.routes import router as rights_router  # noqa: E402

_EXPECTED_PATHS = {
    "/v1/rights/decisions/effective",
    "/v1/rights/decisions/{decision_id}",
    "/v1/rights/revocations",
}


def test_rights_router_imports_with_expected_prefix_and_paths():
    assert rights_router.prefix == "/v1/rights"
    specs = {
        (r.path, tuple(sorted(r.methods or [])))
        for r in rights_router.routes
    }
    for path in _EXPECTED_PATHS:
        assert any(spec[0] == path for spec in specs), f"missing path {path}"
    assert ("/v1/rights/decisions/effective", ("POST",)) in specs
    assert ("/v1/rights/decisions/{decision_id}", ("GET",)) in specs
    assert ("/v1/rights/revocations", ("POST",)) in specs


@pytest.fixture(scope="module")
def app():
    import main  # noqa: E402 - requires AETHER_ENV=local before settings load

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


def test_main_app_imports_and_mounts_rights_router(app):
    """create_app() imports cleanly and the three rights paths are mounted."""
    paths = _route_paths(app)
    for path in _EXPECTED_PATHS:
        assert path in paths, f"rights path {path} not mounted in main app"
