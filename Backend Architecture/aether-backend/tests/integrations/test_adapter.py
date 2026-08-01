"""Tests for the canonical :class:`IntegrationAdapter` facade (§17).

No network: a fake :class:`BaseConnector` subclass provides deterministic
``test_connection`` / ``pull`` behaviour, and a fake authorization broker stands
in for the OAuth legs. Secrets are injected via :class:`AdapterContext` so the
credential platform is never touched.
"""

from __future__ import annotations

import pytest

from services.integrations.adapter import (
    AdapterContext,
    ConnectorIntegrationAdapter,
    IntegrationAdapter,
    integration_adapter_for,
)
from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    NormalizedEvent,
)
from services.integrations.oauth.broker import AuthorizationChallenge
from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.catalog import manifest_from_connector_descriptor
from shared.integration_contracts.manifest import (
    Authentication,
    Availability,
    CredentialFieldSpec,
    ManifestReadiness,
    OAuthSpec,
    ProviderManifest,
)
from shared.integration_contracts.results import AdapterStatus

# ── Fakes ───────────────────────────────────────────────────────────────────


class _FakeConnector(BaseConnector):
    """Deterministic, network-free connector double."""

    connector_type = "hubspot"  # a valid ConnectorType literal that supports pull
    supports_pull = True
    supports_webhook = True
    requires_secret = True

    def __init__(self, *, ok: bool = True, events: list[NormalizedEvent] | None = None) -> None:
        self._ok = ok
        self._events = events or []
        self.last_since: str | None = "UNSET"
        self.last_secret: str | None = "UNSET"

    async def test_connection(
        self, config: ConnectorConfig, secret: str | None = None
    ) -> ConnectionTestResult:
        self.last_secret = secret
        if self._ok:
            return ConnectionTestResult(
                connector_type=self.connector_type, ok=True, status="ok", detail="fake ok"
            )
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=False, status="error", detail="fake boom"
        )

    async def pull(
        self, config: ConnectorConfig, since: str | None = None, secret: str | None = None
    ) -> list[NormalizedEvent]:
        self.last_since = since
        self.last_secret = secret
        return list(self._events)


class _FakeBroker:
    """Records delegation and returns a canned authorization challenge."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def build_authorization_url(
        self, tenant_id, identity, config, redirect_uri, *, extra_params=None
    ) -> AuthorizationChallenge:
        self.calls.append((tenant_id, identity.key, redirect_uri))
        return AuthorizationChallenge(
            url="https://acme.example/oauth/authorize?state=st", state="st", code_verifier=None
        )


def _config(connector_type: str = "hubspot", sync_status: str = "never_synced") -> ConnectorConfig:
    return ConnectorConfig(
        tenant_id="t1",
        connector_type=connector_type,  # type: ignore[arg-type]
        enabled=True,
        secret_configured=True,
        sync_status=sync_status,  # type: ignore[arg-type]
    )


def _ctx(connector_type: str = "hubspot", secret: str = "tok", sync_status: str = "never_synced"):
    return AdapterContext(
        tenant_id="t1",
        connector_type=connector_type,
        config=_config(connector_type, sync_status),
        secret=secret,
    )


def _api_key_manifest() -> ProviderManifest:
    """Honest api_key manifest derived from the fake connector's descriptor."""
    return manifest_from_connector_descriptor(_FakeConnector().descriptor())


def _oauth_manifest() -> ProviderManifest:
    return ProviderManifest(
        provider_family="acme",
        product_id="ingestion",
        capability_id="connector",
        display_name="Acme CRM",
        category="crm",
        readiness=ManifestReadiness(state=CredentialReadiness.REPLAY_VALIDATED, level=3),
        availability=Availability(tenant_self_service=True),
        authentication=Authentication(
            type="oauth2",
            credential_schema=[
                CredentialFieldSpec(name="oauth_token", type="oauth_token", secret=True)
            ],
            oauth=OAuthSpec(scopes=["read"], refresh_supported=True),
        ),
        data_outputs=["bronze.acme"],
        product_destinations=[],
    )


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_credentials_ok_maps_to_success():
    adapter = ConnectorIntegrationAdapter(
        connector=_FakeConnector(ok=True), manifest=_api_key_manifest()
    )
    result = await adapter.validate_credentials(_ctx(), credentials="tok")

    assert result.success is True
    assert result.status is AdapterStatus.OK
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_validate_credentials_error_maps_to_failure():
    fake = _FakeConnector(ok=False)
    adapter = ConnectorIntegrationAdapter(connector=fake, manifest=_api_key_manifest())
    result = await adapter.validate_credentials(_ctx(secret="injected"))

    assert result.success is False
    # ConnectionTestResult.status "error" bridges to a retryable error.
    assert result.status is AdapterStatus.RETRYABLE_ERROR
    assert result.retryable is True
    # Injected secret reached the connector (no credential-platform round trip).
    assert fake.last_secret == "injected"


@pytest.mark.asyncio
async def test_run_incremental_sync_carries_events_and_advances_cursor():
    events = [
        NormalizedEvent(event_type="custom.event", source="hubspot", external_id="1"),
        NormalizedEvent(event_type="custom.event", source="hubspot", external_id="2"),
    ]
    fake = _FakeConnector(events=events)
    adapter = ConnectorIntegrationAdapter(connector=fake, manifest=_api_key_manifest())

    result = await adapter.run_incremental_sync(_ctx(), cursor="2024-01-01T00:00:00Z")

    assert result.success is True
    assert result.status is AdapterStatus.OK
    assert result.data is not None and len(result.data) == 2
    assert result.data[0].event_type == "custom.event"
    # The provided cursor was passed to the connector as ``since``.
    assert fake.last_since == "2024-01-01T00:00:00Z"
    assert result.account is not None
    assert result.account["cursor"] == "2024-01-01T00:00:00Z"
    assert result.account["event_count"] == 2


@pytest.mark.asyncio
async def test_unsupported_op_returns_not_supported_and_never_raises():
    adapter = ConnectorIntegrationAdapter(
        connector=_FakeConnector(), manifest=_api_key_manifest()
    )

    reconcile = await adapter.reconcile(_ctx())
    discover = await adapter.discover_accounts(_ctx())

    for result in (reconcile, discover):
        assert result.success is False
        assert result.status is AdapterStatus.NOT_SUPPORTED
        assert result.error_code is not None and result.error_code.startswith("not_supported:")


@pytest.mark.asyncio
async def test_begin_authorization_delegates_to_broker_for_oauth2():
    broker = _FakeBroker()
    adapter = ConnectorIntegrationAdapter(
        connector=_FakeConnector(), manifest=_oauth_manifest(), broker=broker
    )
    ctx = AdapterContext(tenant_id="t1", connector_type="hubspot", secret="x")

    result = await adapter.begin_authorization(ctx, redirect_uri="https://app.example/callback")

    assert result.success is True
    assert result.status is AdapterStatus.OK
    assert result.data["authorization_url"].startswith("https://")
    assert result.data["state"] == "st"
    # The broker was actually driven.
    assert broker.calls == [("t1", "acme.ingestion.connector", "https://app.example/callback")]


@pytest.mark.asyncio
async def test_begin_authorization_not_supported_for_non_oauth_manifest():
    broker = _FakeBroker()
    adapter = ConnectorIntegrationAdapter(
        connector=_FakeConnector(), manifest=_api_key_manifest(), broker=broker
    )
    ctx = AdapterContext(tenant_id="t1", connector_type="hubspot", secret="x")

    result = await adapter.begin_authorization(ctx, redirect_uri="https://app.example/callback")

    assert result.success is False
    assert result.status is AdapterStatus.NOT_SUPPORTED
    assert broker.calls == []


@pytest.mark.asyncio
async def test_health_check_maps_sync_status():
    adapter = ConnectorIntegrationAdapter(
        connector=_FakeConnector(), manifest=_api_key_manifest()
    )

    healthy = await adapter.health_check(_ctx(sync_status="healthy"))
    assert healthy.success is True
    assert healthy.status is AdapterStatus.OK
    assert healthy.data["lifecycle_state"] == "connected"

    failed = await adapter.health_check(_ctx(sync_status="failed"))
    assert failed.success is False
    assert failed.retryable is True
    assert failed.data["lifecycle_state"] == "sync_failed"


def test_integration_adapter_for_builds_matching_manifest():
    adapter = integration_adapter_for("slack")

    assert isinstance(adapter, ConnectorIntegrationAdapter)
    assert isinstance(adapter, IntegrationAdapter)
    assert adapter.manifest.provider_family == "slack"


def test_integration_adapter_for_unknown_connector_raises():
    with pytest.raises(KeyError):
        integration_adapter_for("definitely_not_a_connector")
