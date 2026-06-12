"""
Aether Service — x402 Challenge Middleware
FastAPI HTTP middleware that intercepts requests to registered protected resources
and issues HTTP 402 PAYMENT-REQUIRED challenges when the caller lacks a valid
entitlement. Operates as step 8.5 in the middleware stack (after auth, before
route dispatch).

Behaviour:
  - Path not in registry → pass through (no-op)
  - Valid active entitlement found for caller → pass through
  - X-Payment-Identifier present and already settled → pass through (idempotency)
  - Otherwise → 402 with PAYMENT-REQUIRED header and challenge body
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.middleware.challenge")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChallengeMiddleware(BaseHTTPMiddleware):
    """
    Optional x402 challenge middleware. Only intercepts paths registered as
    protected resources. Must be added to the FastAPI app after auth middleware
    so that request.state.tenant is available.

    Wire via: app.add_middleware(ChallengeMiddleware)
    Enable via: settings.commerce_enable_challenge_middleware = True
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Fast exit: only POST/GET to non-public paths may be gated
        if request.method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)

        tenant = getattr(request.state, "tenant", None)
        if tenant is None:
            # Auth hasn't run yet or path is public — let the stack handle it
            return await call_next(request)

        tenant_id: str = getattr(tenant, "tenant_id", "")
        if not tenant_id:
            return await call_next(request)

        # Lazy import to avoid circular at module load
        from .resources import get_resource_registry
        from .entitlements import get_entitlement_service
        from .idempotency import get_idempotency_store

        registry = get_resource_registry()
        resource = await registry.find_by_path(tenant_id, path)

        if resource is None or not resource.active:
            # Path not registered as a protected resource — pass through
            return await call_next(request)

        caller_id: str = getattr(tenant, "user_id", "") or getattr(tenant, "tenant_id", "")

        # --- Idempotency: X-Payment-Identifier already settled? ---
        payment_id = request.headers.get("X-Payment-Identifier")
        if payment_id:
            store = get_idempotency_store()
            settled = await store.lookup(tenant_id, payment_id)
            if settled:
                metrics.increment("challenge_middleware_idempotency_pass")
                return await call_next(request)

        # --- SIWX / entitlement reuse: active entitlement grants access ---
        svc = get_entitlement_service()
        entitlement = await svc.lookup(tenant_id, caller_id, resource.resource_id)
        if entitlement is not None:
            request.state.x402_entitlement_id = entitlement.entitlement_id
            metrics.increment("challenge_middleware_entitlement_pass")
            return await call_next(request)

        # --- No entitlement — issue 402 challenge ---
        metrics.increment("challenge_middleware_402_issued")
        logger.info(
            f"402 challenge issued: resource={resource.resource_id} "
            f"tenant={tenant_id} caller={caller_id} path={path}"
        )

        challenge_body = {
            "error": {
                "code": 402,
                "type": "payment_required",
                "message": f"Payment required to access {resource.name}",
                "resource_id": resource.resource_id,
                "resource_class": resource.resource_class,
                "price_usd": resource.price_usd,
                "accepted_assets": resource.accepted_assets,
                "challenge_issued_at": _now_iso(),
                "challenge_endpoint": "/v1/x402/challenge",
                "preflight_endpoint": "/v1/x402/access/preflight",
            }
        }
        payment_required_header = json.dumps({
            "version": "2",
            "resource_id": resource.resource_id,
            "price_usd": str(resource.price_usd),
            "accepted_assets": resource.accepted_assets,
            "challenge_endpoint": "/v1/x402/challenge",
        })

        return JSONResponse(
            status_code=402,
            content=challenge_body,
            headers={
                "PAYMENT-REQUIRED": payment_required_header,
                "X-Resource-ID": resource.resource_id,
                "X-Challenge-Endpoint": "/v1/x402/challenge",
            },
        )


def register_challenge_middleware(app) -> None:
    """Wire ChallengeMiddleware into the FastAPI app when enabled in settings."""
    try:
        from config.settings import settings
        if not getattr(settings, "commerce_enable_challenge_middleware", False):
            logger.debug("Challenge middleware disabled (commerce_enable_challenge_middleware=False)")
            return
    except Exception:
        return

    app.add_middleware(ChallengeMiddleware)
    logger.info("x402 ChallengeMiddleware registered")
