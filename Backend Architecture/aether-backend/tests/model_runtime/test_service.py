"""Service-level tests for the provider-neutral model runtime.

Exercises ModelRuntimeService orchestration: provider selection, sorted
registration, fail-closed configuration checks, register/replace semantics,
and token-budget reserve/release/charge reconciliation. The deterministic
provider is used throughout so no provider SDK or network is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.model_runtime import (
    BaseModelProvider,
    DeterministicModelProvider,
    ModelBudgetExceeded,
    ModelNotConfigured,
    ModelRequest,
    ModelRuntimeService,
)
from services.model_runtime.models import ModelProvider, ModelResponse, TokenUsage

# The service source this security-invariant test asserts against.
_SERVICE_SOURCE = (
    Path(__file__).resolve().parents[2] / "services" / "model_runtime" / "service.py"
)


def _req() -> ModelRequest:
    return ModelRequest(model="m", messages=[{"role": "user", "content": "hi"}])


class FakeBudget:
    """In-memory TokenBudget recording every call for assertions."""

    def __init__(self, reserve_ok: bool = True) -> None:
        self.reserve_ok = reserve_ok
        self.released: list[int] = []
        self.charged: list[int] = []
        self.reserved: list[tuple[str, int]] = []

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        self.reserved.append((tenant_id, estimated_tokens))
        return self.reserve_ok

    async def release(self, tenant_id: str, tokens: int) -> None:
        self.released.append(tokens)

    async def charge(self, tenant_id: str, tokens: int) -> None:
        self.charged.append(tokens)


class _CountingProvider:
    """Configured provider that counts invocations and returns a fixed response."""

    provider_name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            content="ok",
            model=request.model,
            provider=ModelProvider.DETERMINISTIC,
            usage=TokenUsage(),
            latency_ms=0.0,
        )


@pytest.mark.asyncio
async def test_complete_uses_default_provider():
    svc = ModelRuntimeService(
        providers={"deterministic": DeterministicModelProvider(response_override="ok")}
    )
    resp = await svc.complete("t1", _req())
    assert resp.content == "ok"


@pytest.mark.asyncio
async def test_complete_provider_override():
    svc = ModelRuntimeService(
        providers={
            "deterministic": DeterministicModelProvider(response_override="default-ok"),
            "b": DeterministicModelProvider(response_override="b-ok"),
        }
    )
    # Explicit provider selection wins.
    resp = await svc.complete("t1", _req(), provider="b")
    assert resp.content == "b-ok"
    # Without a provider, the default ("deterministic") is used.
    default_resp = await svc.complete("t1", _req())
    assert default_resp.content == "default-ok"


def test_provider_names_sorted():
    svc = ModelRuntimeService(
        providers={
            "zebra": DeterministicModelProvider(),
            "alpha": DeterministicModelProvider(),
        }
    )
    assert svc.provider_names() == ["alpha", "zebra"]


@pytest.mark.asyncio
async def test_unknown_provider_raises():
    svc = ModelRuntimeService(providers={"deterministic": DeterministicModelProvider()})
    with pytest.raises(ModelNotConfigured):
        await svc.complete("t1", _req(), provider="nope")


@pytest.mark.asyncio
async def test_disabled_provider_raises_not_configured():
    disabled = BaseModelProvider(enabled=False)
    svc = ModelRuntimeService(providers={"deterministic": disabled})
    with pytest.raises(ModelNotConfigured):
        await svc.complete("t1", _req())


@pytest.mark.asyncio
async def test_budget_blocks_when_reservation_fails():
    budget = FakeBudget(reserve_ok=False)
    counter = _CountingProvider()
    svc = ModelRuntimeService(providers={"deterministic": counter}, budget=budget)
    with pytest.raises(ModelBudgetExceeded):
        await svc.complete("t1", _req())
    # The provider is never reached and nothing is released/charged.
    assert counter.calls == 0
    assert budget.reserved == [("t1", 800)]
    assert budget.released == []
    assert budget.charged == []


@pytest.mark.asyncio
async def test_budget_reconciles_release_when_under():
    budget = FakeBudget()
    # Usage total = 10 + 20 = 30, under the default 800 estimate.
    provider = DeterministicModelProvider(input_tokens=10, output_tokens=20)
    svc = ModelRuntimeService(providers={"deterministic": provider}, budget=budget)
    resp = await svc.complete("t1", _req())
    assert resp.usage.total_tokens == 30
    assert budget.reserved == [("t1", 800)]
    assert budget.released == [800 - 30]
    assert budget.charged == []


@pytest.mark.asyncio
async def test_budget_reconciles_charge_when_over():
    budget = FakeBudget()
    # Usage total = 1000 + 500 = 1500, over the default 800 estimate.
    provider = DeterministicModelProvider(input_tokens=1000, output_tokens=500)
    svc = ModelRuntimeService(providers={"deterministic": provider}, budget=budget)
    resp = await svc.complete("t1", _req())
    assert resp.usage.total_tokens == 1500
    assert budget.reserved == [("t1", 800)]
    assert budget.released == []
    assert budget.charged == [1500 - 800]


@pytest.mark.asyncio
async def test_budget_release_on_error():
    budget = FakeBudget()
    provider = DeterministicModelProvider(raise_error=RuntimeError("boom"))
    svc = ModelRuntimeService(providers={"deterministic": provider}, budget=budget)
    with pytest.raises(RuntimeError, match="boom"):
        await svc.complete("t1", _req())
    # The full reservation is released when the invocation fails.
    assert budget.reserved == [("t1", 800)]
    assert budget.released == [800]
    assert budget.charged == []


@pytest.mark.asyncio
async def test_register_replaces_provider():
    svc = ModelRuntimeService()
    svc.register(DeterministicModelProvider(response_override="a"))
    svc.register(DeterministicModelProvider(response_override="b"))
    resp = await svc.complete("t1", _req())
    assert resp.content == "b"


@pytest.mark.asyncio
async def test_complete_without_budget_succeeds():
    svc = ModelRuntimeService(
        providers={"deterministic": DeterministicModelProvider(response_override="ok")}
    )
    resp = await svc.complete("t1", _req())
    assert resp.content == "ok"


def test_no_logged_secrets():
    """Security invariant: no logger path emits request content or system_prompt."""
    src = _SERVICE_SOURCE.read_text(encoding="utf-8")
    logger_lines = [ln.strip() for ln in src.splitlines() if "logger." in ln]
    assert logger_lines, "expected logger statements in service.py"
    for line in logger_lines:
        assert "content=" not in line
        assert "system_prompt=" not in line
