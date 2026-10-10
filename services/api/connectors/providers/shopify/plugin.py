"""Shopify orders capability plugin — the reference provider plugin for the UPR.

Identity: ``shopify.admin.orders_read`` (family ``shopify``, product ``admin``,
capability ``orders_read``). The manifest declares auth/account/pull/webhook
true and report/stream/reconciliation false. It remains credential-waiting and
environment-hidden until recorded replay or sandbox evidence establishes a
higher readiness level. REST Basic and GraphQL token modes are explicit
alternative credential profiles.

``connectors.provider_runtime.plugin`` (Team C: :class:`BaseProviderPlugin` /
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
    CredentialProfileSpec,
    CredentialFieldSpec,
    Deployment,
    EnvironmentAvailability,
    ManifestReadiness,
    ProviderManifest,
    Sync,
    Webhooks,
)
from shared.integration_contracts.normalization import EventNormalizer
from shared.integration_contracts.streams import StreamDescriptor
from shared.privacy.classification import DataClassification

from connectors.providers.shopify.account import ShopifyAccountAdapter
from connectors.providers.shopify.auth import ShopifyAuthAdapter
from connectors.providers.shopify.normalizer import ShopifyOrderNormalizer
from connectors.providers.shopify.pull import ShopifyPullAdapter
from connectors.providers.shopify.webhook import ShopifyWebhookAdapter
from connectors.providers.shopify.webhook import SHOPIFY_ORDER_WEBHOOK_TOPICS

try:
    from connectors.provider_runtime.plugin import BaseProviderPlugin
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
        return ProviderIdentity(family="shopify", product="admin", capability="orders_read")

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="shopify",
            product_id="admin",
            capability_id="orders_read",
            display_name="Shopify Orders",
            # category mirrors the legacy ShopifyConnector.category.
            category="commerce",
            readiness=ManifestReadiness(
                # Synthetic tests do not establish provider replay or sandbox
                # evidence. Certification caps CREDENTIAL_WAITING at level 2.
                state=CredentialReadiness.CREDENTIAL_WAITING,
                level=2,
            ),
            availability=Availability(
                tenant_self_service=False,
                environments=EnvironmentAvailability(),
            ),
            authentication=Authentication(
                type="api_key",
                credential_schema=[
                    # REST and GraphQL use different credential shapes;
                    # validate_credentials enforces the selected transport.
                    CredentialFieldSpec(name="api_key", type="secret", required=False, secret=True),
                    CredentialFieldSpec(
                        name="password", type="secret", required=False, secret=True
                    ),
                    CredentialFieldSpec(
                        name="shop_domain", type="string", required=False, secret=False
                    ),
                    CredentialFieldSpec(
                        name="shop_access_token", type="secret", required=False, secret=True
                    ),
                    # Poll-only profiles do not need a webhook secret. The
                    # rest_webhook profile requires it before that connection
                    # mode can pass credential validation.
                    CredentialFieldSpec(
                        name="webhook_secret", type="secret", required=False, secret=True
                    ),
                ],
                credential_profiles=[
                    CredentialProfileSpec(
                        name="rest_basic",
                        mode_field="orders_api",
                        mode_value="rest",
                        required_fields=["api_key", "password"],
                    ),
                    CredentialProfileSpec(
                        name="rest_hmac_webhooks",
                        mode_field="orders_api",
                        mode_value="rest_webhook",
                        required_fields=["api_key", "password", "webhook_secret"],
                    ),
                    CredentialProfileSpec(
                        name="graphql_token",
                        mode_field="orders_api",
                        mode_value="graphql",
                        required_fields=["shop_access_token"],
                    ),
                ],
            ),
            configuration=Configuration(
                fields=[
                    # A structured MultiCredential carries secrets only;
                    # the validated shop host may live in non-secret config.
                    ConfigFieldSpec(name="shop_domain", type="string", required=False),
                    ConfigFieldSpec(name="api_version", type="string", required=False),
                    ConfigFieldSpec(
                        name="orders_api",
                        type="enum",
                        required=False,
                        # `rest` and `graphql` are pull-only; rest_webhook
                        # explicitly configures REST plus signed webhooks.
                        allowed_values=["rest", "rest_webhook", "graphql"],
                        default_value="rest",
                    ),
                    ConfigFieldSpec(name="updated_since", type="string", required=False),
                    ConfigFieldSpec(
                        name="source_account_realm",
                        type="enum",
                        required=False,
                        allowed_values=["live", "test"],
                    ),
                ]
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(
                supported=True,
                registration_supported=False,
                verification_scheme="shopify_hmac",
            ),
            sync=Sync(
                initial_backfill=True, incremental=True, reconciliation=False, cursor="updated_at"
            ),
            streams=[
                StreamDescriptor(
                    stream_id="orders_rest",
                    object_kind="order",
                    domain_pack="commerce",
                    acquisition_modes=("pull",),
                    output_contract="bronze.provider_events",
                    source_authority_class="commerce.store_order",
                    data_classification=DataClassification.SENSITIVE_PII,
                    required_scopes=(),
                    cursor_scheme="shopify-rest-v1",
                    initial_backfill=True,
                    incremental=True,
                    # The manifest's orders_api default selects this stream
                    # when the connection omits an explicit mode.
                    enabled_by_default=False,
                    activation_config_field="orders_api",
                    activation_config_value="rest",
                ),
                StreamDescriptor(
                    stream_id="orders_rest_webhook",
                    object_kind="order",
                    domain_pack="commerce",
                    acquisition_modes=("pull",),
                    output_contract="bronze.provider_events",
                    source_authority_class="commerce.store_order",
                    data_classification=DataClassification.SENSITIVE_PII,
                    required_scopes=(),
                    cursor_scheme="shopify-rest-v1",
                    initial_backfill=True,
                    incremental=True,
                    enabled_by_default=False,
                    activation_config_field="orders_api",
                    activation_config_value="rest_webhook",
                ),
                StreamDescriptor(
                    stream_id="orders",
                    object_kind="order",
                    domain_pack="commerce",
                    acquisition_modes=("pull",),
                    output_contract="bronze.provider_events",
                    source_authority_class="commerce.store_order",
                    data_classification=DataClassification.SENSITIVE_PII,
                    # StreamDescriptor.required_scopes is restricted to
                    # OAuth2 manifests. GraphQL checks read_orders at
                    # connection test, account discovery, and pull time; it
                    # requires read_all_orders only for older history. The
                    # REST Basic profile relies on Shopify's endpoint response
                    # for its configured app permissions.
                    required_scopes=(),
                    cursor_scheme="shopify-gql-v1",
                    initial_backfill=True,
                    incremental=True,
                    # Keep the GraphQL snapshot stream out of scheduled pulls
                    # for existing REST and webhook connections. A connection
                    # opts in explicitly with orders_api=graphql.
                    enabled_by_default=False,
                    activation_config_field="orders_api",
                    activation_config_value="graphql",
                ),
                StreamDescriptor(
                    stream_id="orders_webhook",
                    object_kind="order",
                    domain_pack="commerce",
                    acquisition_modes=("webhook",),
                    output_contract="bronze.provider_events",
                    source_authority_class="commerce.store_order",
                    data_classification=DataClassification.SENSITIVE_PII,
                    required_scopes=(),
                    webhook_topics=SHOPIFY_ORDER_WEBHOOK_TOPICS,
                    # Webhook ingress is enabled only for the explicit
                    # HMAC-enabled REST profile. The GraphQL stream above is
                    # a separate poll-only stream.
                    enabled_by_default=False,
                    activation_config_field="orders_api",
                    activation_config_value="rest_webhook",
                ),
            ],
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
