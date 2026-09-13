"""App-level TestClient tests for the model-runtime fail-closed surface.

The D9 feature gate lives in ``services/model_runtime/config.py``
(``MODEL_RUNTIME_ENABLED``, default OFF), and ``main.create_app()`` mounts the
``/v1/model-runtime`` surface unconditionally:

* gate ON  → the real guarded router is mounted (each route 503s via
  ``_gate_guard`` while the gate is closed, and serves real data once open);
* gate OFF → a lightweight disabled-prefix router serves the documented
  ``model_runtime_disabled`` HTTP 503 contract instead of a bare FastAPI 404.

The isolated-router suite (``test_model_runtime_routes.py``) can only exercise
the guard because it mounts the router manually, so it misses the application
boundary. These tests drive the REAL ``main.create_app()`` application through
``TestClient`` — a minted JWT passes the app's auth middleware so requests reach
routing — and pin the app-boundary contract:

* gate OFF → ``GET /v1/model-runtime/health`` (and every other model-runtime
  path) returns HTTP 503 ``model_runtime_disabled``, NOT 404;
* gate ON  → the real guarded router is mounted and serves the real response
  shapes;
* other app routes are unaffected (``/v1/health`` stays 200).

``main`` builds the whole app at import time, so this module is intentionally
isolated; ``test_model_runtime_app_wiring.py`` covers the config gate without
the import.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AETHER_ENV", "local")

import main as main_module  # noqa: E402
from shared.auth.auth import JWTHandler  # noqa: E402

DISABLED_CODE = "model_runtime_disabled"

GET_PATHS = (
    "/v1/model-runtime/models",
    "/v1/model-runtime/registry",
    "/v1/model-runtime/health",
    "/v1/model-runtime/entitlements",
    "/v1/model-runtime/usage",
    "/v1/model-runtime/traces",
)
PUT_PATH = "/v1/model-runtime/tenant-default"


@pytest.fixture(scope="module")
def operator_headers() -> dict[str, str]:
    """A Kyber-operator JWT the app's auth middleware accepts.

    Uses the app's own ``JWTHandler``/secret (HS256 in local mode) so the
    ``Authorization: Bearer`` token passes ``_authenticate_async`` and reaches
    routing. ``kyber:operator`` satisfies the model-runtime operator gate, and
    ``read``/``write`` satisfy the app's route policy for tenant-panel GET/PUT
    methods so those requests reach the model-runtime surface instead of being
    denied by the policy layer.
    """
    token = JWTHandler().encode(
        {
            "tenant_id": "tenant-demo",
            "sub": "user-test",
            "role": "viewer",
            "permissions": ["kyber:operator", "read", "write"],
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _fresh_app(monkeypatch: pytest.MonkeyPatch, *, enabled: bool):
    """Build the real app with the model-runtime gate pinned to ``enabled``.

    ``create_app()`` constructs ``ModelRuntimeSettings`` fresh on every call, so
    the monkeypatched ``MODEL_RUNTIME_*`` env is read at build time. The
    ``AETHER_ENV=local`` pin keeps the gate-ON configuration valid (the
    in-memory credential backend is the fail-closed-allowed local backend).
    """
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.delenv("MODEL_RUNTIME_ENABLED", raising=False)
    monkeypatch.delenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", raising=False)
    if enabled:
        monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
        monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "in_memory")
    return main_module.create_app()


# ---------------------------------------------------------------------------
# Gate OFF — the documented 503 surface (NOT a bare 404).
# ---------------------------------------------------------------------------


def test_gate_off_returns_503_not_404(
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    """With the D9 gate OFF the app serves the documented 503, not 404."""
    app = _fresh_app(monkeypatch, enabled=False)
    resp = TestClient(app).get("/v1/model-runtime/health", headers=operator_headers)
    assert resp.status_code == 503, f"expected 503, got {resp.status_code}"
    detail = resp.json()["detail"]
    assert detail["code"] == DISABLED_CODE
    assert detail["status"] == "disabled"


def test_gate_off_covers_every_frontend_path(
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    """Every model-runtime frontend path 503s while the gate is OFF."""
    app = _fresh_app(monkeypatch, enabled=False)
    client = TestClient(app)
    for path in GET_PATHS:
        resp = client.get(path, headers=operator_headers)
        assert resp.status_code == 503, f"{path} -> {resp.status_code}"
        assert resp.json()["detail"]["code"] == DISABLED_CODE
    resp = client.put(
        PUT_PATH,
        headers=operator_headers,
        json={"modelId": "claude-haiku-4-5-20251001"},
    )
    assert resp.status_code == 503, f"{PUT_PATH} -> {resp.status_code}"
    assert resp.json()["detail"]["code"] == DISABLED_CODE


# ---------------------------------------------------------------------------
# Gate ON — the real guarded router is mounted and serves real data.
# ---------------------------------------------------------------------------


def test_gate_on_mounts_real_router(
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    """With the gate ON the real health route responds with real data."""
    app = _fresh_app(monkeypatch, enabled=True)
    resp = TestClient(app).get("/v1/model-runtime/health", headers=operator_headers)
    assert resp.status_code == 200, f"real health route expected 200, got {resp.status_code}"
    body = resp.json()
    assert set(body) == {"status", "providers", "checks"}


def test_gate_on_serves_models_shape(
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    """The Aether tenant-panel surface is live once the gate is ON."""
    app = _fresh_app(monkeypatch, enabled=True)
    resp = TestClient(app).get("/v1/model-runtime/models", headers=operator_headers)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    body = resp.json()
    assert set(body) == {"models", "tenantDefaultModel"}
    assert body["models"]


# ---------------------------------------------------------------------------
# Other app routes are unaffected.
# ---------------------------------------------------------------------------


def test_other_app_routes_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mounting the disabled surface does not disturb unrelated app routes."""
    app = _fresh_app(monkeypatch, enabled=False)
    resp = TestClient(app).get("/v1/health")
    assert resp.status_code == 200
