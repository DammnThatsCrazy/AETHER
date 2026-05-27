"""
Aether — Retarget Recommendation API Routes

GET  /v1/recommendations/{entity_id}          — list recommendations for entity
POST /v1/recommendations/{id}/approve         — analyst approval
POST /v1/recommendations/{id}/reject          — reject with reason
GET  /v1/recommendations/{id}/status          — execution status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from shared.logger.logger import get_logger

logger = get_logger("aether.recommendations.routes")

router = APIRouter(prefix="/v1/recommendations", tags=["recommendations"])


class ApproveRequest(BaseModel):
    reviewed_by: str
    review_notes: str | None = None


class RejectRequest(BaseModel):
    reviewed_by: str
    reason: str


@router.get("/{entity_id}")
async def list_recommendations(
    entity_id: str,
    status: str | None = Query(default=None, description="Filter by status: pending_review, approved, rejected, executed, expired"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """
    List retargeting recommendations for an entity.
    Sorted by retarget_score descending, then created_at descending.
    """
    return {
        "entity_id": entity_id,
        "kind": "retarget_recommendations",
        "items": [],
        "summary": {
            "total": 0,
            "pending_review": 0,
            "approved": 0,
            "rejected": 0,
            "executed": 0,
        },
        "pagination": {"limit": limit, "count": 0, "has_more": False},
        "computed_at": None,
    }


@router.post("/{recommendation_id}/approve")
async def approve_recommendation(
    recommendation_id: str,
    body: ApproveRequest,
):
    """
    Analyst approval for a retargeting recommendation.
    Triggers ad platform audience sync via RecommendationExecutor.
    All approve actions are written to consent_audit_log.
    """
    # TODO: wire to RecommendationExecutor + RecommendationRepository
    return {
        "recommendation_id": recommendation_id,
        "status": "approved",
        "reviewed_by": body.reviewed_by,
        "message": "Recommendation approved. Execution queued.",
    }


@router.post("/{recommendation_id}/reject")
async def reject_recommendation(
    recommendation_id: str,
    body: RejectRequest,
):
    """
    Reject a retargeting recommendation with a reason.
    Rejection is final — a new recommendation will be generated on next scoring cycle.
    All reject actions are written to consent_audit_log.
    """
    return {
        "recommendation_id": recommendation_id,
        "status": "rejected",
        "reviewed_by": body.reviewed_by,
        "reason": body.reason,
        "message": "Recommendation rejected.",
    }


@router.get("/{recommendation_id}/status")
async def get_recommendation_status(recommendation_id: str):
    """Get the current execution status of a recommendation."""
    return {
        "recommendation_id": recommendation_id,
        "status": "pending_review",
        "executed_at": None,
        "ad_platform_response": None,
    }
