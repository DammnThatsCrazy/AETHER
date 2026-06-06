"""LLM text-to-query seam for Noesis.

The first production version intentionally avoids direct query execution. A
provider may return only a structured allowlisted QueryPlan; Noesis validates
that plan before dispatching it through existing read-only repositories.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from shared.logger.logger import get_logger

from .models import (
    SUPPORTED_INTENTS,
    SUPPORTED_FILTERS,
    MAX_LIMIT,
    WRITE_LIKE_KEYWORDS,
    NoesisQueryRequest,
    QueryPlan,
)

logger = get_logger("aether.service.noesis.provider")

_UNSAFE_PATTERNS = frozenset({"sql", "graphql", "gremlin", "cypher", "mutation", "drop", "truncate"})


class NoesisPlanProvider(Protocol):
    async def plan(self, request: NoesisQueryRequest, effective_tenant_id: str) -> QueryPlan | None:
        """Return a structured query plan or None when unavailable."""


class EnvironmentNoesisPlanProvider:
    """Minimal provider adapter used for tests and future OpenAI/Claude wiring.

    If NOESIS_LLM_PLAN_JSON is set, it is parsed as a QueryPlan. This keeps the
    runtime seam real and mockable without requiring live provider keys.
    """

    async def plan(self, request: NoesisQueryRequest, effective_tenant_id: str) -> QueryPlan | None:
        raw = os.getenv("NOESIS_LLM_PLAN_JSON", "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            data.setdefault("source", "llm")
            data.setdefault("tenant_id", effective_tenant_id)
            return QueryPlan.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - provider output is untrusted
            logger.warning(f"Noesis provider returned invalid plan: {exc}")
            return None


class ProductionNoesisPlanProvider:
    """Production-grade provider with feature flag gating, timeout, and validation.

    Reads configuration from environment:
    - NOESIS_LLM_ENABLED (default "false") — master kill-switch
    - NOESIS_LLM_PROVIDER — provider name (e.g. "openai", "anthropic")
    - NOESIS_LLM_TIMEOUT_MS (default 5000)
    - NOESIS_LLM_MAX_TOKENS (default 512)
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("NOESIS_LLM_ENABLED", "false").lower() in ("true", "1", "yes")
        self.provider_name = os.getenv("NOESIS_LLM_PROVIDER", "none")
        self.timeout_ms = int(os.getenv("NOESIS_LLM_TIMEOUT_MS", "5000"))
        self.max_tokens = int(os.getenv("NOESIS_LLM_MAX_TOKENS", "512"))

    async def plan(self, request: NoesisQueryRequest, effective_tenant_id: str) -> QueryPlan | None:
        if not self.enabled:
            logger.info("Noesis LLM provider disabled, returning None")
            return None

        # Placeholder for real LLM API call
        logger.info(
            "Noesis LLM provider would call external API",
            extra={
                "provider": self.provider_name,
                "timeout_ms": self.timeout_ms,
                "max_tokens": self.max_tokens,
                "tenant_id": effective_tenant_id,
            },
        )
        # When implemented, the call would go here with:
        # - asyncio.wait_for(call, timeout=self.timeout_ms / 1000)
        # - token limit enforcement via max_tokens
        # - response parsed into QueryPlan
        # - _validate_provider_plan() called before return
        return None

    def _validate_provider_plan(self, plan: QueryPlan, effective_tenant_id: str) -> QueryPlan | None:
        """Validate a plan from the provider before returning it upstream."""
        # Reject unsupported intents
        if plan.intent not in SUPPORTED_INTENTS:
            logger.warning("Provider returned unsupported intent", extra={"intent": plan.intent})
            return None

        # Reject tenant override
        if plan.tenant_id and plan.tenant_id != effective_tenant_id:
            logger.warning("Provider plan attempted tenant override", extra={"plan_tenant": plan.tenant_id, "effective": effective_tenant_id})
            return None

        # Reject unsafe filters
        plan_str = json.dumps(plan.model_dump()).lower()
        for pattern in _UNSAFE_PATTERNS:
            if pattern in plan_str:
                logger.warning("Provider plan contains unsafe pattern", extra={"pattern": pattern})
                return None

        # Reject mutation-like intents in filter values
        for v in plan.filters.values():
            if isinstance(v, str) and any(kw in v.lower() for kw in WRITE_LIKE_KEYWORDS):
                logger.warning("Provider plan filter contains write keyword")
                return None

        # Reject unsupported filters
        for key in plan.filters:
            if key not in SUPPORTED_FILTERS:
                logger.warning("Provider plan contains unsupported filter", extra={"filter": key})
                return None

        # Clamp limit
        plan.limit = min(max(plan.limit, 1), MAX_LIMIT)
        plan.tenant_id = effective_tenant_id
        plan.source = "llm"
        return plan
