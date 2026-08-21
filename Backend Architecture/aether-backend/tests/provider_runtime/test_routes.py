"""API route tests for the Universal Provider Runtime routers.

Routers are constructor-injected: tests monkeypatch the module-level singleton
globals (``_REGISTRY``, ``_ORCHESTRATOR``, …) with fakes so every endpoint is
exercised without the not-yet-landed sibling seams or any live network call.
The operator gate mirrors the Kyber pattern — admin routes are fail-closed.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import services.provider_runtime.routes as routes_mod
from services.provider_runtime.connection import ProviderConnection
from services.provider_runtime.errors import (
    ProviderNotInstalled,
    ProviderRateLimited,
    WebhookVerificationFailed,
)
from shared.certification.readiness import CredentialReadiness
from shared.common.common import AetherError
from shared.integration_contracts.acquisition import ProviderAccount
from shared.integration_contracts.health import ProviderHealthReport
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    Availability,
    Configuration,
    CredentialFieldSpec,
    Deployment,
    ManifestReadiness,
    ProviderManifest,
    Sync,
    Webhooks,
)
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.results import AdapterResult

# ── Fakes ───────────────────────────────────────────────────────────────────


class FakeConnectionsRepo:
    def __init__(self) -> None:
        self._store: dict[str, ProviderConnection] = {}

    async def find(self, connection_id: str):
        return self._store.get(connection_id)

    async def find_by_id(self, connection_id: str):
        return self._store.get(connection_id)

    async def upsert(self, record: ProviderConnection):
        self._store[record.connection_id] = record
        return record

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100):
        return [c for c in self._store.values() if c.tenant_id == tenant_id]

    async def find_many(self, filters=None, **kwargs):
        rows = [c.model_dump() for c in self._store.values()]
        if filters:
            rows = [
                r for r in rows
                if all(r.get(k) == v for k, v in filters.items())
            ]
        return rows


class FakeOrchestrator:
    def __init__(self) -> None:
        self.connections = FakeConnectionsRepo()
        self.stored_credentials: list[object] = []

    async def create_connection(self, *, tenant_id, provider_identity, display_name="", config=None):
        connection = ProviderConnection(
            connection_id="conn_test",
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            display_name=display_name,
            config=config or {},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        await self.connections.upsert(connection)
        return connection

    async def store_credential(self, connection, credential):
        self.stored_credentials.append(credential)
        connection.credential_ref = "ref_1"
        return connection

    async def test_connection(self, connection, *, plugin=None):
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider plugin not installed for {connection.provider_identity}"
            )
        return AdapterResult.ok(data={"ok": True})

    async def run_sync(self, connection, *, since=None):
        return {"sync_run_id": "run_1", "status": "completed"}

    def transition(self, connection, target):
        connection.state = target
        connection.updated_at = "2026-01-01T00:00:00Z"
        return connection


class FakeCoordinator:
    async def discover_accounts(self, connection, *, plugin=None, credential=None):
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider plugin not installed for {connection.provider_identity}"
            )
        return AdapterResult.ok(data=[ProviderAccount(account_id="acct_1", display_name="Shop")])

    async def select_account(self, connection, *, account_id, plugin=None, credential=None):
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider plugin not installed for {connection.provider_identity}"
            )
        connection.selected_accounts.append(account_id)
        return connection


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def ingest(self, identity_key, *, raw_body, headers, signature, tenant_id):
        self.calls.append((identity_key, raw_body, headers, signature, tenant_id))
        return {"accepted": True, "record_count": 1, "event_count": 0}


class FakeHealthEngine:
    async def report(self, connection):
        return ProviderHealthReport(
            provider_identity=connection.provider_identity,
            connection_id=connection.connection_id,
            state=connection.state,
            readiness=ManifestReadiness(state=CredentialReadiness.SCAFFOLDED, level=1),
        )


class FakeRegistry:
    def __init__(self, manifests=None, plugins=None) -> None:
        self._manifests = list(manifests or [])
        self._plugins = dict(plugins or {})

    def manifests(self):
        return list(self._manifests)

    def list(self):
        return list(self._plugins.values())

    def get(self, identity_key):
        return self._plugins.get(identity_key)


# ── App fixture ─────────────────────────────────────────────────────────────


def _make_app(*, tenant_id: str = "tenant_abc") -> FastAPI:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def error_handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def inject_tenant(request, call_next):
        tenant = MagicMock()
        tenant.tenant_id = tenant_id
        tenant.user_id = "user_test"
        tenant.require_permission = MagicMock()
        request.state.tenant = tenant
        return await call_next(request)

    app.include_router(routes_mod.router)
    app.include_router(routes_mod.admin_router)
    app.include_router(routes_mod.webhook_public_router)
    return app


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, **singletons) -> None:
    for name, value in singletons.items():
        monkeypatch.setattr(routes_mod, name, value)


@pytest.fixture
def orchestrator() -> FakeOrchestrator:
    return FakeOrchestrator()


@pytest.fixture
def registry() -> FakeRegistry:
    # A registered provider so create/connection routes see a real plugin.
    reg = FakeRegistry()
    reg._plugins["shopify.products.read"] = _ManifestPlugin(
        {"identity_key": "shopify.products.read", "display_name": "Shop"}
    )
    return reg


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(monkeypatch, orchestrator, registry, gateway):
    _patch_runtime(
        monkeypatch,
        _ORCHESTRATOR=orchestrator,
        _REGISTRY=registry,
        _COORDINATOR=FakeCoordinator(),
        _GATEWAY=gateway,
        _HEALTH_ENGINE=FakeHealthEngine(),
    )
    return TestClient(_make_app())


# ── Providers ───────────────────────────────────────────────────────────────


def test_list_providers_returns_merged_manifests(client, registry):
    registry._manifests = [{"identity_key": "shopify.products.read", "display_name": "Shop"}]

    response = client.get("/v1/provider-connections/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["count"] == 1
    assert body["data"]["providers"][0]["identity_key"] == "shopify.products.read"


def test_list_providers_with_real_registry(monkeypatch):
    """Integration: the merged surface honors Team C's registry + ManifestService."""
    from services.provider_runtime.registry import provider_registry

    provider_registry.load_all()
    monkeypatch.setattr(routes_mod, "_REGISTRY", provider_registry)

    response = TestClient(_make_app()).get("/v1/provider-connections/providers")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["count"] >= 1
    # The merged surface carries the legacy connector corpus, source-attributed.
    sources = {p.get("source") for p in body["providers"]}
    assert "legacy" in sources


def test_list_providers_requires_tenant_permission():
    # No tenant injection: the request.state.tenant access raises AttributeError
    # (500). The route never silently succeeds without tenant context.
    app = FastAPI()
    app.include_router(routes_mod.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/v1/provider-connections/providers")

    assert response.status_code == 500


def test_get_provider_manifest_unknown_returns_404(client, registry):
    response = client.get("/v1/provider-connections/providers/nope.products.read")

    assert response.status_code == 404


def test_get_provider_manifest(client, registry):
    manifest = {"identity_key": "shopify.products.read", "display_name": "Shop"}
    registry._plugins["shopify.products.read"] = _ManifestPlugin(manifest)

    response = client.get("/v1/provider-connections/providers/shopify.products.read")

    assert response.status_code == 200
    assert response.json()["data"]["display_name"] == "Shop"


# ── Connection lifecycle ────────────────────────────────────────────────────


def test_create_connection(client):
    response = client.post(
        "/v1/provider-connections",
        json={
            "provider_identity": "shopify.products.read",
            "display_name": "Shopify",
            "config": {"store": "acme"},
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider_identity"] == "shopify.products.read"
    assert data["tenant_id"] == "tenant_abc"
    assert data["state"] == ConnectionState.AVAILABLE.value


def test_create_connection_rejects_extra_fields(client):
    response = client.post(
        "/v1/provider-connections",
        json={"provider_identity": "shopify.products.read", "bogus": True},
    )

    assert response.status_code == 422  # extra="forbid"


def test_get_connection_cross_tenant_404(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.get("/v1/provider-connections/conn_test")

    assert response.status_code == 200

    cross = TestClient(_make_app(tenant_id="tenant_other"))
    cross_response = cross.get("/v1/provider-connections/conn_test")
    assert cross_response.status_code == 404


def test_patch_connection(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.patch(
        "/v1/provider-connections/conn_test",
        json={"display_name": "Renamed", "config": {"region": "us"}},
    )

    assert response.status_code == 200
    assert response.json()["data"]["display_name"] == "Renamed"
    assert response.json()["data"]["config"]["region"] == "us"


def test_delete_connection(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.delete("/v1/provider-connections/conn_test")

    assert response.status_code == 200
    assert response.json()["data"]["state"] == ConnectionState.DISABLED.value


def test_store_credential_never_echoes_secrets(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.post(
        "/v1/provider-connections/conn_test/credentials",
        json={"type": "api_key", "api_key": "sk_live_TOP_SECRET"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["credential_ref"] == "ref_1"
    # No secret material ever appears in the response.
    assert "sk_live_TOP_SECRET" not in response.text


def test_store_credential_rejects_invalid_payload(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.post(
        "/v1/provider-connections/conn_test/credentials",
        json={"type": "no_such_type", "whatever": 1},
    )

    assert response.status_code == 400


def test_test_connection(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.post("/v1/provider-connections/conn_test/test")

    assert response.status_code == 200
    assert response.json()["data"]["success"] is True


# ── Accounts ────────────────────────────────────────────────────────────────


def test_list_accounts(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.get("/v1/provider-connections/conn_test/accounts")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["account_id"] == "acct_1"


def test_select_account(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.post(
        "/v1/provider-connections/conn_test/accounts/select",
        json={"account_id": "acct_1"},
    )

    assert response.status_code == 200
    assert "acct_1" in response.json()["data"]["selected_accounts"]


# ── Sync / health / raw records ────────────────────────────────────────────


def test_trigger_sync(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.post("/v1/provider-connections/conn_test/sync", json={})

    assert response.status_code == 200
    assert response.json()["data"]["sync_run_id"] == "run_1"


def test_list_sync_runs(client, orchestrator, monkeypatch):
    await_create_connection(orchestrator)

    class FakeSyncRunService:
        async def list_for_connector(self, tenant_id, connector_instance_id, *, limit=50):
            return [{"sync_run_id": "run_1", "status": "completed"}]

    monkeypatch.setattr(
        "services.comms.sync_runs.SyncRunService", FakeSyncRunService
    )

    response = client.get("/v1/provider-connections/conn_test/sync-runs")

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1


def test_connection_health(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.get("/v1/provider-connections/conn_test/health")

    assert response.status_code == 200
    assert response.json()["data"]["provider_identity"] == "shopify.products.read"


def test_raw_records(client, orchestrator):
    await_create_connection(orchestrator)

    response = client.get("/v1/provider-connections/conn_test/raw-records")

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


# ── Kyber admin (operator-gated, fail-closed) ───────────────────────────────


def test_admin_overview_fail_closed_without_operator():
    client = TestClient(_make_app())

    response = client.get("/v1/admin/kyber/provider-connections/overview")

    # RFC-7807 body: status is an int code, message in ``detail``.
    assert response.status_code in (401, 403)
    body = response.json()
    assert body["status"] == response.status_code
    assert body["detail"]


def test_admin_overview_as_operator(client, orchestrator, monkeypatch):
    await_create_connection(orchestrator)
    monkeypatch.setattr(
        routes_mod, "_require_operator", lambda request: {"actor": "operator"}
    )

    response = client.get("/v1/admin/kyber/provider-connections/overview")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["total"] == 1
    assert body["providers"]["shopify.products.read"][ConnectionState.AVAILABLE.value] == 1


def test_admin_health_as_operator(client, registry, monkeypatch):
    registry._plugins["shopify.products.read"] = _ManifestPlugin(
        {"identity_key": "shopify.products.read"}
    )
    monkeypatch.setattr(
        routes_mod, "_require_operator", lambda request: {"actor": "operator"}
    )

    response = client.get("/v1/admin/kyber/provider-connections/health")

    assert response.status_code == 200
    assert response.json()["data"]["providers_loaded"] == 1


def test_admin_certify_returns_report(client, registry, monkeypatch):
    from services.provider_runtime import certification as cert_mod

    monkeypatch.setattr(cert_mod, "_capability_violations", lambda plugin: [])
    monkeypatch.setattr(
        routes_mod, "_require_operator", lambda request: {"actor": "operator"}
    )
    registry._plugins["shopify.products.read"] = _make_cert_plugin()

    response = client.post(
        "/v1/admin/kyber/provider-connections/certify",
        json={"identity_key": "shopify.products.read"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["identity"] == "shopify.products.read"
    assert data["passed"] is True


def test_admin_certify_unknown_provider_404(client, monkeypatch):
    monkeypatch.setattr(
        routes_mod, "_require_operator", lambda request: {"actor": "operator"}
    )

    response = client.post(
        "/v1/admin/kyber/provider-connections/certify",
        json={"identity_key": "nope.products.read"},
    )

    assert response.status_code == 404


def test_admin_tenant_view_as_operator(client, orchestrator, monkeypatch):
    await_create_connection(orchestrator)
    monkeypatch.setattr(
        routes_mod, "_require_operator", lambda request: {"actor": "operator"}
    )

    response = client.get("/v1/admin/kyber/provider-connections/tenants/tenant_abc")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["health"]["connection_id"] == "conn_test"


# ── Public webhook ──────────────────────────────────────────────────────────


def test_webhook_requires_tenant_header(client, gateway):
    response = client.post("/v1/provider-webhooks/shopify.products.read", content=b"{}")

    assert response.status_code == 400
    assert gateway.calls == []


def test_webhook_ingest_passes_headers(client, gateway):
    response = client.post(
        "/v1/provider-webhooks/shopify.products.read",
        content=b'{"order": 1}',
        headers={
            "X-Aether-Tenant-ID": "tenant_abc",
            "X-Signature": "sig_123",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["accepted"] is True
    assert len(gateway.calls) == 1
    _, raw_body, headers, signature, tenant_id = gateway.calls[0]
    assert signature == "sig_123"
    assert tenant_id == "tenant_abc"
    assert raw_body == b'{"order": 1}'


def test_webhook_verification_failure_403(client, monkeypatch):
    async def failing_ingest(identity_key, *, raw_body, headers, signature, tenant_id):
        raise WebhookVerificationFailed("signature mismatch")

    monkeypatch.setattr(
        routes_mod, "_GATEWAY", _GatewayWith(failing_ingest)
    )

    response = client.post(
        "/v1/provider-webhooks/shopify.products.read",
        content=b"{}",
        headers={
            "X-Aether-Tenant-ID": "tenant_abc",
            "X-Signature": "bad",
            "X-Aether-Signature": "bad",
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["status"] == 403
    assert body["detail"] == "signature mismatch"


def test_webhook_rate_limited_429(client, monkeypatch):
    async def rate_limited(identity_key, *, raw_body, headers, signature, tenant_id):
        raise ProviderRateLimited("rate limited")

    monkeypatch.setattr(routes_mod, "_GATEWAY", _GatewayWith(rate_limited))

    response = client.post(
        "/v1/provider-webhooks/shopify.products.read",
        content=b"{}",
        headers={
            "X-Aether-Tenant-ID": "tenant_abc",
            "X-Signature": "sig",
        },
    )

    assert response.status_code == 429


def test_webhook_denial_acknowledgement_is_403(client, monkeypatch):
    """A gateway that returns ``accepted: False`` (verification/payload denial)
    must surface as a closed 4xx, never a 200."""

    async def denying_ingest(identity_key, *, raw_body, headers, signature, tenant_id):
        return {"accepted": False, "reason": "verification_failed",
                "record_count": 0, "event_count": 0}

    monkeypatch.setattr(routes_mod, "_GATEWAY", _GatewayWith(denying_ingest))

    response = client.post(
        "/v1/provider-webhooks/shopify.products.read",
        content=b"{}",
        headers={
            "X-Aether-Tenant-ID": "tenant_abc",
            "X-Signature": "bad",
            "X-Aether-Signature": "bad",
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["status"] == 403
    assert "verification_failed" in body["detail"]


def test_create_connection_unknown_provider_404(client):
    """Creating a connection for a provider that is not installed fails fast."""
    response = client.post(
        "/v1/provider-connections",
        json={"provider_identity": "nope.products.read", "display_name": "Ghost"},
    )

    assert response.status_code == 404


def test_test_connection_unregistered_provider_404(client, orchestrator, registry):
    """A connection whose provider is not installed must surface a 404 on test,
    not an unhandled 500 (the seam error is translated to HTTP)."""
    import asyncio

    asyncio.run(
        orchestrator.create_connection(
            tenant_id="tenant_abc",
            provider_identity="ghost.products.read",
            display_name="Ghost",
        )
    )

    response = client.post("/v1/provider-connections/conn_test/test")

    assert response.status_code == 404
    assert response.json()["status"] == 404


# ── Helpers ─────────────────────────────────────────────────────────────────


def await_create_connection(orchestrator: FakeOrchestrator) -> None:
    import asyncio

    asyncio.run(
        orchestrator.create_connection(
            tenant_id="tenant_abc",
            provider_identity="shopify.products.read",
            display_name="Shopify",
        )
    )


class _ManifestPlugin:
    """Minimal plugin whose manifest() returns a plain dict (route shape)."""

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest

    def manifest(self):
        return self._manifest


class _GatewayWith:
    def __init__(self, ingest) -> None:
        self.ingest = ingest


class _FakeNormalizer:
    def normalize(self, raw):
        return NormalizationResult(events=[], dropped=[])


def _make_cert_plugin():
    """A plugin that satisfies the full certification harness."""
    from shared.integration_contracts.identity import ProviderIdentity

    manifest = ProviderManifest(
        provider_family="shopify",
        product_id="products",
        capability_id="read",
        display_name="Shop",
        category="ecommerce",
        readiness=ManifestReadiness(state=CredentialReadiness.SCAFFOLDED, level=1),
        availability=Availability(),
        authentication=Authentication(
            type="api_key",
            credential_schema=[
                CredentialFieldSpec(name="api_key", type="secret", required=True, secret=True)
            ],
        ),
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=Webhooks(),
        sync=Sync(),
        data_outputs=["shopify.orders"],
        product_destinations=["olympus_lake"],
        deployment=Deployment(),
    )

    class _CertPlugin:
        def identity(self):
            return ProviderIdentity.parse("shopify.products.read")

        def manifest(self):
            return manifest

        def auth(self):
            return None

        def account(self):
            return None

        def pull(self):
            return None

        def webhook(self):
            return None

        def report(self):
            return None

        def stream(self):
            return None

        def reconciliation(self):
            return None

        def normalizer(self):
            return _FakeNormalizer()

    return _CertPlugin()
