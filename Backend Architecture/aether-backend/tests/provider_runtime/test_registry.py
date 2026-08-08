"""Tests for the provider registry — honest registration, collisions, loading.

Team C seam: ``services.provider_runtime.registry``.
"""

from __future__ import annotations

import pytest

from shared.integration_contracts.plugin import PluginValidationError

from services.provider_runtime.errors import ProviderNotInstalled
from services.provider_runtime.legacy import LegacyConnectorPlugin
from services.provider_runtime.registry import (
    ProviderRegistry,
    provider_registry,
    registry,
)
from services.providers.shopify.plugin import ShopifyOrdersPlugin


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Each test gets a fresh registry with the legacy install disabled where
    the test wants to control registration itself."""
    r = ProviderRegistry(auto_install_legacy=False)
    yield r


def test_register_get_list_manifests_sources(_isolated_registry) -> None:
    r = _isolated_registry
    key = r.register(ShopifyOrdersPlugin(), source="test")
    assert key == "shopify.admin.orders_read"
    assert r.get(key) is not None
    assert key in r
    assert r.require(key) is r.get(key)
    assert r.list() == [r.get(key)]
    assert key in r.manifests()
    assert r.sources() == {key: "test"}
    assert len(r) == 1


def test_require_missing_raises(_isolated_registry) -> None:
    with pytest.raises(ProviderNotInstalled):
        _isolated_registry.require("ghost.product.cap")


def test_register_dishonest_plugin_raises(_isolated_registry) -> None:
    r = _isolated_registry

    class Dishonest(ShopifyOrdersPlugin):
        def webhook(self):
            return None  # manifest claims webhooks.supported

    with pytest.raises(PluginValidationError) as excinfo:
        r.register(Dishonest(), source="bad")
    assert excinfo.value.violations


def test_register_duplicate_key_different_object_raises(_isolated_registry) -> None:
    r = _isolated_registry
    r.register(ShopifyOrdersPlugin(), source="a")
    with pytest.raises(PluginValidationError) as excinfo:
        r.register(ShopifyOrdersPlugin(), source="b")
    assert any("duplicate" in v for v in excinfo.value.violations)


def test_register_same_object_is_idempotent(_isolated_registry) -> None:
    r = _isolated_registry
    plugin = ShopifyOrdersPlugin()
    first = r.register(plugin, source="a")
    second = r.register(plugin, source="b")
    assert first == second
    assert len(r) == 1
    assert r.sources()[first] == "a"  # first registration's source is kept


def test_catalog_byte_identical_collision_is_allowed(_isolated_registry) -> None:
    """A legacy plugin re-derives the catalog manifest byte-for-byte -> allowed."""
    from services.integrations.connectors.registry import CONNECTORS

    r = _isolated_registry
    key = r.register(LegacyConnectorPlugin(CONNECTORS["klaviyo"]), source="legacy")
    assert key == "klaviyo.ingestion.connector"


def test_catalog_conflicting_collision_raises(_isolated_registry) -> None:
    """Same identity as a catalog manifest but a different manifest -> rejected."""
    from services.integrations.connectors.registry import CONNECTORS

    r = _isolated_registry

    class ConflictingKlaviyo(LegacyConnectorPlugin):
        def manifest(self):
            return super().manifest().model_copy(update={"display_name": "Not Klaviyo"})

    with pytest.raises(PluginValidationError) as excinfo:
        r.register(ConflictingKlaviyo(CONNECTORS["klaviyo"]), source="conflict")
    assert any("catalog" in v for v in excinfo.value.violations)


def test_discover_entry_points_disabled_by_default() -> None:
    assert ProviderRegistry().discover_entry_points() == []


def test_load_all_installs_local_and_legacy() -> None:
    from services.integrations.connectors.registry import CONNECTORS

    r = ProviderRegistry()  # auto_install_legacy=True by default
    n = r.load_all()
    # Exactly one local plugin (Shopify) + every connector in the live registry
    # — asserted against the real CONNECTORS count, never a hardcoded number.
    assert n == 1 + len(CONNECTORS)
    assert "shopify.admin.orders_read" in r
    assert "klaviyo.ingestion.connector" in r
    assert r.sources()["shopify.admin.orders_read"] == "local"
    assert r.sources()["klaviyo.ingestion.connector"] == "legacy"


def test_load_all_is_idempotent() -> None:
    r = ProviderRegistry()
    first = r.load_all()
    second = r.load_all()
    assert first == second == len(r)


def test_load_all_guards_broken_entry_point_module(monkeypatch) -> None:
    r = ProviderRegistry()
    monkeypatch.setattr(r, "entry_points_enabled", True)
    monkeypatch.setattr(r, "discover_entry_points", lambda: ["totally.bogus.module"])
    # A broken optional plugin module must be logged and skipped — never fatal —
    # and the legacy install still runs.
    n = r.load_all()
    assert "klaviyo.ingestion.connector" in r
    assert n == len(r)


def test_singleton_aliases() -> None:
    assert registry is provider_registry
    assert isinstance(provider_registry, ProviderRegistry)
