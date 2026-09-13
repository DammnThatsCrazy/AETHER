"""Walmart Marketplace orders capability plugin (UPR follow-on, Team G).

Identity: ``walmart.marketplace.orders_read`` (family ``walmart``, product
``marketplace``, capability ``orders_read``). The manifest declares the honest
capability set — auth/account/pull true, webhook/report/stream/reconciliation
false — and passes :func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`.

Walmart authentication is OAuth 2.0 client_credentials signed with the seller's
private key (consumer id + private key); this build is STRUCTURAL in CI — no
live token exchange is claimed. The API base is FIXED at
``https://marketplace.walmartapis.com`` and routed through
:func:`validated_https_host <shared.security.ssrf.validated_https_host>` with a
fixed allowlist — a tenant value never selects the host. Webhooks are NOT
claimed (``supported=False``): no webhook scheme is implemented this build, and
the normalizer surfaces any unmappable order status via ``dropped``
(``known_unsupported_behavior``), never silently.

Readiness is ``REPLAY_VALIDATED`` at level 3 — the evidence basis is offline
fixture-replay determinism, not live verification. ``certification_state``
stays ``uncertified``. The live OAuth client_credentials exchange is a
certification-level follow-on and is NOT claimed as a build fact.
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

from services.providers.walmart.account import WalmartAccountAdapter
from services.providers.walmart.auth import WalmartAuthAdapter
from services.providers.walmart.normalizer import WalmartOrderNormalizer
from services.providers.walmart.pull import WalmartPullAdapter

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


class WalmartOrdersPlugin(_PluginBase):
    """Walmart Marketplace Orders (marketplace, orders_read) provider plugin."""

    version = "1.0.0"  # used by certification
    # Honest certification state: structural + offline fixture replay only.
    certification_state = "uncertified"

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family="walmart", product="marketplace", capability="orders_read"
        )

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="walmart",
            product_id="marketplace",
            capability_id="orders_read",
            display_name="Walmart Marketplace Orders",
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
                    scopes=["orders"],
                ),
                credential_schema=[
                    CredentialFieldSpec(name="consumer_id", type="string", required=True, secret=False),
                    # PEM/DER private key used to sign the client_credentials grant.
                    CredentialFieldSpec(name="private_key", type="secret", required=True, secret=True),
                ],
            ),
            configuration=Configuration(
                fields=[
                    # Channel type for the auth signature (Walmart distinguishes
                    # the channel in the signed grant).
                    ConfigFieldSpec(name="channel_type", type="enum", required=False),
                ]
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(supported=False),
            sync=Sync(
                initial_backfill=True,
                incremental=True,
                reconciliation=False,
                # The incremental window, not the pagination token.
                cursor="createdStartDate",
            ),
            data_outputs=["bronze.provider_events"],
            product_destinations=[],
            deployment=Deployment(),
        )

    def normalizer(self) -> EventNormalizer:
        return WalmartOrderNormalizer()

    def auth(self) -> Optional[AuthAdapter]:
        return WalmartAuthAdapter()

    def account(self) -> Optional[AccountAdapter]:
        return WalmartAccountAdapter()

    def pull(self) -> Optional[PullAdapter]:
        return WalmartPullAdapter(provider_identity=self.identity().key)

    def webhook(self) -> Optional[WebhookAdapter]:
        # Walmart webhooks are NOT claimed this build — honest None default.
        return None

    # report() / stream() / reconciliation() -> None (inherited from the base).


__all__ = ["WalmartOrdersPlugin"]
