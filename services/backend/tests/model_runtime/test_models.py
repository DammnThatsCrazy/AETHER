"""Provider-neutral model-runtime data models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelInvocationError,
    ModelNotConfigured,
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    TokenUsage,
)


def test_model_request_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        ModelRequest(model="x", messages=[], bogus=1)


def test_model_request_defaults():
    req = ModelRequest(model="x", messages=[])
    assert req.messages == []
    assert req.metadata == {}
    assert req.system_prompt is None
    assert req.max_tokens is None
    assert req.temperature is None
    # messages is required
    with pytest.raises(ValidationError):
        ModelRequest(model="x")


def test_token_usage_defaults():
    usage = TokenUsage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 0
    # total_tokens is independent, not auto-computed from input + output.
    assert TokenUsage(input_tokens=5, output_tokens=7).total_tokens == 0
    assert TokenUsage(input_tokens=5, output_tokens=7, total_tokens=12).total_tokens == 12


def test_model_response_is_frozen():
    resp = ModelResponse(
        content="hi",
        model="m",
        provider=ModelProvider.DETERMINISTIC,
        usage=TokenUsage(),
        latency_ms=1.0,
    )
    with pytest.raises(ValidationError):
        resp.content = "x"


def test_model_response_fields():
    usage = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3)
    resp = ModelResponse(
        content="hello",
        model="claude-haiku-4-5-20251001",
        provider=ModelProvider.ANTHROPIC,
        usage=usage,
        latency_ms=42.5,
        finish_reason="stop",
        raw={"k": "v"},
    )
    assert resp.content == "hello"
    assert resp.model == "claude-haiku-4-5-20251001"
    assert resp.provider == ModelProvider.ANTHROPIC
    assert resp.usage == usage
    assert resp.latency_ms == 42.5
    assert resp.finish_reason == "stop"
    assert resp.raw == {"k": "v"}
    # raw defaults to {} when omitted
    bare = ModelResponse(
        content="c",
        model="m",
        provider=ModelProvider.OPENAI,
        usage=TokenUsage(),
        latency_ms=0.0,
    )
    assert bare.raw == {}


def test_error_hierarchy():
    assert issubclass(ModelProviderError, ModelInvocationError)
    assert issubclass(ModelTimeoutError, ModelInvocationError)
    assert issubclass(ModelBudgetExceeded, ModelInvocationError)
    assert issubclass(ModelNotConfigured, ModelInvocationError)
    assert issubclass(ModelInvocationError, Exception)


def test_provider_enum_values():
    assert ModelProvider.ANTHROPIC.value == "anthropic"
    assert ModelProvider.OPENAI.value == "openai"
    assert ModelProvider.DETERMINISTIC.value == "deterministic"
