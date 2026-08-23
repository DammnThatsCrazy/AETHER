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
  select tenant scope from headers, body, or query. Fail-closed: no
  authenticated tenant is HTTP 400.
* The five Kyber admin surfaces (registry, health, entitlements, usage, traces)
  are additionally operator-authorized via :func:`require_operator`, which
  mirrors the repo's ``require_kyber_operator`` gate. Aether tenant-panel
  surfaces (``/models``, ``/tenant-default``) stay tenant-scoped only.
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
health is probed via :class:`RuntimeHealthProbe` over a deterministic seed
provider set, and entitlements use the server-authoritative
:class:`AllowlistEntitlementResolver`. Usage and traces are deterministic seed
data (no metering/trace store is wired into this surface yet); every route that
serves seed data says so in its docstring and returns fail-closed shapes that
match the frontend types exactly.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from services.model_runtime.config import ModelRuntimeSettings
from services.model_runtime.deterministic import DeterministicModelProvider
from services.model_runtime.observability.health import (
    ProviderHealthCheck,
    RuntimeHealth,
    RuntimeHealthProbe,
)
from services.model_runtime.routing.entitlements import AllowlistEntitlementResolver
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

# Non-durable in-memory seed for the per-tenant default model (PUT
# /tenant-default). A real tenant-preference store plugs in here.
_TENANT_DEFAULT_MODELS: dict[str, str] = {
    "tenant-demo": "claude-haiku-4-5-20251001",
}

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


class _UnconfiguredSeedProvider:
    """AsyncModelProvider-shaped seed that reports itself unconfigured."""

    def __init__(self, name: str) -> None:
        self.provider_name = name

    def is_configured(self) -> bool:
        return False


def _seed_providers() -> dict[str, object]:
    """Deterministic provider set for the health seed.

    The local deterministic provider is configured by construction; every
    network-backed registry provider is reported unconfigured (fail-closed) —
    no real adapters are wired into this surface yet.
    """
    providers: dict[str, object] = {"deterministic": DeterministicModelProvider()}
    providers.update(
        {name: _UnconfiguredSeedProvider(name) for name in MODEL_REGISTRY_PROVIDERS}
    )
    return providers


def _build_runtime_health(tenant_id: str) -> RuntimeHealth:
    """Probe provider health for ``tenant_id`` (deterministic seed data).

    Uses the landed :class:`RuntimeHealthProbe`/:class:`ProviderHealthCheck`
    over ``_seed_providers``. This is seed data — the probe slot is where a
    real ModelRuntimeService provider set plugs in.
    """
    probe = RuntimeHealthProbe(ProviderHealthCheck(_seed_providers()))
    return probe.status()


# Deterministic seed allowlist (non-durable, demo tenant only). Unknown tenants
# fail closed: every model is denied with a tenant-safe reason.
_SEED_ENTITLEMENTS: dict[str, set[str]] = {
    "tenant-demo": {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "gpt-4o-mini",
    },
}


async def _build_entitlement_rows(tenant_id: str) -> list[EntitlementRowOut]:
    """Entitlement rows for ``tenant_id`` across every registry model.

    Backed by the server-authoritative :class:`AllowlistEntitlementResolver`
    seeded with ``_SEED_ENTITLEMENTS``; unknown tenants are denied for every
    model with a tenant-safe reason.
    """
    resolver = AllowlistEntitlementResolver(_SEED_ENTITLEMENTS)
    rows: list[EntitlementRowOut] = []
    for entry in MODEL_REGISTRY_MODELS:
        decision = await resolver.assert_model_entitled(tenant_id, str(entry["modelId"]))
        rows.append(
            EntitlementRowOut(
                tenantId=decision.tenant_id,
                modelId=decision.model_id,
                entitled=decision.entitled,
                reason=_sanitize_reason(decision.reason),
            )
        )
    return rows


# Deterministic seed period label; a real metering store will provide actuals.
_SEED_USAGE_PERIOD = "deterministic-seed-period"


def _build_usage(tenant_id: str) -> UsageResponseOut:
    """Usage summary — deterministic seed data (all-zero, fail-closed).

    No metering store is wired into this surface yet, so every registry model
    reports zero calls/tokens/cost. The shape matches the Kyber
    ``UsageResponse`` exactly; rows are the full registry so the contract is
    visible. ``tenant_id`` is reserved for the future tenant-scoped metering
    lookup.
    """
    rows = [
        UsageByModelOut(
            modelId=str(entry["modelId"]),
            calls=0,
            inputTokens=0,
            outputTokens=0,
            costUsd=0.0,
        )
        for entry in MODEL_REGISTRY_MODELS
    ]
    totals = UsageTotalsOut(calls=0, inputTokens=0, outputTokens=0, costUsd=0.0)
    return UsageResponseOut(period=_SEED_USAGE_PERIOD, totals=totals, byModel=rows)


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
    comes from the non-durable in-memory seed (see PUT /tenant-default); an
    unknown tenant gets ``null``. Registry rows are the generated catalog —
    never credentials.
    """
    return ModelListResponseOut(
        models=_registry_models_out(),
        tenantDefaultModel=_TENANT_DEFAULT_MODELS.get(tenant_id),
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
    non-durable in-memory seed only; a real tenant-preference store plugs in
    here. Unknown model ids are rejected (HTTP 400); a model the tenant is not
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
    resolver = AllowlistEntitlementResolver(_SEED_ENTITLEMENTS)
    decision = await resolver.assert_model_entitled(tenant_id, body.modelId)
    if not decision.entitled:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "error",
                "code": "model_not_entitled",
                "message": _sanitize_reason(decision.reason),
            },
        )
    _TENANT_DEFAULT_MODELS[tenant_id] = body.modelId
    return Response(status_code=204)


@router.get(
    "/registry",
    response_model=RegistryResponseOut,
    summary="Model registry",
)
async def get_registry(
    operator: None = Depends(require_operator),
    tenant_id: str = Depends(require_tenant_id),
) -> RegistryResponseOut:
    """GET /v1/model-runtime/registry — the full model catalog.

    Consumed by the Kyber ``ModelRegistryPage`` (C14). Operator-authorized
    (Kyber admin surface). Serves the generated registry projected to the
    frontend shape; no per-tenant data, no credentials.
    """
    return RegistryResponseOut(models=_registry_models_out())


@router.get(
    "/health",
    response_model=HealthResponseOut,
    summary="Provider health summary",
)
async def get_health(
    operator: None = Depends(require_operator),
    tenant_id: str = Depends(require_tenant_id),
) -> HealthResponseOut:
    """GET /v1/model-runtime/health — provider health summary.

    Consumed by the Kyber ``ModelRuntimeHealthPage`` (C14). Operator-authorized
    (Kyber admin surface). Reasons pass through :func:`_sanitize_reason` so
    secret-shaped material is blanked before it can reach the client. Backed by
    ``RuntimeHealthProbe`` over the deterministic seed provider set.
    """
    health = _build_runtime_health(tenant_id)
    return HealthResponseOut(
        status=health.status,
        providers=[
            ProviderHealthOut(
                provider=p.provider,
                configured=p.configured,
                healthy=p.healthy,
                reason=_sanitize_reason(p.reason),
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
    operator: None = Depends(require_operator),
    tenant_id: str = Depends(require_tenant_id),
) -> EntitlementsResponseOut:
    """GET /v1/model-runtime/entitlements — per-model entitlement rows.

    Consumed by the Kyber ``EntitlementsPage`` (C14). Operator-authorized
    (Kyber admin surface). Server-authoritative: rows are resolved by the
    ``AllowlistEntitlementResolver`` for the requesting tenant only; a model can
    never select tenant scope.
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
    tenant_id: str = Depends(require_tenant_id),
) -> UsageResponseOut:
    """GET /v1/model-runtime/usage — aggregate + per-model usage.

    Consumed by the Kyber ``UsagePage`` (C14). Operator-authorized (Kyber admin
    surface). Deterministic seed data (all-zero, fail-closed) until a metering
    store is wired; the shape matches the Kyber ``UsageResponse`` exactly.
    """
    return _build_usage(tenant_id)


@router.get(
    "/traces",
    response_model=TracesResponseOut,
    summary="Routing trace summaries",
)
async def get_traces(
    operator: None = Depends(require_operator),
    tenant_id: str = Depends(require_tenant_id),
) -> TracesResponseOut:
    """GET /v1/model-runtime/traces — routing trace summaries.

    Consumed by the Kyber ``TracesPage`` (C14). Operator-authorized (Kyber admin
    surface). Deterministic seed data, tenant-scoped, and content-free: only
    routing-decision summary fields are ever returned — never request/response
    bodies.
    """
    return TracesResponseOut(traces=_build_traces(tenant_id))


__all__ = [
    "HealthResponseOut",
    "ModelListResponseOut",
    "RegistryResponseOut",
    "TenantDefaultRequest",
    "TracesResponseOut",
    "UsageResponseOut",
    "require_operator",
    "require_tenant_id",
    "router",
]
