"""
Aether Backend — Middleware Stack
Auth, request tracing, rate limiting, body limits, and error handling middleware.
Applied globally to the FastAPI app.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from shared.common.common import AetherError, UnauthorizedError
from shared.auth.auth import JWTHandler, APIKeyValidator, TenantContext
from shared.logger.logger import get_logger, set_request_context, metrics
from shared.rate_limit.limiter import TokenBucketLimiter
from config.settings import settings
from dependencies.providers import get_registry

logger = get_logger("aether.middleware")

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
                context = _authenticate(
                    request, registry.jwt_handler, registry.api_key_validator
                )
            except AetherError as e:
                return JSONResponse(status_code=e.code.value, content=e.to_dict())
            request.state.tenant = context
            set_request_context(
                correlation_id=request_id,
                tenant_id=context.tenant_id,
            )

            # --- Rate limiting ---
            api_key = (
                request.headers.get("X-API-Key", "")
                or request.headers.get("Authorization", "").replace("Bearer ", "")
            )
            rl_result = registry.rate_limiter.check(api_key, context.api_key_tier)
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


def _authenticate(
    request: Request,
    jwt_handler: JWTHandler,
    api_key_validator: APIKeyValidator,
) -> TenantContext:
    """Try API key first, then JWT bearer token."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key_validator.validate(api_key)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = jwt_handler.decode(token)
        return jwt_handler.extract_context(payload)

    raise UnauthorizedError("Missing API key or Bearer token")
