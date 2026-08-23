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

Deployment wiring (ADR-008): :meth:`ModelRuntimeService.from_settings` builds a
runtime from :class:`ModelRuntimeSettings` so the advertised deployment controls
are EFFECTIVE rather than inert — ``adapters_dir`` actually loads provider
adapters (:func:`load_provider_adapters`), ``estimated_request_tokens`` feeds
the budget reservation size, ``max_providers`` bounds the provider registry, and
``default_provider`` plus the circuit settings feed dispatch. Explicit
constructor kwargs win over the settings (env-precedence pattern); the plain
constructor is unchanged, so existing callers are unaffected.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import time
import typing
from collections.abc import Mapping
from pathlib import Path

from services.model_runtime.config import (
    ConfigError,
    ModelRuntimeSettings,
    get_settings,
)
from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelInvocationError,
    ModelNotConfigured,
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
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


def load_provider_adapters(
    adapters_dir: str | os.PathLike[str],
) -> dict[str, AsyncModelProvider]:
    """Discover and instantiate provider adapters from a directory of modules.

    The consumer for ``MODEL_RUNTIME_ADAPTERS_DIR``: every ``*.py`` module in
    ``adapters_dir`` (excluding ``__init__.py`` and underscore-private modules)
    is imported; each concrete class the module defines that carries a string
    ``provider_name`` is instantiated with no arguments and collected under that
    name. Adapters read their own environment in ``__init__`` (unconfigured
    providers remain registered but fail closed at dispatch), matching the
    package convention.

    FAILS CLOSED with :class:`ConfigError` on a missing/unreadable directory, a
    module that fails to import, or a provider class that cannot be constructed
    — a misconfigured ``MODEL_RUNTIME_ADAPTERS_DIR`` never silently loads no
    adapters.

    Relative paths resolve against the backend root (``Path(__file__).parents[2]``
    = the directory containing ``services/``), so the default
    ``services/model_runtime/adapters`` works regardless of the process working
    directory.
    """
    backend_root = Path(__file__).resolve().parents[2]
    path = Path(adapters_dir)
    if not path.is_absolute():
        path = backend_root / path
    path = path.resolve()
    if not path.is_dir():
        raise ConfigError(f"adapters_dir is not a directory: {path}")

    loaded: dict[str, AsyncModelProvider] = {}
    for module_file in sorted(path.glob("*.py")):
        if module_file.name == "__init__.py" or module_file.name.startswith("_"):
            continue
        module_name = f"aether_adapter_{module_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if spec is None or spec.loader is None:
            raise ConfigError(f"cannot import adapter module: {module_file}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — bad adapters fail closed
            raise ConfigError(
                f"failed to import adapter module {module_file.name}: {exc}"
            ) from exc
        for attr_name, obj in vars(module).items():
            if not isinstance(obj, type):
                continue
            # Only classes DEFINED by this module (not re-exported imports).
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            if inspect.isabstract(obj):
                continue
            if not isinstance(getattr(obj, "provider_name", None), str):
                continue
            try:
                provider = obj()
            except Exception as exc:  # noqa: BLE001 — bad adapters fail closed
                raise ConfigError(
                    f"adapter class {attr_name!r} in {module_file.name} failed "
                    f"to construct: {exc}"
                ) from exc
            if not callable(getattr(provider, "complete", None)):
                raise ConfigError(
                    f"adapter class {attr_name!r} in {module_file.name} exposes "
                    "no complete(); not an AsyncModelProvider"
                )
            loaded[provider.provider_name] = provider
    return loaded


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
        max_providers: int | None = None,
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

        ``max_providers`` (deployment wiring, default ``None`` = unbounded)
        bounds the provider registry: the initial ``providers`` mapping is
        capped to the ``max_providers`` lowest provider names (deterministic
        order) and :meth:`register` refuses to add a NEW provider once the cap
        is reached (replacing an existing name is always allowed). The
        settings-backed :meth:`from_settings` factory feeds
        ``ModelRuntimeSettings.max_providers`` here, so
        ``MODEL_RUNTIME_MAX_PROVIDERS`` actually bounds routing fan-out.
        """
        providers_init = dict(providers or {})
        if max_providers is not None:
            cap = max(1, int(max_providers))
            self._max_providers = cap
            if len(providers_init) > cap:
                keep = sorted(providers_init)[:cap]
                providers_init = {name: providers_init[name] for name in keep}
        else:
            self._max_providers = None
        self._providers: dict[str, AsyncModelProvider] = providers_init
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

    @classmethod
    def from_settings(
        cls,
        settings: ModelRuntimeSettings | None = None,
        *,
        providers: Mapping[str, AsyncModelProvider] | None = None,
        adapters_dir: str | os.PathLike[str] | None = None,
        max_providers: int | None = None,
        estimated_request_tokens: int | None = None,
        default_provider: str | None = None,
        circuit_failure_threshold: int | None = None,
        circuit_recovery_timeout_s: float | None = None,
        **kwargs: object,
    ) -> "ModelRuntimeService":
        """Build a runtime backed by :class:`ModelRuntimeSettings`.

        The deployment wiring seam (ADR-008): construct the service from the
        settings singleton (or an explicit ``settings`` object) so the
        advertised ``MODEL_RUNTIME_*`` controls are EFFECTIVE instead of inert:

        * ``adapters_dir`` — provider adapters are discovered and instantiated
          from the configured directory via :func:`load_provider_adapters` and
          merged into the registry (explicitly passed ``providers`` win by
          name).
        * ``estimated_request_tokens`` — the per-request budget reservation
          size used at dispatch.
        * ``max_providers`` — bounds the provider registry (the initial
          population is capped and :meth:`register` refuses to exceed the cap).
        * ``default_provider`` and the circuit settings — fed from settings so
          the given ``settings`` object is authoritative.

        Precedence mirrors the env-override pattern used throughout the
        codebase: an explicit kwarg wins over the settings value. Pass
        ``providers`` / ``adapters_dir`` / ``estimated_request_tokens`` /
        ``max_providers`` / ``default_provider`` / circuit kwargs to override.
        ``budget``, ``router``, credential wiring, and other constructor kwargs
        pass through unchanged. ``settings`` defaults to :func:`get_settings`.

        The service's default provider must be present in the registry (loaded
        from ``adapters_dir`` or passed via ``providers``) before dispatch —
        the same contract as the plain constructor. To build an unbounded
        registry, construct :class:`ModelRuntimeService` directly.
        """
        settings = settings if settings is not None else get_settings()
        providers_out = dict(providers or {})
        adapters_path = (
            adapters_dir if adapters_dir is not None else settings.adapters_dir
        )
        loaded = load_provider_adapters(adapters_path)
        for name, provider in loaded.items():
            # Explicitly passed providers win over dir-loaded adapters.
            providers_out.setdefault(name, provider)
        return cls(
            providers=providers_out,
            default_provider=(
                default_provider
                if default_provider is not None
                else settings.default_provider
            ),
            estimated_request_tokens=(
                estimated_request_tokens
                if estimated_request_tokens is not None
                else settings.estimated_request_tokens
            ),
            max_providers=(
                max_providers if max_providers is not None else settings.max_providers
            ),
            circuit_failure_threshold=(
                circuit_failure_threshold
                if circuit_failure_threshold is not None
                else settings.circuit_failure_threshold
            ),
            circuit_recovery_timeout_s=(
                circuit_recovery_timeout_s
                if circuit_recovery_timeout_s is not None
                else settings.circuit_recovery_timeout_s
            ),
            **kwargs,
        )

    @property
    def circuit_registry(self) -> CircuitRegistry:
        """The per-provider/model fail-closed circuit registry gating dispatch."""
        return self._circuit_registry

    def register(self, provider: AsyncModelProvider) -> None:
        """Add or replace a provider by its provider_name.

        When the service was constructed with a ``max_providers`` bound, the
        registry is capped: registering a provider NOT already present once the
        cap is reached raises :class:`RuntimeError` (fail-closed), so a
        misconfigured deployment that exceeds ``MODEL_RUNTIME_MAX_PROVIDERS``
        fails loudly at startup wiring instead of silently growing past the
        bound. Replacing an already-registered name is always allowed.
        """
        if (
            self._max_providers is not None
            and provider.provider_name not in self._providers
            and len(self._providers) >= self._max_providers
        ):
            raise RuntimeError(
                f"provider registry is full (max_providers="
                f"{self._max_providers}); cannot register "
                f"{provider.provider_name!r}"
            )
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

        # ADR-008 D5: resolve the tenant-scoped provider credential at call
        # time BEFORE any provider-configuration check. In a tenant-BYOK
        # deployment the registered adapter may deliberately carry no
        # process-wide API key, so gating on ``is_configured()`` first would
        # reject the call before the tenant's valid env credential could ever
        # be bound. Wiring a CredentialService puts the runtime in per-tenant
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
                self._metrics.record_credential_rejection(name)
                raise ModelNotConfigured(
                    f"provider not configured for tenant: {name} "
                    "(no tenant credential)"
                )
            impl = self._bind_provider(impl, resolution)

        # Only NOW gate on provider configuration — after tenant credential
        # binding, so a tenant-bound provider is judged on its own (materialized)
        # credential rather than the process-wide key it may never hold.
        if not impl.is_configured():
            if self._credential_service is not None:
                self._metrics.record_credential_rejection(name)
                raise ModelNotConfigured(
                    f"provider not configured for tenant: {name}"
                )
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
                self._metrics.record_budget_exceeded(name)
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
            self._metrics.record_call(name, request.model, status="circuit_open")
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
        except asyncio.CancelledError:
            # A cancelled dispatch must still settle budget + breaker state.
            # asyncio.CancelledError derives from BaseException (not
            # Exception), so the handler below never runs for it. Without this
            # cleanup a reserved budget is never returned and — if this was the
            # sole half-open probe — ``_probe_in_flight`` stays set so the
            # circuit rejects every later call indefinitely. Fail-closed:
            # record a failure (which settles a half-open probe) and release
            # the reservation, then re-raise the cancellation. The release is
            # best-effort so a backend hiccup never masks the cancellation.
            breaker.record_failure()
            if self._budget is not None:
                try:
                    await self._budget.release(
                        tenant_id, self._estimated_request_tokens
                    )
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    pass
            raise
        except Exception as exc:
            breaker.record_failure()
            # Fail-open for telemetry: release the full reservation, log the
            # error metric, then re-raise so the call stays fail-closed.
            if self._budget is not None:
                await self._budget.release(tenant_id, self._estimated_request_tokens)
            metrics.increment(
                "model_runtime_invocation_error",
                labels={"provider": name},
            )
            error_type = self._provider_error_type(exc)
            self._metrics.record_call(name, request.model, status="error")
            if error_type is not None:
                self._metrics.record_provider_error(name, error_type)
            self._metrics.record_latency(name, (time.monotonic() - started) * 1000)
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

        # Emit the canonical runtime invocation metrics (ADR-008 D8) on the
        # success outcome, alongside the legacy model_runtime_invocation_*
        # counters.
        self._metrics.record_call(name, request.model, status="success")
        self._metrics.record_tokens(
            name, resp.usage.input_tokens, resp.usage.output_tokens
        )
        self._metrics.record_latency(name, latency_ms)
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

    def _bind_provider(
        self, impl: AsyncModelProvider, resolution: CredentialResolution
    ) -> AsyncModelProvider:
        """Return the provider that serves this tenant's call (ADR-008 D5).

        Providers that implement ``bind_credential`` return a client bound to
        the resolved tenant credential; a binding that raises (or returns
        ``None``) FAILS CLOSED with :class:`ModelNotConfigured` so the tenant
        never silently falls back to the process-wide / shared provider.
        Providers with no ``bind_credential`` surface (e.g. the deterministic
        test/local fixture) return the registered instance unchanged — they
        hold no key, so there is no shared credential to leak.

        When the wired credential service can materialize a secret-backend
        credential, the just-in-time materializer is attached to the bound
        provider so a ``secret_backend`` resolution can actually invoke. The
        key is fetched at call time and never passes through the (secret-free)
        resolution metadata, so it can never leak into metrics, logs, or the
        resolution models.
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
        if bound is not impl:
            materializer = self._build_credential_materializer()
            if materializer is not None:
                bound._credential_materializer = materializer  # type: ignore[attr-defined]
        return bound

    def _build_credential_materializer(self):
        """Return a just-in-time secret-backend materializer, or ``None``.

        The materializer is ``(tenant_id, ref) -> str | None`` (sync or async)
        and is handed to the bound provider at dispatch time. It is built from
        the wired credential service:

        * Preferred: the resolver exposes an explicit ``reveal`` /
          ``materialize`` surface (a raw-key fetch that returns the primary
          secret for a tenant/ref).
        * Fallback: the resolver wraps a secret backend whose ``get`` returns a
          structured credential (the ``aws_secrets`` resolver's backend), from
          which the primary secret is extracted.

        Returns ``None`` when no raw surface exists — the bound adapter then
        fails closed for ``secret_backend`` resolutions, never reusing the
        process-wide key.
        """
        cs = self._credential_service
        if cs is None:
            return None
        resolver = getattr(cs, "_resolver", None)
        if resolver is None:
            return None

        for attr in ("reveal", "materialize"):
            fn = getattr(resolver, attr, None)
            if callable(fn):
                return fn

        backend = getattr(resolver, "_backend", None)
        getter = getattr(backend, "get", None)
        if callable(getter):

            async def _materialize(tenant_id: str, ref: str) -> str | None:
                try:
                    cred = await getter(tenant_id, ref)
                except Exception:  # noqa: BLE001 — fail closed on backend errors
                    return None
                return _primary_secret(cred)

            return _materialize
        return None

    @staticmethod
    def _provider_error_type(exc: BaseException) -> str | None:
        """A canonical provider-error label for a raised invocation exception.

        Only genuine provider/transport failures are counted as provider errors
        (``ModelProviderError`` / ``ModelTimeoutError``); anything else is not
        a provider fault and emits no provider-error metric.
        """
        if isinstance(exc, ModelTimeoutError):
            return "timeout"
        if isinstance(exc, ModelProviderError):
            return "provider_error"
        return None

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


def _primary_secret(cred: object) -> str | None:
    """Extract the primary API key from a structured credential, secret-safe.

    Handles ``ApiKeyCredential`` (``api_key`` field) and falls back to the
    first ``SecretStr`` field for other structured shapes. Never logs or
    serializes the value — it is returned straight to the bound adapter.
    """
    from pydantic import SecretStr

    api_key = getattr(cred, "api_key", None)
    if isinstance(api_key, SecretStr):
        return api_key.get_secret_value()
    if isinstance(cred, dict):
        values = cred.values()
    else:
        values = dict(cred).values()
    for value in values:
        if isinstance(value, SecretStr):
            return value.get_secret_value()
    return None
