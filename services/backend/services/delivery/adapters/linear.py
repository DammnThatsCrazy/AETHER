"""Linear adapter — GraphQL IssueCreate mutation.

Creates a Linear issue and returns its `id` as the external_id.
"""

from __future__ import annotations

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

logger = get_logger("aether.delivery.adapters.linear")

_LINEAR_API_URL = "https://api.linear.app/graphql"

_ISSUE_CREATE_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      identifier
      url
      title
    }
  }
}
"""


class LinearAdapter(ProviderAdapter):
    """Delivers a payload to Linear by creating an issue."""

    adapter_name = "linear"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        api_key = credential or provider_config.get("api_key") or provider_config.get("token")
        if not api_key:
            raise ConfigurationError(
                "LinearAdapter requires an API key (credential or provider_config.api_key)"
            )

        team_id = provider_config.get("team_id")
        if not team_id:
            raise ConfigurationError("LinearAdapter requires provider_config.team_id")

        title = payload.get("title", "Aether Notification")
        description = payload.get("body") or payload.get("summary", "")
        priority = _map_priority(payload.get("priority"))
        assignee_id = provider_config.get("assignee_id")
        label_ids = provider_config.get("label_ids") or []

        issue_input: dict[str, Any] = {
            "title": title[:255],
            "description": description,
            "teamId": team_id,
            "priority": priority,
        }
        if assignee_id:
            issue_input["assigneeId"] = assignee_id
        if label_ids:
            issue_input["labelIds"] = label_ids

        variables = {"input": issue_input}
        request_body = {"query": _ISSUE_CREATE_MUTATION, "variables": variables}

        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

        try:
            import aiohttp
        except ImportError:
            raise ConfigurationError("aiohttp is required for LinearAdapter: pip install aiohttp")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                _LINEAR_API_URL,
                headers=headers,
                data=json.dumps(request_body),
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
                        "Linear rate-limited: HTTP 429",
                        http_status=429,
                        retry_after_seconds=retry_after,
                    )
                if status >= 500:
                    raise RetryableProviderError(
                        f"Linear server error: HTTP {status}",
                        http_status=status,
                    )
                if status >= 400:
                    raise ProviderError(
                        f"Linear client error: HTTP {status} — {data}",
                        http_status=status,
                    )

                errors = data.get("errors")
                if errors:
                    raise ProviderError(
                        f"Linear GraphQL errors: {errors}",
                        http_status=status,
                    )

                result = (data.get("data") or {}).get("issueCreate") or {}
                if not result.get("success"):
                    raise ProviderError(
                        f"Linear IssueCreate returned success=false: {data}",
                        http_status=status,
                    )

                issue = result.get("issue") or {}
                external_id = issue.get("id")
                if not external_id:
                    raise ProviderError(
                        f"Linear response missing issue.id: {data}",
                        http_status=status,
                    )

                logger.info(
                    f"Linear issue created: id={external_id!r} "
                    f"identifier={issue.get('identifier')!r}"
                )
                return AdapterReceipt(
                    external_id=external_id,
                    raw_response=data,
                    http_status=status,
                )


def _map_priority(priority_str: Optional[str]) -> int:
    """Map Aether priority strings to Linear priority integers (0=no priority, 1=urgent, 4=low)."""
    mapping = {"P0": 1, "P1": 2, "P2": 3, "P3": 4, "INFO": 0}
    return mapping.get(str(priority_str).upper() if priority_str else "", 3)
