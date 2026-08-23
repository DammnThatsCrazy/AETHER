"""Service-level tests for the provider-neutral model runtime.

Exercises ModelRuntimeService orchestration: provider selection, sorted
registration, fail-closed configuration checks, register/replace semantics,
and token-budget reserve/release/charge reconciliation. The deterministic
provider is used throughout so no provider SDK or network is involved.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.model_runtime import (
    BaseModelProvider,
    CredentialResolution,
    CredentialService,
    DeterministicModelProvider,
    ModelBudgetExceeded,
    ModelNotConfigured,
    ModelRequest,
    ModelRuntimeService,
)
from services.model_runtime.credentials.models import ResolverConfig, mask_identifier
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


# ---------------------------------------------------------------------------
# Per-tenant credential dispatch (ADR-008 D5, Fix-3)
# ---------------------------------------------------------------------------


class _BindableProvider:
    """Provider with the ADR-008 D5 ``bind_credential`` surface (like the real
    adapters): materializes the per-tenant key at call time and fails closed
    when the tenant credential cannot be materialized."""

    provider_name = "bindable"

    def __init__(self, api_key: str = "sk-process-wide") -> None:
        self.api_key = api_key
        self._bound_resolution = None
        self.calls = 0

    def is_configured(self) -> bool:
        if self._bound_resolution is not None:
            try:
                return bool(self._effective_api_key())
            except ModelNotConfigured:
                return False
        return bool(self.api_key)

    def bind_credential(self, resolution):
        import copy

        bound = copy.copy(self)
        bound._bound_resolution = resolution
        return bound

    def _effective_api_key(self) -> str:
        bound = self._bound_resolution
        if bound is None:
            return self.api_key
        if bound.source == "env" and bound.ref:
            key = os.environ.get(bound.ref, "")
            if key:
                return key
            raise ModelNotConfigured("bindable: tenant credential env ref not set")
        raise ModelNotConfigured(
            "bindable: tenant credential requires backend materialization"
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            content=f"key={self._effective_api_key()}",
            model=request.model,
            provider=ModelProvider.DETERMINISTIC,
            usage=TokenUsage(),
            latency_ms=0.0,
        )


def _credential_service(resolution: CredentialResolution) -> CredentialService:
    """A gate-ENABLED CredentialService returning the canned resolution."""

    class _FakeResolver:
        async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
            return resolution

        async def health(self) -> bool:
            return True

    return CredentialService(
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        config=ResolverConfig(enabled=True),
    )


@pytest.mark.asyncio
async def test_no_credential_service_uses_registered_instance():
    # No CredentialService wired -> the registered provider serves unchanged and
    # no tenant resolution happens.
    provider = _BindableProvider(api_key="sk-process-wide")
    svc = ModelRuntimeService(providers={"bindable": provider})
    resp = await svc.complete("t1", _req(), provider="bindable")
    assert resp.content == "key=sk-process-wide"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_env_source_credential_binds_and_uses_tenant_key(monkeypatch):
    monkeypatch.setenv("T1_BINDABLE_API_KEY", "sk-tenant-1")
    resolution = CredentialResolution(
        provider="bindable",
        tenant_id="t1",
        ref="T1_BINDABLE_API_KEY",
        resolved=True,
        configured=True,
        masked_identifier=mask_identifier("sk-tenant-1"),
        source="env",
        reason="tenant-scoped env fallback",
    )
    provider = _BindableProvider(api_key="sk-process-wide")
    svc = ModelRuntimeService(
        providers={"bindable": provider},
        credential_service=_credential_service(resolution),
    )
    resp = await svc.complete("t1", _req(), provider="bindable")
    # The per-tenant key is materialized; the process-wide key is never reused
    # for the tenant, and the registered instance itself is never mutated.
    assert resp.content == "key=sk-tenant-1"
    assert provider.api_key == "sk-process-wide"
    assert provider._bound_resolution is None
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_gate_active_unresolved_tenant_fails_closed(monkeypatch):
    # The D5 gate is active (credential service wired) but the tenant has no
    # credential -> dispatch FAILS CLOSED with ModelNotConfigured and NEVER
    # reaches the process-wide/shared provider (cross-tenant leak guard).
    resolution = CredentialResolution(
        provider="bindable",
        tenant_id="t1",
        ref="llm/bindable",
        resolved=True,
        configured=False,
        source="none",
        reason="no credential configured for provider",
    )
    provider = _BindableProvider(api_key="sk-process-wide")
    svc = ModelRuntimeService(
        providers={"bindable": provider},
        credential_service=_credential_service(resolution),
    )
    with pytest.raises(ModelNotConfigured, match="not configured for tenant"):
        await svc.complete("t1", _req(), provider="bindable")
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_secret_backend_credential_fails_closed(monkeypatch):
    # A secret-backend credential cannot be materialized by the adapter -> the
    # bound provider is unconfigured -> dispatch fails closed and the provider
    # is never reached (no fall-through to the shared key).
    resolution = CredentialResolution(
        provider="bindable",
        tenant_id="t1",
        ref="aether/credentials/t1/bindable",
        resolved=True,
        configured=True,
        masked_identifier=mask_identifier("sk-tenant-1"),
        source="secret_backend",
        reason="resolved from secret backend",
    )
    provider = _BindableProvider(api_key="sk-process-wide")
    svc = ModelRuntimeService(
        providers={"bindable": provider},
        credential_service=_credential_service(resolution),
    )
    with pytest.raises(ModelNotConfigured, match="not configured for tenant"):
        await svc.complete("t1", _req(), provider="bindable")
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_bind_failure_fails_closed():
    # A bind_credential that raises must NOT silently fall back to the shared
    # provider: dispatch fails closed.
    class _ExplodingBinder(_BindableProvider):
        def bind_credential(self, resolution):
            raise RuntimeError("backend hiccup")

    provider = _ExplodingBinder(api_key="sk-process-wide")
    resolution = CredentialResolution(
        provider="bindable",
        tenant_id="t1",
        ref="T1_BINDABLE_API_KEY",
        resolved=True,
        configured=True,
        masked_identifier=mask_identifier("sk-tenant-1"),
        source="env",
        reason="tenant-scoped env fallback",
    )
    svc = ModelRuntimeService(
        providers={"bindable": provider},
        credential_service=_credential_service(resolution),
    )
    with pytest.raises(ModelNotConfigured, match="binding failed"):
        await svc.complete("t1", _req(), provider="bindable")
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_non_bindable_provider_registered_instance_unchanged():
    # Deterministic has no bind_credential surface (no key to leak) -> the
    # registered instance serves even with a gate-active, configured tenant.
    resolution = CredentialResolution(
        provider="deterministic",
        tenant_id="t1",
        ref="T1_DETERMINISTIC_API_KEY",
        resolved=True,
        configured=True,
        masked_identifier=mask_identifier("sk-tenant-1"),
        source="env",
        reason="tenant-scoped env fallback",
    )
    provider = DeterministicModelProvider(response_override="ok")
    svc = ModelRuntimeService(
        providers={"deterministic": provider},
        credential_service=_credential_service(resolution),
    )
    resp = await svc.complete("t1", _req())
    assert resp.content == "ok"
