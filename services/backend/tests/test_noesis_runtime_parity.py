"""Commit 3 parity tests: Noesis legacy seam preserved behind the model-runtime.

These tests prove Commit 3's invariant: the LLM transport moved out of the
Noesis providers' ``_call_api`` methods and behind the model-runtime adapters
(``services.model_runtime.adapters``), while the public ``plan()`` behavior and
the legacy ``_call_api -> dict`` seam are fully preserved.

The 37 tests in ``tests/test_noesis_llm_provider.py`` still monkeypatch
``provider._call_api = async fn`` and assert the dict shape; they pass
unchanged. This file adds the runtime-aware parity assertions on top.
"""

from __future__ import annotations

import asyncio  # noqa: F401  (kept for parity with the legacy test module)
import json

import pytest

import services.noesis.provider as provider_module
from services.model_runtime.models import (
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)
from services.noesis.models import NoesisQueryRequest, QueryPlan
from services.noesis.provider import (
    _ESTIMATED_REQUEST_TOKENS,
    AnthropicNoesisPlanProvider,
    OpenAINoesisPlanProvider,
    ProductionNoesisPlanProvider,
)

TENANT = "tenant-x"
_PLAN_JSON = json.dumps({
    "intent": "alert_lookup",
    "tenant_id": TENANT,
    "confidence": 0.85,
    "limit": 10,
    "filters": {},
})


# ─── Budget stubs (mirror the legacy test file style) ────────────────────────


class _UnderBudget:
    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        return True

    async def release(self, tenant_id: str, tokens: int) -> None:
        pass

    async def charge(self, tenant_id: str, tokens: int) -> None:
        pass


class _ChargeSpy:
    def __init__(self) -> None:
        self.releases = 0
        self.charges = 0

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        return True

    async def release(self, tenant_id: str, tokens: int) -> None:
        self.releases += 1

    async def charge(self, tenant_id: str, tokens: int) -> None:
        self.charges += 1


# ─── Fakes ────────────────────────────────────────────────────────────────────


def _response(
    content: str,
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    provider: ModelProvider = ModelProvider.ANTHROPIC,
    model: str = "claude-test",
) -> ModelResponse:
    return ModelResponse(
        content=content,
        model=model,
        provider=provider,
        usage=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        latency_ms=1.0,
        finish_reason="stop",
        raw={},
    )


def _fake_adapter(response: ModelResponse | None = None, error: Exception | None = None):
    """Build a fake model-runtime adapter that records constructor + calls."""
    records: dict[str, object] = {"construct_kwargs": [], "requests": []}

    class FakeAdapter:
        def __init__(self, **kwargs: object) -> None:
            kwargs_list = records["construct_kwargs"]
            assert isinstance(kwargs_list, list)
            kwargs_list.append(kwargs)

        async def complete(self, request: ModelRequest) -> ModelResponse:
            requests = records["requests"]
            assert isinstance(requests, list)
            requests.append(request)
            if error is not None:
                raise error
            if response is None:
                raise AssertionError("fake adapter response not configured")
            return response

    return FakeAdapter, records


# ═══════════════════════════════════════════════════════════════════════════
# A. No direct SDK imports in provider.py
# ═══════════════════════════════════════════════════════════════════════════


def test_provider_module_has_no_direct_sdk_imports():
    """The SDK/httpx transport must live in the adapters, not in provider.py."""
    from pathlib import Path

    source = Path(provider_module.__file__).resolve().read_text()
    assert "import anthropic" not in source
    assert "import httpx" not in source
    assert "from anthropic" not in source
    assert "from httpx" not in source


def test_provider_module_has_no_sdk_module_attributes():
    """Commit 3 must not leave anthropic/httpx bound in the module namespace."""
    assert getattr(provider_module, "anthropic", None) is None
    assert getattr(provider_module, "httpx", None) is None


# ═══════════════════════════════════════════════════════════════════════════
# B. Anthropic _call_api delegates to the model-runtime adapter
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_anthropic_call_api_delegates_request(monkeypatch):
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.api_key = "sk-test"
    provider.model = "claude-test"
    provider.max_tokens = 123
    provider._system_prompt = "system prompt"

    fake, records = _fake_adapter(_response(content="hello"))
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    await provider._call_api("user message")

    requests = records["requests"]
    assert isinstance(requests, list)
    assert len(requests) == 1
    request = requests[0]
    assert isinstance(request, ModelRequest)
    assert request.messages == [{"role": "user", "content": "user message"}]
    assert request.system_prompt == "system prompt"
    assert request.max_tokens == 123
    assert request.metadata == {"task": "noesis_query_planning", "surface": "noesis"}


@pytest.mark.asyncio
async def test_anthropic_call_api_returns_legacy_dict_shape(monkeypatch):
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.api_key = "sk-test"
    provider.model = "claude-test"
    provider.max_tokens = 123
    provider._system_prompt = "system prompt"

    resp = _response(content="plan text", input_tokens=10, output_tokens=5)
    fake, _ = _fake_adapter(resp)
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    result = await provider._call_api("user message")
    assert set(result.keys()) == {"text", "tokens_used", "input_tokens", "output_tokens"}
    assert result["text"] == resp.content
    assert result["tokens_used"] == 15
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5


@pytest.mark.asyncio
async def test_anthropic_adapter_constructed_with_provider_config(monkeypatch):
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.api_key = "sk-test"
    provider.model = "claude-test"
    provider.timeout_s = 3.0
    provider.max_tokens = 123
    provider.max_retries = 2
    provider._system_prompt = "system prompt"

    fake, records = _fake_adapter(_response(content="hello"))
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    await provider._call_api("user message")

    kwargs_list = records["construct_kwargs"]
    assert isinstance(kwargs_list, list)
    assert len(kwargs_list) == 1
    kwargs = kwargs_list[0]
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["model"] == "claude-test"
    assert kwargs["timeout_s"] == 3.0
    assert kwargs["max_tokens"] == 123
    assert kwargs["max_retries"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# C. OpenAI _call_api delegates to the model-runtime adapter
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_openai_call_api_delegates_request(monkeypatch):
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.api_key = "sk-openai"
    provider.model = "gpt-test"
    provider.base_url = "https://custom.example/v1"
    provider.max_tokens = 456
    provider._system_prompt = "system prompt"

    fake, records = _fake_adapter(
        _response(content="hello", provider=ModelProvider.OPENAI, model="gpt-test")
    )
    monkeypatch.setattr(provider_module, "OpenAIModelProvider", fake)

    await provider._call_api("user message")

    requests = records["requests"]
    assert isinstance(requests, list)
    assert len(requests) == 1
    request = requests[0]
    assert isinstance(request, ModelRequest)
    assert request.messages == [{"role": "user", "content": "user message"}]
    assert request.system_prompt == "system prompt"
    assert request.max_tokens == 456
    assert request.response_format == "json_object"
    assert request.metadata == {"task": "noesis_query_planning", "surface": "noesis"}


@pytest.mark.asyncio
async def test_openai_call_api_returns_legacy_dict_shape(monkeypatch):
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.api_key = "sk-openai"
    provider.model = "gpt-test"
    provider.base_url = "https://custom.example/v1"
    provider.max_tokens = 456
    provider._system_prompt = "system prompt"

    resp = _response(
        content="plan text", input_tokens=20, output_tokens=7,
        provider=ModelProvider.OPENAI, model="gpt-test",
    )
    fake, _ = _fake_adapter(resp)
    monkeypatch.setattr(provider_module, "OpenAIModelProvider", fake)

    result = await provider._call_api("user message")
    assert set(result.keys()) == {"text", "tokens_used", "input_tokens", "output_tokens"}
    assert result["text"] == resp.content
    assert result["tokens_used"] == 27
    assert result["input_tokens"] == 20
    assert result["output_tokens"] == 7


@pytest.mark.asyncio
async def test_openai_adapter_constructed_with_provider_config(monkeypatch):
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.api_key = "sk-openai"
    provider.model = "gpt-test"
    provider.base_url = "https://custom.example/v1"
    provider.timeout_s = 4.0
    provider.max_tokens = 456
    provider.max_retries = 3
    provider._system_prompt = "system prompt"

    fake, records = _fake_adapter(
        _response(content="hello", provider=ModelProvider.OPENAI, model="gpt-test")
    )
    monkeypatch.setattr(provider_module, "OpenAIModelProvider", fake)

    await provider._call_api("user message")

    kwargs_list = records["construct_kwargs"]
    assert isinstance(kwargs_list, list)
    assert len(kwargs_list) == 1
    kwargs = kwargs_list[0]
    assert kwargs["api_key"] == "sk-openai"
    assert kwargs["model"] == "gpt-test"
    assert kwargs["base_url"] == "https://custom.example/v1"
    assert kwargs["timeout_s"] == 4.0
    assert kwargs["max_tokens"] == 456
    assert kwargs["max_retries"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# D. End-to-end behavior preserved through the adapters
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_anthropic_plan_end_to_end_via_adapter(monkeypatch):
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    fake, _ = _fake_adapter(_response(content=_PLAN_JSON, input_tokens=100, output_tokens=100))
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    result = await provider.plan(NoesisQueryRequest(message="hi", surface="aether"), TENANT)
    assert isinstance(result, QueryPlan)
    assert result.intent == "alert_lookup"
    assert result.tenant_id == TENANT
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_openai_plan_end_to_end_via_adapter(monkeypatch):
    provider = OpenAINoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-openai"
    provider.max_retries = 0

    fake, _ = _fake_adapter(
        _response(content=_PLAN_JSON, input_tokens=100, output_tokens=100,
                  provider=ModelProvider.OPENAI, model="gpt-test")
    )
    monkeypatch.setattr(provider_module, "OpenAIModelProvider", fake)

    result = await provider.plan(NoesisQueryRequest(message="hi", surface="aether"), TENANT)
    assert isinstance(result, QueryPlan)
    assert result.intent == "alert_lookup"
    assert result.tenant_id == TENANT
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_plan_fails_closed_on_provider_error(monkeypatch):
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    fake, _ = _fake_adapter(error=ModelProviderError("provider failure"))
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    result = await provider.plan(NoesisQueryRequest(message="hi", surface="aether"), TENANT)
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# E. _call_api is still monkeypatchable (legacy seam)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_legacy_call_api_seam_still_monkeypatchable():
    """The test seam used by test_noesis_llm_provider.py must be intact."""
    provider = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    async def good_call(msg: str) -> dict:
        return {"text": _PLAN_JSON, "tokens_used": 100}

    provider._call_api = good_call  # type: ignore[method-assign]
    result = await provider.plan(NoesisQueryRequest(message="hi", surface="aether"), TENANT)
    assert result is not None
    assert result.intent == "alert_lookup"
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_plan_releases_overestimate_when_usage_low(monkeypatch):
    """Actual spend below the 800-token estimate releases the reservation."""
    spy = _ChargeSpy()
    provider = AnthropicNoesisPlanProvider(budget=spy)
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    low = _ESTIMATED_REQUEST_TOKENS // 4  # 200 tokens total spend
    fake, _ = _fake_adapter(_response(content=_PLAN_JSON, input_tokens=low // 2,
                                      output_tokens=low // 2))
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    result = await provider.plan(NoesisQueryRequest(message="hi", surface="aether"), TENANT)
    assert result is not None
    assert spy.releases == 1
    assert spy.charges == 0


@pytest.mark.asyncio
async def test_plan_charges_overestimate_when_usage_high(monkeypatch):
    """Actual spend above the 800-token estimate charges the difference."""
    spy = _ChargeSpy()
    provider = AnthropicNoesisPlanProvider(budget=spy)
    provider.enabled = True
    provider.api_key = "sk-test"
    provider.max_retries = 0

    high = _ESTIMATED_REQUEST_TOKENS  # 800+800 = 1600 total spend
    fake, _ = _fake_adapter(_response(content=_PLAN_JSON, input_tokens=high,
                                      output_tokens=high))
    monkeypatch.setattr(provider_module, "AnthropicModelProvider", fake)

    result = await provider.plan(NoesisQueryRequest(message="hi", surface="aether"), TENANT)
    assert result is not None
    assert spy.charges == 1
    assert spy.releases == 0


# ═══════════════════════════════════════════════════════════════════════════
# F. Construction parity (factory + env var wiring unchanged by Commit 3)
# ═══════════════════════════════════════════════════════════════════════════


def test_production_factory_construction_parity(monkeypatch):
    monkeypatch.delenv("NOESIS_LLM_PROVIDER", raising=False)
    provider = ProductionNoesisPlanProvider()
    assert provider.provider_name == "anthropic"
    assert isinstance(provider._inner, AnthropicNoesisPlanProvider)

    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "openai")
    provider = ProductionNoesisPlanProvider()
    assert provider.provider_name == "openai"
    assert isinstance(provider._inner, OpenAINoesisPlanProvider)


def test_provider_constructors_read_documented_env_vars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-e")
    monkeypatch.setenv("NOESIS_LLM_MODEL", "claude-test")
    anthropic = AnthropicNoesisPlanProvider(budget=_UnderBudget())
    assert anthropic.api_key == "sk-e"
    assert anthropic.model == "claude-test"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("NOESIS_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_API_BASE", "https://custom.example/v1")
    openai = OpenAINoesisPlanProvider(budget=_UnderBudget())
    assert openai.api_key == "sk-openai-test"
    assert openai.model == "gpt-test"
    assert openai.base_url == "https://custom.example/v1"
