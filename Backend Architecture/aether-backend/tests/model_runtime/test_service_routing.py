"""Service-level tests for ADR-008 D4 routing integration (Commit 5).

Exercises ``ModelRuntimeService.complete`` routed through the Commit-5
routing layer: mode selection (auto / explicit / tenant_default /
policy_required), entitlement checks, safe fallback, fail-closed policy
enforcement, the ``RouteAuditEntry`` log, and the ``model_runtime_route``
metric — while proving the legacy non-routed path stays behaviorally
identical. The deterministic provider is used throughout; no SDK or network.

The router/entitlements/fallback contracts are the routing subpackage owned by
the Commit-5 routing team (agents A-E); this suite constructs them exactly per
those landed signatures.
"""

from __future__ import annotations

import pytest

from services.model_runtime import (
    AllowlistEntitlementResolver,
    DeterministicModelProvider,
    ModelBudgetExceeded,
    ModelNotConfigured,
    ModelRequest,
    ModelRouter,
    ModelRuntimeService,
    RoutingMode,
    RoutingPolicyViolation,
    StaticFallbackChain,
)
from services.model_runtime import service as service_module
from services.model_runtime.models import ModelProvider, ModelResponse
from shared.logger.logger import metrics

# A small, deterministic registry the router can resolve. "restricted" exists
# but is NOT in any tenant allowlist, so every denial path is exercisable.
_REGISTRY = [
    {"modelId": "alpha", "provider": "deterministic", "status": "recommended"},
    {"modelId": "beta", "provider": "deterministic", "status": "stable"},
    {"modelId": "gamma", "provider": "deterministic", "status": "stable"},
    {"modelId": "restricted", "provider": "deterministic", "status": "stable"},
]

# Tenant allowlist: t1 may use alpha/beta/gamma; "restricted" is denied.
_ENTITLEMENTS: dict[str, set[str]] = {
    "t1": {"alpha", "beta", "gamma"},
}


def _req(model: str = "m") -> ModelRequest:
    return ModelRequest(model=model, messages=[{"role": "user", "content": "hi"}])


def _routed_service(**overrides: object) -> ModelRuntimeService:
    """Build a router-backed service wired to the deterministic provider."""
    chain = StaticFallbackChain(
        order=["gamma"], provider=ModelProvider.DETERMINISTIC
    )
    router = ModelRouter(
        entitlements=AllowlistEntitlementResolver(entitlements=_ENTITLEMENTS),
        registry_models=_REGISTRY,
        fallback=chain,
    )
    kwargs: dict[str, object] = {
        "providers": {"deterministic": DeterministicModelProvider()},
        "router": router,
        "default_routing_mode": RoutingMode.AUTO,
        "tenant_model_defaults": {"t1": "alpha"},
        "entitled_model_ids": _ENTITLEMENTS,
    }
    kwargs.update(overrides)
    return ModelRuntimeService(**kwargs)  # type: ignore[arg-type]


class _DenyBudget:
    """TokenBudget whose reservation always fails (blocks the routed path)."""

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        return False

    async def release(self, tenant_id: str, tokens: int) -> None:
        pass

    async def charge(self, tenant_id: str, tokens: int) -> None:
        pass


def _route_metric_total() -> int:
    """Sum every ``model_runtime_route`` counter, regardless of label values."""
    counters = metrics.snapshot()["counters"]
    return sum(v for k, v in counters.items() if k.startswith("model_runtime_route"))


@pytest.mark.asyncio
async def test_routing_auto_selects_provider():
    svc = _routed_service()
    resp = await svc.complete("t1", _req())
    # AUTO picks the recommended "alpha" from the entitled allowlist.
    assert resp.model == "alpha"
    assert resp.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_routing_explicit_requested_model():
    svc = _routed_service()
    resp = await svc.complete(
        "t1", _req(), routing_mode=RoutingMode.EXPLICIT, requested_model="beta"
    )
    # An entitled explicit request routes straight to that model.
    assert resp.model == "beta"
    assert resp.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_routing_denial_falls_back():
    svc = _routed_service()
    resp = await svc.complete(
        "t1", _req(), routing_mode=RoutingMode.EXPLICIT, requested_model="restricted"
    )
    # "restricted" is not entitled -> the router engages the fallback chain,
    # so the response comes from the fallback model "gamma".
    assert resp.model == "gamma"
    assert resp.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_routing_tenant_default_uses_service_default():
    svc = _routed_service()
    resp = await svc.complete("t1", _req(), routing_mode=RoutingMode.TENANT_DEFAULT)
    # tenant_model_defaults supplies "alpha" for t1.
    assert resp.model == "alpha"


@pytest.mark.asyncio
async def test_routing_policy_required_denial_raises():
    svc = _routed_service()
    with pytest.raises(RoutingPolicyViolation):
        await svc.complete(
            "t1",
            _req(),
            routing_mode=RoutingMode.POLICY_REQUIRED,
            requested_model="restricted",
        )


@pytest.mark.asyncio
async def test_legacy_non_routed_path_unchanged():
    svc = ModelRuntimeService(
        providers={
            "deterministic": DeterministicModelProvider(response_override="default-ok"),
            "b": DeterministicModelProvider(response_override="b-ok"),
        }
    )
    # Provider override and default both keep their pre-routing behavior.
    resp = await svc.complete("t1", _req(), provider="b")
    assert resp.content == "b-ok"
    default_resp = await svc.complete("t1", _req())
    assert default_resp.content == "default-ok"


@pytest.mark.asyncio
async def test_route_audit_logged_and_metric(monkeypatch):
    calls: list[tuple[str, object]] = []

    def _recorder(msg: object, *args: object, **kwargs: object) -> None:
        calls.append((str(msg), kwargs))

    monkeypatch.setattr(service_module.logger, "info", _recorder)
    before = _route_metric_total()
    svc = _routed_service()
    resp = await svc.complete("t1", _req())
    after = _route_metric_total()
    # Invocation itself succeeded (deterministic provider echoed "alpha").
    assert resp.model == "alpha"
    # A RouteAuditEntry was emitted on the routed call.
    assert any(msg == "model_runtime route" for msg, _ in calls)
    # The model_runtime_route counter was incremented with mode/entitled/fallback
    # labels.
    assert after > before


@pytest.mark.asyncio
async def test_routed_path_still_applies_budget():
    svc = _routed_service(budget=_DenyBudget())
    with pytest.raises(ModelBudgetExceeded):
        await svc.complete("t1", _req())


# ------------------------------------------------------------------ dispatch fallback
# Fix-5: a dispatch-time rejection (unconfigured provider, denied budget, or
# OPEN circuit) feeds back through the router's bounded fallback chain instead
# of surfacing immediately — up to ``max_dispatch_fallback_depth`` distinct
# models, never re-selecting a rejected model, and never for ``policy_required``.


class _UnconfiguredProvider:
    """Registered provider that is not configured (dispatch-time rejection)."""

    provider_name = "unconfigured"

    def is_configured(self) -> bool:
        return False

    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("unconfigured provider must never be invoked")


def _router_with(registry, chain, entitlements=_ENTITLEMENTS) -> ModelRouter:
    return ModelRouter(
        entitlements=AllowlistEntitlementResolver(entitlements=entitlements),
        registry_models=registry,
        fallback=chain,
    )


def _dispatch_fallback_service(
    registry, chain, providers, *, entitlements=None, **service_kwargs
) -> ModelRuntimeService:
    ent = entitlements if entitlements is not None else _ENTITLEMENTS
    return ModelRuntimeService(
        providers=providers,
        router=_router_with(registry, chain, ent),
        default_routing_mode=RoutingMode.AUTO,
        entitled_model_ids=ent,
        **service_kwargs,
    )


@pytest.mark.asyncio
async def test_unconfigured_primary_dispatch_falls_back():
    # alpha routes to an unconfigured provider -> dispatch rejects -> bounded
    # fallback picks the configured gamma.
    registry = [
        {"modelId": "alpha", "provider": "unconfigured", "status": "recommended"},
        {"modelId": "gamma", "provider": "deterministic", "status": "stable"},
    ]
    ent = {"t1": {"alpha", "gamma"}}
    svc = _dispatch_fallback_service(
        registry,
        StaticFallbackChain(["gamma"]),
        {"unconfigured": _UnconfiguredProvider(), "deterministic": DeterministicModelProvider()},
        entitlements=ent,
    )
    resp = await svc.complete("t1", _req())
    assert resp.model == "gamma"
    assert resp.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_open_circuit_primary_dispatch_falls_back():
    svc = _routed_service(circuit_failure_threshold=1)
    breaker = svc.circuit_registry.get("deterministic:alpha", "t1")
    breaker.record_failure()  # 1 failure at threshold=1 -> OPEN
    resp = await svc.complete("t1", _req())
    # alpha's circuit is OPEN -> dispatch rejects -> bounded fallback to gamma.
    assert resp.model == "gamma"
    assert resp.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_dispatch_fallback_never_reuses_rejected_model():
    # A chain that points back at alpha cannot create a cycle: the rejected
    # model is excluded, so the fallback lands on gamma.
    registry = [
        {"modelId": "alpha", "provider": "unconfigured", "status": "recommended"},
        {"modelId": "gamma", "provider": "deterministic", "status": "stable"},
    ]
    ent = {"t1": {"alpha", "gamma"}}
    svc = _dispatch_fallback_service(
        registry,
        StaticFallbackChain(["alpha", "gamma"]),
        {"unconfigured": _UnconfiguredProvider(), "deterministic": DeterministicModelProvider()},
        entitlements=ent,
    )
    resp = await svc.complete("t1", _req())
    assert resp.model == "gamma"


@pytest.mark.asyncio
async def test_dispatch_fallback_bounded_exhaust_raises_original():
    # Every model rejects; after max_dispatch_fallback_depth distinct attempts
    # the original dispatch error propagates (no unbounded loop).
    registry = [
        {"modelId": "alpha", "provider": "unconfigured", "status": "recommended"},
        {"modelId": "beta", "provider": "unconfigured", "status": "stable"},
        {"modelId": "gamma", "provider": "unconfigured", "status": "stable"},
    ]
    ent = {"t1": {"alpha", "beta", "gamma"}}
    svc = _dispatch_fallback_service(
        registry,
        StaticFallbackChain(["beta", "gamma"]),
        {"unconfigured": _UnconfiguredProvider()},
        entitlements=ent,
    )
    with pytest.raises(ModelNotConfigured):
        await svc.complete("t1", _req())


@pytest.mark.asyncio
async def test_dispatch_fallback_disabled_at_zero_depth():
    # max_dispatch_fallback_depth=0 disables runtime fallback: the first
    # dispatch rejection propagates immediately.
    registry = [
        {"modelId": "alpha", "provider": "unconfigured", "status": "recommended"},
        {"modelId": "gamma", "provider": "deterministic", "status": "stable"},
    ]
    ent = {"t1": {"alpha", "gamma"}}
    svc = _dispatch_fallback_service(
        registry,
        StaticFallbackChain(["gamma"]),
        {"unconfigured": _UnconfiguredProvider(), "deterministic": DeterministicModelProvider()},
        entitlements=ent,
        max_dispatch_fallback_depth=0,
    )
    with pytest.raises(ModelNotConfigured):
        await svc.complete("t1", _req())


@pytest.mark.asyncio
async def test_dispatch_fallback_policy_required_stays_strict():
    # policy_required never dispatch-falls back: an unconfigured mandated model
    # surfaces as ModelNotConfigured (fail closed), not a silent downgrade.
    registry = [
        {"modelId": "alpha", "provider": "unconfigured", "status": "recommended"},
        {"modelId": "gamma", "provider": "deterministic", "status": "stable"},
    ]
    ent = {"t1": {"alpha", "gamma"}}
    svc = _dispatch_fallback_service(
        registry,
        StaticFallbackChain(["gamma"]),
        {"unconfigured": _UnconfiguredProvider(), "deterministic": DeterministicModelProvider()},
        entitlements=ent,
    )
    with pytest.raises(ModelNotConfigured):
        await svc.complete(
            "t1",
            _req(),
            routing_mode=RoutingMode.POLICY_REQUIRED,
            requested_model="alpha",
        )
