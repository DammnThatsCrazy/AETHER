"""Notification Intelligence — Channel Gateway Abstraction

Abstract base + concrete implementations for:
  - Slack (Block Kit, OAuth tokens, signature verification, interactive callbacks)
  - Discord (Embed via webhook URL, rate-limit headers)
  - Telegram (Bot API, Markdown v2, inline keyboard for operator actions)
  - Generic Webhook (JSON, optional HMAC-SHA256 signature)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.notification.channel_gateway")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HTTPX_AVAILABLE = False


# Severity → Discord embed colour (decimal)
_DISCORD_COLOURS: dict[str, int] = {
    "P0": 0xFF0000,
    "P1": 0xFF8C00,
    "P2": 0xFFD700,
    "P3": 0x4169E1,
    "info": 0x808080,
}

# Severity → Slack emoji prefix
_SLACK_SEVERITY_EMOJI: dict[str, str] = {
    "P0": "🔴",
    "P1": "🟠",
    "P2": "🟡",
    "P3": "🔵",
    "info": "⚪",
}

MAX_RETRIES = 3
BASE_BACKOFF_S = 1.0
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_RESET_S = 60


class DeliveryResult:
    def __init__(
        self,
        success: bool,
        channel_type: str,
        message_ref: Optional[str] = None,
        error: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ):
        self.success = success
        self.channel_type = channel_type
        self.message_ref = message_ref
        self.error = error
        self.latency_ms = latency_ms


class _CircuitBreaker:
    """Simple per-instance circuit breaker."""

    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD, reset_s: float = CIRCUIT_RESET_S):
        self._failures = 0
        self._open_until: float = 0.0
        self._threshold = threshold
        self._reset_s = reset_s

    @property
    def is_open(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._reset_s
            logger.warning("circuit_breaker_open failures=%d", self._failures)


class ChannelGateway(ABC):
    """Abstract delivery backend."""

    channel_type: str = "unknown"
    _circuit: _CircuitBreaker

    def __init__(self) -> None:
        self._circuit = _CircuitBreaker()

    @abstractmethod
    async def deliver(self, notification: Any, config: dict[str, Any], credentials: str) -> DeliveryResult:
        ...

    @abstractmethod
    async def test(self, config: dict[str, Any], credentials: str) -> DeliveryResult:
        ...

    async def _post_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, dict]:
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx not installed — pip install httpx")
        if self._circuit.is_open:
            raise RuntimeError(f"{self.channel_type} circuit breaker open")

        for attempt in range(MAX_RETRIES):
            t0 = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload, headers=headers or {})
                latency_ms = (time.monotonic() - t0) * 1000
                if resp.status_code in (200, 201, 204):
                    self._circuit.record_success()
                    try:
                        return resp.status_code, resp.json()
                    except Exception:
                        return resp.status_code, {}
                if resp.status_code == 429:
                    # Respect rate limit header
                    retry_after = float(resp.headers.get("Retry-After", BASE_BACKOFF_S * (2 ** attempt)))
                    logger.warning("%s rate limited, waiting %.1fs", self.channel_type, retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code >= 500:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                # 4xx (except 429) — no retry
                return resp.status_code, {}
            except Exception as exc:
                self._circuit.record_failure()
                if attempt == MAX_RETRIES - 1:
                    raise
                backoff = BASE_BACKOFF_S * (2 ** attempt)
                logger.warning("%s delivery attempt %d failed: %s — retry in %.1fs",
                               self.channel_type, attempt + 1, exc, backoff)
                await asyncio.sleep(backoff)
        return 500, {}


# ─────────────────────────────────────────────────────────────────────────────
# Slack
# ─────────────────────────────────────────────────────────────────────────────

class SlackChannelGateway(ChannelGateway):
    channel_type = "slack"
    SLACK_API_POST = "https://slack.com/api/chat.postMessage"
    SLACK_API_UPDATE = "https://slack.com/api/chat.update"

    def _build_blocks(self, notification: Any) -> list[dict]:
        severity = getattr(notification, "severity", "info")
        emoji = _SLACK_SEVERITY_EMOJI.get(str(severity), "⚪")
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        title = getattr(notification, "title", "")
        what = getattr(notification, "what", "")
        why = getattr(notification, "why", "")
        impact = getattr(notification, "impact", "")
        recommended = getattr(notification, "recommended_action", None)
        deep_link = getattr(notification, "deep_link", "/mission")
        source_service = getattr(notification, "source_service", "")
        correlation_id = getattr(notification, "correlation_id", "")
        tenant_id = getattr(notification, "tenant_id", "")
        notification_id = getattr(notification, "notification_id", "")
        detected_at = getattr(notification, "detected_at", "")

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} [{sev_val}] {title}", "emoji": True},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Tenant: `{tenant_id}` | Source: `{source_service}` | Trace: `{correlation_id}`"},
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*What:*\n{what}"},
                    {"type": "mrkdwn", "text": f"*Why:*\n{why}"},
                    {"type": "mrkdwn", "text": f"*Impact:*\n{impact}"},
                ],
            },
        ]

        if recommended:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Recommended Action:*\n{recommended}"},
            })

        # Operator action buttons (only for operator_review state)
        lifecycle_state = getattr(notification, "lifecycle_state", None)
        state_val = lifecycle_state.value if hasattr(lifecycle_state, "value") else str(lifecycle_state)
        if state_val == "operator_review":
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✓ Approve", "emoji": True},
                        "style": "primary",
                        "action_id": f"approve:{notification_id}:{tenant_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✗ Suppress", "emoji": True},
                        "style": "danger",
                        "action_id": f"suppress:{notification_id}:{tenant_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "↑ Escalate", "emoji": True},
                        "action_id": f"escalate:{notification_id}:{tenant_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✎ Annotate", "emoji": True},
                        "action_id": f"annotate:{notification_id}:{tenant_id}",
                    },
                ],
            })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"<{deep_link}|Open in Kyber> | {detected_at}"},
            ],
        })

        return blocks

    async def deliver(self, notification: Any, config: dict[str, Any], credentials: str) -> DeliveryResult:
        channel = config.get("channel_id") or config.get("channel", "#aether-ops")
        blocks = self._build_blocks(notification)
        payload = {"channel": channel, "blocks": blocks, "text": getattr(notification, "title", "")}
        headers = {"Authorization": f"Bearer {credentials}", "Content-Type": "application/json"}
        t0 = time.monotonic()
        try:
            status, body = await self._post_with_retry(self.SLACK_API_POST, payload, headers)
            latency_ms = (time.monotonic() - t0) * 1000
            ok = body.get("ok", False)
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "slack", "outcome": "success" if ok else "failed"})
            return DeliveryResult(
                success=ok,
                channel_type="slack",
                message_ref=body.get("ts"),
                error=body.get("error") if not ok else None,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "slack", "outcome": "failed"})
            return DeliveryResult(success=False, channel_type="slack", error=str(exc))

    async def update_message(self, channel: str, ts: str, text: str, credentials: str) -> None:
        payload = {"channel": channel, "ts": ts, "text": text, "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}}
        ]}
        headers = {"Authorization": f"Bearer {credentials}", "Content-Type": "application/json"}
        try:
            await self._post_with_retry(self.SLACK_API_UPDATE, payload, headers)
        except Exception as exc:
            logger.warning("slack_update_message_failed ts=%s error=%s", ts, exc)

    async def test(self, config: dict[str, Any], credentials: str) -> DeliveryResult:
        channel = config.get("channel_id") or config.get("channel", "#aether-ops")
        payload = {
            "channel": channel,
            "text": "✅ Aether notification channel test — connection verified.",
        }
        headers = {"Authorization": f"Bearer {credentials}", "Content-Type": "application/json"}
        try:
            status, body = await self._post_with_retry(self.SLACK_API_POST, payload, headers)
            ok = body.get("ok", False)
            return DeliveryResult(success=ok, channel_type="slack", error=body.get("error") if not ok else None)
        except Exception as exc:
            return DeliveryResult(success=False, channel_type="slack", error=str(exc))

    @staticmethod
    def verify_signature(body: bytes, timestamp: str, signature: str, signing_secret: str) -> bool:
        if abs(time.time() - float(timestamp)) > 300:
            return False
        base = f"v0:{timestamp}:{body.decode('utf-8')}"
        expected = "v0=" + hmac.new(
            signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────────────────────────────────────────
# Discord
# ─────────────────────────────────────────────────────────────────────────────

class DiscordChannelGateway(ChannelGateway):
    channel_type = "discord"

    def _build_embed(self, notification: Any) -> dict:
        severity = getattr(notification, "severity", "info")
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        colour = _DISCORD_COLOURS.get(sev_val, 0x808080)
        return {
            "title": f"[{sev_val}] {getattr(notification, 'title', '')}",
            "description": getattr(notification, "body", ""),
            "color": colour,
            "fields": [
                {"name": "What", "value": getattr(notification, "what", ""), "inline": False},
                {"name": "Why", "value": getattr(notification, "why", ""), "inline": False},
                {"name": "Impact", "value": getattr(notification, "impact", ""), "inline": False},
            ],
            "footer": {"text": f"Tenant: {getattr(notification, 'tenant_id', '')} | {getattr(notification, 'detected_at', '')}"},
            "url": getattr(notification, "deep_link", ""),
        }

    async def deliver(self, notification: Any, config: dict[str, Any], credentials: str) -> DeliveryResult:
        webhook_url = credentials  # credentials IS the webhook URL for Discord
        embed = self._build_embed(notification)
        t0 = time.monotonic()
        try:
            status, body = await self._post_with_retry(webhook_url, {"embeds": [embed]})
            latency_ms = (time.monotonic() - t0) * 1000
            success = status in (200, 204)
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "discord", "outcome": "success" if success else "failed"})
            return DeliveryResult(success=success, channel_type="discord", latency_ms=latency_ms,
                                  error=None if success else f"HTTP {status}")
        except Exception as exc:
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "discord", "outcome": "failed"})
            return DeliveryResult(success=False, channel_type="discord", error=str(exc))

    async def test(self, config: dict[str, Any], credentials: str) -> DeliveryResult:
        webhook_url = credentials
        payload = {"embeds": [{"title": "✅ Aether Test", "description": "Notification channel verified.", "color": 0x00AA00}]}
        try:
            status, _ = await self._post_with_retry(webhook_url, payload)
            success = status in (200, 204)
            return DeliveryResult(success=success, channel_type="discord", error=None if success else f"HTTP {status}")
        except Exception as exc:
            return DeliveryResult(success=False, channel_type="discord", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

class TelegramChannelGateway(ChannelGateway):
    channel_type = "telegram"
    TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    _ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"

    @classmethod
    def _escape_md2(cls, text: str) -> str:
        for ch in cls._ESCAPE_CHARS:
            text = text.replace(ch, f"\\{ch}")
        return text

    def _build_text(self, notification: Any) -> str:
        severity = getattr(notification, "severity", "info")
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        title = self._escape_md2(getattr(notification, "title", ""))
        what = self._escape_md2(getattr(notification, "what", ""))
        why = self._escape_md2(getattr(notification, "why", ""))
        impact = self._escape_md2(getattr(notification, "impact", ""))
        return (
            f"*\\[{self._escape_md2(sev_val)}\\] {title}*\n\n"
            f"*What:* {what}\n"
            f"*Why:* {why}\n"
            f"*Impact:* {impact}"
        )

    def _build_keyboard(self, notification: Any) -> Optional[dict]:
        lifecycle_state = getattr(notification, "lifecycle_state", None)
        state_val = lifecycle_state.value if hasattr(lifecycle_state, "value") else str(lifecycle_state)
        if state_val != "operator_review":
            return None
        nid = getattr(notification, "notification_id", "")
        tid = getattr(notification, "tenant_id", "")
        return {
            "inline_keyboard": [[
                {"text": "✓ Approve", "callback_data": f"approve:{nid}:{tid}"},
                {"text": "✗ Suppress", "callback_data": f"suppress:{nid}:{tid}"},
                {"text": "↑ Escalate", "callback_data": f"escalate:{nid}:{tid}"},
            ]]
        }

    async def deliver(self, notification: Any, config: dict[str, Any], credentials: str) -> DeliveryResult:
        token = credentials
        chat_id = config.get("chat_id", "")
        url = self.TELEGRAM_API.format(token=token)
        text = self._build_text(notification)
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"}
        kb = self._build_keyboard(notification)
        if kb:
            payload["reply_markup"] = kb
        t0 = time.monotonic()
        try:
            status, body = await self._post_with_retry(url, payload)
            latency_ms = (time.monotonic() - t0) * 1000
            ok = body.get("ok", False)
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "telegram", "outcome": "success" if ok else "failed"})
            return DeliveryResult(success=ok, channel_type="telegram",
                                  message_ref=str(body.get("result", {}).get("message_id")),
                                  error=body.get("description") if not ok else None,
                                  latency_ms=latency_ms)
        except Exception as exc:
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "telegram", "outcome": "failed"})
            return DeliveryResult(success=False, channel_type="telegram", error=str(exc))

    async def test(self, config: dict[str, Any], credentials: str) -> DeliveryResult:
        token = credentials
        chat_id = config.get("chat_id", "")
        url = self.TELEGRAM_API.format(token=token)
        payload = {"chat_id": chat_id, "text": "✅ Aether notification channel test — connection verified\\.", "parse_mode": "MarkdownV2"}
        try:
            status, body = await self._post_with_retry(url, payload)
            ok = body.get("ok", False)
            return DeliveryResult(success=ok, channel_type="telegram",
                                  error=body.get("description") if not ok else None)
        except Exception as exc:
            return DeliveryResult(success=False, channel_type="telegram", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Generic Webhook
# ─────────────────────────────────────────────────────────────────────────────

class WebhookChannelGateway(ChannelGateway):
    channel_type = "webhook"

    def _build_payload(self, notification: Any) -> dict:
        severity = getattr(notification, "severity", "info")
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        lc = getattr(notification, "lifecycle_state", "unknown")
        lc_val = lc.value if hasattr(lc, "value") else str(lc)
        nc = getattr(notification, "notification_class", "alert")
        nc_val = nc.value if hasattr(nc, "value") else str(nc)
        return {
            "schema_version": "1.0",
            "notification_id": getattr(notification, "notification_id", ""),
            "tenant_id": getattr(notification, "tenant_id", ""),
            "severity": sev_val,
            "class": nc_val,
            "title": getattr(notification, "title", ""),
            "what": getattr(notification, "what", ""),
            "why": getattr(notification, "why", ""),
            "impact": getattr(notification, "impact", ""),
            "recommended_action": getattr(notification, "recommended_action", None),
            "lifecycle_state": lc_val,
            "source_topic": getattr(notification, "source_topic", ""),
            "deep_link": getattr(notification, "deep_link", ""),
            "detected_at": getattr(notification, "detected_at", ""),
            "correlation_id": getattr(notification, "correlation_id", ""),
            "metadata": {},
        }

    def _sign_payload(self, body: str, secret: str) -> str:
        return "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    async def deliver(self, notification: Any, config: dict[str, Any], credentials: str) -> DeliveryResult:
        # credentials = JSON string: {"url": "...", "secret": "..."}
        try:
            creds = json.loads(credentials)
        except Exception:
            creds = {"url": credentials}
        url = creds.get("url", "")
        secret = creds.get("secret", "")
        payload = self._build_payload(notification)
        body_str = json.dumps(payload)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if secret:
            headers["X-Aether-Signature"] = self._sign_payload(body_str, secret)
        custom_headers = config.get("headers", {})
        headers.update(custom_headers)
        t0 = time.monotonic()
        try:
            status, _ = await self._post_with_retry(url, payload, headers)
            latency_ms = (time.monotonic() - t0) * 1000
            success = 200 <= status < 300
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "webhook", "outcome": "success" if success else "failed"})
            return DeliveryResult(success=success, channel_type="webhook", latency_ms=latency_ms,
                                  error=None if success else f"HTTP {status}")
        except Exception as exc:
            metrics.increment("aether_notifications_delivered_total",
                              labels={"channel": "webhook", "outcome": "failed"})
            return DeliveryResult(success=False, channel_type="webhook", error=str(exc))

    async def test(self, config: dict[str, Any], credentials: str) -> DeliveryResult:
        try:
            creds = json.loads(credentials)
        except Exception:
            creds = {"url": credentials}
        url = creds.get("url", "")
        secret = creds.get("secret", "")
        payload = {"schema_version": "1.0", "type": "test", "message": "Aether notification channel test"}
        body_str = json.dumps(payload)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if secret:
            headers["X-Aether-Signature"] = self._sign_payload(body_str, secret)
        try:
            status, _ = await self._post_with_retry(url, payload, headers)
            success = 200 <= status < 300
            return DeliveryResult(success=success, channel_type="webhook",
                                  error=None if success else f"HTTP {status}")
        except Exception as exc:
            return DeliveryResult(success=False, channel_type="webhook", error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_SLACK_GW = SlackChannelGateway()
_DISCORD_GW = DiscordChannelGateway()
_TELEGRAM_GW = TelegramChannelGateway()
_WEBHOOK_GW = WebhookChannelGateway()

GATEWAY_REGISTRY: dict[str, ChannelGateway] = {
    "slack": _SLACK_GW,
    "discord": _DISCORD_GW,
    "telegram": _TELEGRAM_GW,
    "webhook": _WEBHOOK_GW,
}


def get_gateway(channel_type: str) -> Optional[ChannelGateway]:
    return GATEWAY_REGISTRY.get(channel_type)
