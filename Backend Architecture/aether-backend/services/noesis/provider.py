"""LLM text-to-query seam for Noesis.

The provider returns only a structured allowlisted QueryPlan. Noesis validates
that plan before read-only dispatch and never executes provider text directly.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from shared.logger.logger import get_logger

from .models import NoesisQueryRequest, QueryPlan

logger = get_logger("aether.service.noesis.provider")

try:
    import httpx
except ImportError:  # pragma: no cover - optional in lightweight envs
    httpx = None  # type: ignore[assignment]

_ALLOWED_INTENTS = [
    "entity_search",
    "graph_lookup",
    "alert_lookup",
    "tenant_summary",
    "profile_lookup",
    "wallet_lookup",
    "agent_lookup",
    "health_lookup",
    "campaign_reward_lookup",
    "risk_cluster_lookup",
    "unsupported",
]


class NoesisPlanProvider(Protocol):
    async def plan(self, request: NoesisQueryRequest, effective_tenant_id: str) -> QueryPlan | None:
        """Return a structured query plan or None when unavailable."""


class EnvironmentNoesisPlanProvider:
    """Mockable provider adapter plus OpenAI-compatible structured-plan support.

    Test/local override:
      - NOESIS_LLM_PLAN_JSON={...QueryPlan...}

    OpenAI-compatible provider:
      - NOESIS_LLM_PROVIDER=openai_compatible
      - NOESIS_LLM_ENDPOINT=https://.../v1/chat/completions
      - NOESIS_LLM_API_KEY=...
      - NOESIS_LLM_MODEL=...
    """

    async def plan(self, request: NoesisQueryRequest, effective_tenant_id: str) -> QueryPlan | None:
        mocked = self._mock_plan(effective_tenant_id)
        if mocked is not None:
            return mocked
        if os.getenv("NOESIS_LLM_PROVIDER", "").strip().lower() == "openai_compatible":
            return await self._openai_compatible_plan(request, effective_tenant_id)
        return None

    def _mock_plan(self, effective_tenant_id: str) -> QueryPlan | None:
        raw = os.getenv("NOESIS_LLM_PLAN_JSON", "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            data.setdefault("source", "llm")
            data.setdefault("tenant_id", effective_tenant_id)
            return QueryPlan.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - provider output is untrusted
            logger.warning(f"Noesis provider returned invalid mock plan: {exc}")
            return None

    async def _openai_compatible_plan(
        self,
        request: NoesisQueryRequest,
        effective_tenant_id: str,
    ) -> QueryPlan | None:
        endpoint = os.getenv("NOESIS_LLM_ENDPOINT", "").strip()
        api_key = os.getenv("NOESIS_LLM_API_KEY", "").strip()
        model = os.getenv("NOESIS_LLM_MODEL", "").strip() or "gpt-4o-mini"
        if not endpoint or not api_key or httpx is None:
            return None
        prompt = self._planner_prompt(request, effective_tenant_id)
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": request.message},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed.setdefault("source", "llm")
            parsed.setdefault("tenant_id", effective_tenant_id)
            return QueryPlan.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001 - fail closed to deterministic/fallback
            logger.warning(f"Noesis OpenAI-compatible provider failed closed: {exc}")
            return None

    def _planner_prompt(self, request: NoesisQueryRequest, effective_tenant_id: str) -> str:
        return (
            "You are Noesis query planner. Return only JSON for a read-only QueryPlan. "
            f"Allowed intents: {', '.join(_ALLOWED_INTENTS)}. "
            "Never generate SQL, GraphQL, Gremlin, mutations, deletes, writes, or operational commands. "
            f"The only allowed tenant_id is {effective_tenant_id!r}. "
            "Use limit 1..50. Include target/entity_type/time_range only if needed. "
            f"Surface is {request.surface!r}; context is {request.context.model_dump_json()}."
        )
