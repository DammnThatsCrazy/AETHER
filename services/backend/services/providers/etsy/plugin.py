"""Etsy orders capability plugin (UPR follow-on, Team G).

Identity: ``etsy.api.orders_read`` (family ``etsy``, product ``api``,
capability ``orders_read``). The manifest declares the honest capability set —
auth/account/pull true, webhook/report/stream/reconciliation false — and passes
:func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`.

Etsy uses the OAuth 2.0 authorization-code flow with PKCE and refresh; the
credential schema declares the OAuth token material plus the ``shop_id`` the
receipts pull is scoped to. The API base is FIXED at ``https://openapi.etsy.com/v3``
and routed through :func:`validated_https_host <shared.security.ssrf.validated_https_host>`
with a fixed ``openapi.etsy.com`` allowlist — a tenant value never selects the
host. Webhooks are NOT claimed (``supported=False``): no webhook scheme is
implemented this build, and the normalizer surfaces any unmappable receipt
state via ``dropped`` (``known_unsupported_behavior``), never silently.

Readiness is ``REPLAY_VALIDATED`` at level 3 — the evidence basis is offline
fixture-replay determinism, not live verification. ``certification_state``
stays ``uncertified``. The live OAuth exchange (PKCE, refresh, token replay) is
a certification-level follow-on and is NOT claimed as a build fact.
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

from services.providers.etsy.account import EtsyAccountAdapter
from services.providers.etsy.auth import EtsyAuthAdapter
from services.providers.etsy.normalizer import EtsyOrderNormalizer
from services.providers.etsy.pull import EtsyPullAdapter

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


class EtsyOrdersPlugin(_PluginBase):
    """Etsy Orders (api, orders_read) provider plugin."""

    version = "1.0.0"  # used by certification
    # Honest certification state: structural + offline fixture replay only.
    certification_state = "uncertified"

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family="etsy", product="api", capability="orders_read"
        )

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="etsy",
            product_id="api",
            capability_id="orders_read",
            display_name="Etsy Orders",
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
                    pkce=True,
                    refresh_supported=True,
                    scopes=["transactions_r", "orders_r"],
                ),
                credential_schema=[
                    CredentialFieldSpec(name="shop_id", type="string", required=True, secret=False),
                    CredentialFieldSpec(name="client_id", type="string", required=True, secret=False),
                    CredentialFieldSpec(name="access_token", type="oauth_token", required=True, secret=True),
                    CredentialFieldSpec(name="refresh_token", type="oauth_token", required=True, secret=True),
                ],
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(supported=False),
            sync=Sync(
                initial_backfill=True,
                incremental=True,
                reconciliation=False,
                cursor="update_ts",
            ),
            data_outputs=["bronze.provider_events"],
            product_destinations=[],
            deployment=Deployment(),
        )

    def normalizer(self) -> EventNormalizer:
        return EtsyOrderNormalizer()

    def auth(self) -> Optional[AuthAdapter]:
        return EtsyAuthAdapter()

    def account(self) -> Optional[AccountAdapter]:
        return EtsyAccountAdapter()

    def pull(self) -> Optional[PullAdapter]:
        return EtsyPullAdapter(provider_identity=self.identity().key)

    def webhook(self) -> Optional[WebhookAdapter]:
        # Etsy webhooks are NOT claimed this build — honest None default.
        return None

    # report() / stream() / reconciliation() -> None (inherited from the base).


__all__ = ["EtsyOrdersPlugin"]
