"""Noesis API routes."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from dependencies.providers import get_cache, get_graph
from repositories.repos import AnalyticsRepository
from shared.auth.auth import Role
from services.security.audit_ledger import audit_ledger
from services.security.contracts import SecurityAuditOutcome
from shared.common.common import APIResponse, ForbiddenError
from shared.graph.graph import GraphClient

from .conversations import NoesisConversationStore
from .models import NoesisConversationList, NoesisQueryRequest
from .service import NoesisService

router = APIRouter(prefix="/v1/noesis", tags=["Noesis"])
_conversations = NoesisConversationStore()
_RATE_BUCKETS: dict[tuple[str, str], tuple[float, int]] = {}




def _actor_id(request: Request) -> str:
    tenant = request.state.tenant
    return getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", "unknown")


def _actor_type(request: Request) -> str:
    tenant = request.state.tenant
    return "olympus_operator" if tenant.role == Role.ADMIN or tenant.has_permission("kyber:read") else "tenant_user"


async def _record_audit(
    request: Request,
    *,
    event_type: str,
    action: str,
    tenant_id: Optional[str],
    resource_id: Optional[str] = None,
    outcome: SecurityAuditOutcome = "allowed",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    try:
        await audit_ledger.record(
            actor_id=_actor_id(request),
            actor_type=_actor_type(request),
            event_type=event_type,
            resource_type="noesis_conversation" if "conversation" in event_type else "noesis_query",
            action=action,
            outcome=outcome,
            tenant_id=tenant_id,
            resource_id=resource_id,
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001 - audit must not break read-only query UX
        from shared.logger.logger import get_logger
        get_logger("aether.service.noesis.routes").warning(f"Noesis audit event failed: {exc}")


def _enforce_budget(request: Request, *, bucket: str, limit: int) -> None:
    tenant = request.state.tenant
    key = (getattr(tenant, "tenant_id", "unknown"), bucket)
    now = time.time()
    window_start, count = _RATE_BUCKETS.get(key, (now, 0))
    if now - window_start >= 60:
        window_start, count = now, 0
    if count >= limit:
        from shared.common.common import RateLimitedError
        raise RateLimitedError(retry_after=max(1, int(60 - (now - window_start))))
    _RATE_BUCKETS[key] = (window_start, count + 1)

def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def _query_event_stream(
    body: NoesisQueryRequest,
    request: Request,
    graph: GraphClient,
) -> AsyncIterator[str]:
    yield _sse("status", {"stage": "received", "message": "Noesis received the request."})
    _enforce_budget(request, bucket="stream", limit=30)
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics, conversation_store=_conversations)
    yield _sse("status", {"stage": "planning", "message": "Planning a safe read-only graph query."})
    response = await service.query(body, request.state.tenant)
    await _record_audit(
        request,
        event_type="noesis_query",
        action="read",
        tenant_id=response.query_debug.get("plan", {}).get("tenant_id") if response.query_debug else request.state.tenant.tenant_id,
        resource_id=response.conversation_id,
        metadata={"surface": body.surface, "intent": response.intent, "mode": response.mode, "stream": True},
    )
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
    _enforce_budget(request, bucket="query", limit=60)
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics, conversation_store=_conversations)
    response = await service.query(body, request.state.tenant)
    await _record_audit(
        request,
        event_type="noesis_query",
        action="read",
        tenant_id=response.query_debug.get("plan", {}).get("tenant_id") if response.query_debug else request.state.tenant.tenant_id,
        resource_id=response.conversation_id,
        metadata={"surface": body.surface, "intent": response.intent, "mode": response.mode},
    )
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




@router.get("/conversations/export")
async def export_noesis_conversations(
    request: Request,
    surface: Literal["kyber", "aether"] = Query(default="aether"),
    tenant_id: Optional[str] = None,
    limit: int = 500,
):
    """Export Noesis conversations visible to the authenticated caller."""
    scoped_tenant = _history_tenant_scope(request, surface, tenant_id)
    _enforce_budget(request, bucket="export", limit=10)
    data = await _conversations.export_for_scope(surface=surface, tenant_id=scoped_tenant, limit=limit)
    await _record_audit(request, event_type="noesis_conversation_export", action="export", tenant_id=scoped_tenant, metadata={"surface": surface, "count": data.get("count", 0)})
    return APIResponse(data=data).to_dict()

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
    _enforce_budget(request, bucket="query", limit=60)
    analytics = AnalyticsRepository(get_cache())
    service = NoesisService(graph=graph, analytics=analytics, conversation_store=_conversations)
    response = await service.query(body, request.state.tenant)
    await _record_audit(
        request,
        event_type="noesis_query",
        action="read",
        tenant_id=response.query_debug.get("plan", {}).get("tenant_id") if response.query_debug else request.state.tenant.tenant_id,
        resource_id=response.conversation_id,
        metadata={"surface": body.surface, "intent": response.intent, "mode": response.mode},
    )
    return APIResponse(data=response.model_dump(exclude_none=True)).to_dict()


@router.delete("/conversations/{conversation_id}")
async def delete_noesis_conversation(
    conversation_id: str,
    request: Request,
    surface: Literal["kyber", "aether"] = Query(default="aether"),
    tenant_id: Optional[str] = None,
):
    """Delete a Noesis conversation visible to the authenticated caller."""
    scoped_tenant = _history_tenant_scope(request, surface, tenant_id)
    result = await _conversations.delete(conversation_id, tenant_id=scoped_tenant, surface=surface)
    await _record_audit(request, event_type="noesis_conversation_delete", action="delete", tenant_id=scoped_tenant, resource_id=conversation_id, metadata={"surface": surface})
    return APIResponse(data=result).to_dict()


@router.post("/conversations/purge-expired")
async def purge_expired_noesis_conversations(
    request: Request,
    surface: Optional[Literal["kyber", "aether"]] = None,
    retention_days: int = Query(default=90, ge=1, le=3650),
):
    """Purge expired Noesis conversations. Operator/admin only."""
    tenant = request.state.tenant
    if not (tenant.role == Role.ADMIN or tenant.has_permission("admin") or tenant.has_permission("kyber:read")):
        raise ForbiddenError("Noesis retention purge requires operator permission")
    result = await _conversations.purge_expired(retention_days=retention_days, surface=surface)
    await _record_audit(request, event_type="noesis_conversation_purge", action="delete", tenant_id=None, metadata={"surface": surface or "all", **result})
    return APIResponse(data=result).to_dict()
