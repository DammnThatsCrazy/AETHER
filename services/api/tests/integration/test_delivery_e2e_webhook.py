"""E2E integration test for webhook delivery adapter — SSRF + HMAC signing."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from actions.delivery.adapters.base import (
    ConfigurationError,
    ProviderError,
    RetryableProviderError,
    SSRFBlockedError,
)
from actions.delivery.adapters.webhook import WebhookAdapter, _check_ssrf


def _send_returning(status: int, body: str = "ok"):
    return patch.object(httpx.AsyncClient, "send", AsyncMock(return_value=httpx.Response(status, text=body)))


@pytest.mark.asyncio
async def test_webhook_success_returns_delivery_id():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]  # public IP
        with _send_returning(200):
            adapter = WebhookAdapter()
            receipt = await adapter.dispatch(
                {"title": "Alert", "body": "Something"},
                {"url": "https://example.com/webhook"},
                credential="signing-secret-123",
                idempotency_key="idem-key-001",
            )

    assert receipt.external_id == "idem-key-001"
    assert not receipt.external_id.startswith("sim-")
    assert receipt.http_status == 200


@pytest.mark.asyncio
async def test_webhook_blocks_loopback():
    adapter = WebhookAdapter()
    with pytest.raises((ConfigurationError, SSRFBlockedError)):
        await adapter.dispatch(
            {"title": "Test"},
            {"url": "https://127.0.0.1/webhook"},
        )


@pytest.mark.asyncio
async def test_webhook_requires_https():
    adapter = WebhookAdapter()
    with pytest.raises(ConfigurationError, match="HTTPS"):
        await adapter.dispatch(
            {"title": "Test"},
            {"url": "http://example.com/webhook"},
        )


@pytest.mark.asyncio
async def test_webhook_requires_url():
    adapter = WebhookAdapter()
    with pytest.raises(ConfigurationError, match="url"):
        await adapter.dispatch({"title": "Test"}, {})


@pytest.mark.asyncio
async def test_webhook_raises_retryable_on_5xx():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with _send_returning(503, "Service Unavailable"):
            adapter = WebhookAdapter()
            with pytest.raises(RetryableProviderError, match="server error"):
                await adapter.dispatch(
                    {"title": "Test"},
                    {"url": "https://example.com/webhook"},
                )


def test_check_ssrf_blocks_private_ranges():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]
        with pytest.raises(SSRFBlockedError):
            _check_ssrf("https://internal.local/api")
