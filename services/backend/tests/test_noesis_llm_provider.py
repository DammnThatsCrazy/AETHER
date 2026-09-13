"""Tests for the Noesis Phase 2 LLM provider layer."""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from services.noesis.models import MAX_LIMIT, NoesisQueryRequest, QueryPlan
from services.noesis.provider import (
    AnthropicNoesisPlanProvider,
    EnvironmentNoesisPlanProvider,
    OpenAINoesisPlanProvider,
    ProductionNoesisPlanProvider,
    _parse_plan_json,
    _validate_provider_plan,
)

TENANT = "tenant-x"


def _request(msg: str = "show me something obscure") -> NoesisQueryRequest:
    return NoesisQueryRequest(message=msg, surface="aether")


def _plan_json(intent: str = "alert_lookup", tenant_id: str = TENANT, extra: dict | None = None) -> str:
    data: dict = {
        "intent": intent,
        "tenant_id": tenant_id,
        "confidence": 0.85,
        "limit": 10,
        "filters": {},
    }
    if extra:
        data.update(extra)
    return json.dumps(data)


class _UnderBudget:
    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        return True

    async def release(self, tenant_id: str, tokens: int) -> None:
        pass


class _OverBudget:
    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        return False

    async def release(self, tenant_id: str, tokens: int) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# _parse_plan_json unit tests
# ═══════════════════════════════════════════════════════════════════════════


def test_parse_plan_json_valid():
    plan = _parse_plan_json(_plan_json(), TENANT)
    assert plan is not None
    assert plan.intent == "alert_lookup"
    assert plan.tenant_id == TENANT


def test_parse_plan_json_strips_markdown_fences():
    raw = f"```json\n{_plan_json()}\n```"
    plan = _parse_plan_json(raw, TENANT)
    assert plan is not None
    assert plan.intent == "alert_lookup"


def test_parse_plan_json_strips_bare_code_fence():
    raw = f"```\n{_plan_json()}\n```"
    plan = _parse_plan_json(raw, TENANT)
    assert plan is not None


def test_parse_plan_json_invalid_json_returns_none():
    plan = _parse_plan_json("not json at all {{{", TENANT)
    assert plan is None


def test_parse_plan_json_wrong_schema_returns_none():
    plan = _parse_plan_json(json.dumps({"completely_wrong": "value"}), TENANT)
    assert plan is None


def test_parse_plan_json_nonallowlisted_intent_returns_none():
    raw = json.dumps({
        "intent": "drop_table",
        "tenant_id": TENANT,
        "confidence": 0.9,
        "limit": 10,
        "filters": {},
    })
    plan = _parse_plan_json(raw, TENANT)
    assert plan is None


# ═══════════════════════════════════════════════════════════════════════════
# _validate_provider_plan unit tests
# ═══════════════════════════════════════════════════════════════════════════


def test_validate_provider_plan_tenant_override_rejected():
    plan = QueryPlan(intent="alert_lookup", tenant_id="evil-tenant", confidence=0.9)
    assert _validate_provider_plan(plan, TENANT) is None


def test_validate_provider_plan_unsafe_pattern_in_filters_rejected():
    plan = QueryPlan(
        intent="alert_lookup",
        tenant_id=TENANT,
        confidence=0.9,
        filters={"status": "1; sql injection"},
    )
    assert _validate_provider_plan(plan, TENANT) is None


def test_validate_provider_plan_write_keyword_in_filter_rejected():
    plan = QueryPlan(
        intent="alert_lookup",
        tenant_id=TENANT,
        confidence=0.9,
        filters={"status": "delete all records"},
    )
    assert _validate_provider_plan(plan, TENANT) is None


def test_validate_provider_plan_unsupported_filter_key_rejected():
    plan = QueryPlan(
        intent="alert_lookup",
        tenant_id=TENANT,
        confidence=0.9,
        filters={"unknown_field": "value"},
    )
    assert _validate_provider_plan(plan, TENANT) is None


def test_validate_provider_plan_clamps_limit_to_max():
    plan = QueryPlan(intent="alert_lookup", tenant_id=TENANT, confidence=0.9, limit=MAX_LIMIT)
    result = _validate_provider_plan(plan, TENANT)
    assert result is not None
    assert result.limit <= MAX_LIMIT


def test_validate_provider_plan_sets_source_and_tenant():
    plan = QueryPlan(intent="alert_lookup", tenant_id=None, confidence=0.9)
    result = _validate_provider_plan(plan, TENANT)
    assert result is not None
    assert result.source == "llm"
    assert result.tenant_id == TENANT


def test_validate_provider_plan_valid_passes():
    plan = QueryPlan(
        intent="entity_search",
        tenant_id=TENANT,
        confidence=0.75,
        filters={"entity_type": "human"},
    )
    result = _validate_provider_plan(plan, TENANT)
    assert result is not None
    assert result.intent == "entity_search"


# ═══════════════════════════════════════════════════════════════════════════
# AnthropicNoesisPlanProvider
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_anthropic_provider_disabled_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = False
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_missing_api_key_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = ""
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_budget_exceeded_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_OverBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_timeout_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.timeout_s = 0.001
    provider.max_retries = 0

    async def slow_call(msg: str) -> dict:
        await asyncio.sleep(10)
        return {"text": "{}", "tokens_used": 100}

    provider._call_api = slow_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_invalid_json_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    async def bad_call(msg: str) -> dict:
        return {"text": "not json at all", "tokens_used": 50}

    provider._call_api = bad_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_tenant_override_rejected():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    async def evil_call(msg: str) -> dict:
        return {"text": _plan_json(tenant_id="evil-tenant"), "tokens_used": 100}

    provider._call_api = evil_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_unsupported_intent_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    async def unsupported_call(msg: str) -> dict:
        return {"text": _plan_json(intent="unsupported"), "tokens_used": 100}

    provider._call_api = unsupported_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_anthropic_provider_valid_plan_returned():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    async def good_call(msg: str) -> dict:
        return {"text": _plan_json(), "tokens_used": 200}

    provider._call_api = good_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is not None
    assert result.intent == "alert_lookup"
    assert result.tenant_id == TENANT
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_anthropic_provider_retries_on_transient_error():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 1

    calls = 0

    async def flaky_call(msg: str) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient network error")
        return {"text": _plan_json(), "tokens_used": 200}

    provider._call_api = flaky_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is not None
    assert calls == 2


@pytest.mark.asyncio
async def test_anthropic_provider_exhausts_retries_returns_none():
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 1

    calls = 0

    async def always_fail(msg: str) -> dict:
        nonlocal calls
        calls += 1
        raise RuntimeError("persistent error")

    provider._call_api = always_fail  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None
    assert calls == 2  # initial attempt + 1 retry


# ═══════════════════════════════════════════════════════════════════════════
# OpenAINoesisPlanProvider
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_openai_provider_disabled_returns_none():
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = False
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_openai_provider_missing_api_key_returns_none():
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = ""
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_openai_provider_budget_exceeded_returns_none():
    provider = OpenAINoesisPlanProvider(budget=_OverBudget())
    provider.enabled = True
    provider.api_key = "sk-openai"
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_openai_provider_valid_plan_returned():
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-openai"
    provider.max_retries = 0

    async def good_call(msg: str) -> dict:
        return {"text": _plan_json(), "tokens_used": 150}

    provider._call_api = good_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is not None
    assert result.intent == "alert_lookup"
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_openai_provider_invalid_json_returns_none():
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-openai"
    provider.max_retries = 0

    async def bad_call(msg: str) -> dict:
        return {"text": "}{bad json", "tokens_used": 50}

    provider._call_api = bad_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_openai_provider_timeout_returns_none():
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-openai"
    provider.timeout_s = 0.001
    provider.max_retries = 0

    async def slow_call(msg: str) -> dict:
        await asyncio.sleep(10)
        return {"text": "{}", "tokens_used": 100}

    provider._call_api = slow_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_openai_provider_tenant_override_rejected():
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-openai"
    provider.max_retries = 0

    async def evil_call(msg: str) -> dict:
        return {"text": _plan_json(tenant_id="another-tenant"), "tokens_used": 100}

    provider._call_api = evil_call  # type: ignore[method-assign]
    result = await provider.plan(_request(), TENANT)
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# ProductionNoesisPlanProvider factory
# ═══════════════════════════════════════════════════════════════════════════


def test_production_factory_default_is_anthropic(monkeypatch):
    monkeypatch.delenv("NOESIS_LLM_PROVIDER", raising=False)
    provider = ProductionNoesisPlanProvider()
    assert provider.provider_name == "anthropic"
    assert isinstance(provider._inner, AnthropicNoesisPlanProvider)


def test_production_factory_selects_openai(monkeypatch):
    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "openai")
    provider = ProductionNoesisPlanProvider()
    assert provider.provider_name == "openai"
    assert isinstance(provider._inner, OpenAINoesisPlanProvider)


def test_production_factory_case_insensitive(monkeypatch):
    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "OPENAI")
    provider = ProductionNoesisPlanProvider()
    assert isinstance(provider._inner, OpenAINoesisPlanProvider)


@pytest.mark.asyncio
async def test_production_factory_delegates_plan_call():
    provider = ProductionNoesisPlanProvider()
    provider._inner.enabled = True
    provider._inner.api_key = "sk-test"
    provider._inner.max_retries = 0

    async def good_call(msg: str) -> dict:
        return {"text": _plan_json(), "tokens_used": 200}

    provider._inner._call_api = good_call  # type: ignore[method-assign]
    provider._inner._budget = _UnderBudget()  # type: ignore[assignment]
    result = await provider.plan(_request(), TENANT)
    assert result is not None
    assert result.intent == "alert_lookup"


# ═══════════════════════════════════════════════════════════════════════════
# EnvironmentNoesisPlanProvider (CI/test stub)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_environment_provider_empty_env_returns_none(monkeypatch):
    monkeypatch.setenv("NOESIS_LLM_PLAN_JSON", "")
    provider = EnvironmentNoesisPlanProvider()
    result = await provider.plan(_request(), TENANT)
    assert result is None


@pytest.mark.asyncio
async def test_environment_provider_reads_valid_plan(monkeypatch):
    monkeypatch.setenv("NOESIS_LLM_PLAN_JSON", _plan_json())
    provider = EnvironmentNoesisPlanProvider()
    result = await provider.plan(_request(), TENANT)
    assert result is not None
    assert result.intent == "alert_lookup"


@pytest.mark.asyncio
async def test_environment_provider_invalid_json_returns_none(monkeypatch):
    monkeypatch.setenv("NOESIS_LLM_PLAN_JSON", "{{bad json")
    provider = EnvironmentNoesisPlanProvider()
    result = await provider.plan(_request(), TENANT)
    assert result is None
