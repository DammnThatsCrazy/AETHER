"""Error-path tests for the generic OpenAI-compatible model adapter.

Covers the failure surface of ``OpenAICompatibleModelProvider`` (the
``MODEL_RUNTIME_COMPAT_*`` env-driven subclass of ``OpenAIModelProvider``):
not-configured, HTTP status errors, transport errors, timeout, and
malformed-body resilience. All I/O is faked by monkeypatching
``httpx.AsyncClient`` so no network and no real credentials are ever touched.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from services.model_runtime.adapters.compatible import OpenAICompatibleModelProvider
from services.model_runtime.models import (
    ModelNotConfigured,
    ModelProviderError,
    ModelRequest,
    ModelTimeoutError,
)

COMPAT_KEY = "MODEL_RUNTIME_COMPAT_API_KEY"
OPENAI_KEY = "OPENAI_API_KEY"


def _request(**overrides: object) -> ModelRequest:
    """Build a minimal ModelRequest, honoring per-test field overrides."""
    fields: dict[str, object] = {
        "model": "m-test",
        "messages": [{"role": "user", "content": "hi"}],
    }
    fields.update(overrides)
    return ModelRequest(**fields)


def _body(
    content: str = "hello",
    prompt_tokens: int = 5,
    completion_tokens: int = 7,
) -> dict[str, object]:
    """Shape a fake OpenAI-compatible chat-completions response body."""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class _FakeResponse:
    """Stand-in for ``httpx.Response`` returned by the fake client's ``post``."""

    def __init__(self, body: object, status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("POST", "https://fake/v1/chat/completions")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("err", request=req, response=resp)

    def json(self) -> object:
        return self._body


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` used with ``async with``."""

    def __init__(self, response: object | None = None, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._response = response
        self.url: str | None = None
        self.post_kwargs: dict[str, object] = {}

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> object:
        self.url = url
        self.post_kwargs = kwargs
        return self._response


class _SlowFakeClient(_FakeClient):
    """Fake client whose ``post`` hangs far beyond any real timeout budget."""

    async def post(self, url: str, **kwargs: object) -> object:
        await asyncio.sleep(0.2)
        return self._response


class _ConnectErrorResponse:
    """Response whose ``json()`` fails like a dropped transport connection."""

    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        raise httpx.ConnectError("connection refused")


def _install_httpx_fake(
    monkeypatch: pytest.MonkeyPatch,
    response: object | None = None,
    client_cls: type[_FakeClient] = _FakeClient,
) -> dict[str, _FakeClient]:
    """Replace ``httpx.AsyncClient`` with a recording fake."""
    holder: dict[str, _FakeClient] = {}

    def _factory(**kwargs: object) -> _FakeClient:
        client = client_cls(response=response, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(httpx, "AsyncClient", _factory)  # type: ignore[union-attr]
    return holder


# ---------------------------------------------------------------------------
# Not-configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_not_configured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(COMPAT_KEY, raising=False)
    monkeypatch.delenv(OPENAI_KEY, raising=False)
    provider = OpenAICompatibleModelProvider(api_key="")
    assert provider.is_configured() is False
    with pytest.raises(ModelNotConfigured, match="openai"):
        await provider.complete(_request())


# ---------------------------------------------------------------------------
# HTTP status errors (400 / 401 / 500)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 500])
async def test_compatible_http_status_raises_provider_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _install_httpx_fake(monkeypatch, response=_FakeResponse(body={}, status=status))
    provider = OpenAICompatibleModelProvider(api_key="sk-test", model="m-test")
    with pytest.raises(ModelProviderError) as exc_info:
        await provider.complete(_request())
    assert str(exc_info.value).startswith("openai API error")


# ---------------------------------------------------------------------------
# Transport + timeout errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_transport_error_wraps_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_httpx_fake(monkeypatch, response=_ConnectErrorResponse())
    provider = OpenAICompatibleModelProvider(api_key="sk-test", model="m-test")
    with pytest.raises(ModelProviderError) as exc_info:
        await provider.complete(_request())
    msg = str(exc_info.value)
    assert msg.startswith("openai transport error")
    assert "connection refused" in msg


@pytest.mark.asyncio
async def test_compatible_timeout_raises_model_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_httpx_fake(monkeypatch, client_cls=_SlowFakeClient)
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", model="m-test", timeout_s=0.01
    )
    with pytest.raises(ModelTimeoutError, match="openai request timed out"):
        await provider.complete(_request())


# ---------------------------------------------------------------------------
# Malformed-body resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_empty_choices_defaults_to_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_httpx_fake(monkeypatch, response=_FakeResponse(body={"choices": []}))
    provider = OpenAICompatibleModelProvider(api_key="sk-test", model="m-test")
    resp = await provider.complete(_request())
    assert resp.content == ""
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0
    assert resp.usage.total_tokens == 0


@pytest.mark.asyncio
async def test_compatible_missing_body_defaults_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_httpx_fake(monkeypatch, response=_FakeResponse(body={}))
    provider = OpenAICompatibleModelProvider(api_key="sk-test", model="m-test")
    resp = await provider.complete(_request())
    assert resp.content == ""
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0
    assert resp.usage.total_tokens == 0


@pytest.mark.asyncio
async def test_compatible_malformed_usage_absent_key_defaults_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_httpx_fake(
        monkeypatch,
        response=_FakeResponse(
            body={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3},  # completion_tokens absent
            }
        ),
    )
    provider = OpenAICompatibleModelProvider(api_key="sk-test", model="m-test")
    resp = await provider.complete(_request())
    assert resp.content == "ok"
    assert resp.usage.input_tokens == 3
    assert resp.usage.output_tokens == 0
    assert resp.usage.total_tokens == 3


@pytest.mark.asyncio
async def test_compatible_negative_usage_counts_never_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed usage never crashes the parse (resilience guard).

    The inherited ``or 0`` parser guards missing/zero counts; signed negative
    counts are preserved verbatim but must never raise during parsing.
    """
    _install_httpx_fake(
        monkeypatch,
        response=_FakeResponse(
            body={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": -5, "completion_tokens": -3},
            }
        ),
    )
    provider = OpenAICompatibleModelProvider(api_key="sk-test", model="m-test")
    resp = await provider.complete(_request())
    assert resp.content == "ok"
    assert resp.usage.input_tokens == -5
    assert resp.usage.output_tokens == -3
    assert resp.usage.total_tokens == -8


# ---------------------------------------------------------------------------
# Config precedence under the MODEL_RUNTIME_COMPAT_* env surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_falls_back_to_openai_env_when_compat_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(COMPAT_KEY, raising=False)
    monkeypatch.setenv(OPENAI_KEY, "sk-openai-fallback")
    _install_httpx_fake(monkeypatch, response=_FakeResponse(body=_body(content="fallback")))
    provider = OpenAICompatibleModelProvider()
    assert provider.is_configured() is True
    resp = await provider.complete(_request())
    assert resp.content == "fallback"


@pytest.mark.asyncio
async def test_compatible_unconfigured_without_any_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(COMPAT_KEY, raising=False)
    monkeypatch.delenv(OPENAI_KEY, raising=False)
    provider = OpenAICompatibleModelProvider()
    assert provider.is_configured() is False
    with pytest.raises(ModelNotConfigured, match="openai"):
        await provider.complete(_request())


# ---------------------------------------------------------------------------
# provider_name stability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_provider_name_survives_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_httpx_fake(monkeypatch, response=_FakeResponse(body={}, status=500))
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", model="m-test", provider_name="vllm"
    )
    with pytest.raises(ModelProviderError):
        await provider.complete(_request())
    assert provider.provider_name == "vllm"
