"""Slack outbound notification service — per-tenant channel mapping + templates.

Sends structured messages from Aether to operator-configured Slack channels
when platform events occur (connector errors, agent alerts, billing events, etc.).

Design:
- Per-tenant configuration: bot token (from vault) + channel mappings per event family
- Template rendering: simple key→value interpolation, no external templating deps
- Delivery: httpx POST to Slack Web API chat.postMessage
- Audit: every send is logged; failures are soft (never break the caller)
"""
from __future__ import annotations

import os
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.service.slack_notify")


# ── Template library ──────────────────────────────────────────────────────────

_DEFAULT_TEMPLATES: dict[str, str] = {
    "connector.error": ":warning: *Connector alert* — `{connector_type}` on tenant `{tenant_id}` entered status `{status}`. Last synced: {last_synced_at}.",
    "connector.healthy": ":white_check_mark: *Connector recovered* — `{connector_type}` on tenant `{tenant_id}` is healthy.",
    "agent.kill_switch": ":rotating_light: *Agent kill switch triggered* on tenant `{tenant_id}` by `{actor}`. Reason: {reason}.",
    "billing.overage": ":credit_card: *Usage overage* — tenant `{tenant_id}` exceeded plan limit for `{metric}` (current: {current}, limit: {limit}).",
    "graph.contamination": ":spider_web: *Graph contamination detected* on tenant `{tenant_id}` — cluster churn rate: {churn_rate}%.",
    "default": ":bell: *Aether alert* — event `{event_type}` on tenant `{tenant_id}`.",
}


def _render(template: str, context: dict[str, Any]) -> str:
    try:
        return template.format_map({k: str(v) for k, v in context.items()})
    except (KeyError, ValueError):
        return template


# ── Delivery ──────────────────────────────────────────────────────────────────

async def _post_message(bot_token: str, channel: str, text: str) -> bool:
    """POST to Slack chat.postMessage. Returns True on success."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
                json={"channel": channel, "text": text},
            )
            body = r.json() if r.content else {}
            if r.status_code == 200 and body.get("ok"):
                return True
            logger.warning(f"Slack postMessage failed: {body.get('error', r.status_code)}")
    except Exception as exc:
        logger.warning(f"Slack delivery error: {exc}")
    return False


# ── Channel mapping model ─────────────────────────────────────────────────────

class SlackChannelConfig:
    """Per-tenant Slack outbound channel mapping (stored in vault/config, not here)."""

    def __init__(
        self,
        tenant_id: str,
        bot_token: str,
        default_channel: str,
        channel_map: Optional[dict[str, str]] = None,
        templates: Optional[dict[str, str]] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.bot_token = bot_token
        self.default_channel = default_channel
        # event_family → channel override (e.g. "connector.error" → "#ops-alerts")
        self.channel_map: dict[str, str] = channel_map or {}
        # event_family → message template override
        self.templates: dict[str, str] = {**_DEFAULT_TEMPLATES, **(templates or {})}

    def channel_for(self, event_family: str) -> str:
        return self.channel_map.get(event_family, self.default_channel)

    def template_for(self, event_family: str) -> str:
        return self.templates.get(event_family, self.templates["default"])


# ── Service ───────────────────────────────────────────────────────────────────

class SlackNotificationService:
    """Resolves tenant channel config from vault and delivers Slack notifications."""

    def __init__(self) -> None:
        self._providers: Any = None

    def _providers_repo(self):
        if self._providers is None:
            from repositories.repos import ProvidersRepository
            self._providers = ProvidersRepository()
        return self._providers

    async def _resolve_bot_token(self, tenant_id: str) -> Optional[str]:
        try:
            from repositories.repos import BaseRepository
            repo = BaseRepository("slack_channel_configs")
            record = await repo.find_by_id(tenant_id)
            if record and record.get("bot_token_ref"):
                vault = self._providers_repo()
                cred = await vault.find_by_id(record["bot_token_ref"])
                return cred.get("api_key") if cred else None
        except Exception as exc:
            logger.warning(f"Slack token resolution failed for {tenant_id}: {exc}")
        return None

    async def _load_channel_config(self, tenant_id: str) -> Optional[SlackChannelConfig]:
        try:
            from repositories.repos import BaseRepository
            repo = BaseRepository("slack_channel_configs")
            record = await repo.find_by_id(tenant_id)
            if not record or not record.get("enabled"):
                return None
            bot_token = await self._resolve_bot_token(tenant_id)
            if not bot_token:
                return None
            return SlackChannelConfig(
                tenant_id=tenant_id,
                bot_token=bot_token,
                default_channel=record.get("default_channel", "#general"),
                channel_map=record.get("channel_map") or {},
                templates=record.get("templates") or {},
            )
        except Exception as exc:
            logger.warning(f"SlackChannelConfig load failed for {tenant_id}: {exc}")
        return None

    def _is_live(self) -> bool:
        return os.getenv("AETHER_ENV", "local").lower() != "local"

    async def send(
        self,
        tenant_id: str,
        event_family: str,
        context: dict[str, Any],
        *,
        channel_override: Optional[str] = None,
    ) -> bool:
        """Send a Slack notification for a platform event.

        Returns True if delivered, False if skipped (local mode, not configured, or delivery failed).
        Never raises — failures are soft.
        """
        if not self._is_live():
            logger.debug(f"Slack notify skipped in local mode: {event_family} for {tenant_id}")
            return False
        cfg = await self._load_channel_config(tenant_id)
        if cfg is None:
            logger.debug(f"Slack not configured for {tenant_id}")
            return False
        channel = channel_override or cfg.channel_for(event_family)
        template = cfg.template_for(event_family)
        text = _render(template, {"tenant_id": tenant_id, "event_type": event_family, **context})
        ok = await _post_message(cfg.bot_token, channel, text)
        logger.info(f"Slack notify {'ok' if ok else 'failed'}: {event_family} → {channel} ({tenant_id})")
        return ok


slack_notify = SlackNotificationService()
