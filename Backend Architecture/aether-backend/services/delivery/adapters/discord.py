"""Discord delivery adapter — delegates to DiscordChannelGateway."""

from __future__ import annotations

import time
from typing import Any, Optional

from services.delivery.adapters.base import (
    AdapterReceipt,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
)


class DiscordAdapter(ProviderAdapter):
    """Delivers notifications to a Discord channel via webhook URL."""

    adapter_name = "discord"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        from services.notification_intelligence.channel_gateway import DiscordChannelGateway

        webhook_url = provider_config.get("webhook_url") or credential
        if not webhook_url:
            raise ProviderError("Discord adapter requires webhook_url in provider_config or credential")

        gateway = DiscordChannelGateway()
        t0 = time.monotonic()
        try:
            status, _body = await gateway._post_with_retry(
                webhook_url,
                {
                    "embeds": [
                        {
                            "title": payload.get("title", ""),
                            "description": payload.get("body", payload.get("summary", "")),
                            "color": 0x5865F2,
                        }
                    ]
                },
            )
        except Exception as exc:
            raise RetryableProviderError(f"Discord POST failed: {exc}") from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        if status not in (200, 204):
            if status == 429:
                raise RetryableProviderError(f"Discord rate-limited (HTTP {status})", http_status=status)
            if status >= 500:
                raise RetryableProviderError(f"Discord server error (HTTP {status})", http_status=status)
            raise ProviderError(f"Discord rejected delivery (HTTP {status})", http_status=status)

        # Discord webhooks return 204 No Content on success — use idempotency key as external_id
        external_id = idempotency_key or f"discord:{int(t0 * 1000)}"
        return AdapterReceipt(
            external_id=external_id,
            raw_response={"http_status": status, "latency_ms": latency_ms},
            http_status=status,
        )
