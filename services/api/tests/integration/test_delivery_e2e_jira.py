"""E2E integration test for Jira delivery adapter."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from actions.delivery.adapters.base import ConfigurationError, ProviderError
from actions.delivery.adapters.jira import JiraAdapter


def _jira_responding(status: int, data: dict):
    """Resolve the Jira host to a public address and answer with *data*."""
    dns = patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    send = patch.object(httpx.AsyncClient, "send", AsyncMock(return_value=httpx.Response(status, json=data)))
    return dns, send


@pytest.mark.asyncio
async def test_jira_success_returns_issue_key():
    issue_id = str(uuid.uuid4())
    dns, send = _jira_responding(201, {
        "id": issue_id,
        "key": "PROJ-42",
        "self": "https://mycompany.atlassian.net/rest/api/3/issue/" + issue_id,
    })
    with dns, send:
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
    dns, send = _jira_responding(400, {"errorMessages": ["Invalid project key"], "errors": {}})
    with dns, send:
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
