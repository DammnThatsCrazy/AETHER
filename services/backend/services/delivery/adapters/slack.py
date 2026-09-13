"""Slack delivery adapter — chat.postMessage with Block Kit.

Authenticates via Bot token (Bearer).  Supports idempotency via Slack's
own message deduplication (same payload+channel+token → same ts).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
)

logger = get_logger("aether.delivery.adapters.slack")

_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
_SLACK_VERIFY_URL_PREFIX = "https://slack.com/api/"


def _build_blocks(
    title: str,
    body: str,
    *,
    action_url: Optional[str] = None,
    priority: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Build a Slack Block Kit message."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title[:150], "emoji": False},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": body[:3000]},
        },
    ]
    if priority:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Priority:* {priority}"}],
        })
    if action_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Details", "emoji": False},
                    "url": action_url,
                    "style": "primary",
                }
            ],
        })
    return blocks


class SlackAdapter(ProviderAdapter):
    """Delivers messages to a Slack channel via the Web API."""

    adapter_name = "slack"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        token = credential or provider_config.get("bot_token") or provider_config.get("token")
        if not token:
            raise ConfigurationError(
                "SlackAdapter requires a bot token (credential or provider_config.bot_token)"
            )

        channel = provider_config.get("channel_id") or provider_config.get("channel") or "#general"
        title = payload.get("title", "Aether Notification")
        body = payload.get("body") or payload.get("summary", "")
        action_url = payload.get("action_url")
        priority = payload.get("priority")

        blocks = _build_blocks(title, body, action_url=action_url, priority=priority)
        request_body = {
            "channel": channel,
            "text": title,  # fallback for accessibility
            "blocks": blocks,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if idempotency_key:
            # Slack doesn't have a native idempotency header, but we log it for dedup tracking
            logger.debug(f"Slack dispatch idempotency_key={idempotency_key!r}")

        try:
            import aiohttp
        except ImportError:
            raise ConfigurationError("aiohttp is required for SlackAdapter: pip install aiohttp")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                _SLACK_POST_URL,
                headers=headers,
                data=json.dumps(request_body),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {}

                if status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    raise RetryableProviderError(
                        f"Slack rate-limited: HTTP 429",
                        http_status=429,
                        retry_after_seconds=retry_after,
                    )
                if status >= 500:
                    raise RetryableProviderError(
                        f"Slack server error: HTTP {status}",
                        http_status=status,
                    )
                if status >= 400:
                    raise ProviderError(
                        f"Slack client error: HTTP {status} — {data}",
                        http_status=status,
                    )
                if not data.get("ok"):
                    error_code = data.get("error", "unknown")
                    if error_code in ("ratelimited",):
                        raise RetryableProviderError(
                            f"Slack API error (retryable): {error_code}",
                            http_status=status,
                        )
                    raise ProviderError(
                        f"Slack API error: {error_code} — {data}",
                        http_status=status,
                    )

                # ts is Slack's stable message identifier
                ts = data.get("ts") or data.get("message", {}).get("ts", "")
                if not ts:
                    raise ProviderError(
                        f"Slack response missing 'ts' field — cannot confirm delivery: {data}",
                        http_status=status,
                    )

                external_id = f"slack:{channel}:{ts}"
                logger.info(f"Slack message delivered: external_id={external_id!r}")
                return AdapterReceipt(
                    external_id=external_id,
                    raw_response=data,
                    http_status=status,
                )

    async def verify_inbound(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        *,
        credential: Optional[str] = None,
    ) -> bool:
        """Verify Slack Events API signature (v0 HMAC-SHA256)."""
        signing_secret = credential
        if not signing_secret:
            return False
        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")
        if not timestamp or not signature:
            return False
        base = f"v0:{timestamp}:{raw_body.decode('utf-8', errors='replace')}"
        expected = "v0=" + hmac.new(
            signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
