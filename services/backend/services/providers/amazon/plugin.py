"""Amazon Selling Partner API orders capability plugin (UPR follow-on, Team G).

Identity: ``amazon.merchant.orders_read`` (family ``amazon``, product
``merchant``, capability ``orders_read``). The manifest declares the honest
capability set — auth/account/pull true, webhook/report/stream/reconciliation
false — and passes :func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`.

Amazon authentication is LWA (client_credentials) yielding an access token plus
AWS SigV4 request signing. The API host is FIXED to the regional SP-API
allowlist ``sellingpartnerapi-{na,eu,fe}.amazon.com`` and routed through
:func:`validated_https_host <shared.security.ssrf.validated_https_host>` — a
tenant value never selects the host (region only picks between allowlisted
entries). Webhooks are NOT claimed (``supported=False``): no webhook scheme is
implemented this build, and the normalizer surfaces any unmappable order status
via ``dropped`` (``known_unsupported_behavior``), never silently.

Readiness is ``REPLAY_VALIDATED`` at level 3 — the evidence basis is offline
fixture-replay determinism, not live verification. ``certification_state``
stays ``uncertified``. The live LWA exchange and the SigV4 request-signing
round-trip are certification-level follow-ons and are NOT claimed as build
facts.
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
    OAuthSpec,
    ProviderManifest,
    Sync,
    Webhooks,
)
from shared.integration_contracts.normalization import EventNormalizer

from services.providers.amazon.account import AmazonAccountAdapter
from services.providers.amazon.auth import AmazonAuthAdapter
from services.providers.amazon.normalizer import AmazonOrderNormalizer
from services.providers.amazon.pull import AmazonPullAdapter

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


class AmazonOrdersPlugin(_PluginBase):
    """Amazon SP-API Orders (merchant, orders_read) provider plugin."""

    version = "1.0.0"  # used by certification
    # Honest certification state: structural + offline fixture replay only.
    certification_state = "uncertified"

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family="amazon", product="merchant", capability="orders_read"
        )

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="amazon",
            product_id="merchant",
            capability_id="orders_read",
            display_name="Amazon Orders (SP-API)",
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
                type="oauth2",
                oauth=OAuthSpec(
                    pkce=False,
                    refresh_supported=False,
                    scopes=["sellingpartnerapi"],
                ),
                credential_schema=[
                    CredentialFieldSpec(name="client_id", type="string", required=True, secret=False),
                    CredentialFieldSpec(name="client_secret", type="oauth_token", required=True, secret=True),
                    CredentialFieldSpec(name="refresh_token", type="oauth_token", required=True, secret=True),
                    CredentialFieldSpec(name="seller_id", type="string", required=True, secret=False),
                ],
            ),
            configuration=Configuration(
                fields=[
                    # Region picks between allowlisted SP-API hosts only.
                    ConfigFieldSpec(name="region", type="enum", required=False),
                ]
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(supported=False),
            sync=Sync(
                initial_backfill=True,
                incremental=True,
                reconciliation=False,
                cursor="created",
            ),
            data_outputs=["bronze.provider_events"],
            product_destinations=[],
            deployment=Deployment(),
        )

    def normalizer(self) -> EventNormalizer:
        return AmazonOrderNormalizer()

    def auth(self) -> Optional[AuthAdapter]:
        return AmazonAuthAdapter()

    def account(self) -> Optional[AccountAdapter]:
        return AmazonAccountAdapter()

    def pull(self) -> Optional[PullAdapter]:
        return AmazonPullAdapter(provider_identity=self.identity().key)

    def webhook(self) -> Optional[WebhookAdapter]:
        # Amazon webhooks are NOT claimed this build — honest None default.
        return None

    # report() / stream() / reconciliation() -> None (inherited from the base).


__all__ = ["AmazonOrdersPlugin"]
