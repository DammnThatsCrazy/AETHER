"""Unified Exploration Fabric API — /v1/explore.

Tenant-scoped exploration workbench: validate a context (dry-run
applicability), run a query or facets against a surface adapter, persist and
resolve saved views, and resolve context-preserving navigation links.

Flag-gated INSIDE every handler via ``settings.exploration.enabled``
(``AETHER_EXPLORATION_ENABLED``, default OFF): when the flag is off the surface
answers 404 (NotFoundError), indistinguishable from an unmounted route. Reads
require the ``read`` permission, writes ``write``. Every submitted filter is
accounted for in the response applicability — silent filter drops are
structurally impossible.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.settings import settings
from dependencies.providers import get_cache, get_graph
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, ForbiddenError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics

from shared.contracts_models.filters import FilterExpression, FilterGroup
from shared.exploration.models import (
    ExplorationAnchor,
    ExplorationContextV1,
    ExplorationOperation,
    PivotSpec,
    TemporalSelection,
)
from services.exploration import service as exploration_service
from services.exploration.store import ExplorationViewRepository
from services.client_sync.emitter import enqueue_sync_change

logger = get_logger("aether.service.exploration")
router = APIRouter(prefix="/v1/explore", tags=["Exploration Fabric"])

_views = ExplorationViewRepository()


def _require_enabled() -> None:
    if not settings.exploration.enabled:
        raise NotFoundError("exploration fabric (feature not enabled)")


def _tenant(request: Request, permission: str) -> TenantContext:
    _require_enabled()
    tenant: TenantContext = request.state.tenant
    tenant.require_permission(permission)
    return tenant


def _bind_scope(context: ExplorationContextV1, tenant: TenantContext) -> ExplorationContextV1:
    """Force the context scope onto the authenticated tenant."""
    if context.scope.tenant_id and context.scope.tenant_id != tenant.tenant_id:
        raise ForbiddenError("context scope tenant_id does not match authenticated tenant")
    if context.scope.tenant_id == tenant.tenant_id:
        return context
    return context.model_copy(
        update={"scope": context.scope.model_copy(update={"tenant_id": tenant.tenant_id})}
    )


def _count_dispositions(applicability: dict[str, Any]) -> None:
    for entry in applicability.get("entries", []):
        metrics.increment(
            "exploration_filter_dispositions_total",
            labels={"disposition": entry.get("disposition", "unknown")},
        )


# ── Request models ────────────────────────────────────────────────────────────

class _ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ExplorationContextV1

    @field_validator("context", mode="before")
    @classmethod
    def _coerce_context(cls, value: Any) -> Any:
        if isinstance(value, ExplorationContextV1):
            return value
        if isinstance(value, BaseModel) and value.__class__.__name__ == "ExplorationContextV1":
            return value.model_dump(mode="python")
        return value


class ValidateRequest(_ContextRequest):
    pass


class QueryRequest(_ContextRequest):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: Optional[str] = None


class FacetRequest(_ContextRequest):
    fields: list[str] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=500)


class ViewUpsertRequest(_ContextRequest):
    view_id: Optional[str] = None
    name: str


class LinkResolveRequest(_ContextRequest):
    to: str
    focus: Optional[ExplorationAnchor] = None


class SessionCreateRequest(_ContextRequest):
    session_id: Optional[str] = None


class SessionOperationRequest(BaseModel):
    """Apply one operation to an existing session.

    ``filter_delta`` carries a ``FilterGroup`` (for FILTER_ADD) or a
    ``{"fields": [...]}`` list of field ids (for FILTER_REMOVE).
    """

    model_config = ConfigDict(extra="forbid")

    operation: ExplorationOperation
    pivot: Optional[PivotSpec] = None
    lens_ids: Optional[list[str]] = None
    temporal: Optional[TemporalSelection] = None
    focus: Optional[ExplorationAnchor] = None
    filter_delta: Optional[dict] = None
    temporal_mode: Optional[str] = None


def _filter_group_from_delta(filter_delta: Optional[dict]) -> Optional[FilterGroup]:
    """Coerce a route ``filter_delta`` into a canonical ``FilterGroup``.

    FILTER_ADD sends a ``FilterGroup`` shape; FILTER_REMOVE sends a
    ``{"fields": [...]}`` list whose leaf fields identify what to remove.
    """
    if not filter_delta:
        return None
    if "logic" in filter_delta:
        return FilterGroup.model_validate(filter_delta)
    fields = filter_delta.get("fields")
    if isinstance(fields, list) and fields:
        return FilterGroup(
            logic="AND",
            expressions=[FilterExpression(field=str(f), op="eq") for f in fields],
        )
    return None


# ── Validate / Query / Facets ─────────────────────────────────────────────────

@router.post("/validate")
async def validate_context(request: Request, payload: ValidateRequest) -> APIResponse:
    tenant = _tenant(request, "read")
    context = _bind_scope(payload.context, tenant)
    result = exploration_service.validate(context)
    metrics.increment("exploration_validate_total")
    _count_dispositions(result["applicability"])
    return APIResponse(data=result)


@router.post("/query")
async def query_surface(
    request: Request,
    payload: QueryRequest,
    graph=Depends(get_graph),
    cache=Depends(get_cache),
) -> APIResponse:
    tenant = _tenant(request, "read")
    context = _bind_scope(payload.context, tenant)
    envelope = await exploration_service.execute_query(
        context,
        request=request,
        graph=graph,
        cache=cache,
        limit=payload.limit,
        cursor=payload.cursor,
    )
    metrics.increment("exploration_queries_total")
    _count_dispositions(envelope.applicability.model_dump(mode="json"))
    return APIResponse(data={"envelope": envelope.model_dump(mode="json")})


@router.post("/facets")
async def facet_surface(
    request: Request,
    payload: FacetRequest,
    graph=Depends(get_graph),
    cache=Depends(get_cache),
) -> APIResponse:
    tenant = _tenant(request, "read")
    context = _bind_scope(payload.context, tenant)
    envelope = await exploration_service.execute_facets(
        context,
        payload.fields,
        request=request,
        graph=graph,
        cache=cache,
        limit=payload.limit,
    )
    metrics.increment("exploration_facets_total")
    data = envelope.data or {}
    suppressed = sum(
        int(f.get("suppressed_bucket_count", 0)) for f in data.get("facets", [])
    )
    if suppressed:
        metrics.increment(
            "exploration_facet_suppressed_total", labels={"count": str(suppressed)}
        )
    return APIResponse(data={"envelope": envelope.model_dump(mode="json")})


# ── Saved views ───────────────────────────────────────────────────────────────

@router.get("/views")
async def list_views(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await _views.list_scoped(tenant.tenant_id, limit=limit, offset=offset)
    return APIResponse(data={"views": rows})


@router.post("/views")
async def upsert_view(request: Request, payload: ViewUpsertRequest) -> APIResponse:
    tenant = _tenant(request, "write")
    context = _bind_scope(payload.context, tenant)
    view_id = payload.view_id or str(uuid.uuid4())
    record = {
        "view_id": view_id,
        "name": payload.name,
        "context": context.model_dump(mode="json"),
        "created_by": tenant.user_id,
        "saved_at": utc_now().isoformat(),
    }
    stored = await _views.upsert_scoped(tenant.tenant_id, view_id, record)
    metrics.increment("exploration_saved_views_total")
    await enqueue_sync_change(
        scope_key=f"t:{tenant.tenant_id}",
        principal_id=tenant.user_id or tenant.tenant_id,
        change_type="saved_view_changed",
        resource_kind="saved_view",
        resource_id=view_id,
    )
    return APIResponse(data={"view": stored})


@router.get("/views/{view_id}")
async def get_view(request: Request, view_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    record = await _views.get_scoped(tenant.tenant_id, view_id)
    if record is None:
        raise NotFoundError("exploration saved view")
    return APIResponse(data={"view": record})


@router.delete("/views/{view_id}")
async def delete_view(request: Request, view_id: str) -> APIResponse:
    tenant = _tenant(request, "write")
    deleted = await _views.delete_scoped(tenant.tenant_id, view_id)
    if not deleted:
        raise NotFoundError("exploration saved view")
    await enqueue_sync_change(
        scope_key=f"t:{tenant.tenant_id}",
        principal_id=tenant.user_id or tenant.tenant_id,
        change_type="saved_view_changed",
        resource_kind="saved_view",
        resource_id=view_id,
    )
    return APIResponse(data={"deleted": view_id})


# ── Context-preserving navigation links ───────────────────────────────────────

@router.post("/links/resolve")
async def resolve_link(request: Request, payload: LinkResolveRequest) -> APIResponse:
    """Retarget a context to another surface, preserving filters.

    Returns the retargeted ``ContextLink`` plus the destination surface's
    applicability — so the caller sees exactly how each filter carries over
    (applied / not-applicable / unsupported) before navigating.
    """
    tenant = _tenant(request, "read")
    context = _bind_scope(payload.context, tenant)
    retargeted = context.model_copy(
        update={"scope": context.scope.model_copy(update={"surface": payload.to})}
    )
    result = exploration_service.validate(retargeted)
    _count_dispositions(result["applicability"])
    return APIResponse(
        data={
            "link": {
                "to": payload.to,
                "context": retargeted.model_dump(mode="json"),
                "focus": payload.focus.model_dump(mode="json") if payload.focus else None,
            },
            "applicability": result["applicability"],
            "adapter_available": result["adapter_available"],
            "warnings": result["warnings"],
        }
    )


# ── Exploration sessions + operations (S5) ────────────────────────────────────

@router.post("/sessions")
async def create_session(
    request: Request, payload: SessionCreateRequest
) -> APIResponse:
    tenant = _tenant(request, "write")
    context = _bind_scope(payload.context, tenant)
    session = await exploration_service.create_session(
        context, tenant_id=tenant.tenant_id, session_id=payload.session_id
    )
    metrics.increment("exploration_sessions_total")
    return APIResponse(data={"session": session.model_dump(mode="json")})


@router.get("/sessions")
async def list_sessions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await exploration_service.list_sessions(
        tenant.tenant_id, limit=limit, offset=offset
    )
    return APIResponse(data={"sessions": rows})


@router.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    session = await exploration_service.load_session(tenant.tenant_id, session_id)
    if session is None:
        raise NotFoundError("exploration session")
    return APIResponse(data={"session": session.model_dump(mode="json")})


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> APIResponse:
    tenant = _tenant(request, "write")
    deleted = await exploration_service.delete_session(tenant.tenant_id, session_id)
    if not deleted:
        raise NotFoundError("exploration session")
    metrics.increment("exploration_sessions_deleted_total")
    return APIResponse(data={"deleted": session_id})


@router.post("/sessions/{session_id}/operations")
async def apply_session_operation(
    request: Request, session_id: str, payload: SessionOperationRequest
) -> APIResponse:
    tenant = _tenant(request, "write")
    result = await exploration_service.execute_operation(
        None,
        payload.operation,
        tenant_id=tenant.tenant_id,
        request=request,
        session_id=session_id,
        pivot=payload.pivot,
        lens_ids=payload.lens_ids,
        temporal=payload.temporal,
        filter_group=_filter_group_from_delta(payload.filter_delta),
        focus=payload.focus,
        temporal_mode=payload.temporal_mode,
    )
    metrics.increment(
        "exploration_operations_total", labels={"operation": payload.operation}
    )
    session = await exploration_service.load_session(tenant.tenant_id, session_id)
    return APIResponse(
        data={
            "result": result.model_dump(mode="json"),
            "session": session.model_dump(mode="json") if session else None,
        }
    )
