"""E2E tests for Slack outbound notification channel-map routing.

Validates that SlackNotificationService.send():
  1. Routes to the event-specific channel when channel_map matches
  2. Falls back to default_channel when event family not in channel_map
  3. Renders custom templates with event context
  4. Returns False and makes no HTTP call in local mode (AETHER_ENV=local)
  5. Returns False (soft failure) when no bot token is configured in vault
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from repositories.repos import ProvidersRepository, BaseRepository, reset_in_memory_stores


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


async def _store_channel_config(tenant_id: str, default_channel: str,
                                 channel_map: dict | None = None,
                                 templates: dict | None = None,
                                 bot_token: str | None = "xoxb-test") -> None:
    """Store a Slack channel config + vault token for a tenant (in-memory)."""
    repo = BaseRepository("slack_channel_configs")
    record: dict = {
        "tenant_id": tenant_id,
        "default_channel": default_channel,
        "channel_map": channel_map or {},
        "templates": templates or {},
        "enabled": True,
    }
    if bot_token:
        vault = ProvidersRepository()
        await vault.insert(f"slack:bot:{tenant_id}", {"api_key": bot_token})
        record["bot_token_ref"] = f"slack:bot:{tenant_id}"
    await repo.insert(tenant_id, record)


# ── Test 1: Channel-map routing by event family ───────────────────────────────


@pytest.mark.asyncio
async def test_channel_map_routing_by_event_family():
    await _store_channel_config(
        "t1", "#general",
        channel_map={"connector.error": "#ops-alerts", "agent.kill_switch": "#security"},
    )

    from services.integrations.slack_notify import SlackNotificationService
    svc = SlackNotificationService()

    captured: list[dict] = []

    async def _mock_post(bot_token: str, channel: str, text: str) -> bool:
        captured.append({"channel": channel, "text": text})
        return True

    with patch("services.integrations.slack_notify._post_message", side_effect=_mock_post), \
         patch.object(svc, "_is_live", return_value=True):
        ok = await svc.send(
            "t1", "connector.error",
            {"connector_type": "shopify", "status": "failed", "last_synced_at": "2026-01-01"},
        )

    assert ok is True
    assert len(captured) == 1
    assert captured[0]["channel"] == "#ops-alerts"
    assert "shopify" in captured[0]["text"]


# ── Test 2: Default channel fallback ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_channel_fallback():
    await _store_channel_config("t2", "#aether-alerts", channel_map={"connector.error": "#ops"})

    from services.integrations.slack_notify import SlackNotificationService
    svc = SlackNotificationService()

    captured: list[dict] = []

    async def _mock_post(bot_token: str, channel: str, text: str) -> bool:
        captured.append({"channel": channel, "text": text})
        return True

    with patch("services.integrations.slack_notify._post_message", side_effect=_mock_post), \
         patch.object(svc, "_is_live", return_value=True):
        ok = await svc.send("t2", "billing.overage",
                             {"metric": "api_calls", "current": 1000, "limit": 500})

    assert ok is True
    assert captured[0]["channel"] == "#aether-alerts"


# ── Test 3: Custom template rendering ────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_rendering():
    await _store_channel_config(
        "t3", "#general",
        templates={"connector.healthy": "Connector {connector_type} is back online for {tenant_id}!"},
    )

    from services.integrations.slack_notify import SlackNotificationService
    svc = SlackNotificationService()

    captured: list[dict] = []

    async def _mock_post(bot_token: str, channel: str, text: str) -> bool:
        captured.append({"channel": channel, "text": text})
        return True

    with patch("services.integrations.slack_notify._post_message", side_effect=_mock_post), \
         patch.object(svc, "_is_live", return_value=True):
        await svc.send("t3", "connector.healthy", {"connector_type": "stripe"})

    assert "stripe" in captured[0]["text"]
    assert "t3" in captured[0]["text"]
    assert "back online" in captured[0]["text"]


# ── Test 4: Delivery skipped in local mode ────────────────────────────────────


@pytest.mark.asyncio
async def test_delivery_skipped_in_local_mode():
    await _store_channel_config("t4", "#general")

    from services.integrations.slack_notify import SlackNotificationService
    svc = SlackNotificationService()

    with patch("services.integrations.slack_notify._post_message",
               new=AsyncMock(side_effect=AssertionError("should not be called in local mode"))), \
         patch.object(svc, "_is_live", return_value=False):
        ok = await svc.send("t4", "connector.error", {"connector_type": "stripe"})

    assert ok is False


# ── Test 5: Missing bot token returns False (soft failure) ───────────────────


@pytest.mark.asyncio
async def test_missing_bot_token_returns_false():
    await _store_channel_config("t5", "#general", bot_token=None)

    from services.integrations.slack_notify import SlackNotificationService
    svc = SlackNotificationService()

    with patch("services.integrations.slack_notify._post_message",
               new=AsyncMock(side_effect=AssertionError("should not post without a token"))), \
         patch.object(svc, "_is_live", return_value=True):
        ok = await svc.send("t5", "connector.error", {"connector_type": "stripe"})

    assert ok is False
