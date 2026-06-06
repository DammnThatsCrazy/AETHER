"""
Aether — Retarget Recommendation API Routes

GET  /v1/recommendations/{entity_id}          — list recommendations for entity
POST /v1/recommendations/{id}/approve         — analyst approval
POST /v1/recommendations/{id}/reject          — reject with reason
GET  /v1/recommendations/{id}/status          — execution status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from dependencies.providers import get_provider_gateway
from repositories.repos import RecommendationRepository
from services.recommendations.executor import RecommendationExecutor
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

logger = get_logger("aether.recommendations.routes")

router = APIRouter(prefix="/v1/recommendations", tags=["recommendations"])

_rec_repo = RecommendationRepository()


def _summary(items: list[dict]) -> dict:
    counts: dict[str, int] = {"pending_review": 0, "approved": 0, "rejected": 0, "executed": 0, "expired": 0}
    for item in items:
        s = item.get("status", "pending_review")
        counts[s] = counts.get(s, 0) + 1
    return {"total": len(items), **counts}


class ApproveRequest(BaseModel):
    reviewed_by: str
    review_notes: str | None = None


class RejectRequest(BaseModel):
    reviewed_by: str
    reason: str


@router.get("/{entity_id}")
async def list_recommendations(
    entity_id: str,
    request: Request,
    status: str | None = Query(default=None, description="Filter by status: pending_review, approved, rejected, executed, expired"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List retargeting recommendations for an entity sorted by retarget_score descending."""
    tenant_id = request.state.tenant.tenant_id
    items = await _rec_repo.list_for_entity(entity_id, tenant_id, status=status, limit=limit)
    items.sort(key=lambda r: (r.get("retarget_score", 0), r.get("created_at", "")), reverse=True)
    return APIResponse(data={
        "entity_id": entity_id,
        "kind": "retarget_recommendations",
        "items": items,
        "summary": _summary(items),
        "pagination": {"limit": limit, "count": len(items), "has_more": len(items) == limit},
        "computed_at": items[0].get("created_at") if items else None,
    }).to_dict()


@router.post("/{recommendation_id}/approve")
async def approve_recommendation(
    recommendation_id: str,
    body: ApproveRequest,
    request: Request,
    provider_gateway=Depends(get_provider_gateway),
):
    """Analyst approval — triggers ad platform audience sync via RecommendationExecutor."""
    tenant_id = request.state.tenant.tenant_id
    request.state.tenant.require_permission("read")

    rec = await _rec_repo.get(recommendation_id, tenant_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Recommendation {recommendation_id} not found")
    if rec["status"] != "pending_review":
        raise HTTPException(
            status_code=409,
            detail=f"Recommendation is not in pending_review state (current: {rec['status']})",
        )

    # Mark approved before execution so executor sees correct state
    await _rec_repo.update_status(
        recommendation_id, tenant_id, "approved",
        reviewed_by=body.reviewed_by,
        review_notes=body.review_notes,
    )

    # Attempt ad-platform execution
    from repositories.repos import BaseRepository
    audit_repo = BaseRepository("consent_audit_log")
    executor = RecommendationExecutor(
        provider_registry=provider_gateway,
        recommendation_repo=_rec_repo,
        audit_log_repo=audit_repo,
    )
    try:
        updated = await executor.execute(
            recommendation_id,
            tenant_id,
            reviewed_by=body.reviewed_by,
            review_notes=body.review_notes,
        )
    except Exception as exc:
        logger.error(f"Executor failed for {recommendation_id}: {exc}")
        raise HTTPException(status_code=502, detail=f"Ad platform execution failed: {exc}") from exc

    return APIResponse(data=updated).to_dict()


@router.post("/{recommendation_id}/reject")
async def reject_recommendation(
    recommendation_id: str,
    body: RejectRequest,
    request: Request,
):
    """Reject a retargeting recommendation with a reason (final)."""
    tenant_id = request.state.tenant.tenant_id
    request.state.tenant.require_permission("read")

    rec = await _rec_repo.get(recommendation_id, tenant_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Recommendation {recommendation_id} not found")
    if rec["status"] in ("rejected", "executed"):
        raise HTTPException(status_code=409, detail=f"Recommendation already in terminal state: {rec['status']}")

    updated = await _rec_repo.update_status(
        recommendation_id, tenant_id, "rejected",
        reviewed_by=body.reviewed_by,
        review_notes=body.reason,
    )
    return APIResponse(data=updated).to_dict()


@router.get("/{recommendation_id}/status")
async def get_recommendation_status(
    recommendation_id: str,
    request: Request,
):
    """Get the current execution status of a recommendation."""
    tenant_id = request.state.tenant.tenant_id
    rec = await _rec_repo.get(recommendation_id, tenant_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Recommendation {recommendation_id} not found")
    return APIResponse(data={
        "recommendation_id": recommendation_id,
        "status": rec.get("status", "pending_review"),
        "reviewed_by": rec.get("reviewed_by"),
        "review_notes": rec.get("review_notes"),
        "executed_at": rec.get("executed_at"),
        "ad_platform_response": rec.get("ad_platform_response"),
        "retarget_score": rec.get("retarget_score"),
        "recommended_platform": rec.get("recommended_platform"),
    }).to_dict()
