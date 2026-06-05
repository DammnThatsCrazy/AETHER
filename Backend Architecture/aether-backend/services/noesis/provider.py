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

from .models import NoesisQueryRequest, QueryPlan

logger = get_logger("aether.service.noesis.provider")


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
