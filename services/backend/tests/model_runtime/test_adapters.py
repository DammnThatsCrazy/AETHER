"""Adapter tests for the provider-neutral model runtime (real SDK transports).

Exercises the two real transport adapters in
``services/model_runtime/adapters/`` — ``AnthropicModelProvider`` (lazy
``import anthropic``) and ``OpenAIModelProvider`` (lazy ``import httpx``) —
against monkeypatched SDK client factories so no network and no real
credentials are ever touched. Both SDKs are installed in the dev venv
(anthropic 0.120.2, httpx 0.28.1); ``complete()`` lazy-imports them and this
suite swaps the client factory before the real transport would attempt I/O.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services.model_runtime.adapters import AnthropicModelProvider, OpenAIModelProvider
from services.model_runtime.credentials.models import CredentialResolution, mask_identifier
from services.model_runtime.models import (
    ModelNotConfigured,
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    TokenUsage,
)


def _request(**overrides: object) -> ModelRequest:
    """Build a minimal ModelRequest, honoring per-test field overrides."""
    fields: dict[str, object] = {
        "model": "claude-test",
        "messages": [{"role": "user", "content": "hi"}],
    }
    fields.update(overrides)
    return ModelRequest(**fields)


# ---------------------------------------------------------------------------
# Anthropic fakes
# ---------------------------------------------------------------------------


def _anthropic_response(
    content_text: str | None = "hello",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> SimpleNamespace:
    """Shape a fake anthropic Messages API response object."""
    content = [SimpleNamespace(text=content_text)] if content_text is not None else []
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=content, usage=usage)


class _AnthropicMessages:
    """The nested ``messages`` object on the fake ``AsyncAnthropic`` client."""

    def __init__(
        self,
        response: object | None = None,
        handler: object | None = None,
    ) -> None:
        self._response = response
        self._handler = handler
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if self._handler is not None:
            return await self._handler(**kwargs)  # type: ignore[operator]
        return self._response


class _AnthropicFakeClient:
    """Stand-in for ``anthropic.AsyncAnthropic``.

    Records the client kwargs plus the exact create-kwargs sent to
    ``client.messages.create(...)`` so tests can assert the request contract.
    """

    def __init__(
        self,
        response: object | None = None,
        handler: object | None = None,
        **kwargs: object,
    ) -> None:
        self.client_kwargs: dict[str, object] = kwargs
        self.messages = _AnthropicMessages(response=response, handler=handler)


def _install_anthropic_fake(
    monkeypatch: object,
    response: object | None = None,
    handler: object | None = None,
) -> dict[str, _AnthropicFakeClient]:
    """Replace ``anthropic.AsyncAnthropic`` with a recording fake.

    ``complete()`` constructs one client per call, so the returned holder's
    ``client`` key is populated on first instantiation.
    """
    import anthropic

    holder: dict[str, _AnthropicFakeClient] = {}

    def _factory(**kwargs: object) -> _AnthropicFakeClient:
        client = _AnthropicFakeClient(response=response, handler=handler, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _factory)  # type: ignore[union-attr]
    return holder


# ---------------------------------------------------------------------------
# OpenAI (httpx) fakes
# ---------------------------------------------------------------------------


def _openai_body(
    content: str = "hello",
    prompt_tokens: int = 5,
    completion_tokens: int = 7,
) -> dict[str, object]:
    """Shape a fake OpenAI chat-completions response body."""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class _HttpxFakeResponse:
    """Stand-in for ``httpx.Response`` returned by ``client.post``."""

    def __init__(self, body: object | None = None, status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("POST", "https://x")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("request failed", request=req, response=resp)

    def json(self) -> object:
        return self._body


class _RaisingJsonResponse:
    """httpx response whose ``json()`` blows up (transport error path)."""

    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        raise ValueError("bad json")


class _HttpxFakeClient:
    """Stand-in for ``httpx.AsyncClient`` used with ``async with``."""

    def __init__(
        self,
        response: object | None = None,
        handler: object | None = None,
        **kwargs: object,
    ) -> None:
        self.client_kwargs: dict[str, object] = kwargs
        self._response = response
        self._handler = handler
        self.url: str | None = None
        self.post_kwargs: dict[str, object] = {}

    async def __aenter__(self) -> "_HttpxFakeClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> object:
        self.url = url
        self.post_kwargs = kwargs
        if self._handler is not None:
            return await self._handler()  # type: ignore[operator]
        return self._response


def _install_httpx_fake(
    monkeypatch: object,
    response: object | None = None,
    handler: object | None = None,
) -> dict[str, _HttpxFakeClient]:
    """Replace ``httpx.AsyncClient`` with a recording fake."""
    import httpx

    holder: dict[str, _HttpxFakeClient] = {}

    def _factory(**kwargs: object) -> _HttpxFakeClient:
        client = _HttpxFakeClient(response=response, handler=handler, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(httpx, "AsyncClient", _factory)  # type: ignore[union-attr]
    return holder


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_not_configured_raises():
    provider = AnthropicModelProvider(api_key="")
    assert provider.is_configured() is False
    with pytest.raises(ModelNotConfigured, match="anthropic"):
        await provider.complete(_request())


@pytest.mark.asyncio
async def test_anthropic_success_maps_response(monkeypatch):
    _install_anthropic_fake(
        monkeypatch, response=_anthropic_response(content_text="hello world")
    )
    provider = AnthropicModelProvider(api_key="sk-test", model="claude-test")
    assert provider.is_configured() is True

    resp = await provider.complete(_request())

    assert isinstance(resp, ModelResponse)
    assert resp.content == "hello world"
    assert resp.model == "claude-test"
    assert resp.provider == ModelProvider.ANTHROPIC
    assert resp.usage == TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30)
    assert resp.finish_reason == "stop"
    assert resp.raw == {}
    assert resp.latency_ms >= 0


@pytest.mark.asyncio
async def test_anthropic_send_kwargs_contract(monkeypatch):
    fake = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(
        api_key="sk-test", model="claude-test", max_tokens=64, max_retries=2
    )
    messages = [{"role": "user", "content": "hi"}]
    req = ModelRequest(model="claude-test", messages=messages, system_prompt="be concise")
    await provider.complete(req)

    client = fake["client"]
    assert client.client_kwargs == {"api_key": "sk-test", "max_retries": 2}
    kwargs = client.messages.kwargs
    assert kwargs["model"] == "claude-test"
    assert kwargs["max_tokens"] == 64
    assert kwargs["messages"] == messages
    assert kwargs["system"] == "be concise"


@pytest.mark.asyncio
async def test_anthropic_system_key_absent_without_prompt(monkeypatch):
    fake = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="sk-test", model="claude-test")
    await provider.complete(_request(system_prompt=None))
    assert "system" not in fake["client"].messages.kwargs


@pytest.mark.asyncio
async def test_anthropic_never_sends_sampling_params(monkeypatch):
    """Capability invariant: never send temperature/top_p/top_k to Anthropic.

    The neutral ModelRequest accepts ``temperature``/``max_tokens``, but this
    adapter must drop sampling params because newer Anthropic models reject
    them with HTTP 400.
    """
    fake = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="sk-test", model="claude-test")
    req = ModelRequest(
        model="claude-test",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=100,
    )
    await provider.complete(req)

    kwargs = fake["client"].messages.kwargs
    assert {"temperature", "top_p", "top_k"}.isdisjoint(kwargs.keys())
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


@pytest.mark.asyncio
async def test_anthropic_timeout_raises_model_timeout(monkeypatch):
    async def _slow(**kwargs: object) -> object:
        await asyncio.sleep(0.2)
        return None

    _install_anthropic_fake(monkeypatch, handler=_slow)
    provider = AnthropicModelProvider(api_key="sk-test", timeout_s=0.01)
    with pytest.raises(ModelTimeoutError, match="anthropic request timed out"):
        await provider.complete(_request())


@pytest.mark.asyncio
async def test_anthropic_api_error_wraps_provider_error(monkeypatch):
    async def _boom(**kwargs: object) -> object:
        raise RuntimeError("boom")

    _install_anthropic_fake(monkeypatch, handler=_boom)
    provider = AnthropicModelProvider(api_key="sk-test")
    with pytest.raises(ModelProviderError) as exc_info:
        await provider.complete(_request())
    assert "anthropic API error" in str(exc_info.value)
    assert "boom" in str(exc_info.value)


@pytest.mark.asyncio
async def test_anthropic_api_status_error_wraps_provider_error(monkeypatch):
    import anthropic
    import httpx

    async def _reject(**kwargs: object) -> object:
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        resp = httpx.Response(400, request=req)
        raise anthropic.APIStatusError("bad request", request=req, response=resp)

    _install_anthropic_fake(monkeypatch, handler=_reject)
    provider = AnthropicModelProvider(api_key="sk-test")
    with pytest.raises(ModelProviderError) as exc_info:
        await provider.complete(_request())
    assert "anthropic API error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_anthropic_empty_content_returns_empty_string(monkeypatch):
    _install_anthropic_fake(
        monkeypatch,
        response=_anthropic_response(content_text=None, input_tokens=3, output_tokens=5),
    )
    provider = AnthropicModelProvider(api_key="sk-test")
    resp = await provider.complete(_request())
    assert resp.content == ""
    assert resp.usage.input_tokens == 3
    assert resp.usage.output_tokens == 5
    assert resp.usage.total_tokens == 8


@pytest.mark.asyncio
async def test_anthropic_missing_usage_defaults_zero(monkeypatch):
    response = SimpleNamespace(content=[SimpleNamespace(text="hi")], usage=None)
    _install_anthropic_fake(monkeypatch, response=response)
    provider = AnthropicModelProvider(api_key="sk-test")
    resp = await provider.complete(_request())
    assert resp.content == "hi"
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0
    assert resp.usage.total_tokens == 0


# ---------------------------------------------------------------------------
# OpenAI (httpx) adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_not_configured_raises():
    provider = OpenAIModelProvider(api_key="")
    assert provider.is_configured() is False
    with pytest.raises(ModelNotConfigured, match="openai"):
        await provider.complete(_request())


@pytest.mark.asyncio
async def test_openai_success_maps_response(monkeypatch):
    _install_httpx_fake(
        monkeypatch,
        response=_HttpxFakeResponse(
            body=_openai_body(content="openai answer", prompt_tokens=5, completion_tokens=7)
        ),
    )
    provider = OpenAIModelProvider(api_key="sk-test", model="gpt-test")
    resp = await provider.complete(_request())

    assert isinstance(resp, ModelResponse)
    assert resp.content == "openai answer"
    # Fix-4: the adapter echoes the request's model when set, not its own
    # configured default.
    assert resp.model == "claude-test"
    assert resp.provider == ModelProvider.OPENAI
    assert resp.usage == TokenUsage(input_tokens=5, output_tokens=7, total_tokens=12)
    assert resp.finish_reason == "stop"
    assert resp.raw == {}
    assert resp.latency_ms >= 0


@pytest.mark.asyncio
async def test_openai_post_url_and_auth_headers(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-o", model="gpt-test")
    await provider.complete(_request())

    client = fake["client"]
    assert client.url == "https://api.openai.com/v1/chat/completions"
    assert client.client_kwargs == {"timeout": 5.0}
    headers = client.post_kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-o"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_openai_payload_system_prepended(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-test", model="gpt-test", max_tokens=32)
    req = ModelRequest(
        model="gpt-test",
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="be helpful",
    )
    await provider.complete(req)

    payload = fake["client"].post_kwargs["json"]
    assert payload["model"] == "gpt-test"
    assert payload["max_tokens"] == 32
    assert payload["messages"] == [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
    ]


@pytest.mark.asyncio
async def test_openai_response_format_json_object_present(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-test")
    await provider.complete(_request(response_format="json_object"))
    assert fake["client"].post_kwargs["json"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_openai_response_format_absent_by_default(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-test")
    await provider.complete(_request())
    assert "response_format" not in fake["client"].post_kwargs["json"]


@pytest.mark.asyncio
async def test_openai_response_format_absent_for_text(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-test")
    await provider.complete(_request(response_format="text"))
    assert "response_format" not in fake["client"].post_kwargs["json"]


@pytest.mark.asyncio
async def test_openai_http_status_error_raises_provider_error(monkeypatch):
    _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body={}, status=400))
    provider = OpenAIModelProvider(api_key="sk-test")
    with pytest.raises(ModelProviderError) as exc_info:
        await provider.complete(_request())
    assert "openai API error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_transport_error_wraps_provider_error(monkeypatch):
    _install_httpx_fake(monkeypatch, response=_RaisingJsonResponse())
    provider = OpenAIModelProvider(api_key="sk-test")
    with pytest.raises(ModelProviderError) as exc_info:
        await provider.complete(_request())
    assert "openai transport error" in str(exc_info.value)
    assert "bad json" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_timeout_raises_model_timeout(monkeypatch):
    async def _slow() -> object:
        await asyncio.sleep(0.2)
        return None

    _install_httpx_fake(monkeypatch, handler=_slow)
    provider = OpenAIModelProvider(api_key="sk-test", timeout_s=0.01)
    with pytest.raises(ModelTimeoutError, match="openai request timed out"):
        await provider.complete(_request())


@pytest.mark.asyncio
async def test_openai_missing_content_and_usage_defaults(monkeypatch):
    _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body={}))
    provider = OpenAIModelProvider(api_key="sk-test")
    resp = await provider.complete(_request())
    assert resp.content == ""
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0
    assert resp.usage.total_tokens == 0


# ---------------------------------------------------------------------------
# Fix-4: adapters honor the routed request model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_sends_request_model_when_set(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-test", model="gpt-test")
    resp = await provider.complete(_request(model="req-model"))
    payload = fake["client"].post_kwargs["json"]
    # The routed/request model is what is actually invoked, not the provider's
    # configured default.
    assert payload["model"] == "req-model"
    assert resp.model == "req-model"


@pytest.mark.asyncio
async def test_openai_uses_configured_model_when_request_model_empty(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-test", model="gpt-test")
    resp = await provider.complete(_request(model=""))
    payload = fake["client"].post_kwargs["json"]
    assert payload["model"] == "gpt-test"
    assert resp.model == "gpt-test"


@pytest.mark.asyncio
async def test_anthropic_sends_request_model_when_set(monkeypatch):
    holder = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="sk-test", model="claude-configured")
    resp = await provider.complete(_request(model="req-model"))
    kwargs = holder["client"].messages.kwargs
    assert kwargs["model"] == "req-model"
    assert resp.model == "req-model"


@pytest.mark.asyncio
async def test_anthropic_uses_configured_model_when_request_model_empty(monkeypatch):
    holder = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="sk-test", model="claude-configured")
    resp = await provider.complete(_request(model=""))
    kwargs = holder["client"].messages.kwargs
    assert kwargs["model"] == "claude-configured"
    assert resp.model == "claude-configured"


# ---------------------------------------------------------------------------
# Fix-3: per-tenant credential binding on the adapters (ADR-008 D5)
# ---------------------------------------------------------------------------


def _env_resolution(provider: str, tenant_id: str, ref: str, key: str):
    return CredentialResolution(
        provider=provider,
        tenant_id=tenant_id,
        ref=ref,
        resolved=True,
        configured=True,
        masked_identifier=mask_identifier(key),
        source="env",
        reason="tenant-scoped env fallback",
    )


def _secret_backend_resolution(provider: str, tenant_id: str, ref: str, key: str):
    return CredentialResolution(
        provider=provider,
        tenant_id=tenant_id,
        ref=ref,
        resolved=True,
        configured=True,
        masked_identifier=mask_identifier(key),
        source="secret_backend",
        reason="resolved from secret backend",
    )


@pytest.mark.asyncio
async def test_openai_bind_credential_env_source_materializes_tenant_key(monkeypatch):
    monkeypatch.setenv("T1_OPENAI_API_KEY", "sk-tenant-1")
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-process-wide", model="gpt-test")
    bound = provider.bind_credential(
        _env_resolution("openai", "t1", "T1_OPENAI_API_KEY", "sk-tenant-1")
    )
    assert bound is not provider
    assert bound.is_configured() is True
    await bound.complete(_request())
    headers = fake["client"].post_kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-tenant-1"
    # The process-wide key is never used and the registered instance is intact.
    assert provider.api_key == "sk-process-wide"


@pytest.mark.asyncio
async def test_openai_bind_credential_env_ref_missing_fails_closed(monkeypatch):
    monkeypatch.delenv("T1_OPENAI_API_KEY", raising=False)
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-process-wide", model="gpt-test")
    bound = provider.bind_credential(
        _env_resolution("openai", "t1", "T1_OPENAI_API_KEY", "sk-tenant-1")
    )
    assert bound.is_configured() is False
    with pytest.raises(ModelNotConfigured):
        await bound.complete(_request())
    assert "client" not in fake  # no request was dispatched


@pytest.mark.asyncio
async def test_openai_bind_credential_secret_backend_fails_closed(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-process-wide", model="gpt-test")
    bound = provider.bind_credential(
        _secret_backend_resolution(
            "openai", "t1", "aether/credentials/t1/openai", "sk-tenant-1"
        )
    )
    assert bound.is_configured() is False
    with pytest.raises(ModelNotConfigured):
        await bound.complete(_request())
    assert "client" not in fake  # never falls back to the process-wide key


def _fake_materializer(key: str):
    """Async just-in-time secret-backend materializer returning ``key``."""

    async def _materialize(tenant_id: str, ref: str) -> str:
        return key

    return _materialize


@pytest.mark.asyncio
async def test_openai_bind_credential_secret_backend_materializes_with_materializer(monkeypatch):
    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="", model="gpt-test")  # no process-wide key
    bound = provider.bind_credential(
        _secret_backend_resolution(
            "openai", "t1", "aether/credentials/t1/openai", "sk-tenant-aws"
        ),
        materializer=_fake_materializer("sk-tenant-aws"),
    )
    assert bound.is_configured() is True
    await bound.complete(_request())
    headers = fake["client"].post_kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-tenant-aws"
    # The materialized key is bound to the per-request adapter only — the
    # registered instance and the resolution metadata carry nothing.
    assert provider.api_key == ""
    assert bound._bound_resolution.masked_identifier == mask_identifier("sk-tenant-aws")


@pytest.mark.asyncio
async def test_openai_bind_credential_secret_backend_materializer_failure_fails_closed(
    monkeypatch,
):
    async def _empty(tenant_id: str, ref: str) -> None:
        return None

    fake = _install_httpx_fake(monkeypatch, response=_HttpxFakeResponse(body=_openai_body()))
    provider = OpenAIModelProvider(api_key="sk-process-wide", model="gpt-test")
    bound = provider.bind_credential(
        _secret_backend_resolution(
            "openai", "t1", "aether/credentials/t1/openai", "sk-tenant-1"
        ),
        materializer=_empty,
    )
    # A materializer that returns nothing still fails closed — never the
    # process-wide key.
    with pytest.raises(ModelNotConfigured):
        await bound.complete(_request())
    assert "client" not in fake


@pytest.mark.asyncio
async def test_anthropic_bind_credential_env_source_materializes_tenant_key(monkeypatch):
    monkeypatch.setenv("T1_ANTHROPIC_API_KEY", "sk-tenant-anthropic")
    holder = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="sk-process-wide", model="claude-test")
    bound = provider.bind_credential(
        _env_resolution("anthropic", "t1", "T1_ANTHROPIC_API_KEY", "sk-tenant-anthropic")
    )
    assert bound is not provider
    assert bound.is_configured() is True
    await bound.complete(_request())
    assert holder["client"].client_kwargs["api_key"] == "sk-tenant-anthropic"
    assert provider.api_key == "sk-process-wide"


@pytest.mark.asyncio
async def test_anthropic_bind_credential_secret_backend_fails_closed(monkeypatch):
    holder = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="sk-process-wide", model="claude-test")
    bound = provider.bind_credential(
        _secret_backend_resolution(
            "anthropic", "t1", "aether/credentials/t1/anthropic", "sk-tenant-anthropic"
        )
    )
    assert bound.is_configured() is False
    with pytest.raises(ModelNotConfigured):
        await bound.complete(_request())
    assert "client" not in holder  # never falls back to the process-wide key


@pytest.mark.asyncio
async def test_anthropic_bind_credential_secret_backend_materializes_with_materializer(
    monkeypatch,
):
    holder = _install_anthropic_fake(monkeypatch, response=_anthropic_response())
    provider = AnthropicModelProvider(api_key="", model="claude-test")  # no process-wide key
    bound = provider.bind_credential(
        _secret_backend_resolution(
            "anthropic", "t1", "aether/credentials/t1/anthropic", "sk-tenant-aws"
        ),
        materializer=_fake_materializer("sk-tenant-aws"),
    )
    assert bound.is_configured() is True
    await bound.complete(_request())
    assert holder["client"].client_kwargs["api_key"] == "sk-tenant-aws"
    assert provider.api_key == ""
