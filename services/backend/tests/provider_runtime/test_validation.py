"""Tests for §32 plugin honesty validation (manifest claims vs adapters).

Team C seam: ``services.provider_runtime.validation``. The real ShopifyOrders
plugin (Team G) is the honest reference; the dishonest fixtures flip one claim
or one adapter at a time so each rule is exercised in isolation.
"""

from __future__ import annotations

import pytest

from shared.integration_contracts.manifest import (
    ManifestReadiness,
    ProviderManifest,
    Sync,
)
from shared.integration_contracts.plugin import PluginValidationError
from shared.integration_contracts.streams import StreamDescriptor
from shared.privacy.classification import DataClassification

from services.provider_runtime.validation import (
    assert_plugin_honest,
    capability_violations,
)
from services.providers.shopify.plugin import ShopifyOrdersPlugin


def test_honest_shopify_plugin_has_no_violations() -> None:
    plugin = ShopifyOrdersPlugin()
    assert capability_violations(plugin) == []
    assert_plugin_honest(plugin)  # does not raise


def _declared_shopify_stream(**overrides: object) -> StreamDescriptor:
    values: dict[str, object] = dict(
        stream_id="orders",
        object_kind="order",
        domain_pack="commerce",
        acquisition_modes=("pull", "webhook"),
        output_contract="bronze.provider_events",
        source_authority_class="commerce_order",
        data_classification=DataClassification.SENSITIVE_PII,
        cursor_scheme="updated_at_and_id",
        webhook_topics=("orders/create",),
        initial_backfill=True,
        incremental=True,
    )
    values.update(overrides)
    return StreamDescriptor(**values)  # type: ignore[arg-type]


class _DeclaredShopifyPlugin(ShopifyOrdersPlugin):
    def manifest(self):
        return super().manifest().model_copy(update={"streams": [_declared_shopify_stream()]})


class _MissingReportAdapterPlugin(_DeclaredShopifyPlugin):
    def manifest(self):
        base = super().manifest()
        return base.model_copy(
            update={
                "streams": [
                    *base.streams,
                    _declared_shopify_stream(
                        stream_id="reports",
                        object_kind="order_report",
                        acquisition_modes=("report",),
                        webhook_topics=(),
                        initial_backfill=False,
                        incremental=False,
                    ),
                ]
            }
        )


class _HiddenReportAdapterPlugin(_DeclaredShopifyPlugin):
    def report(self):
        return object()


class _MissingStreamAdapterPlugin(_DeclaredShopifyPlugin):
    def manifest(self):
        base = super().manifest()
        return base.model_copy(
            update={
                "streams": [
                    *base.streams,
                    _declared_shopify_stream(
                        stream_id="continuous_orders",
                        object_kind="order",
                        acquisition_modes=("stream",),
                        webhook_topics=(),
                        initial_backfill=False,
                        incremental=False,
                    ),
                ]
            }
        )


class _HiddenStreamAdapterPlugin(_DeclaredShopifyPlugin):
    def stream(self):
        return object()


def test_declared_streams_with_installed_adapters_are_honest() -> None:
    assert capability_violations(_DeclaredShopifyPlugin()) == []


@pytest.mark.parametrize(
    ("plugin", "needle"),
    [
        (_MissingReportAdapterPlugin(), "no report() adapter"),
        (_HiddenReportAdapterPlugin(), "no declared stream claims report"),
        (_MissingStreamAdapterPlugin(), "no stream() adapter"),
        (_HiddenStreamAdapterPlugin(), "no declared stream claims stream"),
    ],
)
def test_explicit_stream_modes_match_present_adapters(
    plugin: ShopifyOrdersPlugin, needle: str
) -> None:
    violations = capability_violations(plugin)
    assert any(needle in v for v in violations)


class _NoWebhookAdapterPlugin(ShopifyOrdersPlugin):
    """Dishonest: manifest claims webhooks.supported but no webhook adapter."""

    def webhook(self):
        return None


class _UnclaimedPullAdapterPlugin(ShopifyOrdersPlugin):
    """Dishonest: exposes a pull() adapter the manifest does not claim."""

    def manifest(self):
        base = super().manifest()
        return base.model_copy(
            update={
                "streams": [],
                "sync": Sync(initial_backfill=False, incremental=False),
            }
        )


class _NoCursorManifestPlugin(ShopifyOrdersPlugin):
    """Dishonest at the manifest level: incremental stream without a cursor."""

    def manifest(self):
        base = super().manifest()
        return base.model_copy(
            update={
                "streams": [
                    stream.model_copy(update={"cursor_scheme": ""}) for stream in base.streams
                ]
            }
        )


class _NoWebhookSchemeManifestPlugin(ShopifyOrdersPlugin):
    """Dishonest at the manifest level: webhooks supported without a scheme."""

    def manifest(self):
        from shared.integration_contracts.manifest import Webhooks

        base = super().manifest()
        return base.model_copy(
            update={"webhooks": Webhooks(supported=True, verification_scheme="")}
        )


class _IdentityMismatchPlugin(ShopifyOrdersPlugin):
    """Dishonest: identity().key differs from manifest().identity_key."""

    def identity(self):
        from shared.integration_contracts.identity import (
            CapabilityId,
            ProductId,
            ProviderFamily,
            ProviderIdentity,
        )

        return ProviderIdentity(
            family=ProviderFamily("shopify"),
            product=ProductId("admin"),
            capability=CapabilityId("other_read"),  # != manifest orders_read
        )


class _BrokenAuthPlugin(ShopifyOrdersPlugin):
    """A raising accessor is itself a violation, never a silent pass."""

    def auth(self):
        raise RuntimeError("adapter factory exploded")


class _BrokenIdentityPlugin(ShopifyOrdersPlugin):
    """An ``identity()`` that raises must surface as a violation, not propagate."""

    def identity(self):
        raise RuntimeError("identity factory exploded")


def test_missing_adapter_for_claimed_capability() -> None:
    violations = capability_violations(_NoWebhookAdapterPlugin())
    assert any("webhook" in v and "no adapter" in v for v in violations)


def test_adapter_present_but_capability_unclaimed() -> None:
    violations = capability_violations(_UnclaimedPullAdapterPlugin())
    assert any("pull() adapter" in v and "does not claim" in v for v in violations)


def test_manifest_level_violation_is_surfaced() -> None:
    violations = capability_violations(_NoCursorManifestPlugin())
    assert any("cursor" in v for v in violations)
    assert any("incremental" in v for v in violations)


def test_webhook_scheme_missing_is_surfaced() -> None:
    violations = capability_violations(_NoWebhookSchemeManifestPlugin())
    assert any("verification_scheme" in v for v in violations)


def test_identity_mismatch_is_a_violation() -> None:
    violations = capability_violations(_IdentityMismatchPlugin())
    assert any("identity_key" in v for v in violations)


def test_raising_accessor_is_a_violation() -> None:
    violations = capability_violations(_BrokenAuthPlugin())
    assert any("raised" in v for v in violations)


def test_raising_identity_is_a_violation_not_a_propagated_error() -> None:
    violations = capability_violations(_BrokenIdentityPlugin())
    assert any("identity cross-check raised" in v for v in violations)
    # And assert_plugin_honest still raises the typed error, not a raw RuntimeError.
    with pytest.raises(PluginValidationError):
        assert_plugin_honest(_BrokenIdentityPlugin())


def test_assert_plugin_honest_collects_all_violations() -> None:
    with pytest.raises(PluginValidationError) as excinfo:
        assert_plugin_honest(_NoWebhookAdapterPlugin())
    assert excinfo.value.violations
    assert all(isinstance(v, str) for v in excinfo.value.violations)


def test_assert_plugin_honest_passes_clean_plugin() -> None:
    assert_plugin_honest(ShopifyOrdersPlugin())


def test_readiness_level_on_honest_manifest() -> None:
    """A credential-waiting connector stays hidden until replay evidence exists."""
    manifest: ProviderManifest = ShopifyOrdersPlugin().manifest()
    assert isinstance(manifest.readiness, ManifestReadiness)
    assert manifest.readiness.level == 2
    assert manifest.availability.environments.any_enabled() is False
