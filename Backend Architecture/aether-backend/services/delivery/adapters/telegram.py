"""Telegram delivery adapter — delegates to TelegramChannelGateway."""

from __future__ import annotations

from typing import Any, Optional

from services.delivery.adapters.base import (
    AdapterReceipt,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
)


class TelegramAdapter(ProviderAdapter):
    """Delivers notifications to a Telegram chat via Bot API."""

    adapter_name = "telegram"

    TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        from services.notification_intelligence.channel_gateway import TelegramChannelGateway

        token = credential
        if not token:
            raise ProviderError("Telegram adapter requires bot token in credential")
        chat_id = provider_config.get("chat_id", "")
        if not chat_id:
            raise ProviderError("Telegram adapter requires chat_id in provider_config")

        url = self.TELEGRAM_API.format(token=token)
        text = payload.get("body", payload.get("summary", payload.get("title", "")))

        gateway = TelegramChannelGateway()
        try:
            status, body = await gateway._post_with_retry(
                url,
                {"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
        except Exception as exc:
            raise RetryableProviderError(f"Telegram POST failed: {exc}") from exc

        ok = isinstance(body, dict) and body.get("ok", False)
        if not ok:
            if status == 429:
                raise RetryableProviderError(f"Telegram rate-limited (HTTP {status})", http_status=status)
            if status >= 500:
                raise RetryableProviderError(f"Telegram server error (HTTP {status})", http_status=status)
            description = body.get("description", f"HTTP {status}") if isinstance(body, dict) else f"HTTP {status}"
            raise ProviderError(f"Telegram rejected: {description}", http_status=status)

        # Telegram returns message_id in result — use as external_id
        message_id = str(body.get("result", {}).get("message_id", ""))
        external_id = f"telegram:{chat_id}:{message_id}" if message_id else (idempotency_key or "telegram:unknown")
        return AdapterReceipt(
            external_id=external_id,
            raw_response={"ok": ok, "message_id": message_id, "http_status": status},
            http_status=status,
        )
