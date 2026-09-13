"""Unit tests for delivery adapters — uses mocked HTTP clients."""

from __future__ import annotations

import json
import unittest.mock as mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderAdapterRegistry,
    ProviderError,
    RetryableProviderError,
    SSRFBlockedError,
)
from services.delivery.adapters.crm import CRMAdapter
from services.delivery.adapters.marketing import MarketingAdapter
from services.delivery.adapters.ticketing import TicketingAdapter
from services.delivery.adapters.webhook import _check_ssrf


# ─── AdapterReceipt ──────────────────────────────────────────────────────────

def test_adapter_receipt_rejects_empty_external_id():
    with pytest.raises(ValueError, match="must not be empty"):
        AdapterReceipt(external_id="", raw_response={})


def test_adapter_receipt_rejects_sim_prefix():
    with pytest.raises(ValueError, match="sim-"):
        AdapterReceipt(external_id="sim-slack-abc", raw_response={})


def test_adapter_receipt_accepts_valid_external_id():
    r = AdapterReceipt(external_id="real-id-123", raw_response={"ok": True}, http_status=200)
    assert r.external_id == "real-id-123"
    assert r.http_status == 200


# ─── ProviderAdapterRegistry ─────────────────────────────────────────────────

def test_registry_default_registers_all_adapters():
    registry = ProviderAdapterRegistry.default()
    names = registry.list_names()
    assert "slack" in names
    assert "webhook" in names
    assert "linear" in names
    assert "jira" in names
    assert "crm" in names
    assert "marketing" in names
    assert "ticketing" in names
    assert "agent_assist" in names


def test_registry_get_or_raise_unknown():
    registry = ProviderAdapterRegistry()
    with pytest.raises(ConfigurationError, match="No provider adapter registered"):
        registry.get_or_raise("nonexistent_provider")


def test_registry_register_and_get():
    class MyAdapter(ProviderAdapter):
        adapter_name = "my_adapter"

        async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
            return AdapterReceipt(external_id="test-id", raw_response={})

    registry = ProviderAdapterRegistry()
    registry.register(MyAdapter())
    assert registry.get("my_adapter") is not None


# ─── SSRF protection ─────────────────────────────────────────────────────────

def test_ssrf_blocks_loopback():
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 0))
        ]
        with pytest.raises(SSRFBlockedError, match="SSRF"):
            _check_ssrf("https://localhost/webhook")


def test_ssrf_blocks_private_10_range():
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("10.0.0.1", 0))
        ]
        with pytest.raises(SSRFBlockedError):
            _check_ssrf("https://internal.service/webhook")


def test_ssrf_blocks_link_local():
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("169.254.169.254", 0))  # AWS metadata endpoint
        ]
        with pytest.raises(SSRFBlockedError, match="SSRF"):
            _check_ssrf("https://169.254.169.254/latest/meta-data")


# ─── CRMAdapter (fail-closed) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crm_adapter_requires_crm_url():
    adapter = CRMAdapter()
    with pytest.raises(ConfigurationError, match="crm_url"):
        await adapter.dispatch(
            {"title": "Test"},
            {},
            credential="token",
        )


@pytest.mark.asyncio
async def test_crm_adapter_requires_credential():
    adapter = CRMAdapter()
    with pytest.raises(ConfigurationError, match="credential"):
        await adapter.dispatch(
            {"title": "Test"},
            {"crm_url": "https://crm.example.com/api"},
            credential=None,
        )


# ─── MarketingAdapter (fail-closed) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_marketing_adapter_requires_consent():
    adapter = MarketingAdapter()
    with pytest.raises(ConfigurationError, match="consent_verified"):
        await adapter.dispatch(
            {"title": "Test"},
            {"platform_url": "https://marketing.example.com/api", "consent_verified": False},
            credential="token",
        )


@pytest.mark.asyncio
async def test_marketing_adapter_requires_credential():
    adapter = MarketingAdapter()
    with pytest.raises(ConfigurationError, match="credential"):
        await adapter.dispatch(
            {"title": "Test"},
            {"platform_url": "https://marketing.example.com/api", "consent_verified": True},
            credential=None,
        )


# ─── TicketingAdapter ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticketing_adapter_rejects_unknown_backend():
    adapter = TicketingAdapter()
    with pytest.raises(ConfigurationError, match="backend"):
        await adapter.dispatch(
            {"title": "Test"},
            {"backend": "salesforce"},
            credential="token",
        )


@pytest.mark.asyncio
async def test_ticketing_adapter_requires_backend():
    adapter = TicketingAdapter()
    with pytest.raises(ConfigurationError, match="backend"):
        await adapter.dispatch(
            {"title": "Test"},
            {},
            credential="token",
        )


# ─── SlackAdapter (mocked HTTP) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_adapter_dispatch_success():
    from services.delivery.adapters.slack import SlackAdapter

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.headers = {}
    mock_response.json = AsyncMock(return_value={
        "ok": True,
        "ts": "1720000000.123456",
        "channel": "#aether",
        "message": {"ts": "1720000000.123456"},
    })

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.post.return_value = mock_cm

    with patch("aiohttp.ClientSession", return_value=mock_session):
        adapter = SlackAdapter()
        receipt = await adapter.dispatch(
            {"title": "Hello", "body": "World"},
            {"channel_id": "#aether"},
            credential="xoxb-fake-token",
        )

    assert receipt.external_id.startswith("slack:")
    assert "1720000000.123456" in receipt.external_id
    assert not receipt.external_id.startswith("sim-")


@pytest.mark.asyncio
async def test_slack_adapter_requires_token():
    from services.delivery.adapters.slack import SlackAdapter
    adapter = SlackAdapter()
    with pytest.raises(ConfigurationError, match="bot token"):
        await adapter.dispatch(
            {"title": "Test"},
            {},
            credential=None,
        )
