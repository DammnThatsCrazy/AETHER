"""WooCommerce orders capability plugin (UPR follow-on, Team G).

Identity: ``woocommerce.admin.orders_read`` (family ``woocommerce``, product
``admin``, capability ``orders_read``). The manifest declares the honest
capability set — auth/account/pull/webhook true, report/stream/reconciliation
false — and passes :func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`.

WooCommerce is the ONE follow-on family whose API host is tenant-supplied (the
``site_url`` config field). The SSRF seam :func:`validated_https_host
<shared.security.ssrf.validated_https_host>` is used with an EMPTY allowlist
(the exception the program allows): the structural gate returns the public FQDN
of ``site_url`` or rejects it (loopback/private/IP/metadata/port/path tricks),
and the API path is pinned to ``/wp-json/wc/v3`` in code — never tenant input.
The structural gate is NOT a resolver-level DNS-rebinding defense; that check is
documented as required at live-auth time and is NOT claimed by this build (see
``services.providers.woocommerce.auth``).

Readiness is ``REPLAY_VALIDATED`` at level 3 — the evidence basis is the
offline fixture-replay determinism exercised by ``tests/unit/test_provider_plugins.py``,
not live verification. ``certification_state`` stays ``uncertified`` (best
``replay_certified`` via the offline :func:`certify_provider` harness). Live
steps (real Basic-auth round-trip, real webhook replay) are certification-level
follow-ons and are NOT claimed as build facts.
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

from services.providers.woocommerce.account import WooCommerceAccountAdapter
from services.providers.woocommerce.auth import WooCommerceAuthAdapter
from services.providers.woocommerce.normalizer import WooCommerceOrderNormalizer
from services.providers.woocommerce.pull import WooCommercePullAdapter
from services.providers.woocommerce.webhook import WooCommerceWebhookAdapter

try:
    from services.provider_runtime.plugin import BaseProviderPlugin
except ImportError:  # pragma: no cover - runtime not present in this runtime
    BaseProviderPlugin = None  # type: ignore[assignment]


if BaseProviderPlugin is not None:
    _PluginBase = BaseProviderPlugin
else:  # pragma: no cover - exercised only before the runtime lands
    class _PluginBase:
        """Minimal fallback mirroring BaseProviderPlugin's None-defaulting accessors."""

        def report(self) -> None:
            return None

        def stream(self) -> None:
            return None

        def reconciliation(self) -> None:
            return None


class WooCommerceOrdersPlugin(_PluginBase):
    """WooCommerce Orders (admin, orders_read) provider plugin."""

    version = "1.0.0"  # used by certification
    # Honest certification state: this build's evidence is structural + offline
    # fixture replay. Live round-trips would raise it to replay_certified/live.
    certification_state = "uncertified"

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family="woocommerce", product="admin", capability="orders_read"
        )

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="woocommerce",
            product_id="admin",
            capability_id="orders_read",
            display_name="WooCommerce Orders",
            category="commerce",
            readiness=ManifestReadiness(
                state=CredentialReadiness.REPLAY_VALIDATED, level=3
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
                    # REST consumer key/secret, presented as HTTP Basic auth.
                    CredentialFieldSpec(name="consumer_key", type="secret", required=True, secret=True),
                    CredentialFieldSpec(name="consumer_secret", type="secret", required=True, secret=True),
                    # Webhook HMAC secret for the X-WC-Webhook-Signature scheme.
                    CredentialFieldSpec(name="webhook_secret", type="secret", required=True, secret=True),
                ],
            ),
            configuration=Configuration(
                fields=[
                    # Tenant-supplied store origin; SSRF-gated via the S1 seam
                    # (empty allowlist — see the module docstring for the
                    # resolver-level caveat).
                    ConfigFieldSpec(name="site_url", type="url", required=True),
                ]
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(
                supported=True,
                registration_supported=False,
                verification_scheme="wc_hmac",
            ),
            sync=Sync(
                initial_backfill=True,
                incremental=True,
                reconciliation=False,
                cursor="date_modified",
            ),
            data_outputs=["bronze.provider_events"],
            product_destinations=[],
            deployment=Deployment(),
        )

    def normalizer(self) -> EventNormalizer:
        return WooCommerceOrderNormalizer()

    def auth(self) -> Optional[AuthAdapter]:
        return WooCommerceAuthAdapter()

    def account(self) -> Optional[AccountAdapter]:
        return WooCommerceAccountAdapter()

    def pull(self) -> Optional[PullAdapter]:
        return WooCommercePullAdapter(provider_identity=self.identity().key)

    def webhook(self) -> Optional[WebhookAdapter]:
        return WooCommerceWebhookAdapter(provider_identity=self.identity().key)

    # report() / stream() / reconciliation() -> None (inherited from the base).


__all__ = ["WooCommerceOrdersPlugin"]
