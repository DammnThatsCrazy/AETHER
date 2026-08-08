"""Tests for the provider plugin base class + module-level registration hook.

Team C seam: ``services.provider_runtime.plugin``.
"""

from __future__ import annotations

import pytest

from shared.integration_contracts.capabilities import (
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    ReconciliationAdapter,
    ReportAdapter,
    StreamAdapter,
    WebhookAdapter,
)
from shared.integration_contracts.identity import (
    CapabilityId,
    ProductId,
    ProviderFamily,
    ProviderIdentity,
)
from shared.integration_contracts.normalization import (
    EventNormalizer,
    NormalizationResult,
)
from shared.integration_contracts.plugin import PluginValidationError

from services.provider_runtime.plugin import (
    LOCAL_PLUGIN_MODULES,
    BaseProviderPlugin,
    clear_registered_providers,
    plugin_version,
    register_provider,
    registered_providers,
)


@pytest.fixture(autouse=True)
def _preserve_plugin_store():
    """Restore the module-level plugin store after each test.

    The module store is process-global mutable state that other test files (and
    the registry's ``load_all``) read. ``clear_registered_providers`` is a test
    seam — snap it before and restore after so this file's tests never poison
    the state other tests depend on.
    """
    before = registered_providers()
    yield
    clear_registered_providers()
    for plugin in before.values():
        register_provider(plugin)


def _identity(family: str = "testco") -> ProviderIdentity:
    return ProviderIdentity(
        family=ProviderFamily(family),
        product=ProductId("ingestion"),
        capability=CapabilityId("connector"),
    )


def _honest_manifest(family: str = "testco"):
    """A validate_manifest-clean ProviderManifest for the test family."""
    from shared.certification.readiness import CredentialReadiness
    from shared.integration_contracts.manifest import (
        Authentication,
        Availability,
        CredentialFieldSpec,
        EnvironmentAvailability,
        ManifestReadiness,
        ProviderManifest,
        Sync,
        Webhooks,
    )

    return ProviderManifest(
        provider_family=family,
        product_id="ingestion",
        capability_id="connector",
        display_name="Test Co",
        category="messaging",
        readiness=ManifestReadiness(
            state=CredentialReadiness.REPLAY_VALIDATED, level=3
        ),
        availability=Availability(
            environments=EnvironmentAvailability(local=True, integration=True)
        ),
        authentication=Authentication(
            type="api_key",
            credential_schema=[
                CredentialFieldSpec(name="api_key", type="secret", secret=True)
            ],
        ),
        webhooks=Webhooks(supported=True, verification_scheme="hmac"),
        sync=Sync(incremental=True, cursor="updated_at"),
        data_outputs=["bronze.connector_events"],
        product_destinations=[],
    )


class _TrivialNormalizer(EventNormalizer):
    def normalize(self, raw) -> NormalizationResult:
        return NormalizationResult()


class MinimalPlugin(BaseProviderPlugin):
    """Concrete plugin: identity/manifest/normalizer + a couple of adapters."""

    def __init__(self, *, family: str = "testco", identity=None) -> None:
        self._identity = identity or _identity(family)

    def identity(self) -> ProviderIdentity:
        return self._identity

    def manifest(self):
        return _honest_manifest(self._identity.family)

    def normalizer(self) -> EventNormalizer:
        return _TrivialNormalizer()

    def auth(self):
        return object()

    def pull(self):
        return object()


class EmptyPlugin(MinimalPlugin):
    """Plugin exposing no adapters at all."""


def test_base_plugin_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseProviderPlugin()  # type: ignore[abstract]


def test_plugin_version_constant() -> None:
    assert plugin_version == "1"


def test_local_plugin_modules_include_shopify() -> None:
    assert "services.providers.shopify" in LOCAL_PLUGIN_MODULES


def test_default_accessors_return_none() -> None:
    plugin = EmptyPlugin()
    # The three not-overridden capability accessors must default to None so the
    # honest surface is structural (capability_set derives from non-None).
    assert plugin.report() is None
    assert plugin.stream() is None
    assert plugin.reconciliation() is None
    assert plugin.account() is None
    assert plugin.webhook() is None


def test_override_accessors_return_adapters() -> None:
    plugin = MinimalPlugin()
    assert plugin.auth() is not None
    assert plugin.pull() is not None
    # Honest None defaults for the rest.
    assert plugin.account() is None
    assert plugin.webhook() is None
    assert plugin.report() is None
    assert plugin.stream() is None
    assert plugin.reconciliation() is None


def test_register_provider_returns_key_and_stores() -> None:
    clear_registered_providers()
    plugin = MinimalPlugin()
    key = register_provider(plugin)
    assert key == "testco.ingestion.connector"
    assert registered_providers()[key] is plugin


def test_register_provider_idempotent_same_object() -> None:
    clear_registered_providers()
    plugin = MinimalPlugin()
    first = register_provider(plugin)
    second = register_provider(plugin)
    assert first == second == "testco.ingestion.connector"
    assert len(registered_providers()) == 1


def test_register_provider_rejects_conflicting_object() -> None:
    clear_registered_providers()
    register_provider(MinimalPlugin())
    with pytest.raises(PluginValidationError):
        register_provider(MinimalPlugin())


def test_registered_providers_returns_snapshot() -> None:
    clear_registered_providers()
    register_provider(MinimalPlugin())
    snapshot = registered_providers()
    snapshot.clear()
    # The store is untouched by mutating the caller's copy.
    assert len(registered_providers()) == 1


def test_plugin_is_structural_protocol() -> None:
    """BaseProviderPlugin subclasses satisfy the runtime_checkable protocol."""
    from shared.integration_contracts.plugin import ProviderPlugin

    plugin = MinimalPlugin()
    assert isinstance(plugin, ProviderPlugin)
