"""HTTP routes for the model-runtime control plane (ADR-008 D8/D9).

Surfaces the model-runtime package as an externally-servable HTTP API under
``/v1/model-runtime``. The five Kyber admin surfaces (registry, health,
entitlements, usage, traces) and the two Aether tenant surfaces (model list,
tenant-default) are typed to the landed frontend clients:

* ``frontend/aether/src/features/model-selection/types.ts`` — ``GET
  /v1/model-runtime/models`` + ``PUT /v1/model-runtime/tenant-default``.
* ``frontend/kyber/src/features/model-runtime/types.ts`` — ``GET
  /v1/model-runtime/registry|health|entitlements|usage|traces``.

Security contract (D9):

* Feature-gated OFF by default (``MODEL_RUNTIME_ENABLED=false``). When the gate
  is OFF every route returns HTTP 503 — the surface is inert: it never serves
  data and never leaks response shape.
* Server-authoritative tenant scope: the tenant is derived from the
  authenticated request state (``request.state.tenant``, bound by the auth
  middleware from the verified session — ADR-008). A model/client can never
  select tenant scope from headers, body, or query. The Aether tenant-panel
  surfaces (``/models``, ``/tenant-default``) require an authenticated tenant
  (fail-closed HTTP 400 ``tenant_required``).
* The five Kyber admin surfaces (registry, health, entitlements, usage, traces)
  are operator-authorized via :func:`require_operator`, which mirrors the
  repo's ``require_kyber_operator`` gate. Registry, health and usage are global
  surfaces with no per-tenant data — they need no tenant scope. Entitlements
  and traces carry per-tenant rows, so their scope is derived from the Kyber
  workforce access context when a workforce session is present (a workforce
  actor is intentionally tenantless — ``request.state.tenant`` is never bound
  for it, so the ``tenant_required`` path must not reject it), falling back to
  the legacy tenant binding; a workforce session with no tenant scope fails
  closed (HTTP 403 ``tenant_scope_required``).
* Credential-free: responses are masked/aggregated. Health and entitlement
  reason strings pass through :func:`_sanitize_reason`, which blanks any
  secret-shaped material (``sk-``, ``pk_``, ``rk_live_``, ``whsec_``, ``AKIA``,
  ``Bearer ``/``Authorization:``, ``X-Api-Key:``, ``password=``, ``secret=``,
  ``key=``, ``eyJ``) — the same markers the frontend
  ``EntitlementBadge``/``sanitizeHealthReason`` guards against.
* Routing trace summaries carry routing-decision fields only — never raw
  request/response content.

Backing stores: the model registry is the generated catalog
(``shared.model_governance.generated_model_registry.MODEL_REGISTRY_MODELS``),
health is probed via :class:`RuntimeHealthProbe` over the real provider set
(:mod:`services.model_runtime.providers`; a provider without credentials is
"waiting on credentials"), and tenant model entitlements and usage use the
canonical billing authority. Routing traces remain deterministic seed data;
the endpoint is content-free and tenant-scoped.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from services.model_runtime.config import ModelRuntimeSettings
from services.model_runtime.providers import build_providers, credential_reason
from services.model_runtime.observability.health import (
    ProviderHealthCheck,
    RuntimeHealth,
    RuntimeHealthProbe,
)
from shared.model_governance.generated_model_registry import (
    MODEL_REGISTRY_MODELS,
    MODEL_REGISTRY_PROVIDERS,
)

# ---------------------------------------------------------------------------
# Response / request models — field names mirror the frontend types EXACTLY.
# ---------------------------------------------------------------------------


class RegistryModelOut(BaseModel, frozen=True):
    """One registry entry (Aether ``ModelRegistryModel`` / Kyber ``RegistryModel``)."""

    modelId: str
    provider: str
    status: Literal["recommended", "stable", "beta", "deprecated", "experimental"]
    capabilities: list[str]
    inputCostPerMTok: float
    outputCostPerMTok: float


class ModelListResponseOut(BaseModel, frozen=True):
    """GET /v1/model-runtime/models — Aether ``ModelListResponse``."""

    models: list[RegistryModelOut]
    tenantDefaultModel: str | None = None


class RegistryResponseOut(BaseModel, frozen=True):
    """GET /v1/model-runtime/registry — Kyber ``RegistryResponse``."""

    models: list[RegistryModelOut]


class ProviderHealthOut(BaseModel, frozen=True):
    """Per-provider health snapshot (Kyber ``ProviderHealth``)."""

    provider: str
    configured: bool
    healthy: bool
    reason: str


class HealthResponseOut(BaseModel, frozen=True):
    """GET /v1/model-runtime/health — Kyber ``HealthResponse``."""

    status: Literal["ok", "degraded", "unhealthy"]
    providers: list[ProviderHealthOut]
    checks: dict[str, bool]


class EntitlementRowOut(BaseModel, frozen=True):
    """One tenant/model entitlement row (Kyber ``EntitlementRow``)."""

    tenantId: str
    modelId: str
    entitled: bool
    reason: str | None = None


class EntitlementsResponseOut(BaseModel, frozen=True):
    """GET /v1/model-runtime/entitlements — Kyber ``EntitlementsResponse``."""

    entitlements: list[EntitlementRowOut]


class UsageTotalsOut(BaseModel, frozen=True):
    """Aggregate usage totals (Kyber ``UsageTotals``)."""

    calls: int
    inputTokens: int
    outputTokens: int
    costUsd: float


class UsageByModelOut(UsageTotalsOut):
    """Per-model usage row (Kyber ``UsageByModel``)."""

    modelId: str


class UsageResponseOut(BaseModel, frozen=True):
    """GET /v1/model-runtime/usage — Kyber ``UsageResponse``."""

    period: str
    totals: UsageTotalsOut
    byModel: list[UsageByModelOut]


class RoutingTraceOut(BaseModel, frozen=True):
    """Routing decision summary — never raw request/response content."""

    traceId: str
    correlationId: str | None = None
    tenantId: str
    profileId: str
    requestedModel: str | None = None
    selectedModel: str
    mode: str
    entitled: bool
    fallback: bool
    status: str
    latencyMs: float
    createdAt: str


class TracesResponseOut(BaseModel, frozen=True):
    """GET /v1/model-runtime/traces — Kyber ``TracesResponse``."""

    traces: list[RoutingTraceOut]


class TenantDefaultRequest(BaseModel):
    """PUT /v1/model-runtime/tenant-default body — Aether ``setTenantDefault``."""

    model_config = ConfigDict(extra="forbid")

    modelId: str


class TenantCompletionRequest(BaseModel):
    """Tenant-scoped provider-neutral model invocation."""
    model_config = ConfigDict(extra="forbid")
    modelId: str
    messages: list[dict[str, str]]
    systemPrompt: str | None = None
    maxTokens: int | None = None
    temperature: float | None = None


class TenantCompletionResponse(BaseModel, frozen=True):
    modelId: str
    provider: str
    content: str
    inputTokens: int
    outputTokens: int
    totalTokens: int
    latencyMs: float


async def _tenant_model_entitlement(tenant_id: str, model_id: str) -> dict:
    """Resolve a model-specific entitlement from billing, failing closed."""
    from services.billing.revops import TenantEntitlementRepository

    rows = await TenantEntitlementRepository().list_for_tenant(tenant_id)
    keys = {f"model_runtime.model:{model_id}", "model_runtime.enabled"}
    enabled = {str(row.get("feature_key")) for row in rows if row.get("enabled") is True}
    if "model_runtime.enabled" not in enabled or f"model_runtime.model:{model_id}" not in enabled:
        raise HTTPException(status_code=403, detail={"code": "model_not_entitled"})
    return {row.get("feature_key"): row for row in rows if row.get("feature_key") in keys}


async def _reserve_model_token_budget(tenant_id: str, request_id: str, estimated_tokens: int) -> None:
    """Reserve against the durable, transaction-serialized tenant token budget."""
    from services.model_runtime.tenant_state import reserve_token_budget

    if not await reserve_token_budget(tenant_id, request_id, estimated_tokens):
        raise HTTPException(status_code=429, detail={"code": "model_token_budget_exceeded"})


async def _record_model_usage(tenant_id: str, model_id: str, provider: str, input_tokens: int, output_tokens: int) -> None:
    from services.billing.revops import MeteringService, UsageMeteringEvent

    total = max(0, int(input_tokens)) + max(0, int(output_tokens))
    await MeteringService().record_event(UsageMeteringEvent(
        tenant_id=tenant_id,
        event_type="model_runtime_token_usage",
        quantity=total,
        source_type="model_runtime_invocation",
        source_id=f"{tenant_id}:{uuid4().hex}",
        metadata={"model_id": model_id, "provider": provider,
                  "input_tokens": max(0, int(input_tokens)),
                  "output_tokens": max(0, int(output_tokens)),
                  "total_tokens": total},
    ))


# ---------------------------------------------------------------------------
# D9 feature gate + server-authoritative tenant scope.
# ---------------------------------------------------------------------------


def _model_runtime_enabled() -> bool:
    """D9 feature gate — ``MODEL_RUNTIME_ENABLED``, default OFF. Fail-closed.

    Any configuration error while reading settings resolves to OFF so the
    surface can never accidentally serve.
    """
    try:
        return bool(ModelRuntimeSettings().enabled)
    except Exception:
        return False


def _gate_guard() -> None:
    """FastAPI dependency: HTTP 503 (fail-closed) while the gate is OFF.

    Every route carries this dependency; a disabled surface is inert and never
    serves data.
    """
    if not _model_runtime_enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "status": "disabled",
                "code": "model_runtime_disabled",
                "message": "model-runtime HTTP surface is disabled "
                "(MODEL_RUNTIME_ENABLED=false)",
            },
        )


def require_tenant_id(request: Request) -> str:
    """Resolve the server-authoritative tenant scope from authenticated state.

    The auth middleware binds ``request.state.tenant`` from the verified
    session; this dependency reads that tenant id and nothing else. The gate
    guard runs first so a disabled surface 503s even without a tenant identity;
    an enabled surface with no authenticated tenant is rejected (HTTP 400,
    fail-closed). A model/client can never select tenant scope via headers,
    body, or query.
    """
    _gate_guard()
    tenant = getattr(request.state, "tenant", None)
    tenant_id = getattr(tenant, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "code": "tenant_required",
                "message": "authenticated tenant context is required",
            },
        )
    return tenant_id


def require_operator(request: Request) -> None:
    """FastAPI dependency: Kyber operator gate for the admin surfaces.

    Mirrors the repo's ``require_kyber_operator`` gate (services/security/
    request_context.py) so the five operator surfaces are authorized exactly
    like the rest of the Kyber plane. AetherError is mapped to HTTP 401/403 so
    this surface is self-contained — both the isolated-router tests and the
    full app receive a proper status code. Fail-closed: any non-operator (or
    unauthenticated) caller is denied.
    """
    from services.security.request_context import require_kyber_operator
    from shared.common.common import ForbiddenError, UnauthorizedError

    try:
        require_kyber_operator(request)
    except UnauthorizedError:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "operator_required",
                "message": "Kyber operator authentication required",
            },
        )
    except ForbiddenError:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "error",
                "code": "operator_required",
                "message": "Kyber operator access required",
            },
        )


def require_operator_tenant_scope(request: Request) -> str:
    """Combined Kyber-operator + tenant-scope gate for the tenant-scoped admin
    surfaces (``/entitlements``, ``/traces``).

    Runs :func:`require_operator` first, then resolves the server-authoritative
    tenant scope without ever rejecting a valid workforce session for lacking
    ``request.state.tenant``:

    * a Kyber **workforce session** is authoritative when one is present — the
      tenant scope is read from the resolved access context (a workforce actor
      is intentionally tenantless, so ``request.state.tenant`` is never bound
      for it). A workforce session whose access context carries no tenant scope
      fails closed (HTTP 403): a per-tenant surface cannot serve without one;
    * otherwise the **legacy** operator path reads ``request.state.tenant``
      exactly as before (HTTP 400 ``tenant_required`` when absent).
    """
    from services.security.request_context import kyber_access_context

    require_operator(request)

    # A workforce session is authoritative for the tenant scope when its access
    # context carries one. A stale/empty context is NOT treated as a denial —
    # the legacy tenant binding below still wins so a legacy operator is never
    # rejected by an unrelated workforce context.
    ctx = kyber_access_context(request)
    if ctx is not None:
        tenant_id = getattr(ctx, "tenant_id", None)
        if tenant_id:
            return str(tenant_id)
        scope = getattr(ctx, "scope", None)
        scope_tenant = getattr(scope, "tenant_id", None)
        if scope_tenant:
            return str(scope_tenant)

    # Legacy operator path — the tenant binding is authoritative.
    tenant = getattr(request.state, "tenant", None)
    tenant_id = getattr(tenant, "tenant_id", None)
    if tenant_id:
        return tenant_id

    # A workforce session with no tenant scope (and no legacy binding) cannot
    # serve a per-tenant surface — fail closed with a scope error, never the
    # bogus tenant_required that used to reject tenantless workforce operators.
    if ctx is not None:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "error",
                "code": "tenant_scope_required",
                "message": "no active Kyber tenant access scope for this surface",
            },
        )
    raise HTTPException(
        status_code=400,
        detail={
            "status": "error",
            "code": "tenant_required",
            "message": "authenticated tenant context is required",
        },
    )


# ---------------------------------------------------------------------------
# Secret sanitization — mirrors EntitlementBadge / sanitizeHealthReason.
# ---------------------------------------------------------------------------

_GENERIC_REASON = "Details unavailable."

# Secret-shaped markers, matched case-insensitively. Anything matching is
# blanked before it can reach the client (defense-in-depth on top of the
# fail-closed seed data).
_SECRET_MARKERS: tuple[str, ...] = (
    "sk-",
    "pk_",
    "rk_live_",
    "whsec_",
    "AKIA",
    "Bearer ",
    "Authorization:",
    "X-Api-Key:",
    "password=",
    "secret=",
    "key=",
    "eyJ",
)


def _sanitize_reason(value: str | None) -> str:
    """Blank secret-shaped reason material before it can reach the client."""
    if not value or not value.strip():
        return _GENERIC_REASON
    lowered = value.lower()
    if any(marker.lower() in lowered for marker in _SECRET_MARKERS):
        return _GENERIC_REASON
    return value


# ---------------------------------------------------------------------------
# Deterministic seed data — clearly marked; a real store plugs in later.
# ---------------------------------------------------------------------------

# Registry model ids, precomputed for fail-closed validation.
_REGISTRY_MODEL_IDS: frozenset[str] = frozenset(
    str(entry["modelId"]) for entry in MODEL_REGISTRY_MODELS
)


def _registry_models_out() -> list[RegistryModelOut]:
    """Project the generated model catalog onto the frontend contract shape."""
    return [
        RegistryModelOut(
            modelId=str(entry["modelId"]),
            provider=str(entry["provider"]),
            status=str(entry["status"]),
            capabilities=list(entry["capabilities"]),
            inputCostPerMTok=float(entry["inputCostPerMTok"]),
            outputCostPerMTok=float(entry["outputCostPerMTok"]),
        )
        for entry in MODEL_REGISTRY_MODELS
    ]


class _NoAdapterProvider:
    """AsyncModelProvider-shaped placeholder for a registry provider with no adapter yet."""

    def __init__(self, name: str) -> None:
        self.provider_name = name

    def is_configured(self) -> bool:
        return False


def _provider_set() -> dict[str, object]:
    """The provider set the health surface reports on.

    Every provider with a transport adapter is the real adapter (see
    :mod:`services.model_runtime.providers`): configured exactly when its credentials
    are present, otherwise waiting on them. A registry provider with no adapter at all is
    reported as such.
    """
    providers: dict[str, object] = dict(build_providers())
    for name in MODEL_REGISTRY_PROVIDERS:
        providers.setdefault(name, _NoAdapterProvider(name))
    return providers


def _health_reason(health: object) -> str:
    """Reason text for one provider.

    The probe's two standard reasons ("configured" / "not configured") are replaced by
    the credential wording naming the variables that unlock the provider; any other
    probe reason passes through unchanged so it is still sanitized.
    """
    reason = getattr(health, "reason", "")
    if reason in ("configured", "not configured"):
        return credential_reason(health.provider, health.configured)
    return reason


def _build_runtime_health() -> RuntimeHealth:
    """Probe provider health over the real provider set.

    Uses the landed :class:`RuntimeHealthProbe`/:class:`ProviderHealthCheck` over
    :func:`_provider_set`. Health is a global Kyber admin surface: it carries no
    per-tenant data, so it needs no tenant scope.
    """
    probe = RuntimeHealthProbe(ProviderHealthCheck(_provider_set()))
    return probe.status()


async def _build_entitlement_rows(tenant_id: str) -> list[EntitlementRowOut]:
    """Entitlement rows for ``tenant_id`` across every registry model.

    Backed by tenant model entitlement rows in the billing authority; absent
    or disabled rows deny a model.
    """
    from services.billing.revops import TenantEntitlementRepository

    rows_by_key = {
        str(row.get("feature_key")): row
        for row in await TenantEntitlementRepository().list_for_tenant(tenant_id)
    }
    rows: list[EntitlementRowOut] = []
    for entry in MODEL_REGISTRY_MODELS:
        model_id = str(entry["modelId"])
        row = rows_by_key.get(f"model_runtime.model:{model_id}")
        enabled = bool(row and row.get("enabled") is True)
        rows.append(
            EntitlementRowOut(
                tenantId=tenant_id,
                modelId=model_id,
                entitled=enabled,
                reason=None if enabled else "Model is not entitled for this tenant.",
            )
        )
    return rows


# Deterministic seed period label; a real metering store will provide actuals.
async def _build_usage() -> UsageResponseOut:
    """Current-month durable usage from the canonical billing meter."""
    from services.billing.revops import UsageMeteringEventRepository

    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    repo = UsageMeteringEventRepository()
    events = await repo.find_many(limit=10000)
    if len(events) >= 10000:
        raise HTTPException(status_code=503, detail={"code": "model_usage_window_incomplete"})
    by_model: dict[str, dict[str, float]] = {}
    for event in events:
        if event.get("event_type") != "model_runtime_token_usage":
            continue
        try:
            occurred = datetime.fromisoformat(str(event.get("occurred_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if not start <= occurred <= now:
            continue
        metadata = event.get("metadata") or {}
        model_id = str(metadata.get("model_id") or "")
        values = by_model.setdefault(model_id, {"calls": 0, "input": 0, "output": 0, "cost": 0.0})
        values["calls"] += 1
        values["input"] += int(metadata.get("input_tokens") or 0)
        values["output"] += int(metadata.get("output_tokens") or 0)

    catalog = {str(entry["modelId"]): entry for entry in MODEL_REGISTRY_MODELS}
    for model_id, values in by_model.items():
        model = catalog.get(model_id)
        if model:
            values["cost"] = (
                values["input"] * float(model["inputCostPerMTok"])
                + values["output"] * float(model["outputCostPerMTok"])
            ) / 1_000_000
    rows = [UsageByModelOut(
        modelId=model_id,
        calls=int(values["calls"]),
        inputTokens=int(values["input"]),
        outputTokens=int(values["output"]),
        costUsd=values["cost"],
    ) for model_id, values in sorted(by_model.items())]
    totals = UsageTotalsOut(
        calls=sum(row.calls for row in rows),
        inputTokens=sum(row.inputTokens for row in rows),
        outputTokens=sum(row.outputTokens for row in rows),
        costUsd=sum(row.costUsd for row in rows),
    )
    return UsageResponseOut(period=start.strftime("%Y-%m"), totals=totals, byModel=rows)


def _build_traces(tenant_id: str) -> list[RoutingTraceOut]:
    """Routing trace summaries for ``tenant_id`` — deterministic seed data.

    Tenant-scoped: every trace carries the requesting tenant's id; no
    cross-tenant rows and no request/response content ever appear.
    """
    return [
        RoutingTraceOut(
            traceId="seed-trace-0001",
            correlationId=None,
            tenantId=tenant_id,
            profileId="default",
            requestedModel=None,
            selectedModel="claude-haiku-4-5-20251001",
            mode="auto",
            entitled=True,
            fallback=False,
            status="success",
            latencyMs=1.0,
            createdAt="2026-08-08T00:00:00Z",
        ),
        RoutingTraceOut(
            traceId="seed-trace-0002",
            correlationId=None,
            tenantId=tenant_id,
            profileId="analysis",
            requestedModel="gpt-4o",
            selectedModel="gpt-4o-mini",
            mode="auto",
            entitled=True,
            fallback=True,
            status="fallback",
            latencyMs=2.0,
            createdAt="2026-08-08T00:00:01Z",
        ),
    ]


# ---------------------------------------------------------------------------
# Router + routes. Prefix yields the exact frontend contract paths.
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/v1/model-runtime",
    tags=["model-runtime"],
    dependencies=[Depends(_gate_guard)],
)


@router.get(
    "/models",
    response_model=ModelListResponseOut,
    summary="Tenant model registry",
)
async def get_models(tenant_id: str = Depends(require_tenant_id)) -> ModelListResponseOut:
    """GET /v1/model-runtime/models — the model registry + tenant default.

    Consumed by the Aether ``ModelSelectionPanel`` (C13). ``tenantDefaultModel``
    comes from the durable tenant preference repository; an unconfigured tenant
    gets ``null``. Registry rows are the generated catalog —
    never credentials.
    """
    from services.model_runtime.tenant_state import TenantModelPreferenceRepository
    default_model = await TenantModelPreferenceRepository().get_default(tenant_id)
    return ModelListResponseOut(
        models=_registry_models_out(),
        tenantDefaultModel=default_model,
    )


@router.post("/complete", response_model=TenantCompletionResponse, summary="Tenant model completion")
async def complete_for_tenant(
    body: TenantCompletionRequest,
    tenant_id: str = Depends(require_tenant_id),
) -> TenantCompletionResponse:
    """Invoke an entitled provider with a durable token allowance and usage record."""
    entry = next((row for row in MODEL_REGISTRY_MODELS
                  if str(row["modelId"]) == body.modelId), None)
    if entry is None:
        raise HTTPException(status_code=400, detail={"code": "unknown_model"})
    await _tenant_model_entitlement(tenant_id, body.modelId)
    prompt_chars = sum(len(message.get("content", "")) for message in body.messages)
    prompt_chars += len(body.systemPrompt or "")
    # Reserve an input estimate plus the full output ceiling so the tenant's
    # maximum response size is included before any provider request is sent.
    estimate = max(1, prompt_chars) + max(1, int(body.maxTokens or 800))
    request_id = uuid4().hex
    await _reserve_model_token_budget(tenant_id, request_id, estimate)

    from services.model_runtime.models import ModelRequest
    from services.model_runtime.providers import get_runtime

    try:
        result = await get_runtime().complete(
            tenant_id,
            ModelRequest(
                model=body.modelId,
                messages=body.messages,
                system_prompt=body.systemPrompt,
                max_tokens=body.maxTokens,
                temperature=body.temperature,
            ),
            provider=str(entry["provider"]),
        )
    except asyncio.CancelledError:
        from services.model_runtime.tenant_state import settle_token_budget
        await settle_token_budget(tenant_id, request_id, 0, release=True)
        raise
    except Exception as exc:
        from services.model_runtime.tenant_state import settle_token_budget
        await settle_token_budget(tenant_id, request_id, 0, release=True)
        # Provider messages can contain credentials or request material.
        from services.model_runtime.models import ModelBudgetExceeded, ModelNotConfigured
        if isinstance(exc, ModelBudgetExceeded):
            raise HTTPException(status_code=429, detail={"code": "model_token_budget_exceeded"}) from None
        if isinstance(exc, ModelNotConfigured):
            raise HTTPException(status_code=503, detail={"code": "model_provider_unavailable"}) from None
        raise HTTPException(status_code=502, detail={"code": "model_invocation_failed"}) from None

    try:
        await _record_model_usage(
            tenant_id, body.modelId, str(entry["provider"]),
            result.usage.input_tokens, result.usage.output_tokens,
        )
    except Exception:
        # Keep the reservation charged if durable metering fails. This prevents
        # retries from escaping the tenant's budget without billing evidence.
        raise HTTPException(status_code=503, detail={"code": "model_usage_write_failed"}) from None
    from services.model_runtime.tenant_state import settle_token_budget
    await settle_token_budget(
        tenant_id, request_id,
        max(0, int(result.usage.input_tokens)) + max(0, int(result.usage.output_tokens)),
    )
    return TenantCompletionResponse(
        modelId=body.modelId,
        provider=str(result.provider.value if hasattr(result.provider, "value") else result.provider),
        content=result.content,
        inputTokens=result.usage.input_tokens,
        outputTokens=result.usage.output_tokens,
        totalTokens=result.usage.total_tokens,
        latencyMs=result.latency_ms,
    )


@router.put(
    "/tenant-default",
    status_code=204,
    summary="Set the tenant default model",
)
async def set_tenant_default(
    body: TenantDefaultRequest,
    tenant_id: str = Depends(require_tenant_id),
) -> Response:
    """PUT /v1/model-runtime/tenant-default — set the tenant's default model.

    Consumed by the Aether ``ModelSelectionPanel`` (C13). Persists to the
    durable tenant preference repository. Unknown model ids are rejected (HTTP 400); a model the tenant is not
    entitled to is rejected with HTTP 403 (the server-authoritative boundary the
    Aether client detects as "tenant not entitled to model selection").
    """
    if body.modelId not in _REGISTRY_MODEL_IDS:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "code": "unknown_model",
                "message": f"unknown model id: {body.modelId}",
            },
        )
    await _tenant_model_entitlement(tenant_id, body.modelId)
    from services.model_runtime.tenant_state import TenantModelPreferenceRepository
    await TenantModelPreferenceRepository().set_default(tenant_id, body.modelId)
    return Response(status_code=204)


@router.get(
    "/registry",
    response_model=RegistryResponseOut,
    summary="Model registry",
)
async def get_registry(
    operator: None = Depends(require_operator),
) -> RegistryResponseOut:
    """GET /v1/model-runtime/registry — the full model catalog.

    Consumed by the Kyber ``ModelRegistryPage`` (C14). Operator-authorized
    (Kyber admin surface). Global surface: serves the generated registry
    projected to the frontend shape; no per-tenant data, so no tenant scope is
    required — a workforce operator with no ``request.state.tenant`` is served.
    """
    return RegistryResponseOut(models=_registry_models_out())


@router.get(
    "/health",
    response_model=HealthResponseOut,
    summary="Provider health summary",
)
async def get_health(
    operator: None = Depends(require_operator),
) -> HealthResponseOut:
    """GET /v1/model-runtime/health — provider health summary.

    Consumed by the Kyber ``ModelRuntimeHealthPage`` (C14). Operator-authorized
    (Kyber admin surface). Global surface: carries no per-tenant data, so no
    tenant scope is required. Reasons pass through :func:`_sanitize_reason` so
    secret-shaped material is blanked before it can reach the client. Backed by
    ``RuntimeHealthProbe`` over the real provider set; a provider without
    credentials reports ``waiting on credentials`` and the variables that unlock it.
    """
    health = _build_runtime_health()
    return HealthResponseOut(
        status=health.status,
        providers=[
            ProviderHealthOut(
                provider=p.provider,
                configured=p.configured,
                healthy=p.healthy,
                reason=_sanitize_reason(_health_reason(p)),
            )
            for p in health.providers
        ],
        checks=dict(health.checks),
    )


@router.get(
    "/entitlements",
    response_model=EntitlementsResponseOut,
    summary="Per-model entitlements",
)
async def get_entitlements(
    tenant_id: str = Depends(require_operator_tenant_scope),
) -> EntitlementsResponseOut:
    """GET /v1/model-runtime/entitlements — per-model entitlement rows.

    Consumed by the Kyber ``EntitlementsPage`` (C14). Operator-authorized
    (Kyber admin surface). Server-authoritative: rows are resolved by the
    ``AllowlistEntitlementResolver`` for the tenant scope derived by
    :func:`require_operator_tenant_scope` — the workforce access context when a
    workforce session is present (tenantless actors never hit
    ``tenant_required``), else the legacy tenant binding; a model can never
    select tenant scope.
    """
    return EntitlementsResponseOut(
        entitlements=await _build_entitlement_rows(tenant_id)
    )


@router.get(
    "/usage",
    response_model=UsageResponseOut,
    summary="Usage totals by model",
)
async def get_usage(
    operator: None = Depends(require_operator),
) -> UsageResponseOut:
    """GET /v1/model-runtime/usage — aggregate + per-model usage.

    Consumed by the Kyber ``UsagePage`` (C14). Operator-authorized (Kyber admin
    surface). Global surface: current-month durable billing usage, aggregated
    without tenant identifiers. The shape matches the Kyber ``UsageResponse``.
    """
    return await _build_usage()


@router.get(
    "/traces",
    response_model=TracesResponseOut,
    summary="Routing trace summaries",
)
async def get_traces(
    tenant_id: str = Depends(require_operator_tenant_scope),
) -> TracesResponseOut:
    """GET /v1/model-runtime/traces — routing trace summaries.

    Consumed by the Kyber ``TracesPage`` (C14). Operator-authorized (Kyber admin
    surface). Deterministic seed data, scoped to the tenant derived by
    :func:`require_operator_tenant_scope` (workforce access context or legacy
    binding), and content-free: only routing-decision summary fields are ever
    returned — never request/response bodies.
    """
    return TracesResponseOut(traces=_build_traces(tenant_id))


__all__ = [
    "HealthResponseOut",
    "ModelListResponseOut",
    "RegistryResponseOut",
    "TenantDefaultRequest",
    "TenantCompletionRequest",
    "TenantCompletionResponse",
    "TracesResponseOut",
    "UsageResponseOut",
    "require_operator",
    "require_operator_tenant_scope",
    "require_tenant_id",
    "router",
]
