"""Tests for the merged manifest surface (catalog + installed plugins).

Team C seam: ``services.provider_runtime.manifest_service``.
"""

from __future__ import annotations

import pytest

from shared.integration_contracts.catalog import manifest_by_identity

from services.provider_runtime.legacy import LegacyConnectorPlugin
from services.provider_runtime.manifest_service import ManifestService
from services.provider_runtime.registry import ProviderRegistry
from services.providers.shopify.plugin import ShopifyOrdersPlugin


def _fresh_service():
    registry = ProviderRegistry(auto_install_legacy=False)
    return registry, ManifestService(registry)


def test_merged_manifests_includes_catalog() -> None:
    _, service = _fresh_service()
    merged = service.merged_manifests()
    assert merged == manifest_by_identity  # nothing installed yet


def test_merged_includes_installed_plugin() -> None:
    registry, service = _fresh_service()
    registry.register(ShopifyOrdersPlugin(), source="local")
    merged = service.merged_manifests()
    assert "shopify.admin.orders_read" in merged
    assert merged["shopify.admin.orders_read"].provider_family == "shopify"


def test_merged_dedupes_byte_identical_legacy_plugins() -> None:
    """Legacy re-derivation collides with the catalog byte-for-byte -> dedupe."""
    from services.integrations.connectors.registry import CONNECTORS

    registry, service = _fresh_service()
    registry.register(LegacyConnectorPlugin(CONNECTORS["klaviyo"]), source="legacy")
    registry.register(LegacyConnectorPlugin(CONNECTORS["shopify"]), source="legacy")
    merged = service.merged_manifests()
    # Same identity -> still one entry (the catalog's), no duplicate claims.
    assert merged["klaviyo.ingestion.connector"].display_name == "Klaviyo"


def test_merged_rejects_conflicting_collision() -> None:
    from services.integrations.connectors.registry import CONNECTORS

    registry, service = _fresh_service()

    class ConflictingKlaviyo(LegacyConnectorPlugin):
        def manifest(self):
            return super().manifest().model_copy(update={"display_name": "Not Klaviyo"})

    # The registry itself already rejects the catalog conflict at register time,
    # so force it in by seeding the registry store directly (defensive path).
    plugin = ConflictingKlaviyo(CONNECTORS["klaviyo"])
    registry._plugins["klaviyo.ingestion.connector"] = plugin  # noqa: SLF001 - test seam
    registry._sources["klaviyo.ingestion.connector"] = "conflict"  # noqa: SLF001
    with pytest.raises(ValueError):
        service.merged_manifests()


def test_catalog_and_installed_helpers() -> None:
    registry, service = _fresh_service()
    registry.register(ShopifyOrdersPlugin(), source="local")
    assert service.catalog() == manifest_by_identity
    assert "shopify.admin.orders_read" in service.installed()
    # catalog() is a snapshot; mutating it does not touch the real catalog.
    snapshot = service.catalog()
    snapshot.clear()
    assert service.catalog()


def test_default_singleton_service_is_wired() -> None:
    from services.provider_runtime.manifest_service import manifest_service

    assert isinstance(manifest_service, ManifestService)
    assert isinstance(manifest_service.merged_manifests(), dict)
