"""CRM delivery adapter — fail-closed placeholder.

CRM integrations require per-tenant configuration and compliance review.
This adapter raises ConfigurationError unless explicitly configured with
a verified CRM endpoint. It never silently succeeds.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
)

logger = get_logger("aether.delivery.adapters.crm")


class CRMAdapter(ProviderAdapter):
    """Fail-closed CRM adapter.

    Requires explicit CRM endpoint configuration. Raises ConfigurationError
    if no verified crm_url is provided — never falls back silently.
    """

    adapter_name = "crm"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        crm_url = provider_config.get("crm_url") or provider_config.get("url")
        crm_type = provider_config.get("crm_type", "generic")

        if not crm_url:
            raise ConfigurationError(
                f"CRMAdapter ({crm_type}) requires provider_config.crm_url. "
                "CRM delivery requires explicit verified endpoint configuration. "
                "Set crm_url in the connector's provider_config."
            )
        if not credential:
            raise ConfigurationError(
                f"CRMAdapter ({crm_type}) requires a credential (API key or OAuth token). "
                "CRM delivery requires authentication — no anonymous delivery permitted."
            )

        # Delegate to WebhookAdapter with CRM-specific config
        from services.delivery.adapters.webhook import WebhookAdapter
        webhook_config = {
            "url": crm_url,
            "headers": provider_config.get("extra_headers") or {},
        }
        webhook_payload = {
            **payload,
            "crm_type": crm_type,
            "crm_object_type": provider_config.get("object_type", "activity"),
        }
        receipt = await WebhookAdapter().dispatch(
            webhook_payload,
            webhook_config,
            credential=credential,
            idempotency_key=idempotency_key,
        )
        logger.info(
            f"CRM ({crm_type}) delivery completed: external_id={receipt.external_id!r}"
        )
        return AdapterReceipt(
            external_id=f"crm:{crm_type}:{receipt.external_id}",
            raw_response=receipt.raw_response,
            http_status=receipt.http_status,
        )
