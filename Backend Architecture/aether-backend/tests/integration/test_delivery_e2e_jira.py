"""E2E integration test for Jira delivery adapter."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.delivery.adapters.base import ConfigurationError, ProviderError
from services.delivery.adapters.jira import JiraAdapter


def _mock_resp(status: int, data: dict):
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
async def test_jira_success_returns_issue_key():
    issue_id = str(uuid.uuid4())
    mock_resp = _mock_resp(201, {
        "id": issue_id,
        "key": "PROJ-42",
        "self": "https://mycompany.atlassian.net/rest/api/3/issue/" + issue_id,
    })
    with patch("aiohttp.ClientSession", return_value=_make_session(mock_resp)):
        adapter = JiraAdapter()
        receipt = await adapter.dispatch(
            {"title": "Fix the bug", "body": "Critical fix needed"},
            {
                "base_url": "https://mycompany.atlassian.net",
                "project_key": "PROJ",
            },
            credential="user@example.com:api-token-here",
        )
    assert receipt.external_id == "PROJ-42"
    assert not receipt.external_id.startswith("sim-")


@pytest.mark.asyncio
async def test_jira_raises_on_4xx():
    mock_resp = _mock_resp(400, {"errorMessages": ["Invalid project key"], "errors": {}})
    with patch("aiohttp.ClientSession", return_value=_make_session(mock_resp)):
        adapter = JiraAdapter()
        with pytest.raises(ProviderError, match="client error"):
            await adapter.dispatch(
                {"title": "Test"},
                {"base_url": "https://mycompany.atlassian.net", "project_key": "INVALID"},
                credential="user@example.com:token",
            )


@pytest.mark.asyncio
async def test_jira_requires_base_url():
    adapter = JiraAdapter()
    with pytest.raises(ConfigurationError, match="base_url"):
        await adapter.dispatch({"title": "Test"}, {"project_key": "PROJ"}, credential="token")


@pytest.mark.asyncio
async def test_jira_requires_project_key():
    adapter = JiraAdapter()
    with pytest.raises(ConfigurationError, match="project_key"):
        await adapter.dispatch(
            {"title": "Test"},
            {"base_url": "https://mycompany.atlassian.net"},
            credential="token",
        )
