"""Cross-device continuation API — /v1/continuations (tenant / Aether).

Flag-gated INSIDE every handler via ``settings.continuation.enabled``
(``AETHER_CONTINUATION_ENABLED``, default OFF): when off the surface answers 404,
indistinguishable from an unmounted route (the exploration-fabric pattern). Reads
require the ``read`` permission, writes ``write``.

Scope is ``t:{tenant_id}``; the principal is the authenticated user (or the tenant
itself for API-key auth). Server identity always overrides the request body — a
client cannot forge principal_id / tenant_id / app_kind. The operator (Kyber)
continuation router is deferred to the Kyber-mobile milestone.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger, metrics

from services.client_sync.emitter import enqueue_sync_change
from services.continuation import service as continuation_service
from shared.continuation.models import (
    ContinuationCanonicalContext,
    ContinuationContext,
    ContinuationSummary,
    ResourceReference,
)

logger = get_logger("aether.service.continuation")
router = APIRouter(prefix="/v1/continuations", tags=["Continuation Plane"])

APP_KIND = "aether"


def _require_enabled() -> None:
    if not settings.continuation.enabled:
        raise NotFoundError("continuation plane (feature not enabled)")


def _tenant(request: Request, permission: str) -> TenantContext:
    _require_enabled()
    tenant: TenantContext = request.state.tenant
    tenant.require_permission(permission)
    return tenant


def _principal(tenant: TenantContext) -> str:
    return tenant.user_id or tenant.tenant_id


# ── Request models (client-supplied fields only) ──────────────────────────────

class ContinuationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = None
    source_client: str
    surface: str
    summary: ContinuationSummary
    canonical_context: ContinuationCanonicalContext = Field(default_factory=ContinuationCanonicalContext)
    resource_references: list[ResourceReference] = Field(default_factory=list)
    sensitivity: str = "standard"
    freshness: Optional[str] = None
    expires_at: Optional[str] = None


class ContinuationUpdate(ContinuationInput):
    expected_state_revision: int


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    resource_ids: Optional[list[str]] = None
    saved_view_id: Optional[str] = None
    query_id: Optional[str] = None
    as_of: Optional[str] = None
    expires_at: Optional[str] = None


def _build_context(inp: ContinuationInput, principal_id: str, tenant_id: str) -> ContinuationContext:
    from shared.common.common import utc_now
    return ContinuationContext(
        id=inp.id or "",  # empty → the service mints a fresh id (create)
        principal_id=principal_id,
        tenant_id=tenant_id,
        app_kind=APP_KIND,
        source_client=inp.source_client,
        surface=inp.surface,
        resource_references=inp.resource_references,
        canonical_context=inp.canonical_context,
        summary=inp.summary,
        sensitivity=inp.sensitivity,
        freshness=inp.freshness,
        expires_at=inp.expires_at,
        updated_at=utc_now().isoformat(),
    )


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.post("")
async def create_continuation(
    request: Request,
    payload: ContinuationInput,
    idempotency_key: Optional[str] = Query(default=None),
) -> APIResponse:
    tenant = _tenant(request, "write")
    principal = _principal(tenant)
    ctx = _build_context(payload, principal, tenant.tenant_id)
    result = await continuation_service.create(
        scope=continuation_service.tenant_scope(tenant.tenant_id),
        principal_id=principal,
        app_kind=APP_KIND,
        tenant_id=tenant.tenant_id,
        body=ctx,
        idempotency_key=idempotency_key,
    )
    metrics.increment("continuation_created_total", labels={"replayed": str(result.get("replayed", False))})
    await enqueue_sync_change(
        scope_key=continuation_service.tenant_scope(tenant.tenant_id),
        principal_id=principal,
        change_type="continuation_changed",
        resource_kind="continuation",
        resource_id=result.get("id"),
        revision=str(result.get("state_revision", 0)),
    )
    return APIResponse(data=result)


@router.get("/recent")
async def recent_continuations(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
) -> APIResponse:
    tenant = _tenant(request, "read")
    principal = _principal(tenant)
    rows = await continuation_service.list_recent(
        continuation_service.tenant_scope(tenant.tenant_id), principal, limit
    )
    return APIResponse(data={"continuations": rows})


@router.get("/{continuation_id}")
async def get_continuation(request: Request, continuation_id: str = Path(...)) -> APIResponse:
    tenant = _tenant(request, "read")
    row = await continuation_service.get(
        continuation_service.tenant_scope(tenant.tenant_id), continuation_id
    )
    if row is None:
        raise NotFoundError("continuation not found")
    return APIResponse(data=row)


@router.patch("/{continuation_id}")
async def update_continuation(
    request: Request,
    payload: ContinuationUpdate,
    continuation_id: str = Path(...),
) -> APIResponse:
    tenant = _tenant(request, "write")
    principal = _principal(tenant)
    ctx = _build_context(payload, principal, tenant.tenant_id).model_copy(
        update={"id": continuation_id}
    )
    # ConflictError (state_revision mismatch) propagates → HTTP 409.
    row = await continuation_service.update(
        scope=continuation_service.tenant_scope(tenant.tenant_id),
        continuation_id=continuation_id,
        expected_revision=payload.expected_state_revision,
        body=ctx,
    )
    if row is None:
        raise NotFoundError("continuation not found")
    metrics.increment("continuation_updated_total")
    await enqueue_sync_change(
        scope_key=continuation_service.tenant_scope(tenant.tenant_id),
        principal_id=principal,
        change_type="continuation_changed",
        resource_kind="continuation",
        resource_id=continuation_id,
        revision=str(row.get("state_revision", 0)),
    )
    return APIResponse(data=row)


@router.post("/{continuation_id}/handoff")
async def handoff_continuation(
    request: Request,
    payload: HandoffRequest,
    continuation_id: str = Path(...),
) -> APIResponse:
    tenant = _tenant(request, "write")
    principal = _principal(tenant)
    selection = await continuation_service.handoff(
        scope=continuation_service.tenant_scope(tenant.tenant_id),
        principal_id=principal,
        continuation_id=continuation_id,
        mode=payload.mode,
        resource_ids=payload.resource_ids,
        saved_view_id=payload.saved_view_id,
        query_id=payload.query_id,
        as_of=payload.as_of,
        expires_at=payload.expires_at,
    )
    if selection is None:
        raise NotFoundError("continuation not found")
    metrics.increment("continuation_handoff_total", labels={"mode": payload.mode})
    return APIResponse(data=selection)


@router.delete("/{continuation_id}")
async def delete_continuation(request: Request, continuation_id: str = Path(...)) -> APIResponse:
    tenant = _tenant(request, "write")
    deleted = await continuation_service.delete(
        continuation_service.tenant_scope(tenant.tenant_id), continuation_id
    )
    if not deleted:
        raise NotFoundError("continuation not found")
    await enqueue_sync_change(
        scope_key=continuation_service.tenant_scope(tenant.tenant_id),
        principal_id=_principal(tenant),
        change_type="continuation_changed",
        resource_kind="continuation",
        resource_id=continuation_id,
    )
    return APIResponse(data={"deleted": True, "id": continuation_id})
