"""Registry integration tests for the generic OpenAI-compatible adapter.

Proves that many ``OpenAICompatibleModelProvider`` instances (each carrying an
instance-level ``provider_name``) coexist in ``ModelRuntimeService`` under
distinct names and are dispatched, budgeted, and metered exactly like the
native adapters. All HTTP is monkeypatched on the real httpx module, so no
network and no real credentials are ever touched.
"""

from __future__ import annotations

import pytest

from services.model_runtime.adapters.anthropic import AnthropicModelProvider
from services.model_runtime.adapters.compatible import OpenAICompatibleModelProvider
from services.model_runtime.adapters.openai import OpenAIModelProvider
from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelNotConfigured,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)
from services.model_runtime.service import ModelRuntimeService


def _request(**overrides: object) -> ModelRequest:
    """Build a minimal ModelRequest, honoring per-test field overrides."""
    fields: dict[str, object] = {
        "model": "kimi-k2",
        "messages": [{"role": "user", "content": "hi"}],
    }
    fields.update(overrides)
    return ModelRequest(**fields)


def _kimi_provider() -> OpenAICompatibleModelProvider:
    return OpenAICompatibleModelProvider(
        api_key="k1", model="kimi-k2", base_url="http://kimi/v1", provider_name="kimi"
    )


def _deepseek_provider() -> OpenAICompatibleModelProvider:
    return OpenAICompatibleModelProvider(
        api_key="k2", model="deepseek-r1", base_url="http://ds/v1", provider_name="deepseek"
    )


# ---------------------------------------------------------------------------
# httpx fakes (no network)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stand-in for ``httpx.Response`` returned by ``client.post``."""

    def __init__(self, body: dict[str, object], status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("POST", "https://fake/v1/chat/completions")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("err", request=req, response=resp)

    def json(self) -> dict[str, object]:
        return self._body


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` used with ``async with``."""

    def __init__(self, response: _FakeResponse, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._response = response
        self.url: str | None = None
        self.post_kwargs: dict[str, object] = {}

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.url = url
        self.post_kwargs = kwargs
        return self._response


def _install_httpx_fake(
    monkeypatch: pytest.MonkeyPatch, response: _FakeResponse
) -> dict[str, _FakeClient]:
    """Replace ``httpx.AsyncClient`` with a recording fake."""
    import httpx

    holder: dict[str, _FakeClient] = {}

    def _factory(**kwargs: object) -> _FakeClient:
        client = _FakeClient(response=response, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return holder


def _compat_body(
    content: str = "hello", prompt_tokens: int = 10, completion_tokens: int = 5
) -> dict[str, object]:
    """Shape a fake OpenAI-compatible chat-completions response body."""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class BudgetSpy:
    """In-memory TokenBudget recording tenant-scoped calls for assertions."""

    def __init__(self, reserve_ok: bool = True) -> None:
        self.reserve_ok = reserve_ok
        self.reserves: list[tuple[str, int]] = []
        self.releases: list[tuple[str, int]] = []
        self.charges: list[tuple[str, int]] = []

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        self.reserves.append((tenant_id, estimated_tokens))
        return self.reserve_ok

    async def release(self, tenant_id: str, tokens: int) -> None:
        self.releases.append((tenant_id, tokens))

    async def charge(self, tenant_id: str, tokens: int) -> None:
        self.charges.append((tenant_id, tokens))


# ---------------------------------------------------------------------------
# Multiple compatible providers coexist
# ---------------------------------------------------------------------------


def test_two_compatible_providers_coexist_sorted():
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider(), "deepseek": _deepseek_provider()}
    )
    assert svc.provider_names() == ["deepseek", "kimi"]


@pytest.mark.asyncio
async def test_dispatch_to_kimi_by_name(monkeypatch):
    fake = _install_httpx_fake(
        monkeypatch, response=_FakeResponse(body=_compat_body(content="kimi answer"))
    )
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider(), "deepseek": _deepseek_provider()},
        default_provider="kimi",
    )

    resp = await svc.complete("tenant-x", _request(model="kimi-k2"), provider="kimi")

    client = fake["client"]
    assert client.url == "http://kimi/v1/chat/completions"
    headers = client.post_kwargs["headers"]
    assert headers["Authorization"] == "Bearer k1"
    assert client.post_kwargs["json"]["model"] == "kimi-k2"
    assert isinstance(resp, ModelResponse)
    assert resp.content == "kimi answer"
    assert resp.model == "kimi-k2"
    assert resp.provider == ModelProvider.OPENAI
    assert resp.usage == TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)


@pytest.mark.asyncio
async def test_dispatch_to_deepseek_by_name(monkeypatch):
    fake = _install_httpx_fake(
        monkeypatch, response=_FakeResponse(body=_compat_body(content="ds answer"))
    )
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider(), "deepseek": _deepseek_provider()},
        default_provider="kimi",
    )

    resp = await svc.complete(
        "tenant-x", _request(model="deepseek-r1"), provider="deepseek"
    )

    client = fake["client"]
    assert client.url == "http://ds/v1/chat/completions"
    headers = client.post_kwargs["headers"]
    assert headers["Authorization"] == "Bearer k2"
    assert client.post_kwargs["json"]["model"] == "deepseek-r1"
    assert resp.content == "ds answer"
    assert resp.model == "deepseek-r1"


@pytest.mark.asyncio
async def test_default_provider_routes_to_kimi_and_explicit_override(monkeypatch):
    fake = _install_httpx_fake(
        monkeypatch, response=_FakeResponse(body=_compat_body(content="ok"))
    )
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider(), "deepseek": _deepseek_provider()},
        default_provider="kimi",
    )
    await svc.complete("tenant-x", _request(model="kimi-k2"))
    assert fake["client"].url == "http://kimi/v1/chat/completions"

    # default_provider omitted; an explicit provider selection still resolves.
    svc2 = ModelRuntimeService(
        providers={"kimi": _kimi_provider(), "deepseek": _deepseek_provider()}
    )
    await svc2.complete("tenant-x", _request(model="deepseek-r1"), provider="deepseek")
    assert fake["client"].url == "http://ds/v1/chat/completions"


# ---------------------------------------------------------------------------
# Runtime service semantics through the compatible provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_compatible_provider_raises():
    svc = ModelRuntimeService(providers={"kimi": _kimi_provider()}, default_provider="kimi")
    with pytest.raises(ModelNotConfigured, match="unknown provider"):
        await svc.complete("tenant-x", _request(), provider="nonexistent")


@pytest.mark.asyncio
async def test_disabled_compatible_provider_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_RUNTIME_COMPAT_API_KEY", raising=False)
    disabled = OpenAICompatibleModelProvider(
        api_key="", model="kimi-k2", base_url="http://kimi/v1", provider_name="kimi"
    )
    svc = ModelRuntimeService(providers={"kimi": disabled}, default_provider="kimi")
    with pytest.raises(ModelNotConfigured, match="not configured"):
        await svc.complete("tenant-x", _request())


@pytest.mark.asyncio
async def test_budget_reserve_blocks_compatible_call():
    budget = BudgetSpy(reserve_ok=False)
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider()}, default_provider="kimi", budget=budget
    )
    with pytest.raises(ModelBudgetExceeded):
        await svc.complete("tenant-x", _request())
    assert budget.reserves == [("tenant-x", 800)]
    assert budget.releases == []
    assert budget.charges == []


@pytest.mark.asyncio
async def test_budget_release_when_under_estimate(monkeypatch):
    budget = BudgetSpy()
    # usage total = 10 + 5 = 15 < the 800 estimate -> release the difference.
    fake = _install_httpx_fake(
        monkeypatch,
        response=_FakeResponse(body=_compat_body(prompt_tokens=10, completion_tokens=5)),
    )
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider()},
        default_provider="kimi",
        budget=budget,
        estimated_request_tokens=800,
    )
    resp = await svc.complete("tenant-x", _request())
    assert resp.usage.total_tokens == 15
    assert budget.reserves == [("tenant-x", 800)]
    assert budget.releases == [("tenant-x", 785)]
    assert budget.charges == []
    assert fake["client"].url == "http://kimi/v1/chat/completions"


@pytest.mark.asyncio
async def test_budget_charge_when_over_estimate(monkeypatch):
    budget = BudgetSpy()
    # usage total = 1600 + 100 = 1700 > the 800 estimate -> charge the overage.
    fake = _install_httpx_fake(
        monkeypatch,
        response=_FakeResponse(body=_compat_body(prompt_tokens=1600, completion_tokens=100)),
    )
    svc = ModelRuntimeService(
        providers={"kimi": _kimi_provider()},
        default_provider="kimi",
        budget=budget,
        estimated_request_tokens=800,
    )
    resp = await svc.complete("tenant-x", _request())
    assert resp.usage.total_tokens == 1700
    assert budget.reserves == [("tenant-x", 800)]
    assert budget.releases == []
    assert budget.charges == [("tenant-x", 900)]
    assert fake["client"].url == "http://kimi/v1/chat/completions"


# ---------------------------------------------------------------------------
# Default / registry parity with native providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_native_openai_still_dispatches(monkeypatch):
    fake = _install_httpx_fake(
        monkeypatch, response=_FakeResponse(body=_compat_body(content="native"))
    )
    native = OpenAIModelProvider(api_key="n", model="gpt-test", base_url="http://native/v1")
    svc = ModelRuntimeService(
        providers={"openai": native, "kimi": _kimi_provider()},
        default_provider="openai",
    )
    resp = await svc.complete("tenant-x", _request(model="gpt-test"))
    assert fake["client"].url == "http://native/v1/chat/completions"
    assert fake["client"].post_kwargs["headers"]["Authorization"] == "Bearer n"
    assert resp.content == "native"


@pytest.mark.asyncio
async def test_same_name_last_registered_wins(monkeypatch):
    fake = _install_httpx_fake(
        monkeypatch, response=_FakeResponse(body=_compat_body(content="last wins"))
    )
    svc = ModelRuntimeService(default_provider="openai")

    # Compatible first, then native: native (registered last) wins.
    svc.register(
        OpenAICompatibleModelProvider(
            api_key="k", model="kimi-k2", base_url="http://compat/v1", provider_name="openai"
        )
    )
    svc.register(OpenAIModelProvider(api_key="n", model="gpt-test", base_url="http://native/v1"))
    assert svc.provider_names() == ["openai"]
    await svc.complete("tenant-x", _request(model="gpt-test"))
    assert fake["client"].url == "http://native/v1/chat/completions"

    # Native first, then compatible: compatible (registered last) wins.
    svc.register(
        OpenAICompatibleModelProvider(
            api_key="k", model="kimi-k2", base_url="http://compat/v1", provider_name="openai"
        )
    )
    await svc.complete("tenant-x", _request(model="kimi-k2"))
    assert fake["client"].url == "http://compat/v1/chat/completions"


def test_provider_names_sorted_with_mixed_providers():
    svc = ModelRuntimeService(
        providers={
            "openai": OpenAIModelProvider(api_key="n", model="gpt-test"),
            "kimi": _kimi_provider(),
            "anthropic": AnthropicModelProvider(api_key="a", model="claude-test"),
        }
    )
    assert svc.provider_names() == ["anthropic", "kimi", "openai"]
