"""
Aether Backend — Middleware Stack
Auth, request tracing, rate limiting, body limits, extraction defense,
extraction defense mesh, and error handling middleware.
Applied globally to the FastAPI app.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from shared.common.common import AetherError, UnauthorizedError
from shared.auth.auth import JWTHandler, APIKeyValidator, TenantContext, Role
from shared.logger.logger import get_logger, set_request_context, metrics
from shared.rate_limit.limiter import TokenBucketLimiter
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


def _init_extraction_mesh():
    """Lazy-init the extraction defense mesh components."""
    global _mesh_budget_engine, _mesh_expectation_engine, _mesh_scorer
    global _mesh_policy_engine, _mesh_attribution, _mesh_initialized

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


# Paths that skip auth
_PUBLIC_PATHS = {"/health", "/v1/health", "/docs", "/openapi.json", "/redoc", "/"}


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
            content={
                "error": {
                    "code": 500,
                    "message": "Internal server error",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", ""),
                }
            },
        )

    # ── Request lifecycle middleware ──────────────────────────────────
    @app.middleware("http")
    async def request_lifecycle(request: Request, call_next: Callable) -> Response:
        # --- Correlation ID & tracing ---
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
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
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": 400,
                                "message": "Invalid Content-Length header",
                                "request_id": request_id,
                            }
                        },
                    )
                if cl > settings.api.max_request_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": 413,
                                "message": "Request body too large",
                                "details": {
                                    "max_bytes": settings.api.max_request_body_bytes,
                                },
                                "request_id": request_id,
                            }
                        },
                    )

        # --- Auth (skip public paths) ---
        if request.url.path not in _PUBLIC_PATHS:
            try:
                registry = get_registry()
                context = await _authenticate_async(
                    request, registry.jwt_handler, registry.api_key_validator
                )
            except AetherError as e:
                return JSONResponse(status_code=e.code.value, content=e.to_dict())
            request.state.tenant = context
            set_request_context(
                correlation_id=request_id,
                tenant_id=context.tenant_id,
            )

            # --- Rate limiting (async for Redis distributed limiting) ---
            api_key = (
                request.headers.get("X-API-Key", "")
                or request.headers.get("Authorization", "").replace("Bearer ", "")
            )
            rl_result = await registry.rate_limiter.check_async(api_key, context.api_key_tier)
            if not rl_result.allowed:
                metrics.increment("http_rate_limited")
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": 429,
                            "message": "Rate limit exceeded",
                            "details": {
                                "retry_after_seconds": int(
                                    rl_result.reset_at - time.time()
                                )
                            },
                            "request_id": request_id,
                        }
                    },
                    headers=rl_result.headers,
                )

            # --- Extraction Defense Mesh (ML prediction routes) ---
            if request.url.path.startswith("/v1/ml/predict"):
                mesh_response = await _run_extraction_mesh(
                    request, api_key, context, request_id
                )
                if mesh_response is not None:
                    return mesh_response

            # --- Legacy extraction defense (ML prediction routes only) ---
            elif request.url.path.startswith("/v1/ml/predict"):
                defense = _get_backend_defense_layer()
                if defense is not None:
                    ip_address = (
                        request.client.host if request.client else "0.0.0.0"
                    )
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
                            429
                            if "rate limit" in pre_result.block_reason.lower()
                            else 403
                        )
                        metrics.increment("extraction_defense_blocked")
                        headers = {}
                        if pre_result.retry_after_seconds:
                            headers["Retry-After"] = str(
                                pre_result.retry_after_seconds
                            )
                        return JSONResponse(
                            status_code=status,
                            content={
                                "error": {
                                    "code": status,
                                    "message": pre_result.block_reason,
                                    "request_id": request_id,
                                }
                            },
                            headers=headers,
                        )
                    request.state.extraction_risk = (
                        pre_result.risk_assessment.risk_score
                        if pre_result.risk_assessment
                        else 0.0
                    )

        # --- Execute request ---
        response: Response = await call_next(request)

        # --- Response headers ---
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"

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


async def _authenticate_async(
    request: Request,
    jwt_handler: JWTHandler,
    api_key_validator: APIKeyValidator,
) -> TenantContext:
    """Try API key first (async Redis lookup in production), then JWT bearer token."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return await api_key_validator.validate_async(api_key)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = jwt_handler.decode(token)
        return jwt_handler.extract_context(payload)

    raise UnauthorizedError("Missing API key or Bearer token")
