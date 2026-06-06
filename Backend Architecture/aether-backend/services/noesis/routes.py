"""Noesis API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from dependencies.providers import get_cache, get_graph
from repositories.repos import AnalyticsRepository
from shared.common.common import APIResponse, BadRequestError, ForbiddenError
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

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
        data = response.model_dump(exclude_none=True)
        result = APIResponse(data=data).to_dict()
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

    # Attach request/correlation IDs and rate-limit placeholder headers
    headers = {
        "x-request-id": request_id,
        "x-correlation-id": correlation_id,
        "x-ratelimit-limit": "60",
        "x-ratelimit-remaining": "59",
        "x-ratelimit-reset": "60",
    }

    return JSONResponse(content=result, headers=headers)
