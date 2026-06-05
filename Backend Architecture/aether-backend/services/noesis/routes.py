"""Noesis API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from dependencies.providers import get_cache, get_graph
from repositories.repos import AnalyticsRepository
from shared.common.common import APIResponse
from shared.graph.graph import GraphClient

from .models import NoesisQueryRequest
from .service import NoesisService

router = APIRouter(prefix="/v1/noesis", tags=["Noesis"])


@router.post("/query")
async def query_noesis(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    """Execute a tenant-scoped read-only Noesis natural-language query."""
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics)
    response = await service.query(body, request.state.tenant)
    return APIResponse(data=response.model_dump(exclude_none=True)).to_dict()
