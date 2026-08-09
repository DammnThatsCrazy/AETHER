"""Provider-neutral model runtime service.

Owns a provider registry, resolves a provider for a request, invokes it
through the AsyncModelProvider contract, enforces an optional per-tenant
token budget, and records metrics. This is the orchestration seam Noesis
(Commit 3) and later adapters (Commit 4+) plug into. No provider SDK,
credentials backend, or noesis package may be imported here.

Commit 5 adds ADR-008 D4 model routing/policy: when a ``ModelRouter`` is
configured (or routing kwargs are supplied) ``complete`` routes the call
through the routing layer, enforces entitlements/fallback, records a
``RouteAuditEntry`` plus a ``model_runtime_route`` metric, and then invokes
the selected provider on the exact same budget/invoke/reconcile path. With no
router and no routing kwargs the legacy deterministic path is unchanged.
"""

from __future__ import annotations

import time
import typing
from collections.abc import Mapping

from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelNotConfigured,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
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
    from services.model_runtime.routing.engine import ModelRouter

logger = get_logger("aether.service.model_runtime")


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
        aligned between the two.
        """
        impl = self._providers.get(name)
        if impl is None:
            raise ModelNotConfigured(f"unknown provider: {name}")
        if not impl.is_configured():
            raise ModelNotConfigured(f"provider not configured: {name}")

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

        started = time.monotonic()
        try:
            resp = await impl.complete(request)
        except Exception:
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

        # Resolve the route selection to a registered provider name; a
        # selection the runtime does not own is a configuration failure.
        provider_val = (
            sel.provider.value
            if isinstance(sel.provider, ModelProvider)
            else str(sel.provider)
        )
        invoke_request = request.model_copy(update={"model": sel.model_id})

        # Record the route for audit + metrics before invoking.
        self._emit_route_audit(
            tenant_id, profile_id, requested_model, sel, decision_ms
        )

        return await self._invoke_with_budget(tenant_id, invoke_request, provider_val)

    def _emit_route_audit(
        self,
        tenant_id: str,
        profile_id: str | None,
        requested_model: str | None,
        sel: RouteSelection,
        decision_ms: float,
    ) -> None:
        """Log a RouteAuditEntry and increment the ``model_runtime_route`` counter.

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
        metrics.increment(
            "model_runtime_route",
            labels={
                "mode": mode_label,
                "entitled": str(bool(sel.entitled)),
                "fallback": str(bool(sel.fallback)),
            },
        )

    @staticmethod
    def _mode_label(mode: object) -> str:
        """Audit/metric-safe label for a routing mode."""
        if mode is None:
            return "unset"
        value = getattr(mode, "value", mode)
        return str(value)
