"""E2E integration test for webhook delivery adapter — SSRF + HMAC signing."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.delivery.adapters.base import (
    ConfigurationError,
    ProviderError,
    RetryableProviderError,
    SSRFBlockedError,
)
from services.delivery.adapters.webhook import WebhookAdapter, _check_ssrf


def _mock_resp(status: int, body: str = "ok"):
    resp = MagicMock()
    resp.status = status
    resp.headers = {}
    resp.text = AsyncMock(return_value=body)
    return resp


def _make_session(resp):
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    s.post = MagicMock(return_value=cm)
    return s


@pytest.mark.asyncio
async def test_webhook_success_returns_delivery_id():
    mock_resp = _mock_resp(200)
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("203.0.113.1", 0))]  # public IP
        with patch("aiohttp.ClientSession", return_value=_make_session(mock_resp)):
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
    mock_resp = _mock_resp(503, "Service Unavailable")
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("203.0.113.1", 0))]
        with patch("aiohttp.ClientSession", return_value=_make_session(mock_resp)):
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
