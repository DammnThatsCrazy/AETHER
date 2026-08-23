"""Provider-neutral model runtime service.

Owns a provider registry, resolves a provider for a request, invokes it
through the AsyncModelProvider contract, enforces an optional per-tenant
token budget, and records metrics. This is the orchestration seam Noesis
(Commit 3) and later adapters (Commit 4+) plug into. No provider SDK,
credentials backend, or noesis package may be imported here.

Commit 5 adds ADR-008 D4 model routing/policy: when a ``ModelRouter`` is
configured (or routing kwargs are supplied) ``complete`` routes the call
through the routing layer, enforces entitlements/fallback, records a
``RouteAuditEntry`` plus a ``model_runtime_routes`` metric, and then invokes
the selected provider on the exact same budget/invoke/reconcile path. With no
router and no routing kwargs the legacy deterministic path is unchanged.

ADR-008 D8: provider/model dispatch is gated through a fail-closed
:class:`CircuitRegistry` wired from ``ModelRuntimeSettings`` — an OPEN circuit
raises :class:`ModelCircuitOpen` instead of hammering an unhealthy provider.
"""

from __future__ import annotations

import time
import typing
from collections.abc import Mapping

from services.model_runtime.config import get_settings
from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelInvocationError,
    ModelNotConfigured,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from services.model_runtime.observability.circuit_breaker import CircuitRegistry
from services.model_runtime.observability.metrics import RuntimeMetricsRecorder
from services.model_runtime.provider import AsyncModelProvider
from shared.logger.logger import get_logger, metrics

# Routing subpackage (ADR-008 D4) is owned by the Commit-5 routing team
# (sibling agents A-E). Imported guardedly so this module loads even while
# those modules are still landing; every reference below executes only on a
# routed call, which requires the subpackage to be present.
try:
    from services.model_runtime.routing.models import (
        RouteAuditEntry,
        RouteSelection,
        RoutingMode,
        RoutingRequest,
        RoutingResolutionError,
        RoutingUnavailable,
    )
except ImportError:  # pragma: no cover - routing subpackage not landed yet
    RouteAuditEntry = None  # type: ignore[assignment, misc]
    RouteSelection = None  # type: ignore[assignment, misc]
    RoutingMode = None  # type: ignore[assignment, misc]
    RoutingRequest = None  # type: ignore[assignment, misc]
    RoutingResolutionError = None  # type: ignore[assignment, misc]
    RoutingUnavailable = None  # type: ignore[assignment, misc]

if typing.TYPE_CHECKING:  # engine owned by the routing team; type-only here
    from services.model_runtime.credentials.models import CredentialResolution
    from services.model_runtime.credentials.service import CredentialService
    from services.model_runtime.routing.engine import ModelRouter

logger = get_logger("aether.service.model_runtime")


class ModelCircuitOpen(ModelInvocationError):
    """Raised when the provider/model circuit breaker is OPEN and a call is blocked.

    Fail-closed (ADR-008 D8): while a provider/model circuit is tripped the
    runtime refuses to dispatch rather than queueing load onto an unhealthy
    provider. Callers catch :class:`ModelInvocationError` (or this subtype) and
    fail closed; the recovery path is timeout-driven inside the breaker.
    """


# Dispatch-time rejections that a routed call may recover from through a
# bounded runtime fallback: the chosen provider is unconfigured, the token
# budget denied the call, or the provider/model circuit is OPEN. Actual
# provider/transport errors (ModelProviderError / ModelTimeoutError) are NOT
# recoverable here — they are real invocation failures and propagate.
_DISPATCH_REJECTIONS = (ModelNotConfigured, ModelBudgetExceeded, ModelCircuitOpen)


class TokenBudget(typing.Protocol):
    """Per-tenant token budget hook (same shape as NoesisTokenBudget)."""

    async def check_and_reserve(self, tenant_id: str, estimated_tokens: int) -> bool:
        """Reserve estimated_tokens atomically; True if within budget."""

    async def release(self, tenant_id: str, tokens: int) -> None:
        """Return previously reserved tokens (failure or over-estimate)."""

    async def charge(self, tenant_id: str, tokens: int) -> None:
        """Record spend beyond the upfront reservation."""


class ModelRuntimeService:
    """Provider registry, selection, budget enforcement, and metrics."""

    def __init__(
        self,
        providers: Mapping[str, AsyncModelProvider] | None = None,
        *,
        default_provider: str = "deterministic",
        budget: TokenBudget | None = None,
        estimated_request_tokens: int = 800,
        router: ModelRouter | None = None,
        default_routing_mode: RoutingMode | None = None,
        tenant_model_defaults: Mapping[str, str] | None = None,
        entitled_model_ids: Mapping[str, set[str]] | None = None,
        circuit_failure_threshold: int | None = None,
        circuit_recovery_timeout_s: float | None = None,
        credential_service: CredentialService | None = None,
        max_dispatch_fallback_depth: int = 2,
    ) -> None:
        """Build the runtime; default_provider must exist in providers.

        providers: {provider_name: instance}. budget None = unlimited.

        Routing kwargs (Commit 5, ADR-008 D4) all default to None so existing
        callers (including Noesis) are unaffected: with no router and no
        routing kwargs, ``complete`` uses the legacy deterministic path.
        ``router`` supplies the routing engine; ``default_routing_mode`` is the
        fallback mode when a call passes none; ``tenant_model_defaults`` maps
        tenant_id -> default model id; ``entitled_model_ids`` maps tenant_id ->
        allowlist of model ids the tenant may route to.

        Circuit-breaker kwargs (ADR-008 D8) wire the fail-closed breaker into
        dispatch: they default to ``ModelRuntimeSettings.circuit_failure_threshold``
        and ``circuit_recovery_timeout_s`` (config is the single source of
        truth). Explicit values override the settings singleton. The breaker is
        keyed per provider + model (+ tenant scope) inside ``circuit_registry``.

        Per-tenant credentials (ADR-008 D5): ``credential_service`` is an
        optional :class:`CredentialService`; when present the dispatch path
        resolves the tenant/provider credential at call time and dispatches
        through a per-tenant-bound provider (never the process-wide/shared
        key). FAIL-CLOSED: a tenant with no resolved credential raises
        :class:`ModelNotConfigured` instead of silently serving the shared key,
        and a provider credential binding failure raises the same. With
        ``None`` (the default) the registered provider instance serves the call
        exactly as before.

        ``max_dispatch_fallback_depth`` bounds how many distinct models a routed
        dispatch rejection (unconfigured provider, denied budget, open circuit)
        may fall back through before the original error propagates (default 2;
        ``0`` disables runtime fallback entirely).
        """
        self._providers: dict[str, AsyncModelProvider] = dict(providers or {})
        self._default = default_provider
        self._budget = budget
        self._estimated_request_tokens = estimated_request_tokens
        self._router = router
        self._default_routing_mode = default_routing_mode
        self._tenant_model_defaults = dict(tenant_model_defaults or {})
        self._entitled_model_ids = {
            tenant: set(models) for tenant, models in (entitled_model_ids or {}).items()
        }
        self._credential_service = credential_service
        self._max_dispatch_fallback_depth = max(0, int(max_dispatch_fallback_depth))

        settings = get_settings()
        self._circuit_registry = CircuitRegistry(
            failure_threshold=(
                settings.circuit_failure_threshold
                if circuit_failure_threshold is None
                else circuit_failure_threshold
            ),
            recovery_timeout_s=(
                settings.circuit_recovery_timeout_s
                if circuit_recovery_timeout_s is None
                else circuit_recovery_timeout_s
            ),
        )
        self._metrics = RuntimeMetricsRecorder()

    @property
    def circuit_registry(self) -> CircuitRegistry:
        """The per-provider/model fail-closed circuit registry gating dispatch."""
        return self._circuit_registry

    def register(self, provider: AsyncModelProvider) -> None:
        """Add or replace a provider by its provider_name."""
        self._providers[provider.provider_name] = provider

    def provider_names(self) -> list[str]:
        """Sorted provider names available in the registry."""
        return sorted(self._providers)

    async def complete(
        self,
        tenant_id: str,
        request: ModelRequest,
        *,
        provider: str | None = None,
        routing_mode: RoutingMode | None = None,
        requested_model: str | None = None,
        profile_id: str | None = None,
    ) -> ModelResponse:
        """Resolve provider, reserve budget, invoke, reconcile, and log.

        Two paths:

        * Legacy (no router, no routing kwargs): provider override or the
          service default, then budget/invoke/reconcile — behaviorally
          identical to the pre-ADR-008-D4 implementation.
        * Routed (router configured, or any routing kwarg supplied): build a
          :class:`RoutingRequest`, run it through the routing layer, then
          invoke the selected provider on the same budget/invoke path.

        ``routing_mode`` / ``requested_model`` / ``profile_id`` are the
        ADR-008 D4 routing inputs. ``provider`` only affects the legacy path.
        """
        routing_requested = (
            self._router is not None
            or routing_mode is not None
            or requested_model is not None
            or profile_id is not None
        )
        if not routing_requested:
            name = provider or self._default
            return await self._invoke_with_budget(tenant_id, request, name)

        return await self._complete_routed(
            tenant_id,
            request,
            routing_mode=routing_mode,
            requested_model=requested_model,
            profile_id=profile_id,
        )

    async def _invoke_with_budget(
        self,
        tenant_id: str,
        request: ModelRequest,
        name: str,
    ) -> ModelResponse:
        """Resolve ``name``, enforce the per-tenant budget, invoke, reconcile.

        Shared by the legacy and routed paths so token accounting, fail-open
        error telemetry, success metrics, and structured logging stay exactly
        aligned between the two. ADR-008 D8 dispatch is gated through the
        provider/model circuit breaker: an OPEN circuit raises
        :class:`ModelCircuitOpen` instead of invoking the provider.
        """
        impl = self._providers.get(name)
        if impl is None:
            raise ModelNotConfigured(f"unknown provider: {name}")
        if not impl.is_configured():
            raise ModelNotConfigured(f"provider not configured: {name}")

        # ADR-008 D5: resolve the tenant-scoped provider credential at call
        # time. Wiring a CredentialService puts the runtime in per-tenant
        # credential enforcement (fail closed): a tenant with no resolved
        # credential raises instead of silently serving the process-wide /
        # shared key (which would be a cross-tenant credential leak). When a
        # tenant credential resolves, dispatch through a per-tenant-bound
        # provider; a provider with no credential surface (e.g. the local
        # deterministic fixture) serves its registered instance unchanged —
        # it holds no key, so there is nothing to leak.
        if self._credential_service is not None:
            resolution = await self._credential_service.resolve(tenant_id, name)
            if not resolution.configured:
                raise ModelNotConfigured(
                    f"provider not configured for tenant: {name} "
                    "(no tenant credential)"
                )
            impl = self._bind_provider(impl, resolution)
            if not impl.is_configured():
                raise ModelNotConfigured(
                    f"provider not configured for tenant: {name}"
                )

        if self._budget is not None:
            reserved = await self._budget.check_and_reserve(
                tenant_id, self._estimated_request_tokens
            )
            if not reserved:
                metrics.increment(
                    "model_runtime_budget_exceeded",
                    labels={"provider": name},
                )
                raise ModelBudgetExceeded(tenant_id)

        # Gate dispatch through the provider/model circuit breaker. The gate sits
        # immediately before the provider call (and after budget reservation) so
        # every granted call is followed by a record_success / record_failure —
        # a consumed half-open probe is never left in flight.
        breaker = self._circuit_registry.get(
            self._circuit_key(name, request.model), tenant_id
        )
        if not breaker.allowed():
            if self._budget is not None:
                await self._budget.release(tenant_id, self._estimated_request_tokens)
            self._metrics.record_circuit(True)
            logger.info(
                "model_runtime complete",
                extra={
                    "provider": name,
                    "model": request.model,
                    "status": "circuit_open",
                },
            )
            raise ModelCircuitOpen(
                f"circuit open for provider/model: {name}/{request.model}"
            )

        started = time.monotonic()
        try:
            resp = await impl.complete(request)
        except Exception:
            breaker.record_failure()
            # Fail-open for telemetry: release the full reservation, log the
            # error metric, then re-raise so the call stays fail-closed.
            if self._budget is not None:
                await self._budget.release(tenant_id, self._estimated_request_tokens)
            metrics.increment(
                "model_runtime_invocation_error",
                labels={"provider": name},
            )
            logger.info(
                "model_runtime complete",
                extra={
                    "provider": name,
                    "model": request.model,
                    "latency_ms": (time.monotonic() - started) * 1000,
                    "status": "error",
                },
            )
            raise

        breaker.record_success()
        latency_ms = (time.monotonic() - started) * 1000

        # Reconcile the reservation with actual usage (mirrors Noesis).
        if self._budget is not None:
            actual = resp.usage.total_tokens
            if actual < self._estimated_request_tokens:
                await self._budget.release(
                    tenant_id, self._estimated_request_tokens - actual
                )
            elif actual > self._estimated_request_tokens:
                await self._budget.charge(
                    tenant_id, actual - self._estimated_request_tokens
                )

        metrics.increment(
            "model_runtime_invocation_success",
            labels={"provider": name, "model": request.model},
        )
        logger.info(
            "model_runtime complete",
            extra={
                "provider": name,
                "model": request.model,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "latency_ms": latency_ms,
                "status": "success",
            },
        )
        return resp

    @staticmethod
    def _bind_provider(
        impl: AsyncModelProvider, resolution: CredentialResolution
    ) -> AsyncModelProvider:
        """Return the provider that serves this tenant's call (ADR-008 D5).

        Providers that implement ``bind_credential`` return a client bound to
        the resolved tenant credential; a binding that raises (or returns
        ``None``) FAILS CLOSED with :class:`ModelNotConfigured` so the tenant
        never silently falls back to the process-wide / shared provider.
        Providers with no ``bind_credential`` surface (e.g. the deterministic
        test/local fixture) return the registered instance unchanged — they
        hold no key, so there is no shared credential to leak.
        """
        binder = getattr(impl, "bind_credential", None)
        if not callable(binder):
            return impl
        try:
            bound = binder(resolution)
        except Exception as exc:  # noqa: BLE001 — binding failures fail closed
            raise ModelNotConfigured(
                f"provider credential binding failed for tenant: {impl.provider_name}"
            ) from exc
        if bound is None:
            raise ModelNotConfigured(
                f"provider credential binding failed for tenant: {impl.provider_name}"
            )
        return bound

    async def _complete_routed(
        self,
        tenant_id: str,
        request: ModelRequest,
        *,
        routing_mode: RoutingMode | None,
        requested_model: str | None,
        profile_id: str | None,
    ) -> ModelResponse:
        """Route through the ADR-008 D4 layer, then invoke the selected provider.

        Mode precedence: explicit arg -> service default -> profile/router
        default (the router resolves the final value when ``mode`` is None).
        Fail-closed: a ``RoutingResolutionError`` (entitlement denial with no
        fallback, strict policy violation, unavailable router) is metered,
        logged, and re-raised — no silent downgrade unless the router already
        engaged a fallback in the returned selection.
        """
        if self._router is None:
            if RoutingUnavailable is None:  # routing subpackage not installed
                raise ModelNotConfigured(
                    "routing requested but the routing layer is not available"
                )
            raise RoutingUnavailable(
                "routing requested but no ModelRouter configured on "
                "ModelRuntimeService"
            )

        mode = routing_mode or self._default_routing_mode
        rreq = RoutingRequest(
            tenant_id=tenant_id,
            profile_id=profile_id,
            mode=mode,
            requested_model=requested_model,
            tenant_default_model=self._tenant_model_defaults.get(tenant_id),
            entitled_model_ids=self._entitled_model_ids.get(tenant_id),
        )
        decision_started = time.monotonic()
        try:
            sel = await self._router.route(rreq)
        except RoutingResolutionError:
            metrics.increment(
                "model_runtime_routing_error",
                labels={"mode": self._mode_label(mode)},
            )
            logger.info(
                "model_runtime route rejected",
                extra={
                    "tenant_id": tenant_id,
                    "requested_model": requested_model,
                    "mode": self._mode_label(mode),
                    "status": "error",
                },
            )
            raise
        decision_ms = (time.monotonic() - decision_started) * 1000

        # Resolve the route selection to a registered provider name. For
        # OpenAI-compatible registry providers (kimi/deepseek/qwen) the
        # selection carries the registry-declared provider key, so the
        # compatible provider registered under that name is reached rather than
        # the collapsed "openai" endpoint.
        provider_key = self._selection_provider_key(sel)
        invoke_request = request.model_copy(update={"model": sel.model_id})

        # Record the route for audit + metrics before invoking.
        self._emit_route_audit(
            tenant_id, profile_id, requested_model, sel, decision_ms
        )

        # Dispatch through a BOUNDED runtime fallback: a dispatch-time
        # rejection (unconfigured provider, denied budget, or an open circuit)
        # is fed back through the router's fallback chain (which preserves the
        # request allowlist and never re-selects a rejected model) up to
        # ``max_dispatch_fallback_depth`` distinct models before the original
        # error propagates. Strict policy routes never fall back here.
        excluded: list[str] = [sel.model_id]
        attempt = 0
        while True:
            try:
                return await self._invoke_with_budget(
                    tenant_id, invoke_request, provider_key
                )
            except _DISPATCH_REJECTIONS:
                if self._max_dispatch_fallback_depth <= 0:
                    raise
                if attempt >= self._max_dispatch_fallback_depth:
                    raise
                if sel.mode is RoutingMode.POLICY_REQUIRED:
                    raise
                fallback_req = rreq.model_copy(update={"mode": sel.mode})
                fallback_sel = await self._router.dispatch_fallback(
                    fallback_req,
                    exclude=excluded,
                    reason=f"dispatch rejected for model {sel.model_id}",
                )
                if fallback_sel is None or fallback_sel.model_id in excluded:
                    raise
                excluded.append(fallback_sel.model_id)
                sel = fallback_sel
                provider_key = self._selection_provider_key(sel)
                invoke_request = request.model_copy(update={"model": sel.model_id})
                self._emit_route_audit(
                    tenant_id, profile_id, requested_model, sel, decision_ms
                )
                attempt += 1

    @staticmethod
    def _selection_provider_key(sel: RouteSelection) -> str:
        """The registered-provider name for a route selection.

        Prefers the registry-declared provider key carried on the selection
        (``registry_provider`` — e.g. ``"kimi"`` for an OpenAI-compatible
        model) so compatible-provider models reach their declared endpoint;
        falls back to the classification provider value for selections that do
        not carry a registry key.
        """
        registry_provider = getattr(sel, "registry_provider", None)
        if isinstance(registry_provider, str) and registry_provider:
            return registry_provider
        provider = getattr(sel, "provider", None)
        return provider.value if isinstance(provider, ModelProvider) else str(provider)

    @staticmethod
    def _circuit_key(name: str, model: str) -> str:
        """Composite circuit key: provider + model (ADR-008 D8).

        The registry keys on this string (plus tenant scope when present), so
        each provider/model combination owns an independent breaker and one
        model's failures never trip another model's circuit.
        """
        return f"{name}:{model}"

    def _emit_route_audit(
        self,
        tenant_id: str,
        profile_id: str | None,
        requested_model: str | None,
        sel: RouteSelection,
        decision_ms: float,
    ) -> None:
        """Log a RouteAuditEntry and emit the canonical ``model_runtime_routes`` metric.

        The counter is emitted via :class:`RuntimeMetricsRecorder.record_route`
        (``MetricNames.ROUTES``), the canonical name dashboards key off.
        Best-effort telemetry: a malformed audit entry is logged as a plain
        dict rather than failing the invocation. Never includes request
        content, credentials, or tenant-restricted data.
        """
        mode_label = self._mode_label(sel.mode)
        audit_data = {
            "tenant_id": tenant_id,
            "profile_id": profile_id,
            "requested_model": requested_model,
            "selected_model": sel.model_id,
            "mode": sel.mode,
            "entitled": bool(sel.entitled),
            "fallback": bool(sel.fallback),
            "fallback_reason": sel.fallback_reason,
            "decision_ms": decision_ms,
        }
        try:
            audit_log = RouteAuditEntry(**audit_data).model_dump()
        except Exception:
            audit_log = audit_data
        logger.info(
            "model_runtime route",
            extra={"audit_entry": audit_log},
        )
        self._metrics.record_route(
            mode_label,
            entitled=bool(sel.entitled),
            fallback=bool(sel.fallback),
        )

    @staticmethod
    def _mode_label(mode: object) -> str:
        """Audit/metric-safe label for a routing mode."""
        if mode is None:
            return "unset"
        value = getattr(mode, "value", mode)
        return str(value)
