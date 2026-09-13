"""Model-runtime providers: base contract + deterministic fallback."""
from __future__ import annotations

import pytest

from services.model_runtime.deterministic import DeterministicModelProvider
from services.model_runtime.models import (
    ModelNotConfigured,
    ModelProvider,
    ModelRequest,
)
from services.model_runtime.provider import AsyncModelProvider, BaseModelProvider


def _request(model: str = "x") -> ModelRequest:
    return ModelRequest(model=model, messages=[])


def test_base_provider_not_configured_by_default():
    assert BaseModelProvider().is_configured() is False
    assert BaseModelProvider(enabled=True).is_configured() is True


@pytest.mark.asyncio
async def test_base_complete_raises_not_configured():
    with pytest.raises(ModelNotConfigured):
        await BaseModelProvider().complete(_request())


@pytest.mark.asyncio
async def test_deterministic_fixed_response():
    provider = DeterministicModelProvider(response_override="fixed", model_id="m1")
    resp = await provider.complete(_request())
    assert resp.content == "fixed"
    assert resp.model == "m1"
    assert resp.provider == ModelProvider.DETERMINISTIC
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 20
    assert resp.usage.total_tokens == 30
    assert resp.latency_ms == 1.0
    assert resp.finish_reason == "stop"
    assert provider.is_configured() is True


@pytest.mark.asyncio
async def test_deterministic_defaults_to_request_model():
    provider = DeterministicModelProvider()
    resp = await provider.complete(_request(model="my-model"))
    assert resp.model == "my-model"
    assert "my-model" in resp.content
    assert resp.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_deterministic_env_overrides(monkeypatch):
    # Constructor reads env at __init__ time, so set env before constructing.
    monkeypatch.setenv("MODEL_RUNTIME_DETERMINISTIC_RESPONSE", "env text")
    monkeypatch.setenv("MODEL_RUNTIME_DETERMINISTIC_MODEL", "env-model")
    provider = DeterministicModelProvider()
    resp = await provider.complete(_request(model="ignored"))
    assert resp.content == "env text"
    assert resp.model == "env-model"


@pytest.mark.asyncio
async def test_deterministic_constructor_beats_env(monkeypatch):
    monkeypatch.setenv("MODEL_RUNTIME_DETERMINISTIC_RESPONSE", "env text")
    provider = DeterministicModelProvider(response_override="ctor")
    resp = await provider.complete(_request())
    assert resp.content == "ctor"


@pytest.mark.asyncio
async def test_deterministic_raises_injected_error():
    provider = DeterministicModelProvider(raise_error=RuntimeError("boom"))
    with pytest.raises(RuntimeError) as exc_info:
        await provider.complete(_request())
    assert str(exc_info.value) == "boom"


def test_async_model_provider_protocol_is_satisfied():
    """Both providers are structurally compatible with AsyncModelProvider.

    AsyncModelProvider is a plain Protocol (non-runtime_checkable) with a data
    member (provider_name), so ``isinstance`` is unavailable; the structural
    check below mirrors how the orchestrator consumes providers at runtime.
    """

    def accept(p: AsyncModelProvider) -> AsyncModelProvider:
        # Exercise the protocol surface the orchestrator depends on.
        assert p.is_configured() is True
        return p

    base = accept(BaseModelProvider(enabled=True))
    det = accept(DeterministicModelProvider(response_override="p"))
    assert base.provider_name == "base"
    assert det.provider_name == "deterministic"
