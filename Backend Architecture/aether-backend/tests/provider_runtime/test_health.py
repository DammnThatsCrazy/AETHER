"""Tests for the provider health engine (state + manifest readiness + stored signals)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from services.provider_runtime.errors import ProviderNotInstalled
from services.provider_runtime.health import HealthEngine
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.manifest import (
    Authentication,
    Availability,
    ManifestReadiness,
    ProviderManifest,
    Webhooks,
)

IDENTITY = "shopify.orders.catalog"


class FakeRegistry:
    def __init__(self, plugins: dict[str, Any]) -> None:
        self._plugins = dict(plugins)

    def get(self, identity_key: str) -> Any:
        return self._plugins.get(identity_key)


class FakePlugin:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest

    def manifest(self) -> Any:
        return self._manifest


def make_manifest(*, level: int = 3) -> ProviderManifest:
    return ProviderManifest(
        provider_family="shopify",
        product_id="orders",
        capability_id="catalog",
        display_name="Shopify Orders",
        category="commerce",
        readiness=ManifestReadiness(state="sandbox_validated", level=level),
        availability=Availability(),
        authentication=Authentication(type="api_key"),
        webhooks=Webhooks(supported=False),
        data_outputs=["commerce.order.created"],
        product_destinations=["silver"],
    )


def make_connection(
    *,
    state: ConnectionState = ConnectionState.CONNECTED,
    last_sync_at: str | None = None,
) -> Any:
    from services.provider_runtime.connection import ProviderConnection
    return ProviderConnection(
        connection_id="conn_1",
        tenant_id="tenant-1",
        provider_identity=IDENTITY,
        state=state,
        credential_ref="provider:tenant-1:shopify.orders.catalog",
        last_successful_sync_at=last_sync_at,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def make_engine(*, plugin: Any, registry: Any = None) -> HealthEngine:
    return HealthEngine(
        registry=registry if registry is not None else FakeRegistry({IDENTITY: plugin}),
    )


@pytest.mark.asyncio
async def test_report_surfaces_state_readiness_and_last_sync():
    plugin = FakePlugin(manifest=make_manifest())
    engine = make_engine(plugin=plugin)
    connection = make_connection(last_sync_at="2026-01-02T00:00:00+00:00")

    report = await engine.report(connection)

    assert report.provider_identity == IDENTITY
    assert report.connection_id == "conn_1"
    assert report.state == ConnectionState.CONNECTED
    assert report.readiness.level == 3
    assert report.last_sync_at == "2026-01-02T00:00:00+00:00"
    assert report.error_count == 0
    assert report.last_error is None


@pytest.mark.asyncio
async def test_report_sync_failed_state_and_error_signals():
    """Stored error counters surface when a connection record carries them."""
    plugin = FakePlugin(manifest=make_manifest())
    engine = make_engine(plugin=plugin)
    connection = SimpleNamespace(
        provider_identity=IDENTITY,
        connection_id="conn_1",
        state=ConnectionState.SYNC_FAILED,
        last_successful_sync_at=None,
        last_webhook_at=None,
        rate_limit=None,
        error_count=3,
        last_error="provider pull failed: 500",
    )

    report = await engine.report(connection)

    assert report.state == ConnectionState.SYNC_FAILED
    assert report.error_count == 3
    assert report.last_error == "provider pull failed: 500"
    assert report.last_sync_at is None


@pytest.mark.asyncio
async def test_report_missing_plugin_raises():
    engine = HealthEngine(registry=FakeRegistry({}))
    with pytest.raises(ProviderNotInstalled):
        await engine.report(make_connection())


@pytest.mark.asyncio
async def test_report_manifest_without_readiness_raises():
    plugin = FakePlugin(manifest=SimpleNamespace())  # no .readiness declaration
    engine = make_engine(plugin=plugin)
    with pytest.raises(ProviderNotInstalled):
        await engine.report(make_connection())
