"""Read-only consent PolicyDecision evidence surface."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services.policy.engine import consent_policy_engine
from services.security.request_context import tenant_actor

router = APIRouter(prefix="/v1/policy", tags=["Policy"])


@router.get("/decisions")
async def list_policy_decisions(request: Request, limit: int = 100) -> dict:
    """List consent policy decisions for the calling tenant (evidence trail)."""
    actor = tenant_actor(request)
    decisions = await consent_policy_engine.list_decisions(actor.tenant_id, limit=limit)
    return {"decisions": decisions, "count": len(decisions)}
