"""Provider plugin contract: runtime_checkable protocol, identity cross-check, capability set."""

from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.capabilities import AuthAdapter
from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    Availability,
    ConfigFieldSpec,
    Configuration,
    CredentialFieldSpec,
    Deployment,
    EnvironmentAvailability,
    ManifestReadiness,
    OAuthSpec,
    ProviderManifest,
    Sync,
    Webhooks,
    validate_manifest,
)
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.plugin import (
    CapabilitySet,
    PluginValidationError,
    ProviderPlugin,
    capability_set,
    plugin_identity_key,
)


# ── fixtures ────────────────────────────────────────────────────────────────


def _valid_manifest(provider_family: str = "shopify", capability_id: str = "orders_read") -> ProviderManifest:
    m = ProviderManifest(
        provider_family=provider_family,
        product_id="admin",
        capability_id=capability_id,
        display_name="Shopify Orders (read)",
        category="commerce",
        readiness=ManifestReadiness(
            state=CredentialReadiness.SANDBOX_VALIDATED, level=4
        ),
        availability=Availability(
            tenant_self_service=True,
            environments=EnvironmentAvailability(local=True, integration=True),
        ),
        authentication=Authentication(
            type="oauth2",
            credential_schema=[
                CredentialFieldSpec(name="access_token", type="oauth_token", secret=True)
            ],
            oauth=OAuthSpec(pkce=True, scopes=["read_orders"], refresh_supported=True),
        ),
        configuration=Configuration(
            fields=[ConfigFieldSpec(name="shop_domain", type="string", required=True)]
        ),
        accounts=Accounts(discovery_supported=True, selection_required=True),
        webhooks=Webhooks(
            supported=True,
            registration_supported=True,
            verification_scheme="hmac_sha256",
        ),
        sync=Sync(initial_backfill=True, incremental=True, cursor="updated_at"),
        data_outputs=["order.created", "order.updated"],
        product_destinations=["graph", "lake"],
        deployment=Deployment(
            required_secrets=["SHOPIFY_CLIENT_SECRET"],
            required_public_urls=["https://app/oauth/callback"],
            provider_registration_steps=["Create a custom app"],
        ),
    )
    return validate_manifest(m)


class _AuthAdapterStub:
    async def validate_credentials(self, context: object) -> object:
        return None

    async def test(self, context: object) -> object:
        return None


class _NormalizerStub:
    def normalize(self, raw: object) -> NormalizationResult:
        return NormalizationResult()


class _ShopifyOrdersPlugin:
    """A complete, honest plugin: auth-only plus a normalizer."""

    def __init__(self, *, identity_key: str | None = None) -> None:
        self._manifest = _valid_manifest()
        self._identity = ProviderIdentity(
            family="shopify", product="admin", capability="orders_read"
        )
        if identity_key is not None:
            # Force a divergence between manifest and identity (dishonest plugin).
            self._manifest = self._manifest.model_copy(
                update={"capability_id": identity_key.split(".")[2]}
            )

    def identity(self) -> ProviderIdentity:
        return self._identity

    def manifest(self) -> ProviderManifest:
        return self._manifest

    def auth(self) -> AuthAdapter | None:
        return _AuthAdapterStub()

    def account(self) -> object:
        return None

    def pull(self) -> object:
        return None

    def webhook(self) -> object:
        return None

    def report(self) -> object:
        return None

    def stream(self) -> object:
        return None

    def reconciliation(self) -> object:
        return None

    def normalizer(self) -> object:
        return _NormalizerStub()


# ── CapabilitySet ───────────────────────────────────────────────────────────


def test_capability_set_defaults_to_all_false() -> None:
    cs = CapabilitySet()
    for field in cs.model_fields:
        assert getattr(cs, field) is False


def test_capability_set_is_frozen() -> None:
    cs = CapabilitySet(auth=True)
    with pytest.raises(Exception):
        cs.auth = False  # type: ignore[misc]
    assert cs.auth is True


def test_capability_set_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        CapabilitySet(unexpected=True)  # type: ignore[call-arg]


# ── PluginValidationError ───────────────────────────────────────────────────


def test_plugin_validation_error_carries_violations() -> None:
    err = PluginValidationError(["a", "b"])
    assert err.violations == ["a", "b"]
    assert str(err) == "a; b"


# ── ProviderPlugin protocol (runtime_checkable) ─────────────────────────────


def test_plugin_passes_isinstance() -> None:
    plugin = _ShopifyOrdersPlugin()
    assert isinstance(plugin, ProviderPlugin)


def test_plugin_isinstance_rejects_incomplete_object() -> None:
    class _Incomplete:
        def identity(self) -> ProviderIdentity:  # missing every other method
            return ProviderIdentity(family="a", product="b", capability="c")

    assert not isinstance(_Incomplete(), ProviderPlugin)


def test_plugin_isinstance_works_without_subclassing() -> None:
    # Structural conformance: a plain class exposing every accessor qualifies.
    plugin = _ShopifyOrdersPlugin()
    assert isinstance(plugin, ProviderPlugin)


# ── plugin_identity_key ─────────────────────────────────────────────────────


def test_plugin_identity_key_returns_manifest_key_when_consistent() -> None:
    plugin = _ShopifyOrdersPlugin()
    assert plugin_identity_key(plugin) == "shopify.admin.orders_read"
    assert plugin_identity_key(plugin) == plugin.identity().key


def test_plugin_identity_key_raises_on_mismatch() -> None:
    # identity() says orders_read; manifest says orders_write.
    plugin = _ShopifyOrdersPlugin(identity_key="shopify.admin.orders_write")
    try:
        plugin_identity_key(plugin)
    except PluginValidationError as exc:
        assert any("identity_key" in v for v in exc.violations)
    else:
        raise AssertionError("mismatched plugin identity must raise PluginValidationError")


# ── capability_set ──────────────────────────────────────────────────────────


def test_capability_set_reflects_accessors_honestly() -> None:
    plugin = _ShopifyOrdersPlugin()
    cs = capability_set(plugin)
    assert cs.auth is True  # auth() returns a non-None adapter
    for field in ("account", "pull", "webhook", "report", "stream", "reconciliation"):
        assert getattr(cs, field) is False


def test_capability_set_for_all_false_plugin() -> None:
    class _MinimalPlugin:
        def identity(self) -> ProviderIdentity:
            return ProviderIdentity(family="a", product="b", capability="c")

        def manifest(self) -> ProviderManifest:
            return _valid_manifest(provider_family="a", capability_id="c")

        def auth(self) -> object:
            return None

        def account(self) -> object:
            return None

        def pull(self) -> object:
            return None

        def webhook(self) -> object:
            return None

        def report(self) -> object:
            return None

        def stream(self) -> object:
            return None

        def reconciliation(self) -> object:
            return None

        def normalizer(self) -> object:
            return _NormalizerStub()

    cs = capability_set(_MinimalPlugin())
    assert cs == CapabilitySet()
