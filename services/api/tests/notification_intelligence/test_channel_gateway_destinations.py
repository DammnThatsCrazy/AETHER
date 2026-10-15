"""Notification channel gateways reach only validated public addresses."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from journeys.notification_intelligence import channel_gateway as gw
from shared.security.ssrf import UnsafeDestinationError


@contextmanager
def _network(ip: str, status: int = 200):
    """Every host resolves to *ip*; requests are answered with *status*; backoff is instant."""
    send = AsyncMock(return_value=httpx.Response(status, json={}))
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]), \
         patch.object(httpx.AsyncClient, "send", send), \
         patch.object(gw.asyncio, "sleep", AsyncMock()):
        yield send


_NOTIFICATION = SimpleNamespace(tenant_id="t1", title="T", summary="S")
_HOOK = json.dumps({"url": "https://hooks.example.com/in"})


@pytest.mark.asyncio
@pytest.mark.parametrize("ip", ["10.0.0.5", "100.64.0.1", "64:ff9b::a9fe:a9fe", "::ffff:127.0.0.1"])
async def test_webhook_gateway_rejects_non_public_destination(ip):
    with _network(ip) as send:
        result = await gw.WebhookChannelGateway().deliver(_NOTIFICATION, {}, _HOOK)
    assert result.success is False
    send.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_gateway_test_send_rejects_non_public_destination():
    with _network("169.254.169.254") as send:
        result = await gw.WebhookChannelGateway().test({}, _HOOK)
    assert result.success is False
    send.assert_not_called()


@pytest.mark.asyncio
async def test_post_refuses_non_public_destination_without_retrying():
    with _network("10.0.0.5") as send, pytest.raises(UnsafeDestinationError):
        await gw.WebhookChannelGateway()._post_with_retry("https://discord.com/api/webhooks/1/x", {})
    send.assert_not_called()


@pytest.mark.asyncio
async def test_discord_gateway_connects_to_validated_address():
    with _network("162.159.135.232", status=204) as send:
        result = await gw.DiscordChannelGateway().deliver(
            _NOTIFICATION, {}, "https://discord.com/api/webhooks/1/x"
        )
    assert result.success is True
    request = send.call_args.args[0]
    assert request.url.host == "162.159.135.232"
    assert request.headers["host"] == "discord.com"
    assert request.extensions["sni_hostname"] == "discord.com"
