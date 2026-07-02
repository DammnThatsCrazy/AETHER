"""Marketing delivery adapter — fail-closed placeholder.

Marketing integrations require opt-in consent and channel-specific
compliance configuration. This adapter raises ConfigurationError
unless explicitly configured. Never silently succeeds.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
)

logger = get_logger("aether.delivery.adapters.marketing")


class MarketingAdapter(ProviderAdapter):
    """Fail-closed marketing adapter.

    Requires explicit marketing platform endpoint and consent flag.
    Raises ConfigurationError if not configured — never falls back silently.
    """

    adapter_name = "marketing"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        platform_url = (
            provider_config.get("platform_url")
            or provider_config.get("api_url")
            or provider_config.get("url")
        )
        platform_type = provider_config.get("platform_type", "generic")
        consent_verified = provider_config.get("consent_verified", False)

        if not consent_verified:
            raise ConfigurationError(
                f"MarketingAdapter ({platform_type}) requires provider_config.consent_verified=true. "
                "Marketing delivery requires explicit opt-in consent verification."
            )
        if not platform_url:
            raise ConfigurationError(
                f"MarketingAdapter ({platform_type}) requires provider_config.platform_url."
            )
        if not credential:
            raise ConfigurationError(
                f"MarketingAdapter ({platform_type}) requires a credential (API key). "
                "Anonymous marketing delivery is not permitted."
            )

        from services.delivery.adapters.webhook import WebhookAdapter
        webhook_config = {
            "url": platform_url,
            "headers": provider_config.get("extra_headers") or {},
        }
        marketing_payload = {
            **payload,
            "platform_type": platform_type,
            "campaign_id": provider_config.get("campaign_id"),
            "list_id": provider_config.get("list_id"),
        }
        receipt = await WebhookAdapter().dispatch(
            marketing_payload,
            webhook_config,
            credential=credential,
            idempotency_key=idempotency_key,
        )
        logger.info(
            f"Marketing ({platform_type}) delivery completed: external_id={receipt.external_id!r}"
        )
        return AdapterReceipt(
            external_id=f"marketing:{platform_type}:{receipt.external_id}",
            raw_response=receipt.raw_response,
            http_status=receipt.http_status,
        )
