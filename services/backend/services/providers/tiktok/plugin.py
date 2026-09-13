"""TikTok Shop orders capability plugin (UPR follow-on, Team G).

Identity: ``tiktok.shop.orders_read`` (family ``tiktok``, product ``shop``,
capability ``orders_read``). The manifest declares the honest capability set —
auth/account/pull/webhook true, report/stream/reconciliation false — and passes
:func:`validate_manifest <shared.integration_contracts.manifest.validate_manifest>`.

TikTok Shop authentication is ``app_key`` + ``app_secret`` with every request
HMAC-signed; this build is STRUCTURAL in CI (no live signed call is claimed).
The API base is FIXED at ``https://open-api.tiktokglobalshop.com`` and routed
through :func:`validated_https_host <shared.security.ssrf.validated_https_host>`
with a fixed allowlist — a tenant value never selects the host.

Webhooks ARE claimed with the ``tiktok_hmac`` scheme (HMAC-SHA256 over the raw
body, constant-time), implemented in ``services.providers.tiktok.webhook``, and
the normalizer carries a full status map so no claimed webhook status is ever
silently skipped. Readiness is ``REPLAY_VALIDATED`` at level 3 — the evidence
basis is offline fixture-replay determinism, not live verification.
``certification_state`` stays ``uncertified``. Live signed-request verification
and webhook replay are certification-level follow-ons and are NOT claimed as
build facts.
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

from services.providers.tiktok.account import TikTokAccountAdapter
from services.providers.tiktok.auth import TikTokAuthAdapter
from services.providers.tiktok.normalizer import TikTokOrderNormalizer
from services.providers.tiktok.pull import TikTokPullAdapter
from services.providers.tiktok.webhook import TikTokWebhookAdapter

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


class TikTokOrdersPlugin(_PluginBase):
    """TikTok Shop Orders (shop, orders_read) provider plugin."""

    version = "1.0.0"  # used by certification
    # Honest certification state: structural + offline fixture replay only.
    certification_state = "uncertified"

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family="tiktok", product="shop", capability="orders_read"
        )

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="tiktok",
            product_id="shop",
            capability_id="orders_read",
            display_name="TikTok Shop Orders",
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
                    CredentialFieldSpec(name="app_key", type="string", required=True, secret=False),
                    CredentialFieldSpec(name="app_secret", type="secret", required=True, secret=True),
                    CredentialFieldSpec(name="shop_id", type="string", required=True, secret=False),
                ],
            ),
            configuration=Configuration(
                fields=[
                    ConfigFieldSpec(name="shop_cipher", type="string", required=False),
                ]
            ),
            accounts=Accounts(discovery_supported=True, selection_required=True),
            webhooks=Webhooks(
                supported=True,
                registration_supported=False,
                verification_scheme="tiktok_hmac",
            ),
            sync=Sync(
                initial_backfill=True,
                incremental=True,
                reconciliation=False,
                cursor="update_time",
            ),
            data_outputs=["bronze.provider_events"],
            product_destinations=[],
            deployment=Deployment(),
        )

    def normalizer(self) -> EventNormalizer:
        return TikTokOrderNormalizer()

    def auth(self) -> Optional[AuthAdapter]:
        return TikTokAuthAdapter()

    def account(self) -> Optional[AccountAdapter]:
        return TikTokAccountAdapter()

    def pull(self) -> Optional[PullAdapter]:
        return TikTokPullAdapter(provider_identity=self.identity().key)

    def webhook(self) -> Optional[WebhookAdapter]:
        return TikTokWebhookAdapter(provider_identity=self.identity().key)

    # report() / stream() / reconciliation() -> None (inherited from the base).


__all__ = ["TikTokOrdersPlugin"]
