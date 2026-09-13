"""Suggestion Intelligence API routes.

* ``router``        (/v1/suggestions)                  — operator-level tenant routes
* ``admin_router``  (/v1/admin/kyber/suggestions)       — Kyber cross-tenant operator views
* ``aether_router`` (/v1/aether/suggestions)            — tenant-safe (redacted) feed

All routes are feature-gated at mount time in main.py via settings.suggestions.enabled.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from dependencies.providers import get_cache, get_graph, get_producer
from shared.common.common import APIResponse, BadRequestError, ForbiddenError
from shared.logger.logger import get_logger

from .models import (
    SuggestionActionRequest,
    SuggestionCreate,
    SuggestionFeedbackRequest,
    SuggestionOutcomeRequest,
    SuggestionQuery,
    SuggestionRejectRequest,
    SuggestionSuppressRequest,
)
from .policy import redact_for_tenant
from .repository import SuggestionRepository
from .service import SuggestionService

logger = get_logger("aether.suggestions.routes")

router = APIRouter(prefix="/v1/suggestions", tags=["Suggestion Intelligence"])
admin_router = APIRouter(
    prefix="/v1/admin/kyber/suggestions",
    tags=["Admin — Kyber Suggestions"],
)
aether_router = APIRouter(
    prefix="/v1/aether/suggestions",
    tags=["Aether — Suggestion Feed"],
)


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------

def _get_service() -> SuggestionService:
    return SuggestionService(
        repo=SuggestionRepository(),
        producer=get_producer(),
        cache=get_cache(),
        graph=get_graph(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tenant(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return tenant


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


def _require_admin_operator(request: Request):
    actor = _require_operator(request)
    request.state.tenant.require_permission("admin")
    return actor


# ═══════════════════════════════════════════════════════════════════════════
# Tenant-facing routes (/v1/suggestions)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("")
async def list_suggestions(
    request: Request,
    status: Optional[str] = Query(None),
    suggestion_class: Optional[str] = Query(None, alias="class"),
    priority: Optional[str] = Query(None),
    include_closed: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant = _tenant(request)
    svc = _get_service()
    query = SuggestionQuery(
        tenant_id=tenant.tenant_id,
        statuses=[status] if status else None,  # type: ignore[list-item]
        classes=[suggestion_class] if suggestion_class else None,  # type: ignore[list-item]
        priorities=[priority] if priority else None,  # type: ignore[list-item]
        include_closed=include_closed,
        limit=limit,
        offset=offset,
    )
    rows, total = await svc.query_suggestions(query, tenant)
    return APIResponse(data=rows, meta={"total": total, "limit": limit, "offset": offset}).to_dict()


@router.post("/query")
async def query_suggestions(request: Request, body: SuggestionQuery):
    tenant = _tenant(request)
    if body.tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenant_id mismatch")
    svc = _get_service()
    rows, total = await svc.query_suggestions(body, tenant)
    return APIResponse(data=rows, meta={"total": total}).to_dict()


@router.get("/summary")
async def get_summary(request: Request):
    tenant = _tenant(request)
    svc = _get_service()
    summary = await svc.summarize(tenant)
    return APIResponse(data=summary.model_dump()).to_dict()


@router.get("/review-queue")
async def get_review_queue(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    tenant = _tenant(request)
    svc = _get_service()
    rows = await svc.review_queue(tenant, limit=limit)
    return APIResponse(data=rows, meta={"count": len(rows)}).to_dict()


@router.post("")
async def create_suggestion(request: Request, body: SuggestionCreate):
    tenant = _tenant(request)
    tenant.require_permission("write")
    if body.tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenant_id mismatch")
    svc = _get_service()
    record = await svc.create_suggestion(body, tenant)
    return APIResponse(data=record).to_dict()


@router.get("/{suggestion_id}")
async def get_suggestion(suggestion_id: str, request: Request):
    tenant = _tenant(request)
    svc = _get_service()
    record = await svc.get_suggestion(suggestion_id, tenant)
    return APIResponse(data=record).to_dict()


@router.get("/{suggestion_id}/audit")
async def get_audit_trail(suggestion_id: str, request: Request):
    tenant = _tenant(request)
    svc = _get_service()
    trail = await svc.get_audit_trail(suggestion_id, tenant)
    return APIResponse(data=trail).to_dict()


@router.post("/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str,
    request: Request,
    body: SuggestionActionRequest,
):
    tenant = _tenant(request)
    tenant.require_permission("write")
    svc = _get_service()
    record = await svc.approve_suggestion(suggestion_id, body, tenant)
    return APIResponse(data=record).to_dict()


@router.post("/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    request: Request,
    body: SuggestionRejectRequest,
):
    tenant = _tenant(request)
    tenant.require_permission("write")
    svc = _get_service()
    record = await svc.reject_suggestion(suggestion_id, body, tenant)
    return APIResponse(data=record).to_dict()


@router.post("/{suggestion_id}/suppress")
async def suppress_suggestion(
    suggestion_id: str,
    request: Request,
    body: SuggestionSuppressRequest,
):
    tenant = _tenant(request)
    tenant.require_permission("write")
    svc = _get_service()
    record = await svc.suppress_suggestion(suggestion_id, body, tenant)
    return APIResponse(data=record).to_dict()


@router.post("/{suggestion_id}/execute")
async def execute_suggestion(
    suggestion_id: str,
    request: Request,
    body: SuggestionActionRequest,
):
    tenant = _tenant(request)
    tenant.require_permission("admin")
    from config.settings import settings
    svc = _get_service()
    record = await svc.execute_suggestion(
        suggestion_id, body, tenant,
        execution_enabled=settings.suggestions.execution_enabled,
    )
    return APIResponse(data=record).to_dict()


@router.post("/{suggestion_id}/deliver")
async def deliver_suggestion(suggestion_id: str, request: Request):
    tenant = _tenant(request)
    tenant.require_permission("write")
    svc = _get_service()
    record = await svc.deliver_suggestion(suggestion_id, tenant)
    return APIResponse(data=record).to_dict()


@router.post("/{suggestion_id}/outcome")
async def record_outcome(
    suggestion_id: str,
    request: Request,
    body: SuggestionOutcomeRequest,
):
    tenant = _tenant(request)
    tenant.require_permission("write")
    svc = _get_service()
    record = await svc.record_outcome(suggestion_id, body, tenant)
    return APIResponse(data=record).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# Kyber admin routes (/v1/admin/kyber/suggestions)
# ═══════════════════════════════════════════════════════════════════════════

@admin_router.get("")
async def admin_list_suggestions(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    suggestion_class: Optional[str] = Query(None, alias="class"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_operator(request)
    svc = _get_service()
    # Operator queries require an explicit tenant_id or fall back to operator's context
    op_tenant = getattr(request.state.tenant, "tenant_id", tenant_id or "")
    effective_tenant = tenant_id or op_tenant
    if not effective_tenant:
        raise BadRequestError("tenant_id is required for cross-tenant listing")
    query = SuggestionQuery(
        tenant_id=effective_tenant,
        statuses=[status] if status else None,  # type: ignore[list-item]
        classes=[suggestion_class] if suggestion_class else None,  # type: ignore[list-item]
        include_closed=True,
        limit=limit,
        offset=offset,
    )
    # Build a synthetic TenantContext for the target tenant
    from shared.auth.auth import TenantContext, Role
    target_ctx = TenantContext(
        tenant_id=effective_tenant,
        role=Role.ADMIN,
        permissions=["read", "write", "admin"],
    )
    rows, total = await svc.query_suggestions(query, target_ctx)
    return APIResponse(data=rows, meta={"total": total}).to_dict()


@admin_router.get("/summary")
async def admin_summary(
    request: Request,
    tenant_id: Optional[str] = Query(None),
):
    _require_operator(request)
    svc = _get_service()
    effective_tenant = tenant_id or getattr(request.state.tenant, "tenant_id", "")
    if not effective_tenant:
        raise BadRequestError("tenant_id is required")
    from shared.auth.auth import TenantContext, Role
    target_ctx = TenantContext(
        tenant_id=effective_tenant,
        role=Role.ADMIN,
        permissions=["read"],
    )
    summary = await svc.summarize(target_ctx)
    return APIResponse(data=summary.model_dump()).to_dict()


@admin_router.get("/review-queue")
async def admin_review_queue(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    _require_operator(request)
    svc = _get_service()
    effective_tenant = tenant_id or getattr(request.state.tenant, "tenant_id", "")
    if not effective_tenant:
        raise BadRequestError("tenant_id is required")
    from shared.auth.auth import TenantContext, Role
    target_ctx = TenantContext(
        tenant_id=effective_tenant,
        role=Role.ADMIN,
        permissions=["read"],
    )
    rows = await svc.review_queue(target_ctx, limit=limit)
    return APIResponse(data=rows, meta={"count": len(rows)}).to_dict()


@admin_router.get("/quality")
async def admin_quality_report(
    request: Request,
    tenant_id: Optional[str] = Query(None),
):
    _require_operator(request)
    svc = _get_service()
    effective_tenant = tenant_id or getattr(request.state.tenant, "tenant_id", "")
    if not effective_tenant:
        raise BadRequestError("tenant_id is required")
    from shared.auth.auth import TenantContext, Role
    target_ctx = TenantContext(
        tenant_id=effective_tenant,
        role=Role.ADMIN,
        permissions=["read"],
    )
    summary = await svc.summarize(target_ctx)
    repo = SuggestionRepository()
    all_rows = await repo.find_many(
        filters={"tenant_id": effective_tenant},
        limit=1000,
    )
    high_confidence = [r for r in all_rows if (r.get("confidence_score") or 0) >= 0.8]
    return APIResponse(data={
        "summary": summary.model_dump(),
        "quality_metrics": {
            "total": len(all_rows),
            "high_confidence": len(high_confidence),
            "high_confidence_pct": round(len(high_confidence) / max(len(all_rows), 1), 3),
        },
    }).to_dict()


@admin_router.get("/outcomes")
async def admin_outcomes_tracker(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    _require_operator(request)
    effective_tenant = tenant_id or getattr(request.state.tenant, "tenant_id", "")
    if not effective_tenant:
        raise BadRequestError("tenant_id is required")
    repo = SuggestionRepository()
    rows = await repo.find_many(
        filters={"tenant_id": effective_tenant},
        limit=limit,
    )
    with_outcomes = [r for r in rows if r.get("outcome")]
    return APIResponse(data=with_outcomes, meta={"total": len(with_outcomes)}).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# Aether tenant-safe routes (/v1/aether/suggestions)
# ═══════════════════════════════════════════════════════════════════════════

@aether_router.get("")
async def aether_list_suggestions(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    tenant = _tenant(request)
    svc = _get_service()
    query = SuggestionQuery(
        tenant_id=tenant.tenant_id,
        include_closed=False,
        limit=limit,
        offset=offset,
    )
    rows, total = await svc.query_suggestions(query, tenant)
    safe = [redact_for_tenant(r) for r in rows]
    return APIResponse(data=safe, meta={"total": total}).to_dict()


@aether_router.get("/{suggestion_id}")
async def aether_get_suggestion(suggestion_id: str, request: Request):
    tenant = _tenant(request)
    svc = _get_service()
    record = await svc.get_suggestion(suggestion_id, tenant)
    return APIResponse(data=redact_for_tenant(record)).to_dict()


@aether_router.post("/{suggestion_id}/feedback")
async def aether_submit_feedback(
    suggestion_id: str,
    request: Request,
    body: SuggestionFeedbackRequest,
):
    tenant = _tenant(request)
    svc = _get_service()
    result = await svc.submit_feedback(suggestion_id, body, tenant)
    return APIResponse(data=result).to_dict()
