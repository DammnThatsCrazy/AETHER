"""E2E integration test for Slack delivery adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.delivery.adapters.base import ConfigurationError, ProviderError, RetryableProviderError
from services.delivery.adapters.slack import SlackAdapter


def _make_mock_response(status: int, data: dict):
    resp = MagicMock()
    resp.status = status
    resp.headers = {}
    resp.json = AsyncMock(return_value=data)
    return resp


def _make_mock_session(response):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.post = MagicMock(return_value=cm)
    return session


@pytest.mark.asyncio
async def test_slack_success_returns_real_external_id():
    mock_resp = _make_mock_response(200, {
        "ok": True, "ts": "1720000000.999",
        "channel": "#alerts", "message": {"ts": "1720000000.999"},
    })
    with patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)):
        adapter = SlackAdapter()
        receipt = await adapter.dispatch(
            {"title": "Alert", "body": "Something happened"},
            {"channel_id": "#alerts"},
            credential="xoxb-test-token",
        )
    assert receipt.external_id == "slack:#alerts:1720000000.999"
    assert not receipt.external_id.startswith("sim-")
    assert receipt.http_status == 200


@pytest.mark.asyncio
async def test_slack_raises_provider_error_on_api_error():
    mock_resp = _make_mock_response(200, {"ok": False, "error": "channel_not_found"})
    with patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)):
        adapter = SlackAdapter()
        with pytest.raises(ProviderError, match="channel_not_found"):
            await adapter.dispatch(
                {"title": "Alert"},
                {"channel_id": "#nonexistent"},
                credential="xoxb-test-token",
            )


@pytest.mark.asyncio
async def test_slack_raises_retryable_on_rate_limit():
    mock_resp = _make_mock_response(200, {"ok": False, "error": "ratelimited"})
    with patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)):
        adapter = SlackAdapter()
        with pytest.raises(RetryableProviderError):
            await adapter.dispatch(
                {"title": "Alert"},
                {"channel_id": "#alerts"},
                credential="xoxb-test-token",
            )


@pytest.mark.asyncio
async def test_slack_raises_retryable_on_5xx():
    mock_resp = _make_mock_response(500, {})
    with patch("aiohttp.ClientSession", return_value=_make_mock_session(mock_resp)):
        adapter = SlackAdapter()
        with pytest.raises(RetryableProviderError, match="server error"):
            await adapter.dispatch(
                {"title": "Alert"},
                {},
                credential="xoxb-test-token",
            )


@pytest.mark.asyncio
async def test_slack_raises_config_error_without_token():
    adapter = SlackAdapter()
    with pytest.raises(ConfigurationError, match="bot token"):
        await adapter.dispatch({"title": "Alert"}, {})
