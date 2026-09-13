"""Capability (success-path) tests for the generic OpenAI-compatible adapter.

Exercises ``OpenAICompatibleModelProvider`` in ``services/model_runtime/
adapters/compatible.py``: config/env resolution plus the full success-path
request/response contract (reusing the inherited ``OpenAIModelProvider`` httpx
transport). httpx is monkeypatched with a recording fake client so no network
and no real credentials are ever touched. All fixtures use fake URLs and
test-only API keys.
"""

from __future__ import annotations

import asyncio

import pytest

from services.model_runtime.adapters.compatible import OpenAICompatibleModelProvider
from services.model_runtime.models import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)


def _request(**overrides: object) -> ModelRequest:
    """Build a minimal ModelRequest, honoring per-test field overrides."""
    fields: dict[str, object] = {
        "model": "compat-test",
        "messages": [{"role": "user", "content": "q"}],
    }
    fields.update(overrides)
    return ModelRequest(**fields)


# ---------------------------------------------------------------------------
# httpx fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stand-in for ``httpx.Response`` returned by ``client.post``."""

    def __init__(self, body: object, status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("POST", "https://fake/v1/chat/completions")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("request failed", request=req, response=resp)

    def json(self) -> object:
        return self._body


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` used with ``async with``.

    Records the constructor kwargs plus the exact post-kwargs sent to
    ``client.post(...)`` so tests can assert the request contract.
    """

    def __init__(self, response: object, **kwargs: object) -> None:
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


def _ok_response(content: str = "hi") -> _FakeResponse:
    """A fake 200 response with one choice and no usage."""
    return _FakeResponse({"choices": [{"message": {"content": content}}]})


def _install_fake(monkeypatch: object, response: object) -> dict[str, _FakeClient]:
    """Replace ``httpx.AsyncClient`` with a recording fake."""
    import httpx

    holder: dict[str, _FakeClient] = {}

    def _factory(**kwargs: object) -> _FakeClient:
        client = _FakeClient(response, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(httpx, "AsyncClient", _factory)  # type: ignore[union-attr]
    return holder


# ---------------------------------------------------------------------------
# Provider name / config
# ---------------------------------------------------------------------------


def test_compatible_provider_name_explicit_and_default(monkeypatch):
    """provider_name honors the kwarg and falls back to the default."""
    monkeypatch.delenv("MODEL_RUNTIME_COMPAT_PROVIDER_NAME", raising=False)
    named = OpenAICompatibleModelProvider(
        api_key="k", model="m", base_url="http://f/v1", provider_name="kimi"
    )
    assert named.provider_name == "kimi"

    default = OpenAICompatibleModelProvider()
    assert default.provider_name == "openai_compatible"


def test_compatible_env_config_surface(monkeypatch):
    """Default constructor reads the MODEL_RUNTIME_COMPAT_* env surface."""
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_API_KEY", "ck")
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_MODEL", "cm")
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_BASE_URL", "http://f/v1")
    provider = OpenAICompatibleModelProvider()
    assert provider.api_key == "ck"
    assert provider.model == "cm"
    assert provider.base_url == "http://f/v1"
    assert provider.is_configured() is True


def test_compatible_explicit_kwargs_beat_env(monkeypatch):
    """Explicit constructor kwargs win over the MODEL_RUNTIME_COMPAT_* env."""
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_API_KEY", "ck")
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_MODEL", "cm")
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_BASE_URL", "http://f/v1")
    provider = OpenAICompatibleModelProvider(
        api_key="ak", model="am", base_url="http://x/v1"
    )
    assert provider.api_key == "ak"
    assert provider.model == "am"
    assert provider.base_url == "http://x/v1"


# ---------------------------------------------------------------------------
# Capability (success) behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_success_maps_response(monkeypatch):
    """Full success round-trip maps content, provider, usage, and metadata."""
    _install_fake(
        monkeypatch,
        response=_FakeResponse(
            body={
                "choices": [{"message": {"content": "hello from compatible model"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            }
        ),
    )
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", model="compat-test", base_url="http://fake-endpoint/v1"
    )

    resp = await provider.complete(_request())

    assert isinstance(resp, ModelResponse)
    assert resp.content == "hello from compatible model"
    assert resp.provider == ModelProvider.OPENAI
    assert resp.usage == TokenUsage(input_tokens=12, output_tokens=8, total_tokens=20)
    assert resp.finish_reason == "stop"
    assert resp.raw == {}
    assert resp.latency_ms >= 0


@pytest.mark.asyncio
async def test_compatible_post_url_and_auth_headers(monkeypatch):
    """POST target is {base_url}/chat/completions with Bearer + JSON headers."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-compat", model="compat-test", base_url="http://fake-endpoint/v1"
    )
    await provider.complete(_request())

    client = fake["client"]
    assert client.url == "http://fake-endpoint/v1/chat/completions"
    headers = client.post_kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-compat"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_compatible_payload_shape(monkeypatch):
    """Payload carries model/max_tokens and the user turn (no system)."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", model="compat-model", base_url="http://fake-endpoint/v1"
    )
    await provider.complete(_request())

    payload = fake["client"].post_kwargs["json"]
    # Fix-4: the adapter sends the request's model when set, not its own
    # configured default.
    assert payload["model"] == "compat-test"
    assert payload["max_tokens"] == provider.max_tokens
    assert payload["messages"] == [{"role": "user", "content": "q"}]


@pytest.mark.asyncio
async def test_compatible_system_prompt_prepended(monkeypatch):
    """system_prompt is prepended as the first system message."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1"
    )
    await provider.complete(_request(system_prompt="sys"))

    payload = fake["client"].post_kwargs["json"]
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]


@pytest.mark.asyncio
async def test_compatible_response_format_json_object_present(monkeypatch):
    """response_format=json_object emits the json_object format request."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1"
    )
    await provider.complete(_request(response_format="json_object"))
    assert fake["client"].post_kwargs["json"]["response_format"] == {
        "type": "json_object"
    }


@pytest.mark.asyncio
async def test_compatible_response_format_absent_by_default(monkeypatch):
    """response_format is absent from the payload when not requested."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1"
    )
    await provider.complete(_request())
    assert "response_format" not in fake["client"].post_kwargs["json"]


# ---------------------------------------------------------------------------
# Custom max_tokens + timeout plumbing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_custom_max_tokens(monkeypatch):
    """Constructor max_tokens flows into the request payload."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1", max_tokens=2048
    )
    await provider.complete(_request())
    assert fake["client"].post_kwargs["json"]["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_compatible_client_timeout_plumbing(monkeypatch):
    """The httpx client is constructed with timeout == provider.timeout_s."""
    fake = _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1", timeout_s=3.5
    )
    await provider.complete(_request())
    assert fake["client"].kwargs["timeout"] == 3.5


# ---------------------------------------------------------------------------
# Missing data guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compatible_empty_choices_missing_content(monkeypatch):
    """Empty choices / missing content map to an empty content string."""
    _install_fake(
        monkeypatch,
        response=_FakeResponse(
            body={
                "choices": [],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5},
            }
        ),
    )
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1"
    )
    resp = await provider.complete(_request())
    assert resp.content == ""
    assert resp.usage.input_tokens == 3
    assert resp.usage.output_tokens == 5
    assert resp.usage.total_tokens == 8


@pytest.mark.asyncio
async def test_compatible_missing_usage_defaults_zero(monkeypatch):
    """Missing usage maps all token counters to zero."""
    _install_fake(monkeypatch, response=_ok_response())
    provider = OpenAICompatibleModelProvider(
        api_key="sk-test", base_url="http://fake-endpoint/v1"
    )
    resp = await provider.complete(_request())
    assert resp.content == "hi"
    assert resp.usage.input_tokens == 0
    assert resp.usage.output_tokens == 0
    assert resp.usage.total_tokens == 0
