"""Noesis API routes."""

from __future__ import annotations

import json
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from dependencies.providers import get_cache, get_graph
from repositories.repos import AnalyticsRepository
from shared.auth.auth import Role
from shared.common.common import APIResponse, ForbiddenError
from shared.graph.graph import GraphClient

from .conversations import NoesisConversationStore
from .models import NoesisConversationList, NoesisQueryRequest
from .service import NoesisService

router = APIRouter(prefix="/v1/noesis", tags=["Noesis"])
_conversations = NoesisConversationStore()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def _query_event_stream(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient,
) -> AsyncIterator[str]:
    yield _sse("status", {"stage": "received", "message": "Noesis received the request."})
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics, conversation_store=_conversations)
    yield _sse("status", {"stage": "planning", "message": "Planning a safe read-only graph query."})
    response = await service.query(body, request.state.tenant)
    yield _sse("answer", {"conversation_id": response.conversation_id, "answer": response.answer})
    yield _sse("final", response.model_dump(exclude_none=True))


def _history_tenant_scope(request: Request, surface: str, tenant_id: Optional[str]) -> Optional[str]:
    tenant = request.state.tenant
    tenant.require_permission("read")
    requested = (tenant_id or "").strip()
    is_operator = tenant.role == Role.ADMIN or tenant.has_permission("admin") or tenant.has_permission("kyber:read")
    if surface == "aether":
        if requested and requested != tenant.tenant_id:
            raise ForbiddenError("Aether Noesis cannot read another tenant's conversations")
        return tenant.tenant_id
    if requested:
        if requested != tenant.tenant_id and not is_operator:
            raise ForbiddenError("Kyber cross-tenant Noesis conversations require operator permission")
        return requested
    return None if is_operator else tenant.tenant_id


@router.post("/query")
async def query_noesis(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    """Execute a tenant-scoped read-only Noesis natural-language query."""
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics, conversation_store=_conversations)
    response = await service.query(body, request.state.tenant)
    return APIResponse(data=response.model_dump(exclude_none=True)).to_dict()


@router.post("/query/stream")
async def stream_noesis_query(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    """Stream Noesis query status and final response as server-sent events."""
    return StreamingResponse(
        _query_event_stream(body, request, graph),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
async def list_noesis_conversations(
    request: Request,
    surface: Literal["kyber", "aether"] = Query(default="aether"),
    tenant_id: Optional[str] = None,
    limit: int = 50,
):
    """List Noesis conversations visible to the authenticated caller."""
    scoped_tenant = _history_tenant_scope(request, surface, tenant_id)
    rows = await _conversations.list_for_scope(surface=surface, tenant_id=scoped_tenant, limit=limit)
    return APIResponse(data=NoesisConversationList(conversations=rows, count=len(rows)).model_dump()).to_dict()


@router.get("/conversations/{conversation_id}")
async def get_noesis_conversation(
    conversation_id: str,
    request: Request,
    surface: Literal["kyber", "aether"] = Query(default="aether"),
    tenant_id: Optional[str] = None,
):
    """Read a single Noesis conversation visible to the authenticated caller."""
    scoped_tenant = _history_tenant_scope(request, surface, tenant_id)
    row = await _conversations.get(conversation_id, tenant_id=scoped_tenant, surface=surface)
    return APIResponse(data=row).to_dict()


@router.post("/conversations/{conversation_id}/messages")
async def append_noesis_message(
    conversation_id: str,
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    """Append a user message to an existing/new Noesis conversation by executing a query."""
    body.conversation_id = conversation_id
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics, conversation_store=_conversations)
    response = await service.query(body, request.state.tenant)
    return APIResponse(data=response.model_dump(exclude_none=True)).to_dict()
