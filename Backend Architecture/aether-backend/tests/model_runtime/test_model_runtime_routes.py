"""HTTP route tests for the model-runtime control plane (Commit 16, Agent B).

Pins the D9 feature gate (off-by-default 503 fail-closed surface), the exact
response shapes the landed frontend clients expect (Aether model-selection +
Kyber model-runtime), server-authoritative tenant scope via ``X-Tenant-ID``,
and the no-secrets invariant on the health surface.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.model_runtime.routes as routes
from services.model_runtime.observability.health import (
    ProviderHealth as ProbeProviderHealth,
    RuntimeHealth,
)

# ---------------------------------------------------------------------------
# Fixtures + contract constants.
# ---------------------------------------------------------------------------

# X-Tenant-ID is the repo's canonical tenant header; server-authoritative scope.
TENANT_HEADERS = {"X-Tenant-ID": "tenant-demo"}

GET_PATHS = (
    "/v1/model-runtime/models",
    "/v1/model-runtime/registry",
    "/v1/model-runtime/health",
    "/v1/model-runtime/entitlements",
    "/v1/model-runtime/usage",
    "/v1/model-runtime/traces",
)
PUT_PATH = "/v1/model-runtime/tenant-default"

ALL_ROUTES = tuple(("GET", path) for path in GET_PATHS) + (("PUT", PUT_PATH),)

# Field sets taken verbatim from the landed frontend types.
MODEL_FIELDS = {
    "capabilities",
    "inputCostPerMTok",
    "modelId",
    "outputCostPerMTok",
    "provider",
    "status",
}
HEALTH_PROVIDER_FIELDS = {"configured", "healthy", "provider", "reason"}
USAGE_TOTALS_FIELDS = {"calls", "costUsd", "inputTokens", "outputTokens"}
USAGE_BY_MODEL_FIELDS = USAGE_TOTALS_FIELDS | {"modelId"}
TRACE_FIELDS = {
    "correlationId",
    "createdAt",
    "entitled",
    "fallback",
    "latencyMs",
    "mode",
    "profileId",
    "requestedModel",
    "selectedModel",
    "status",
    "tenantId",
    "traceId",
}
ENTITLEMENT_ROW_FIELDS = {"entitled", "modelId", "reason", "tenantId"}

_SECRET_MARKERS = ("sk-", "AKIA", "Bearer ", "Authorization:", "eyJ")


@pytest.fixture()
def client() -> TestClient:
    """A FastAPI app with only the model-runtime router mounted."""
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_seed_store() -> None:
    """Restore the in-memory tenant-default seed between tests."""
    saved = dict(routes._TENANT_DEFAULT_MODELS)
    routes._TENANT_DEFAULT_MODELS.clear()
    routes._TENANT_DEFAULT_MODELS.update(saved)
    yield


def _enable_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the D9 gate ON for the duration of a test."""
    monkeypatch.setattr(routes, "_model_runtime_enabled", lambda: True)


# ---------------------------------------------------------------------------
# Route table + contract registration.
# ---------------------------------------------------------------------------


def test_registers_exact_frontend_contract_paths() -> None:
    """Every frontend path is registered with the expected method."""
    registered = set()
    for route in routes.router.routes:
        raw = getattr(route, "path", None) or ""
        path = raw if raw.startswith("/v1") else f"{routes.router.prefix}{raw}"
        for method in (getattr(route, "methods", None) or ()):
            registered.add((method, path))
    assert set(ALL_ROUTES) == registered


# ---------------------------------------------------------------------------
# D9 feature gate — disabled surface is fail-closed (503) everywhere.
# ---------------------------------------------------------------------------


def test_disabled_gate_returns_503_on_every_path(client: TestClient) -> None:
    """Gate OFF (D9 default) → HTTP 503 on every route, never real data."""
    for method, path in ALL_ROUTES:
        kwargs = {"headers": TENANT_HEADERS}
        if path == PUT_PATH:
            kwargs["json"] = {"modelId": "claude-haiku-4-5-20251001"}
        resp = client.request(method, path, **kwargs)
        assert resp.status_code == 503, f"{method} {path} → {resp.status_code}"
        assert resp.json()["detail"]["code"] == "model_runtime_disabled"
        assert "models" not in resp.text
        assert "entitlements" not in resp.text


def test_disabled_gate_serves_nothing_without_tenant_header(
    client: TestClient,
) -> None:
    """A disabled surface 503s even before tenant validation (no leak)."""
    resp = client.get("/v1/model-runtime/health")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "model_runtime_disabled"


def test_disabled_gate_can_be_flipped_by_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate reads MODEL_RUNTIME_ENABLED through ModelRuntimeSettings."""
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "false")
    assert routes._model_runtime_enabled() is False
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("AETHER_ENV", "local")
    assert routes._model_runtime_enabled() is True


# ---------------------------------------------------------------------------
# Enabled gate — each route serves the EXACT frontend contract shapes.
# ---------------------------------------------------------------------------


def test_enabled_models_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /models → Aether ModelListResponse { models, tenantDefaultModel }."""
    _enable_gate(monkeypatch)
    resp = client.get("/v1/model-runtime/models", headers=TENANT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"models", "tenantDefaultModel"}
    assert body["tenantDefaultModel"] == "claude-haiku-4-5-20251001"
    assert body["models"]
    for model in body["models"]:
        assert set(model) == MODEL_FIELDS


def test_enabled_registry_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /registry → Kyber RegistryResponse { models }."""
    _enable_gate(monkeypatch)
    resp = client.get("/v1/model-runtime/registry", headers=TENANT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"models"}
    assert body["models"]
    for model in body["models"]:
        assert set(model) == MODEL_FIELDS


def test_enabled_health_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /health → Kyber HealthResponse { status, providers, checks }."""
    _enable_gate(monkeypatch)
    resp = client.get("/v1/model-runtime/health", headers=TENANT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "providers", "checks"}
    assert body["status"] in {"ok", "degraded", "unhealthy"}
    assert body["providers"]
    for provider in body["providers"]:
        assert set(provider) == HEALTH_PROVIDER_FIELDS
    assert isinstance(body["checks"], dict)
    assert all(isinstance(value, bool) for value in body["checks"].values())


def test_enabled_entitlements_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /entitlements → Kyber EntitlementsResponse { entitlements }."""
    _enable_gate(monkeypatch)
    resp = client.get("/v1/model-runtime/entitlements", headers=TENANT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"entitlements"}
    assert body["entitlements"]
    for row in body["entitlements"]:
        assert set(row) == ENTITLEMENT_ROW_FIELDS


def test_enabled_usage_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /usage → Kyber UsageResponse { period, totals, byModel }."""
    _enable_gate(monkeypatch)
    resp = client.get("/v1/model-runtime/usage", headers=TENANT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"period", "totals", "byModel"}
    assert body["period"]
    assert set(body["totals"]) == USAGE_TOTALS_FIELDS
    assert body["byModel"]
    for row in body["byModel"]:
        assert set(row) == USAGE_BY_MODEL_FIELDS


def test_enabled_traces_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /traces → Kyber TracesResponse { traces } (no raw content)."""
    _enable_gate(monkeypatch)
    resp = client.get("/v1/model-runtime/traces", headers=TENANT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"traces"}
    assert body["traces"]
    for trace in body["traces"]:
        assert set(trace) == TRACE_FIELDS


# ---------------------------------------------------------------------------
# Tenant scope — X-Tenant-ID is required and server-authoritative.
# ---------------------------------------------------------------------------


def test_tenant_header_required_on_every_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled + missing X-Tenant-ID → HTTP 400 on every route."""
    _enable_gate(monkeypatch)
    for method, path in ALL_ROUTES:
        kwargs = {}
        if path == PUT_PATH:
            kwargs["json"] = {"modelId": "claude-haiku-4-5-20251001"}
        resp = client.request(method, path, **kwargs)
        assert resp.status_code == 400, f"{method} {path} → {resp.status_code}"
        assert resp.json()["detail"]["code"] == "tenant_required"


def test_unknown_tenant_has_no_default_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown tenant gets tenantDefaultModel null (no cross-tenant leak)."""
    _enable_gate(monkeypatch)
    resp = client.get(
        "/v1/model-runtime/models", headers={"X-Tenant-ID": "tenant-unknown"}
    )
    assert resp.status_code == 200
    assert resp.json()["tenantDefaultModel"] is None


def test_entitlements_are_tenant_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entitlement rows always carry the requesting tenant's id."""
    _enable_gate(monkeypatch)
    tenant = "tenant-xyz"
    resp = client.get("/v1/model-runtime/entitlements", headers={"X-Tenant-ID": tenant})
    assert resp.status_code == 200
    rows = resp.json()["entitlements"]
    assert rows
    assert all(row["tenantId"] == tenant for row in rows)


def test_traces_are_tenant_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trace summaries always carry the requesting tenant's id."""
    _enable_gate(monkeypatch)
    tenant = "tenant-xyz"
    resp = client.get("/v1/model-runtime/traces", headers={"X-Tenant-ID": tenant})
    assert resp.status_code == 200
    traces = resp.json()["traces"]
    assert traces
    assert all(trace["tenantId"] == tenant for trace in traces)


# ---------------------------------------------------------------------------
# No-credentials invariant — health reasons are sanitized.
# ---------------------------------------------------------------------------


def test_health_never_renders_secrets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health responses blank sk-/AKIA/Bearer/JWT-shaped reason material."""
    _enable_gate(monkeypatch)
    secret_health = RuntimeHealth(
        status="degraded",
        providers=(
            ProbeProviderHealth(
                provider="anthropic",
                configured=True,
                healthy=True,
                reason="ok sk-ant-api03-leak-value",
            ),
            ProbeProviderHealth(
                provider="openai",
                configured=True,
                healthy=True,
                reason="configured AKIAIOSFODNN7EXAMPLE",
            ),
            ProbeProviderHealth(
                provider="kimi",
                configured=False,
                healthy=False,
                reason="missing Authorization: Bearer eyJ-leak-payload",
            ),
        ),
        checks={"anthropic": True, "openai": True, "kimi": False},
    )
    monkeypatch.setattr(
        routes, "_build_runtime_health", lambda tenant_id: secret_health
    )

    resp = client.get("/v1/model-runtime/health", headers=TENANT_HEADERS)
    assert resp.status_code == 200

    text = resp.text
    for marker in _SECRET_MARKERS:
        assert marker not in text, f"health response leaked marker {marker!r}"

    providers = resp.json()["providers"]
    assert all(
        provider["reason"] == routes._GENERIC_REASON for provider in providers
    )


def test_sanitize_reason_blanks_secret_shapes() -> None:
    """The sanitizer mirrors the frontend marker set (defense-in-depth)."""
    assert routes._sanitize_reason("sk-ant-api03-secret") == routes._GENERIC_REASON
    assert routes._sanitize_reason("AKIAIOSFODNN7EXAMPLE") == routes._GENERIC_REASON
    assert routes._sanitize_reason("key= super-secret") == routes._GENERIC_REASON
    assert routes._sanitize_reason("  ") == routes._GENERIC_REASON
    assert routes._sanitize_reason(None) == routes._GENERIC_REASON
    assert routes._sanitize_reason("provider not configured") == "provider not configured"


# ---------------------------------------------------------------------------
# PUT /tenant-default behavior.
# ---------------------------------------------------------------------------


def test_tenant_default_put_roundtrip(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful PUT persists the default for the requesting tenant."""
    _enable_gate(monkeypatch)
    tenant = "tenant-abc"
    resp = client.put(
        "/v1/model-runtime/tenant-default",
        headers={"X-Tenant-ID": tenant},
        json={"modelId": "gpt-4o"},
    )
    assert resp.status_code == 204
    assert resp.content == b""

    resp = client.get(
        "/v1/model-runtime/models", headers={"X-Tenant-ID": tenant}
    )
    assert resp.status_code == 200
    assert resp.json()["tenantDefaultModel"] == "gpt-4o"


def test_tenant_default_put_unknown_model_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown model id fails closed with HTTP 400."""
    _enable_gate(monkeypatch)
    resp = client.put(
        "/v1/model-runtime/tenant-default",
        headers=TENANT_HEADERS,
        json={"modelId": "not-a-real-model"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_model"


def test_tenant_default_request_forbids_extra_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUT body rejects unknown fields (house style: extra='forbid')."""
    _enable_gate(monkeypatch)
    resp = client.put(
        "/v1/model-runtime/tenant-default",
        headers=TENANT_HEADERS,
        json={"modelId": "gpt-4o", "provider": "openai"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Response models are frozen; request model forbids extras.
# ---------------------------------------------------------------------------


def _config_value(model_cls: type, key: str) -> object:
    """Read a pydantic model_config value (v1/v2 tolerant)."""
    config = getattr(model_cls, "model_config", None)
    if isinstance(config, dict):
        return config.get(key)
    return getattr(config, key, None)


def test_response_models_are_frozen() -> None:
    """Every response model is frozen (house style for read-only contracts)."""
    for model_cls in (
        routes.RegistryModelOut,
        routes.ModelListResponseOut,
        routes.RegistryResponseOut,
        routes.ProviderHealthOut,
        routes.HealthResponseOut,
        routes.EntitlementRowOut,
        routes.EntitlementsResponseOut,
        routes.UsageTotalsOut,
        routes.UsageByModelOut,
        routes.UsageResponseOut,
        routes.RoutingTraceOut,
        routes.TracesResponseOut,
    ):
        assert _config_value(model_cls, "frozen") is True, model_cls.__name__


def test_request_model_forbids_extra_fields() -> None:
    """The tenant-default request model rejects unknown fields."""
    assert _config_value(routes.TenantDefaultRequest, "extra") == "forbid"
