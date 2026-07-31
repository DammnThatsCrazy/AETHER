"""
Aether Backend — Middleware Stack

Layered request processing in this order:
    1. Lifecycle (correlation ID, tracing, timing)
    2. Body size check (POST/PUT/PATCH only)
    3. Auth (API key or JWT)        — sets request.state.tenant
    4. Burst RPM (per-plan)         — 429 with Retry-After
    5. Feature gate (per-plan)      — 403 with upgrade message
    6. Monthly quota (meters only)  — sets X-Quota-* headers
    7. Extraction Defense Mesh      — ML routes only (unchanged)
    8. Route handler

Public paths (health, docs) bypass everything from step 3 onward.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from shared.common.common import AetherError, UnauthorizedError, problem_dict, problem_response
from shared.context.request_context import (
    CORRELATION_HEADER,
    LEGACY_REQUEST_ID_HEADER,
    context_from_request,
)
from shared.auth.auth import (
    APIKeyTier, APIKeyValidator, JWTHandler, PlanTier, Role, TenantContext,
    legacy_tier_to_plan,
)
from shared.logger.logger import get_logger, set_request_context, metrics
from shared.plans.catalog import PLAN_CATALOG
from shared.rate_limit.feature_gate import (
    PUBLIC_PATHS as _GATE_PUBLIC_PATHS,
    PUBLIC_PATH_PREFIXES as _GATE_PUBLIC_PATH_PREFIXES,
)
from config.settings import settings
from dependencies.providers import get_registry

logger = get_logger("aether.middleware")

# ---------------------------------------------------------------------------
# Extraction defense — lazy import to avoid hard dependency
# ---------------------------------------------------------------------------
_defense_layer = None


def _get_backend_defense_layer():
    """Lazy-init the extraction defense layer for backend ML routes."""
    global _defense_layer
    if _defense_layer is not None:
        return _defense_layer
    if not settings.extraction_defense.enabled:
        return None
    try:
        from security.model_extraction_defense import ExtractionDefenseLayer
        _defense_layer = ExtractionDefenseLayer.from_env()
        logger.info("Backend extraction defense layer loaded")
    except ImportError:
        logger.debug("Extraction defense module not available at backend — skipping")
        _defense_layer = None
    return _defense_layer


# ---------------------------------------------------------------------------
# Extraction Defense Mesh — lazy-init components
# ---------------------------------------------------------------------------
_mesh_budget_engine = None
_mesh_expectation_engine = None
_mesh_scorer = None
_mesh_policy_engine = None
_mesh_attribution = None
_mesh_initialized = False
_mesh_init_lock = threading.Lock()


def _init_extraction_mesh():
    """Lazy-init the extraction defense mesh components (thread-safe)."""
    global _mesh_budget_engine, _mesh_expectation_engine, _mesh_scorer
    global _mesh_policy_engine, _mesh_attribution, _mesh_initialized

    if _mesh_initialized:
        return

    with _mesh_init_lock:
        if _mesh_initialized:
            return
        _mesh_initialized = True

    if not settings.extraction_mesh.enabled:
        return

    try:
        from shared.rate_limit.distributed_budget import DistributedBudgetEngine
        from services.expectations.extraction_expectations import ExtractionExpectationEngine
        from shared.scoring.extraction_score import ExtractionRiskScorer
        from shared.scoring.extraction_policy import ExtractionPolicyEngine
        from services.intelligence.extraction_attribution import ExtractionAttributionService

        _mesh_budget_engine = DistributedBudgetEngine()
        _mesh_expectation_engine = ExtractionExpectationEngine()
        _mesh_scorer = ExtractionRiskScorer()
        _mesh_policy_engine = ExtractionPolicyEngine(
            privileged_tenants=set(settings.extraction_mesh.privileged_tenants),
            privileged_api_keys=set(settings.extraction_mesh.privileged_api_keys),
        )
        _mesh_attribution = ExtractionAttributionService(
            canary_secret=settings.extraction_mesh.canary_secret_seed,
        )
        logger.info("Extraction Defense Mesh initialized")
    except Exception as e:
        logger.warning(f"Extraction Defense Mesh init failed: {e}")


def _get_mesh_components():
    """Return mesh components tuple, initializing if needed."""
    if not _mesh_initialized:
        _init_extraction_mesh()
    return (
        _mesh_budget_engine,
        _mesh_expectation_engine,
        _mesh_scorer,
        _mesh_policy_engine,
        _mesh_attribution,
    )


# ---------------------------------------------------------------------------
# Extraction defense mode resolution
#
# Protected ML prediction routes ("/v1/ml/predict*") are guarded by either the
# Extraction Defense Mesh (preferred) or the legacy ExtractionDefenseLayer.
# Resolving an explicit mode makes the "mesh, else legacy, else fail-closed"
# policy observable and correct, instead of depending on branch ordering.
# Historically an ``if``/``elif`` pair tested the same path predicate, so the
# legacy fallback was dead code and disabling the (default-off) mesh left the
# route entirely unprotected.
# ---------------------------------------------------------------------------
EXTRACTION_MODE_MESH = "mesh_active"
EXTRACTION_MODE_LEGACY = "legacy_active"
EXTRACTION_MODE_MESH_WITH_LEGACY_FALLBACK = "mesh_with_legacy_fallback"
EXTRACTION_MODE_FAIL_CLOSED = "degraded_fail_closed"
EXTRACTION_MODE_DISABLED = "disabled_by_profile"

_PROTECTED_ML_PREFIX = "/v1/ml/predict"


def _mesh_available() -> bool:
    """True when the Extraction Defense Mesh is enabled and initialized."""
    if not settings.extraction_mesh.enabled:
        return False
    return _get_mesh_components()[0] is not None


def _legacy_defense_available() -> bool:
    """True when the legacy extraction defense layer is enabled and loadable."""
    return _get_backend_defense_layer() is not None


def _extraction_defense_required() -> bool:
    """True when a protected ML route must fail closed if no defense is available.

    Reads the settings singleton through the module attribute at call time
    rather than the import-time binding: several test suites reload
    config.settings, which replaces the singleton, and a resolver holding the
    stale object would answer from configuration nothing else can see. In a
    process that never reloads (production) the two are identical.
    """
    import config.settings as _config_settings

    return _config_settings.settings.extraction_defense.require_defense


def resolve_extraction_defense_mode() -> str:
    """Resolve the active extraction-defense enforcement mode for protected ML routes.

    Precedence: mesh (with legacy standby) > mesh > legacy > fail-closed (when
    required) > disabled. The returned value is stored on ``request.state`` and
    surfaced to operator diagnostics via :func:`get_extraction_defense_status`.
    """
    mesh = _mesh_available()
    legacy = _legacy_defense_available()
    if mesh and legacy:
        return EXTRACTION_MODE_MESH_WITH_LEGACY_FALLBACK
    if mesh:
        return EXTRACTION_MODE_MESH
    if legacy:
        return EXTRACTION_MODE_LEGACY
    if _extraction_defense_required():
        return EXTRACTION_MODE_FAIL_CLOSED
    return EXTRACTION_MODE_DISABLED


def get_extraction_defense_status() -> dict:
    """Operator diagnostics: the resolved gateway extraction-defense posture."""
    return {
        "mode": resolve_extraction_defense_mode(),
        "mesh_enabled": settings.extraction_mesh.enabled,
        "mesh_available": _mesh_available(),
        "legacy_enabled": settings.extraction_defense.enabled,
        "legacy_available": _legacy_defense_available(),
        "fail_closed_required": _extraction_defense_required(),
        "protected_prefix": _PROTECTED_ML_PREFIX,
    }


async def _apply_legacy_extraction_defense(
    request: Request, api_key: str, request_id: str
) -> Optional[JSONResponse]:
    """Legacy extraction defense for protected ML routes.

    Returns a block response when the request should be denied, otherwise None
    (and records the assessed risk on ``request.state``).
    """
    defense = _get_backend_defense_layer()
    if defense is None:
        return None

    ip_address = request.client.host if request.client else "0.0.0.0"
    features: dict = {}
    body: dict = {}
    batch_size = 1
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes) if body_bytes else {}
        features = body.get("features", {})
        entities = body.get("entities", [])
        if entities:
            batch_size = len(entities)
            features = entities[0] if entities else {}
    except (json.JSONDecodeError, IndexError, TypeError):
        pass

    pre_result = defense.pre_request(
        api_key=api_key,
        ip_address=ip_address,
        features=features,
        model_name=body.get("model_name", ""),
        batch_size=batch_size,
    )
    if pre_result.blocked:
        status = (
            429 if "rate limit" in pre_result.block_reason.lower() else 403
        )
        metrics.increment("extraction_defense_blocked")
        headers = {}
        if pre_result.retry_after_seconds:
            headers["Retry-After"] = str(pre_result.retry_after_seconds)
        return problem_response(
            status,
            "Request Blocked",
            pre_result.block_reason,
            code="EXTRACTION_DEFENSE_BLOCKED",
            retryable=status == 429,
            request_id=request_id,
            headers=headers,
        )
    request.state.extraction_risk = (
        pre_result.risk_assessment.risk_score
        if pre_result.risk_assessment
        else 0.0
    )
    return None


# Paths that skip auth and all rate limiting / gating layers.
# Sourced from the feature_gate constant so both layers stay consistent,
# with /v1/metrics included (internal scrape endpoint).
_PUBLIC_PATHS = set(_GATE_PUBLIC_PATHS) | {"/v1/metrics"}


def _is_public_path(path: str) -> bool:
    """True if the path is exact-matched in PUBLIC_PATHS or prefix-matched in PUBLIC_PATH_PREFIXES."""
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _GATE_PUBLIC_PATH_PREFIXES)


def _resolve_plan_tier(context: TenantContext) -> PlanTier:
    """Pick the PlanTier for a tenant context.

    Prefers the explicit plan_tier set during auth, falling back to a
    legacy APIKeyTier mapping, and finally P1 for unknown values.
    """
    plan = getattr(context, "plan_tier", None)
    if isinstance(plan, PlanTier):
        return plan
    legacy = getattr(context, "api_key_tier", None)
    if isinstance(legacy, APIKeyTier):
        return legacy_tier_to_plan(legacy)
    return PlanTier.P1_HOBBYIST


# ---------------------------------------------------------------------------
# Security response headers
#
# Deliberately a MINIMAL, low-risk subset. The CSP carries `frame-ancestors`
# only (clickjacking) — `script-src`/`style-src` are NOT set here because a
# wrong directive silently breaks the frontend bundle in production; that
# audit is a separate change.
#
# Two hard constraints encoded below:
#   * Permissions-Policy must NOT deny `publickey-credentials-get` — Kyber's
#     WebAuthn device trust depends on it, and denying it silently breaks
#     enrollment and step-up.
#   * No `X-Frame-Options` (redundant with, and able to conflict with,
#     `frame-ancestors`) and no `Cross-Origin-*` isolation headers (they break
#     third-party embeds and SDK flows).
# ---------------------------------------------------------------------------

SECURITY_CSP = "frame-ancestors 'none'"
SECURITY_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURITY_PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
)
SECURITY_HSTS = "max-age=31536000; includeSubDomains"


def _apply_security_headers(response: Response, *, is_production: bool) -> Response:
    """Attach the baseline security headers to an outgoing response.

    ``is_production`` gates HSTS only: sending Strict-Transport-Security from
    a local/dev origin would pin developers' browsers to HTTPS for a year.

    An existing ``Content-Security-Policy`` is never overwritten — a route or
    downstream middleware that sets its own (stricter) policy wins.
    """
    headers = response.headers
    if "Content-Security-Policy" not in headers:
        headers["Content-Security-Policy"] = SECURITY_CSP
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = SECURITY_REFERRER_POLICY
    headers["Permissions-Policy"] = SECURITY_PERMISSIONS_POLICY
    if is_production:
        headers["Strict-Transport-Security"] = SECURITY_HSTS
    return response


def register_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI app."""

    # ── Error handler ─────────────────────────────────────────────────
    @app.exception_handler(AetherError)
    async def aether_error_handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.code.value,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=problem_dict(
                500,
                "Internal Server Error",
                "Internal server error",
                code="INTERNAL",
                retryable=True,
                request_id=getattr(request.state, "request_id", ""),
            ),
        )

    # ── Request lifecycle middleware ──────────────────────────────────
    @app.middleware("http")
    async def request_lifecycle(request: Request, call_next: Callable) -> Response:
        # --- Correlation ID & tracing ---
        # Canonical inbound header is X-Correlation-ID (what the frontends
        # send); X-Request-ID stays accepted for older clients. One ID per
        # operation — request.state.request_id remains the compat alias.
        req_context = context_from_request(request)
        request_id = req_context.correlation_id
        request.state.request_id = request_id
        request.state.context = req_context
        set_request_context(correlation_id=request_id)

        start = time.perf_counter()
        metrics.increment("http_requests_total", labels={
            "method": request.method, "path": request.url.path,
        })

        # --- Body size check (skip for GET/HEAD/OPTIONS) ---
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    cl = int(content_length)
                except (ValueError, TypeError):
                    return problem_response(
                        400,
                        "Bad Request",
                        "Invalid Content-Length header",
                        code="INVALID_CONTENT_LENGTH",
                        request_id=request_id,
                    )
                if cl > settings.api.max_request_body_bytes:
                    return problem_response(
                        413,
                        "Payload Too Large",
                        "Request body too large",
                        code="REQUEST_BODY_TOO_LARGE",
                        request_id=request_id,
                        extensions={
                            "max_bytes": settings.api.max_request_body_bytes,
                        },
                    )

        # Headers we accumulate from each enforcement layer to attach on the
        # final response (or the early-exit error response).
        rate_headers: dict[str, str] = {}
        quota_headers: dict[str, str] = {}
        access_tier_header: Optional[str] = None

        # Valid CORS preflights (OPTIONS + Origin + Access-Control-Request-Method)
        # carry no credentials by design and are answered by the inner
        # CORSMiddleware. Route templates never declare OPTIONS, so route-policy
        # matching would 403 every preflight before CORS could reply. Only real
        # preflights bypass; plain OPTIONS requests stay fully enforced, and the
        # actual (non-preflight) request that follows is enforced as usual.
        if (
            request.method == "OPTIONS"
            and "origin" in request.headers
            and "access-control-request-method" in request.headers
        ):
            return await call_next(request)

        # Resolve the matched FastAPI template when available. Starlette sets
        # this before the inner application executes; unit/direct invocation
        # falls back to the literal path and remains fail closed.
        route_template = _matched_route_template(app, request.scope)
        if route_template is None and settings.route_registry.route_registry_enforced:
            from shared.common.common import ForbiddenError
            denial = ForbiddenError("ROUTE_POLICY_UNKNOWN_ROUTE")
            return JSONResponse(status_code=denial.code.value, content=denial.to_dict())
        route_template = route_template or request.url.path

        # Bind the request for service-layer code that authorizes against the
        # Kyber workforce plane but is not handed a Request (Noesis). The
        # ContextVar is set on this request's own task context, so it is never
        # visible to another request and needs no teardown here.
        from services.security.request_context import bind_current_request
        bind_current_request(request)

        # --- Auth (skip public paths) ---
        if not _is_public_path(route_template):
            try:
                registry = get_registry()
                context = await _authenticate_async(
                    request, registry.jwt_handler, registry.api_key_validator
                )
            except AetherError as e:
                return JSONResponse(status_code=e.code.value, content=e.to_dict())
            request.state.tenant = context
            request.state.tenant_id = context.tenant_id
            # PR 2 route policy hook (observe by default; enforced mode denies
            # unclassified / Kyber-mismatch routes). Never raises.
            _policy_denial = _evaluate_route_policy(request, route_template, context)
            if _policy_denial is not None:
                return JSONResponse(
                    status_code=_policy_denial.code.value, content=_policy_denial.to_dict()
                )
            plan_tier = _resolve_plan_tier(context)
            request.state.plan_tier = plan_tier
            request.state.context = req_context.with_tenant(
                context.tenant_id,
                actor_id=getattr(context, "user_id", None),
                plan_tier=plan_tier.value,
            )
            set_request_context(
                correlation_id=request_id,
                tenant_id=context.tenant_id,
            )

            api_key = (
                request.headers.get("X-API-Key", "")
                or request.headers.get("Authorization", "").replace("Bearer ", "")
            )

            # --- Burst RPM (per-plan, per-tenant) ---
            try:
                rl_result = await registry.rate_limiter.check(
                    context.tenant_id, plan_tier,
                )
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"Burst limiter Redis unreachable: {e}")
                metrics.increment("redis_fallback", labels={"layer": "burst"})
                rl_result = None

            if rl_result is not None:
                rate_headers = {
                    "X-RateLimit-Limit": str(rl_result.limit),
                    "X-RateLimit-Remaining": str(max(0, rl_result.remaining)),
                    "X-RateLimit-Reset": str(int(rl_result.reset_at)),
                }
                if not rl_result.allowed:
                    metrics.increment("http_rate_limited")
                    retry_after = (
                        rl_result.retry_after
                        if rl_result.retry_after is not None
                        else max(1, int(rl_result.reset_at - time.time()))
                    )
                    return problem_response(
                        429,
                        "Rate Limit Exceeded",
                        (
                            f"Burst rate limit exceeded. "
                            f"Limit: {rl_result.limit} RPM."
                        ),
                        code="RATE_LIMIT_EXCEEDED",
                        retryable=True,
                        request_id=request_id,
                        extensions={
                            "retry_after_seconds": retry_after,
                            "plan_tier": plan_tier.value,
                            "upgrade_url": "/v1/admin/billing/upgrade",
                        },
                        headers={
                            **rate_headers,
                            "Retry-After": str(retry_after),
                            "X-RateLimit-Remaining": "0",
                        },
                    )

            # --- Feature Gate (per-plan service access control) ---
            feature_gate = getattr(registry, "feature_gate", None)
            if feature_gate is not None:
                gate_result = feature_gate.check_access(
                    plan_tier, request.url.path,
                )
                if not gate_result.allowed:
                    metrics.increment(
                        "feature_gate_blocked",
                        labels={
                            "plan": plan_tier.value,
                            "service": gate_result.service_name or "unknown",
                        },
                    )
                    min_plan_tier = (
                        gate_result.minimum_plan or PlanTier.P4_PROTOCOL_MASTER
                    )
                    min_plan = PLAN_CATALOG[min_plan_tier]
                    current_plan = PLAN_CATALOG[plan_tier]
                    return problem_response(
                        403,
                        "Service Not Available On Plan",
                        (
                            f"The {gate_result.service_name} service "
                            f"requires {min_plan.display_name} "
                            f"({min_plan.plan_id}) or higher."
                        ),
                        code="SERVICE_NOT_AVAILABLE",
                        type_slug="entitlement/service-not-available",
                        request_id=request_id,
                        extensions={
                            "current_plan": (
                                f"{current_plan.plan_id}: "
                                f"{current_plan.display_name}"
                            ),
                            "required_plan": (
                                f"{min_plan.plan_id}: {min_plan.display_name}"
                            ),
                            "upgrade_url": "/v1/admin/billing/upgrade",
                            "service": gate_result.service_name,
                            "endpoint": request.url.path,
                        },
                        headers=rate_headers,
                    )
                access_tier_header = gate_result.access_tier

            # --- Monthly Quota (meters only, never blocks) ---
            quota_engine = getattr(registry, "quota_engine", None)
            if quota_engine is not None:
                try:
                    quota_result = await quota_engine.check_and_increment(
                        context.tenant_id, plan_tier, request.url.path,
                    )
                    quota_headers = {
                        "X-Quota-Limit": str(quota_result.quota_limit),
                        "X-Quota-Used": str(quota_result.quota_used),
                        "X-Quota-Remaining": str(quota_result.remaining),
                        "X-Quota-Reset": quota_result.reset,
                    }
                    if not quota_result.included:
                        quota_headers["X-Quota-Overage"] = "true"
                        metrics.increment(
                            "overage_request",
                            labels={
                                "plan": plan_tier.value,
                                "service": quota_result.overage_service or "unknown",
                            },
                        )
                    request.state.quota_result = quota_result
                    # Fire threshold notifications (best-effort)
                    notifier = getattr(registry, "quota_notifier", None)
                    if notifier is not None:
                        try:
                            await notifier.check_and_notify(
                                context.tenant_id, plan_tier, quota_result,
                            )
                        except Exception as e:  # pragma: no cover — defensive
                            logger.debug(f"Notifier dispatch error: {e}")
                except (ConnectionError, TimeoutError) as e:
                    logger.warning(f"Quota engine Redis unreachable: {e}")
                    metrics.increment(
                        "redis_fallback", labels={"layer": "quota"},
                    )
                except Exception as e:  # pragma: no cover — defensive
                    logger.warning(f"Quota check error: {e}")

            # --- Extraction defense for protected ML prediction routes ---
            # Mesh preferred; legacy fallback when the mesh is unavailable;
            # fail closed (when required) if neither defense is available.
            if request.url.path.startswith(_PROTECTED_ML_PREFIX):
                mode = resolve_extraction_defense_mode()
                request.state.extraction_defense_mode = mode

                if mode in (
                    EXTRACTION_MODE_MESH,
                    EXTRACTION_MODE_MESH_WITH_LEGACY_FALLBACK,
                ):
                    mesh_response = await _run_extraction_mesh(
                        request, api_key, context, request_id
                    )
                    if mesh_response is not None:
                        return mesh_response
                elif mode == EXTRACTION_MODE_LEGACY:
                    legacy_response = await _apply_legacy_extraction_defense(
                        request, api_key, request_id
                    )
                    if legacy_response is not None:
                        return legacy_response
                elif mode == EXTRACTION_MODE_FAIL_CLOSED:
                    metrics.increment(
                        "extraction_defense_fail_closed",
                        labels={"path": _PROTECTED_ML_PREFIX},
                    )
                    logger.error(
                        "Extraction defense unavailable for protected ML route "
                        f"{request.url.path} — failing closed (503)"
                    )
                    return problem_response(
                        503,
                        "Extraction Defense Unavailable",
                        "Model protection is required for this route but no "
                        "extraction defense is currently available.",
                        code="EXTRACTION_DEFENSE_UNAVAILABLE",
                        retryable=True,
                        request_id=request_id,
                    )
                else:  # EXTRACTION_MODE_DISABLED
                    metrics.increment(
                        "extraction_defense_unprotected",
                        labels={"path": _PROTECTED_ML_PREFIX},
                    )
                    logger.warning(
                        "Extraction defense inactive for protected ML route "
                        f"{request.url.path} (mode={mode}); set "
                        "REQUIRE_EXTRACTION_DEFENSE=true to fail closed"
                    )

        # --- Execute request ---
        response: Response = await call_next(request)

        # --- Response headers ---
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers[LEGACY_REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_HEADER] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        for name, value in rate_headers.items():
            response.headers[name] = value
        for name, value in quota_headers.items():
            response.headers[name] = value
        if access_tier_header:
            response.headers["X-Access-Tier"] = access_tier_header
        _apply_security_headers(response, is_production=settings.is_production)

        metrics.observe("http_request_duration_ms", elapsed_ms, labels={
            "method": request.method, "status": str(response.status_code),
        })

        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"({elapsed_ms:.1f}ms)"
        )

        return response


async def _run_extraction_mesh(
    request: Request,
    api_key: str,
    context: TenantContext,
    request_id: str,
) -> Optional[JSONResponse]:
    """
    Run the Extraction Defense Mesh pipeline.

    Returns a JSONResponse if the request should be blocked, None otherwise.
    Stores extraction context on request.state for downstream use.
    """
    budget_engine, expectation_engine, scorer, policy_engine, attribution = (
        _get_mesh_components()
    )

    if budget_engine is None:
        return None  # Mesh not enabled

    # ── 1. Build identity fabric ─────────────────────────────────────
    from shared.scoring.extraction_models import ExtractionIdentity

    ip_address = request.client.host if request.client else "0.0.0.0"
    ip_prefix = ".".join(ip_address.split(".")[:3]) if "." in ip_address else ip_address
    ua_hash = hashlib.md5(
        request.headers.get("User-Agent", "").encode()
    ).hexdigest()[:12]

    identity = ExtractionIdentity(
        api_key_id=api_key or None,
        tenant_id=context.tenant_id or None,
        user_id=context.user_id or None,
        session_id=request.headers.get("X-Session-ID") or None,
        request_id=request_id,
        source_ip=ip_address,
        ip_prefix=ip_prefix,
        user_agent_hash=ua_hash,
        device_fingerprint=request.headers.get("X-Device-Fingerprint") or None,
        tls_fingerprint=request.headers.get("X-TLS-Fingerprint") or None,
        wallet_id=request.headers.get("X-Wallet-ID") or None,
    )

    # ── 2. Parse request body ────────────────────────────────────────
    features: dict = {}
    body: dict = {}
    batch_size = 1
    model_name = ""
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes) if body_bytes else {}
        features = body.get("features", {})
        model_name = body.get("model_name", "")
        entities = body.get("entities", [])
        if entities:
            batch_size = len(entities)
            features = entities[0] if entities else {}
    except (json.JSONDecodeError, IndexError, TypeError):
        pass

    endpoint = request.url.path
    is_batch = "batch" in endpoint
    caller_is_service = context.role == Role.SERVICE

    # ── 3. Distributed budget check ──────────────────────────────────
    if budget_engine is not None:
        try:
            await budget_engine.connect()
        except Exception:
            pass  # Continue without budget enforcement

        budget_result = await budget_engine.check_and_increment(
            identity, model_name, batch_size
        )
        if not budget_result.allowed:
            metrics.increment("extraction_mesh_budget_blocked")
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": 429,
                        "message": f"Extraction budget exceeded: {budget_result.reason}",
                        "request_id": request_id,
                    }
                },
                headers={"Retry-After": str(budget_result.retry_after_seconds)},
            )

    # ── 4. Compute expectation signals ───────────────────────────────
    expectation_result = None
    if expectation_engine is not None:
        expectation_result = await expectation_engine.compute_signals(
            identity=identity,
            model_name=model_name,
            features=features,
            batch_size=batch_size,
            endpoint=endpoint,
        )

    # ── 5. Score extraction risk ─────────────────────────────────────
    assessment = None
    if scorer is not None and expectation_result is not None:
        assessment = scorer.score(
            identity=identity,
            expectation_signals=expectation_result.signals,
            model_name=model_name,
            budget_utilization=0.0,  # Could compute from budget state
        )

    # ── 6. Apply policy ──────────────────────────────────────────────
    policy_decision = None
    if policy_engine is not None and assessment is not None:
        policy_decision = policy_engine.evaluate(
            assessment=assessment,
            model_name=model_name,
            is_batch=is_batch,
            caller_is_service=caller_is_service,
        )

        # Handle deny actions
        if policy_decision.action == "deny":
            metrics.increment("extraction_mesh_policy_denied")

            # Record alert
            try:
                from services.intelligence.extraction_intel import record_extraction_alert
                record_extraction_alert(
                    actor_id=identity.primary_key,
                    risk_score=assessment.score,
                    band=assessment.band.value,
                    reasons=assessment.reasons,
                )
            except Exception:
                pass

            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": 403,
                        "message": "Request denied by security policy",
                        "request_id": request_id,
                    }
                },
            )

        # Record alerts for orange/red bands
        if policy_decision.should_alert:
            try:
                from services.intelligence.extraction_intel import record_extraction_alert
                record_extraction_alert(
                    actor_id=identity.primary_key,
                    risk_score=assessment.score,
                    band=assessment.band.value,
                    reasons=assessment.reasons,
                )
            except Exception:
                pass

    # ── 7. Record lineage ────────────────────────────────────────────
    if attribution is not None and assessment is not None:
        from services.expectations.extraction_expectations import _feature_hash
        attribution.record_lineage(
            identity=identity,
            model_name=model_name,
            feature_hash=_feature_hash(features),
            response_value="pending",
            risk_score=assessment.score,
            policy_action=policy_decision.action if policy_decision else "allow",
        )

    # ── 8. Store context for downstream use ──────────────────────────
    request.state.extraction_identity = identity
    request.state.extraction_risk = assessment.score if assessment else 0.0
    request.state.extraction_band = assessment.band.value if assessment else "green"
    request.state.extraction_policy = policy_decision
    request.state.extraction_disclosure = (
        policy_decision.disclosure if policy_decision else None
    )

    metrics.increment("extraction_mesh_processed")
    return None  # Request allowed to proceed


def _declared_target_tenant(path: str, request: Request, pol) -> Optional[str]:
    """The tenant a declared Kyber route targets, read from its path template."""
    try:
        from services.security.route_registry import (
            declaration_path_params,
            match_declaration,
        )
    except Exception:
        return None
    method = getattr(request, "method", "GET")
    decl = match_declaration(path, method)
    if decl is None:
        return None
    concrete = getattr(getattr(request, "url", None), "path", None) or path
    params = declaration_path_params(decl.template, concrete)
    for key in ("tenant_id", "tenant_id_param", "tenantId"):
        if params.get(key):
            return params[key]
    return None


def _evaluate_kyber_capability(request: Request, path: str, pol) -> Optional[AetherError]:
    """Enforce a route's DECLARED Kyber capability at the authorization boundary.

    Runs only for routes carrying a schema-v3 declaration and only while
    ``KYBER_BACKEND_AUTHZ_ENFORCED`` is on — that flag is the rollback lever for
    the whole capability plane. Within it, denial vs. observe follows the same
    ``route_registry_enforced`` switch every other route-policy check uses.

    Denies when the workforce context is unresolvable, when the principal lacks
    the declared capability, when the declared action class exceeds the
    principal's ceiling, or when a tenant-scoped capability has no matching
    active scope.
    """
    capability = getattr(pol, "required_capability", None)
    if not capability:
        return None
    kw = getattr(settings, "kyber_workforce", None)
    if kw is None or not kw.backend_authz_enforced:
        return None

    rr = settings.route_registry
    from shared.common.common import ForbiddenError

    def _fail(reason: str) -> Optional[AetherError]:
        if rr.route_registry_enforced:
            return ForbiddenError("ROUTE_POLICY_KYBER_CAPABILITY_REQUIRED")
        logger.warning(
            f"route policy: kyber capability {capability} not satisfied on {path} ({reason})"
        )
        try:
            metrics.increment(
                "route_policy_kyber_capability_observed",
                labels={"capability": capability, "reason": reason},
            )
        except Exception:
            pass
        return None

    from services.security.request_context import (
        context_has_capability,
        context_has_tenant_scope,
        context_is_stepped_up,
        context_max_action_class,
        context_max_disclosure,
        kyber_access_context,
    )

    ctx = kyber_access_context(request)
    if ctx is None:
        return _fail("no_workforce_context")
    if not context_has_capability(ctx, capability):
        return _fail("capability_missing")
    if int(getattr(pol, "action_class", 0) or 0) > context_max_action_class(ctx):
        return _fail("action_class_exceeded")

    try:
        from services.kyber.access.capabilities import get_capability
        declared = get_capability(capability)
    except Exception:
        declared = None
    if declared is not None and declared.tenant_scoped:
        # When the route names a tenant the scope must match it; otherwise the
        # boundary can only require that SOME scope is active and leaves the
        # precise target to the route's own Kyber dependency, which knows the
        # resource the identifier belongs to.
        target = _declared_target_tenant(path, request, pol)
        if not context_has_tenant_scope(ctx, target):
            return _fail("tenant_scope_missing")

    # ── Declared minimum disclosure ──────────────────────────────────────────
    #
    # Until this existed, `minimum_disclosure` was set on every schema-v3
    # RoutePolicy and read by nothing: a `disclosure: D4` declaration was a
    # policy record with no enforcement behind it, which is the same
    # declared-but-inert shape as a retention class the sweeper ignores.
    #
    # Two things follow from a declaration. The principal's ceiling must reach
    # the level the route discloses, and a route disclosing record-level
    # evidence (D4+) requires a live step-up elevation — which is what makes
    # `STEP_UP_REQUIRED_FROM` mean anything at the boundary rather than only
    # for routes that happen to pass `disclosure=` to their own dependency.
    declared_disclosure = getattr(pol, "minimum_disclosure", None)
    if declared_disclosure:
        try:
            from services.kyber.access.disclosure import DisclosureLevel, requires_step_up

            required = DisclosureLevel.parse(declared_disclosure)
        except Exception:
            # An unparseable declaration is a registry defect, not a licence to
            # skip the check.
            return _fail("disclosure_unparseable")
        if int(required) > context_max_disclosure(ctx):
            return _fail("disclosure_exceeded")
        if requires_step_up(required) and not context_is_stepped_up(ctx):
            return _fail("step_up_required")
    return None


def _evaluate_route_policy(request: Request, path: str, context) -> Optional[AetherError]:
    """Apply the canonical route policy and return a stable denial.

    In enforced mode any evaluator error is itself denied.  This deliberately
    avoids the old fail-open exception handler.  Local observe mode retains
    diagnostics without blocking development.
    """
    rr = getattr(settings, "route_registry", None)
    try:
        if rr is None or not rr.policy_enforcement_enabled:
            return None
        from services.security.route_registry import classify
        from shared.common.common import ForbiddenError

        pol = classify(path)
        if pol is None:
            if rr.route_registry_enforced:
                return ForbiddenError("ROUTE_POLICY_UNCLASSIFIED")
            logger.warning(f"route policy: unclassified route {path}")
            try:
                metrics.increment("route_policy_unclassified")
            except Exception:
                pass
            return None

        # Founding-tenant release surface: domains the release manifest
        # excludes are not part of the release. The exclusion set is lazily
        # loaded and empty for every profile other than the manifest's own,
        # so this is a cached frozenset lookup outside that profile.
        from services.security.route_registry import founding_domain_excluded
        if founding_domain_excluded(
            pol.domain, settings.runtime.deployment_profile
        ):
            return ForbiddenError("ROUTE_POLICY_DOMAIN_EXCLUDED")

        if pol.kyber_operator_required:
            from services.security.request_context import is_kyber_operator
            if not is_kyber_operator(context, request=request):
                if rr.route_registry_enforced:
                    return ForbiddenError(
                        "ROUTE_POLICY_KYBER_OPERATOR_REQUIRED"
                    )
                logger.warning(f"route policy: non-operator on kyber route {path}")
                try:
                    metrics.increment("route_policy_kyber_observed")
                except Exception:
                    pass

            # Declared capability enforcement (route registry schema v3). This
            # is what carries capability-level authority to the ~158 existing
            # `require_kyber_operator` call sites without editing them.
            denial = _evaluate_kyber_capability(request, path, pol)
            if denial is not None:
                return denial
        if context is None:
            if pol.requires_auth:
                return ForbiddenError("ROUTE_POLICY_AUTH_REQUIRED")
            return None

        # State is rehydrated by the trust-plane validators on each request.
        state_checks = (
            ("tenant_status", "ROUTE_POLICY_TENANT_INACTIVE"),
            ("organization_status", "ROUTE_POLICY_ORGANIZATION_INACTIVE"),
            ("membership_status", "ROUTE_POLICY_MEMBERSHIP_INACTIVE"),
            ("credential_status", "ROUTE_POLICY_CREDENTIAL_INACTIVE"),
        )
        for attr, reason in state_checks:
            if getattr(context, attr, "active") != "active":
                return ForbiddenError(reason)

        credential_class = getattr(context, "credential_class", "legacy")
        if credential_class == "public_ingest_identifier":
            if path not in ("/v1/batch", "/v1/track") and not path.startswith("/v1/ingest"):
                return ForbiddenError("ROUTE_POLICY_INGEST_IDENTIFIER_SCOPE")
        if credential_class == "service_credential" and not context.permissions:
            return ForbiddenError("ROUTE_POLICY_SERVICE_SCOPE_REQUIRED")

        requested_tenant = getattr(request, "headers", {}).get("X-Tenant-ID")
        if requested_tenant and requested_tenant != context.tenant_id:
            return ForbiddenError("ROUTE_POLICY_TENANT_MISMATCH")

        method = getattr(request, "method", "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            permission = "ingest" if path in ("/v1/batch", "/v1/track") or path.startswith("/v1/ingest") else "write"
            if not context.has_permission(permission):
                return ForbiddenError("ROUTE_POLICY_PERMISSION_REQUIRED")
        elif pol.tenant_scoped and credential_class != "legacy" and not context.has_permission("read"):
            return ForbiddenError("ROUTE_POLICY_PERMISSION_REQUIRED")

        if pol.audit_required:
            logger.info(
                "route_policy_decision",
                extra={
                    "route_template": path,
                    "method": method,
                    "tenant_id": context.tenant_id,
                    "actor_id": context.user_id or "machine",
                    "credential_class": credential_class,
                    "decision": "allow",
                    "request_id": getattr(request.state, "request_id", ""),
                },
            )
        return None
    except Exception as e:
        logger.error(f"route policy evaluation error on {path}: {type(e).__name__}")
        if rr is not None and rr.route_registry_enforced:
            from shared.common.common import ForbiddenError
            return ForbiddenError("ROUTE_POLICY_EVALUATION_FAILED")
        return None


def _matched_route_template(app: FastAPI, scope: dict) -> Optional[str]:
    """Match a request scope to its mounted template before dispatch.

    Middleware runs outside Starlette's router, so ``scope['route']`` is not
    reliably populated yet.  Matching here ensures literal tenant/entity IDs
    never become authorization inputs.
    """
    from starlette.routing import Match

    existing = scope.get("route")
    if existing is not None:
        return getattr(existing, "path", None)
    for route in app.routes:
        try:
            match, _ = route.matches(scope)
        except (AttributeError, KeyError, TypeError):
            continue
        if match is Match.FULL:
            return getattr(route, "path", None)
    return None


async def _authenticate_async(
    request: Request,
    jwt_handler: JWTHandler,
    api_key_validator: APIKeyValidator,
) -> TenantContext:
    """Resolve a request principal.

    Order: X-API-Key → trust-plane credentials (session cookie / X-Session-Token,
    public ingest identifier, service credential) → Bearer (API key, then session
    token, then JWT). The trust-plane resolution is purely additive and gated on
    the trust-plane flags, so API-key and JWT callers are unaffected.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return await api_key_validator.validate_async(api_key)

    # Additive: trust-plane credential classes (sessions / ingest / service).
    trust_ctx = await _resolve_trust_plane_context(request)
    if trust_ctx is not None:
        return trust_ctx

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        # Try API key first (SDK pattern); fall back to JWT (SSO/user pattern)
        try:
            return await api_key_validator.validate_async(token)
        except Exception:
            pass
        # A session token may also arrive via Bearer.
        sess_ctx = await _resolve_session_token(token)
        if sess_ctx is not None:
            return sess_ctx
        payload = jwt_handler.decode(token)
        return jwt_handler.extract_context(payload)

    raise UnauthorizedError("Missing API key or Bearer token")


async def _resolve_trust_plane_context(request: Request) -> Optional[TenantContext]:
    """Resolve a session cookie / header, public ingest identifier, or service
    credential into a TenantContext. Returns None when nothing matches or the
    relevant trust-plane flag is off. Never raises — falls through to legacy."""
    try:
        from config.settings import settings as _settings
        tp = _settings.trust_plane
    except Exception:
        return None

    headers = request.headers
    cookies = getattr(request, "cookies", {}) or {}

    if getattr(tp, "human_sessions_enabled", False):
        token = cookies.get("aether_session") or headers.get("X-Session-Token")
        if token:
            ctx = await _resolve_session_token(token)
            if ctx is not None:
                return ctx

    if getattr(tp, "public_ingest_identifier_enabled", False):
        ident = headers.get("X-Ingest-Key")
        if ident:
            ctx = await _resolve_public_ingest(ident)
            if ctx is not None:
                return ctx

    if getattr(tp, "service_credentials_enabled", False):
        cred = headers.get("X-Service-Credential")
        if cred:
            ctx = await _resolve_service_credential(cred)
            if ctx is not None:
                return ctx

    return None


async def _current_tenant_status(rec: dict) -> str:
    """Authoritative tenant status for a trust-plane credential record.

    A credential-carried ``tenant_status`` is used only as the fresh fast-path
    (the issuing service stamped it at validation time). When the record does
    not carry one — session/service-credential/public-ingest records do not —
    the durable tenant record (the same row ``deactivate_tenant`` flips to
    ``inactive``) is authoritative. Anything unresolvable fails closed as
    ``inactive`` so a deactivated or deleted tenant's surviving credentials
    never keep working.
    """
    carried = rec.get("tenant_status")
    if carried is not None:
        return str(carried)
    tenant_id = rec.get("tenant_id") or ""
    if not tenant_id:
        return "inactive"
    try:
        from repositories.repos import AdminRepository
        tenant = await AdminRepository().find_by_id(tenant_id)
    except Exception as e:
        logger.warning(
            "tenant status lookup failed for %s (%s) — failing closed",
            tenant_id, type(e).__name__,
        )
        return "inactive"
    if not tenant:
        return "inactive"
    return str(tenant.get("status", "inactive"))


async def _resolve_session_token(token: str) -> Optional[TenantContext]:
    try:
        from services.auth.sessions import session_service
        rec = await session_service.validate_session(token)
    except Exception:
        return None
    return TenantContext(
        tenant_id=rec.get("tenant_id", ""),
        user_id=rec.get("principal_id"),
        role=Role.EDITOR,
        permissions=list(rec.get("permissions", ["read", "write", "ingest", "analytics"])),
        credential_class=rec.get("credential_class", "human_session"),
        credential_status=rec.get("status", "inactive"),
        tenant_status=await _current_tenant_status(rec),
        organization_id=rec.get("organization_id"),
        organization_status=rec.get("organization_status", "active"),
        membership_status=rec.get("membership_status", "active"),
    )


async def _resolve_public_ingest(identifier: str) -> Optional[TenantContext]:
    try:
        from services.auth.sessions import public_ingest_service
        rec = await public_ingest_service.validate_identifier(identifier)
    except Exception:
        return None
    # Ingest-only: viewer role, ingest permission only — cannot read analytics
    # or call admin routes.
    return TenantContext(
        tenant_id=rec.get("tenant_id", ""),
        role=Role.VIEWER,
        permissions=["ingest"],
        credential_class=rec.get("credential_class", "public_ingest_identifier"),
        credential_status=rec.get("status", "inactive"),
        tenant_status=await _current_tenant_status(rec),
    )


async def _resolve_service_credential(cred: str) -> Optional[TenantContext]:
    try:
        from services.auth.sessions import service_credential_service
        rec = await service_credential_service.validate_credential(cred)
    except Exception:
        return None
    return TenantContext(
        tenant_id=rec.get("tenant_id", ""),
        role=Role.EDITOR,
        permissions=list(rec.get("permissions", [])),
        credential_class=rec.get("credential_class", "service_credential"),
        credential_status=rec.get("status", "inactive"),
        tenant_status=await _current_tenant_status(rec),
        organization_id=rec.get("organization_id"),
        organization_status=rec.get("organization_status", "active"),
    )
