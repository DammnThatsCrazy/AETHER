"""CORS preflight bypass of route-policy enforcement.

Route templates never declare OPTIONS, so template matching used to 403 every
browser preflight before the inner CORSMiddleware could answer. Valid CORS
preflights (OPTIONS + Origin + Access-Control-Request-Method — which carry no
credentials by design) must bypass route-policy enforcement; plain OPTIONS and
actual requests stay fully enforced.
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _crypto_ok() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
        return True
    except BaseException:  # noqa: BLE001 - PanicException is not an Exception
        return False


pytestmark = pytest.mark.skipif(not _crypto_ok(), reason="cryptography unavailable")

_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def enforced_route_registry():
    """Fresh backend generation with route-registry enforcement forced ON."""
    _evict_backend()
    settings_mod = importlib.import_module("config.settings")
    settings = settings_mod.settings
    original = settings.route_registry
    object.__setattr__(
        settings,
        "route_registry",
        dataclasses.replace(
            original,
            policy_enforcement_enabled=True,
            route_registry_enforced=True,
        ),
    )
    try:
        yield
    finally:
        object.__setattr__(settings, "route_registry", original)


_ORIGIN = "http://spa.example"


def _build_app():
    """App mirroring main.py's middleware order: CORS inner, lifecycle outer."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    mw = importlib.import_module("middleware.middleware")

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )
    mw.register_middleware(app)

    @app.get("/v1/widgets")
    async def widgets():  # pragma: no cover - never dispatched in these tests
        return {"ok": True}

    return app


def test_valid_cors_preflight_bypasses_route_policy():
    with enforced_route_registry():
        from starlette.testclient import TestClient

        client = TestClient(_build_app())
        resp = client.options(
            "/v1/widgets",
            headers={
                "Origin": _ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == _ORIGIN


def test_plain_options_stays_enforced():
    with enforced_route_registry():
        from starlette.testclient import TestClient

        client = TestClient(_build_app())
        resp = client.options("/v1/widgets")
        assert resp.status_code == 403
        assert "ROUTE_POLICY_UNKNOWN_ROUTE" in resp.text


def test_options_with_origin_but_no_request_method_stays_enforced():
    # Not a CORS preflight without Access-Control-Request-Method.
    with enforced_route_registry():
        from starlette.testclient import TestClient

        client = TestClient(_build_app())
        resp = client.options("/v1/widgets", headers={"Origin": _ORIGIN})
        assert resp.status_code == 403


def test_actual_cross_origin_request_stays_enforced():
    # The bypass is preflight-only: a GET with an Origin header still goes
    # through auth/route policy (unauthenticated here → denied).
    with enforced_route_registry():
        from starlette.testclient import TestClient

        client = TestClient(_build_app())
        resp = client.get("/v1/widgets", headers={"Origin": _ORIGIN})
        assert resp.status_code in (401, 403)
