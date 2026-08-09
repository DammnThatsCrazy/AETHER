"""Shopify orders capability plugin — the reference provider plugin for the UPR.

Identity: ``shopify.admin.orders_read`` (family ``shopify``, product ``admin``,
capability ``orders_read``). The manifest declares the honest capability set —
auth/account/pull/webhook true, report/stream/reconciliation false — and passes
:func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`
(env-visible => level>=3, webhooks declare a verification scheme, incremental
sync declares its cursor).

``services.provider_runtime.plugin`` (Team C: :class:`BaseProviderPlugin` /
:func:`register_provider`) may not have landed yet. The import is guarded: when
the runtime base is present, :class:`ShopifyOrdersPlugin` inherits from it;
otherwise it degrades to a minimal protocol-compatible fallback that mirrors the
documented base contract (adapter accessors default to ``None``), so the
reference plugin stays importable and testable. No stub of Team C's module is
created.
"""

from __future__ import annotations

from typing import Optional

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.capabilities import (
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    WebhookAdapter,
)
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
    ProviderManifest,
    Sync,
    Webhooks,
)
from shared.integration_contracts.normalization import EventNormalizer

from services.providers.shopify.account import ShopifyAccountAdapter
from services.providers.shopify.auth import ShopifyAuthAdapter
from services.providers.shopify.normalizer import ShopifyOrderNormalizer
from services.providers.shopify.pull import ShopifyPullAdapter
from services.providers.shopify.webhook import ShopifyWebhookAdapter

try:
    from services.provider_runtime.plugin import BaseProviderPlugin
except ImportError:  # pragma: no cover - Team C has not landed yet
    BaseProviderPlugin = None  # type: ignore[assignment]


if BaseProviderPlugin is not None:
    _PluginBase = BaseProviderPlugin
else:  # pragma: no cover - exercised only before Team C lands
    class _PluginBase:
        """Minimal fallback mirroring BaseProviderPlugin's None-defaulting accessors."""

        def report(self) -> None:
            return None

        def stream(self) -> None:
            return None

        def reconciliation(self) -> None:
            return None


class ShopifyOrdersPlugin(_PluginBase):
    """Reference provider plugin: Shopify Orders (admin, orders_read)."""

    version = "1.0.0"  # used by certification

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family="shopify", product="admin", capability="orders_read"
        )

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="shopify",
            product_id="admin",
            capability_id="orders_read",
            display_name="Shopify Orders",
            # category mirrors the legacy ShopifyConnector.category.
            category="commerce",
            readiness=ManifestReadiness(
                state=CredentialReadiness.CREDENTIAL_WAITING, level=3
            ),
            availability=Availability(
                tenant_self_service=False,
                environments=EnvironmentAvailability(
                    local=True, integration=True, staging=False, production=False
                ),
            ),
            authentication=Authentication(
                type="api_key",
                credential_schema=[
                    CredentialFieldSpec(name="api_key", type="secret", required=True, secret=True),
                    CredentialFieldSpec(name="password", type="secret", required=True, secret=True),
                    CredentialFieldSpec(name="shop_domain", type="string", required=True, secret=False),
                    CredentialFieldSpec(name="shop_access_token", type="secret", required=False, secret=True),
                    # Webhook HMAC secret for X-Shopify-Hmac-SHA256 verification.
                    # Required to make the declared shopify_hmac scheme verifiable —
                    # without it the gateway would deny every delivery (no secret
                    # configured ⇒ cannot prove ownership of the webhook).
                    CredentialFieldSpec(name="webhook_secret", type="secret", required=True, secret=True),
                ],
            ),
            configuration=Configuration(
                fields=[ConfigFieldSpec(name="api_version", type="string", required=False)]
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(
                supported=True,
                registration_supported=False,
                verification_scheme="shopify_hmac",
            ),
            sync=Sync(initial_backfill=True, incremental=True, reconciliation=False, cursor="updated_at"),
            data_outputs=["bronze.provider_events"],
            product_destinations=[],
            deployment=Deployment(),
        )

    def normalizer(self) -> EventNormalizer:
        return ShopifyOrderNormalizer()

    def auth(self) -> Optional[AuthAdapter]:
        return ShopifyAuthAdapter()

    def account(self) -> Optional[AccountAdapter]:
        return ShopifyAccountAdapter()

    def pull(self) -> Optional[PullAdapter]:
        return ShopifyPullAdapter(provider_identity=self.identity().key)

    def webhook(self) -> Optional[WebhookAdapter]:
        return ShopifyWebhookAdapter(provider_identity=self.identity().key)

    # report() / stream() / reconciliation() -> None (inherited from the base).


__all__ = ["ShopifyOrdersPlugin"]
