"""Noesis API routes."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from dependencies.providers import get_cache, get_graph
from repositories.repos import AnalyticsRepository
from shared.common.common import APIResponse, BadRequestError, ForbiddenError, RateLimitedError, ServiceUnavailableError
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

from .capability_registry import capabilities_for_surface
from .flags import NoesisFlags
from .models import NoesisQueryRequest
from .service import NoesisService

logger = get_logger("aether.service.noesis.routes")

router = APIRouter(prefix="/v1/noesis", tags=["Noesis"])


@router.post("/query")
async def query_noesis(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    """Execute a tenant-scoped read-only Noesis natural-language query."""
    request_id = str(uuid.uuid4())
    correlation_id = getattr(request.state, "correlation_id", None) or request.headers.get("x-correlation-id") or request_id

    try:
        analytics = AnalyticsRepository(get_cache())
        service = NoesisService(graph=graph, analytics=analytics)
        response = await service.query(body, request.state.tenant, request_id=request_id)
        data = response.model_dump(mode="json", exclude_none=True)
        result = APIResponse(data=data).to_dict()
    except RateLimitedError as exc:
        retry_after = exc.details.get("retry_after_seconds", 60)
        logger.warning("Noesis rate limited", extra={"request_id": request_id, "retry_after": retry_after})
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded", "retry_after_seconds": retry_after, "request_id": request_id},
            headers={
                "x-request-id": request_id,
                "x-correlation-id": correlation_id,
                "retry-after": str(retry_after),
            },
        )
    except ServiceUnavailableError as exc:
        logger.warning("Noesis unavailable", extra={"request_id": request_id, "error": str(exc)})
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "request_id": request_id},
            headers={"x-request-id": request_id, "x-correlation-id": correlation_id},
        )
    except ForbiddenError as exc:
        logger.warning("Noesis forbidden", extra={"request_id": request_id, "error": str(exc)})
        return JSONResponse(
            status_code=403,
            content={"error": str(exc), "request_id": request_id},
            headers={"x-request-id": request_id, "x-correlation-id": correlation_id},
        )
    except BadRequestError as exc:
        logger.warning("Noesis bad request", extra={"request_id": request_id, "error": str(exc)})
        return JSONResponse(
            status_code=400,
            content={"error": str(exc), "request_id": request_id},
            headers={"x-request-id": request_id, "x-correlation-id": correlation_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Noesis unexpected error", extra={"request_id": request_id, "error": str(exc)})
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Noesis error", "request_id": request_id},
            headers={"x-request-id": request_id, "x-correlation-id": correlation_id},
        )

    # Real rate-limit headers from service state
    rl = service._rate_limit_state
    headers = {
        "x-request-id": request_id,
        "x-correlation-id": correlation_id,
        "x-ratelimit-limit": str(rl.limit if rl else 60),
        "x-ratelimit-remaining": str(rl.remaining if rl else 59),
        "x-ratelimit-reset": str(rl.reset_seconds if rl else 60),
    }

    return JSONResponse(content=result, headers=headers)


@router.post("/query/stream")
async def query_noesis_stream(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    """Stream a Noesis query as SSE events.

    Yields three event phases:
      data: {"type": "intent", "intent": "...", "confidence": 0.xx}
      data: {"type": "results", "count": N}
      data: {"type": "complete", ...full response...}

    On error:
      data: {"type": "error", "error": "...", "code": "..."}
    """
    request_id = str(uuid.uuid4())

    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics)

    return StreamingResponse(
        service.query_stream(body, request.state.tenant, request_id=request_id),
        media_type="text/event-stream",
        headers={
            "x-request-id": request_id,
            "cache-control": "no-cache",
            "x-accel-buffering": "no",
        },
    )


@router.get("/capabilities")
async def list_capabilities(request: Request):
    """Return the Noesis capability registry filtered by the caller's surface.

    Surface is inferred from the Host header: 'kyber' hosts see all capabilities
    (including tenant_summary), 'aether' hosts see only aether-surface capabilities.
    """
    host = request.headers.get("host", "")
    surface = "kyber" if "kyber" in host else "aether"
    caps = capabilities_for_surface(surface)
    return JSONResponse(content={
        "surface": surface,
        "capabilities": [
            {
                "intent": cap.intent,
                "label": cap.label,
                "description": cap.description,
                "requires_target": cap.requires_target,
                "example_prompts": cap.example_prompts,
                "data_sources": cap.data_sources,
            }
            for cap in caps
        ],
        "count": len(caps),
    })


@router.get("/health")
async def noesis_health(request: Request):
    """Noesis readiness probe — no auth required.

    Returns 200 when all critical dependencies are healthy, 503 when degraded.
    """
    flags = NoesisFlags()
    cache = get_cache()

    checks: dict[str, bool] = {
        "noesis_enabled": flags.noesis_enabled,
        "llm_provider_configured": not flags.llm_enabled or bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        ),
    }

    # Lightweight Redis connectivity check
    try:
        redis_ok = await cache.health_check()
        checks["conversation_redis"] = redis_ok
        checks["rate_limiter_redis"] = redis_ok
    except Exception:
        checks["conversation_redis"] = False
        checks["rate_limiter_redis"] = False

    status = "ok" if all(checks.values()) else "degraded"
    status_code = 200 if status == "ok" else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": status, "checks": checks},
    )
