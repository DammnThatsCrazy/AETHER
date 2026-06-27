"""LLM text-to-query seam for Noesis.

Providers may return ONLY a structured allowlisted QueryPlan; Noesis validates
that plan before dispatching it through existing read-only repositories.

Production providers:
- AnthropicNoesisPlanProvider  — uses claude-haiku-4-5 via the Anthropic SDK
- OpenAINoesisPlanProvider      — uses gpt-4o-mini via httpx (no openai SDK required)

Both are gated by NOESIS_LLM_ENABLED and fall back to None on any error.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Protocol

from shared.logger.logger import get_logger, metrics

from .models import (
    MAX_LIMIT,
    SUPPORTED_FILTERS,
    SUPPORTED_INTENTS,
    WRITE_LIKE_KEYWORDS,
    NoesisQueryRequest,
    QueryPlan,
)
from .prompts import PROMPT_VERSION, build_system_prompt, build_user_message
from .token_budget import NoesisTokenBudget

logger = get_logger("aether.service.noesis.provider")

_UNSAFE_PATTERNS = frozenset({"sql", "graphql", "gremlin", "cypher", "mutation", "drop", "truncate"})

# Conservative token estimate for a single Noesis request (prompt + completion)
_ESTIMATED_REQUEST_TOKENS = 800


class NoesisPlanProvider(Protocol):
    async def plan(
        self,
        request: NoesisQueryRequest,
        effective_tenant_id: str,
        history: list[dict] | None = None,
    ) -> QueryPlan | None:
        """Return a structured query plan or None when unavailable."""


# ─── Shared plan validator ────────────────────────────────────────────────────

def _validate_provider_plan(plan: QueryPlan, effective_tenant_id: str) -> QueryPlan | None:
    """Validate a raw plan from any provider before returning upstream."""
    if plan.intent not in SUPPORTED_INTENTS:
        logger.warning("Provider returned unsupported intent", extra={"intent": plan.intent})
        metrics.increment("noesis_provider_invalid_plan", labels={"reason": "unsupported_intent"})
        return None
    if plan.tenant_id and plan.tenant_id != effective_tenant_id:
        logger.warning("Provider plan attempted tenant override", extra={"plan_tenant": plan.tenant_id, "effective": effective_tenant_id})
        metrics.increment("noesis_provider_invalid_plan", labels={"reason": "tenant_override"})
        return None
    plan_str = json.dumps(plan.model_dump()).lower()
    for pattern in _UNSAFE_PATTERNS:
        if pattern in plan_str:
            logger.warning("Provider plan contains unsafe pattern", extra={"pattern": pattern})
            metrics.increment("noesis_provider_invalid_plan", labels={"reason": "unsafe_pattern"})
            return None
    for v in plan.filters.values():
        if isinstance(v, str) and any(kw in v.lower() for kw in WRITE_LIKE_KEYWORDS):
            logger.warning("Provider plan filter contains write keyword")
            metrics.increment("noesis_provider_invalid_plan", labels={"reason": "write_keyword"})
            return None
    for key in plan.filters:
        if key not in SUPPORTED_FILTERS:
            logger.warning("Provider plan contains unsupported filter", extra={"filter": key})
            metrics.increment("noesis_provider_invalid_plan", labels={"reason": "unsupported_filter"})
            return None
    plan.limit = min(max(plan.limit, 1), MAX_LIMIT)
    plan.tenant_id = effective_tenant_id
    plan.source = "llm"
    return plan


def _parse_plan_json(raw: str, effective_tenant_id: str) -> QueryPlan | None:
    """Parse and validate raw JSON text from a provider into a QueryPlan."""
    text = raw.strip()
    # Strip markdown code fences if the model wrapped the JSON
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(l for l in lines if not l.startswith("```")).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"Provider returned invalid JSON: {exc}", extra={"raw": text[:200]})
        metrics.increment("noesis_provider_parse_failure", labels={"reason": "invalid_json"})
        return None
    data.setdefault("source", "llm")
    data.setdefault("tenant_id", effective_tenant_id)
    try:
        plan = QueryPlan.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Provider JSON failed QueryPlan validation: {exc}")
        metrics.increment("noesis_provider_parse_failure", labels={"reason": "schema_mismatch"})
        return None
    return _validate_provider_plan(plan, effective_tenant_id)


# ─── Environment stub (tests / CI without API keys) ──────────────────────────

class EnvironmentNoesisPlanProvider:
    """Minimal provider for tests: reads a fixed plan from NOESIS_LLM_PLAN_JSON."""

    async def plan(
        self,
        request: NoesisQueryRequest,
        effective_tenant_id: str,
        history: list[dict] | None = None,
    ) -> QueryPlan | None:
        raw = os.getenv("NOESIS_LLM_PLAN_JSON", "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            data.setdefault("source", "llm")
            data.setdefault("tenant_id", effective_tenant_id)
            return QueryPlan.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis env provider returned invalid plan: {exc}")
            return None


# ─── Anthropic provider ───────────────────────────────────────────────────────

class AnthropicNoesisPlanProvider:
    """Production provider using the Anthropic SDK (claude-haiku-4-5).

    Environment:
    - NOESIS_LLM_ENABLED       — "true" to enable
    - ANTHROPIC_API_KEY        — required when enabled
    - NOESIS_LLM_MODEL         — default "claude-haiku-4-5-20251001"
    - NOESIS_LLM_TIMEOUT_MS    — default 5000
    - NOESIS_LLM_MAX_TOKENS    — default 512
    - NOESIS_LLM_MAX_RETRIES   — default 1
    """

    provider_name = "anthropic"

    def __init__(self, budget: NoesisTokenBudget | None = None) -> None:
        self.enabled = os.getenv("NOESIS_LLM_ENABLED", "false").lower() in ("true", "1", "yes")
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("NOESIS_LLM_MODEL", "claude-haiku-4-5-20251001")
        self.timeout_s = int(os.getenv("NOESIS_LLM_TIMEOUT_MS", "5000")) / 1000
        self.max_tokens = int(os.getenv("NOESIS_LLM_MAX_TOKENS", "512"))
        self.max_retries = int(os.getenv("NOESIS_LLM_MAX_RETRIES", "1"))
        self._budget = budget or NoesisTokenBudget()
        self._system_prompt = build_system_prompt()

    async def plan(
        self,
        request: NoesisQueryRequest,
        effective_tenant_id: str,
        history: list[dict] | None = None,
    ) -> QueryPlan | None:
        if not self.enabled:
            return None
        if not self.api_key:
            logger.warning("Noesis Anthropic provider: ANTHROPIC_API_KEY not set")
            return None

        under_budget = await self._budget.check_and_reserve(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS)
        if not under_budget:
            return None

        context_hint = _build_context_hint(request)
        user_message = build_user_message(
            request.message, effective_tenant_id, request.surface, context_hint, history
        )

        for attempt in range(1, self.max_retries + 2):
            try:
                result = await asyncio.wait_for(
                    self._call_api(user_message),
                    timeout=self.timeout_s,
                )
                plan = _parse_plan_json(result["text"], effective_tenant_id)
                tokens = result.get("tokens_used", _ESTIMATED_REQUEST_TOKENS)
                # Adjust reservation to match actual spend
                if tokens < _ESTIMATED_REQUEST_TOKENS:
                    await self._budget.release(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS - tokens)
                elif tokens > _ESTIMATED_REQUEST_TOKENS:
                    await self._budget.charge(effective_tenant_id, tokens - _ESTIMATED_REQUEST_TOKENS)
                if plan is not None:
                    metrics.increment("noesis_provider_success", labels={"provider": self.provider_name})
                    logger.info(
                        "Noesis Anthropic provider returned plan",
                        extra={"intent": plan.intent, "confidence": plan.confidence,
                               "tokens": tokens, "model": self.model, "prompt_version": PROMPT_VERSION},
                    )
                return plan
            except asyncio.TimeoutError:
                logger.warning(f"Noesis Anthropic provider timeout (attempt {attempt})", extra={"timeout_s": self.timeout_s})
                metrics.increment("noesis_provider_timeout", labels={"provider": self.provider_name})
                if attempt > self.max_retries:
                    await self._budget.release(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS)
                    return None
                await asyncio.sleep(0.5 * attempt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Noesis Anthropic provider error: {exc}", extra={"attempt": attempt})
                metrics.increment("noesis_provider_error", labels={"provider": self.provider_name})
                if attempt > self.max_retries:
                    await self._budget.release(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS)
                    return None
                await asyncio.sleep(0.5 * attempt)
        return None

    async def _call_api(self, user_message: str) -> dict:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text if response.content else ""
        tokens_used = (response.usage.input_tokens + response.usage.output_tokens) if response.usage else _ESTIMATED_REQUEST_TOKENS
        return {"text": text, "tokens_used": tokens_used}


# ─── OpenAI provider ──────────────────────────────────────────────────────────

class OpenAINoesisPlanProvider:
    """Production provider using OpenAI (gpt-4o-mini) via httpx (no openai SDK needed).

    Environment:
    - NOESIS_LLM_ENABLED       — "true" to enable
    - OPENAI_API_KEY           — required when enabled
    - NOESIS_LLM_MODEL         — default "gpt-4o-mini"
    - NOESIS_LLM_TIMEOUT_MS    — default 5000
    - NOESIS_LLM_MAX_TOKENS    — default 512
    - NOESIS_LLM_MAX_RETRIES   — default 1
    - OPENAI_API_BASE          — override base URL (e.g. for Azure)
    """

    provider_name = "openai"

    def __init__(self, budget: NoesisTokenBudget | None = None) -> None:
        self.enabled = os.getenv("NOESIS_LLM_ENABLED", "false").lower() in ("true", "1", "yes")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("NOESIS_LLM_MODEL", "gpt-4o-mini")
        self.base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        self.timeout_s = int(os.getenv("NOESIS_LLM_TIMEOUT_MS", "5000")) / 1000
        self.max_tokens = int(os.getenv("NOESIS_LLM_MAX_TOKENS", "512"))
        self.max_retries = int(os.getenv("NOESIS_LLM_MAX_RETRIES", "1"))
        self._budget = budget or NoesisTokenBudget()
        self._system_prompt = build_system_prompt()

    async def plan(
        self,
        request: NoesisQueryRequest,
        effective_tenant_id: str,
        history: list[dict] | None = None,
    ) -> QueryPlan | None:
        if not self.enabled:
            return None
        if not self.api_key:
            logger.warning("Noesis OpenAI provider: OPENAI_API_KEY not set")
            return None

        under_budget = await self._budget.check_and_reserve(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS)
        if not under_budget:
            return None

        context_hint = _build_context_hint(request)
        user_message = build_user_message(
            request.message, effective_tenant_id, request.surface, context_hint, history
        )

        for attempt in range(1, self.max_retries + 2):
            try:
                result = await asyncio.wait_for(
                    self._call_api(user_message),
                    timeout=self.timeout_s,
                )
                plan = _parse_plan_json(result["text"], effective_tenant_id)
                tokens = result.get("tokens_used", _ESTIMATED_REQUEST_TOKENS)
                if tokens < _ESTIMATED_REQUEST_TOKENS:
                    await self._budget.release(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS - tokens)
                if plan is not None:
                    metrics.increment("noesis_provider_success", labels={"provider": self.provider_name})
                    logger.info(
                        "Noesis OpenAI provider returned plan",
                        extra={"intent": plan.intent, "confidence": plan.confidence,
                               "tokens": tokens, "model": self.model, "prompt_version": PROMPT_VERSION},
                    )
                return plan
            except asyncio.TimeoutError:
                logger.warning(f"Noesis OpenAI provider timeout (attempt {attempt})")
                metrics.increment("noesis_provider_timeout", labels={"provider": self.provider_name})
                if attempt > self.max_retries:
                    await self._budget.release(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS)
                    return None
                await asyncio.sleep(0.5 * attempt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Noesis OpenAI provider error: {exc}", extra={"attempt": attempt})
                metrics.increment("noesis_provider_error", labels={"provider": self.provider_name})
                if attempt > self.max_retries:
                    await self._budget.release(effective_tenant_id, _ESTIMATED_REQUEST_TOKENS)
                    return None
                await asyncio.sleep(0.5 * attempt)
        return None

    async def _call_api(self, user_message: str) -> dict:
        import httpx
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()
        text = body["choices"][0]["message"]["content"]
        tokens_used = body.get("usage", {}).get("total_tokens", _ESTIMATED_REQUEST_TOKENS)
        return {"text": text, "tokens_used": tokens_used}


# ─── Production provider factory ─────────────────────────────────────────────

class ProductionNoesisPlanProvider:
    """Routes to the configured provider or returns None when disabled.

    Uses NOESIS_LLM_PROVIDER to select "anthropic" (default) or "openai".
    Falls back to None if the provider is not configured or fails.
    """

    provider_name = "production"

    def __init__(self, budget: NoesisTokenBudget | None = None) -> None:
        name = os.getenv("NOESIS_LLM_PROVIDER", "anthropic").lower()
        if name == "openai":
            self._inner: AnthropicNoesisPlanProvider | OpenAINoesisPlanProvider = OpenAINoesisPlanProvider(budget)
            self.provider_name = "openai"
        else:
            self._inner = AnthropicNoesisPlanProvider(budget)
            self.provider_name = "anthropic"

    async def plan(
        self,
        request: NoesisQueryRequest,
        effective_tenant_id: str,
        history: list[dict] | None = None,
    ) -> QueryPlan | None:
        return await self._inner.plan(request, effective_tenant_id, history)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build_context_hint(request: NoesisQueryRequest) -> str | None:
    ctx = request.context
    parts = []
    if ctx.current_page:
        parts.append(f"page={ctx.current_page}")
    if ctx.selected_entity_id:
        parts.append(f"entity={ctx.selected_entity_id}")
    if ctx.time_range:
        parts.append(f"time_range={ctx.time_range}")
    return ", ".join(parts) if parts else None
