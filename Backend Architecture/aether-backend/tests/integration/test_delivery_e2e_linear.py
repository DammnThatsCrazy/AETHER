"""E2E integration test for Linear delivery adapter."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.delivery.adapters.base import ConfigurationError, ProviderError
from services.delivery.adapters.linear import LinearAdapter


def _make_mock_resp(status: int, data: dict):
    resp = MagicMock()
    resp.status = status
    resp.headers = {}
    resp.json = AsyncMock(return_value=data)
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
async def test_linear_success_returns_issue_id():
    issue_id = str(uuid.uuid4())
    mock_resp = _make_mock_resp(200, {
        "data": {
            "issueCreate": {
                "success": True,
                "issue": {"id": issue_id, "identifier": "ENG-42", "url": "https://linear.app/eng/ENG-42", "title": "Test"},
            }
        }
    })
    with patch("aiohttp.ClientSession", return_value=_make_session(mock_resp)):
        adapter = LinearAdapter()
        receipt = await adapter.dispatch(
            {"title": "Test Issue", "body": "Something to fix"},
            {"team_id": "team-abc"},
            credential="lin_api_key_xxx",
        )
    assert receipt.external_id == issue_id
    assert not receipt.external_id.startswith("sim-")


@pytest.mark.asyncio
async def test_linear_raises_on_graphql_errors():
    mock_resp = _make_mock_resp(200, {"errors": [{"message": "Unauthorized"}]})
    with patch("aiohttp.ClientSession", return_value=_make_session(mock_resp)):
        adapter = LinearAdapter()
        with pytest.raises(ProviderError, match="Unauthorized"):
            await adapter.dispatch(
                {"title": "Test"},
                {"team_id": "team-abc"},
                credential="bad-key",
            )


@pytest.mark.asyncio
async def test_linear_requires_team_id():
    adapter = LinearAdapter()
    with pytest.raises(ConfigurationError, match="team_id"):
        await adapter.dispatch({"title": "Test"}, {}, credential="key")


@pytest.mark.asyncio
async def test_linear_requires_api_key():
    adapter = LinearAdapter()
    with pytest.raises(ConfigurationError, match="API key"):
        await adapter.dispatch({"title": "Test"}, {"team_id": "t-1"}, credential=None)
