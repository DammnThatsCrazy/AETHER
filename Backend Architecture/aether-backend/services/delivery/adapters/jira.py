"""Jira REST v3 adapter — creates an issue via the Jira Cloud REST API.

Uses basic auth (email:api_token) or Bearer token. Returns the Jira issue key
(e.g., PROJ-42) as the external_id.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderError,
    RetryableProviderError,
)

logger = get_logger("aether.delivery.adapters.jira")


def _jira_api_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/rest/api/3/issue"


def _build_adf_body(text: str) -> dict[str, Any]:
    """Wrap plain text in Atlassian Document Format (ADF)."""
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text or " "}],
            }
        ],
    }


class JiraAdapter(ProviderAdapter):
    """Delivers a payload to Jira by creating an issue."""

    adapter_name = "jira"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        base_url = provider_config.get("base_url") or provider_config.get("site_url")
        if not base_url:
            raise ConfigurationError(
                "JiraAdapter requires provider_config.base_url "
                "(e.g., https://mycompany.atlassian.net)"
            )

        project_key = provider_config.get("project_key")
        if not project_key:
            raise ConfigurationError("JiraAdapter requires provider_config.project_key")

        issue_type = provider_config.get("issue_type", "Task")
        title = payload.get("title", "Aether Notification")
        body_text = payload.get("body") or payload.get("summary", "")
        priority_name = _map_priority(payload.get("priority"))

        issue_data: dict[str, Any] = {
            "fields": {
                "project": {"key": project_key},
                "summary": title[:255],
                "issuetype": {"name": issue_type},
                "description": _build_adf_body(body_text),
                "priority": {"name": priority_name},
            }
        }

        # Build auth header
        api_url = _jira_api_url(base_url)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        # credential can be "email:api_token" (basic) or "Bearer <token>"
        if credential:
            if ":" in credential and not credential.startswith("Bearer "):
                # Basic auth: email:api_token
                encoded = base64.b64encode(credential.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            else:
                token = credential.removeprefix("Bearer ").strip()
                headers["Authorization"] = f"Bearer {token}"
        else:
            email = provider_config.get("email")
            api_token = provider_config.get("api_token")
            if email and api_token:
                encoded = base64.b64encode(f"{email}:{api_token}".encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            else:
                raise ConfigurationError(
                    "JiraAdapter requires credential or (provider_config.email + provider_config.api_token)"
                )

        try:
            import aiohttp
        except ImportError:
            raise ConfigurationError("aiohttp is required for JiraAdapter: pip install aiohttp")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                headers=headers,
                data=json.dumps(issue_data),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {}

                if status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    raise RetryableProviderError(
                        "Jira rate-limited: HTTP 429",
                        http_status=429,
                        retry_after_seconds=retry_after,
                    )
                if status >= 500:
                    raise RetryableProviderError(
                        f"Jira server error: HTTP {status}",
                        http_status=status,
                    )
                if status >= 400:
                    raise ProviderError(
                        f"Jira client error: HTTP {status} — {data}",
                        http_status=status,
                    )

                # Jira returns 201 Created with {"id": "...", "key": "PROJ-42", "self": "..."}
                issue_key = data.get("key")
                issue_id = data.get("id")
                if not issue_key:
                    raise ProviderError(
                        f"Jira response missing 'key' field: {data}",
                        http_status=status,
                    )

                external_id = issue_key  # e.g., "PROJ-42"
                logger.info(f"Jira issue created: key={external_id!r} id={issue_id!r}")
                return AdapterReceipt(
                    external_id=external_id,
                    raw_response=data,
                    http_status=status,
                )


def _map_priority(priority_str: Optional[str]) -> str:
    """Map Aether priority to Jira priority name."""
    mapping = {
        "P0": "Highest",
        "P1": "High",
        "P2": "Medium",
        "P3": "Low",
        "INFO": "Lowest",
    }
    return mapping.get(str(priority_str).upper() if priority_str else "", "Medium")
