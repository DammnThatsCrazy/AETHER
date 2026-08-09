"""
Aether Backend — Kyber Operator Reward Routes

Operator-only (Kyber workforce / legacy operator) read surface for the reward
enablement service, consumed by the Kyber UI pages:

    GET /v1/admin/kyber/rewards/health
        Platform reward-health summary: rail support matrix, proof lifecycle
        counts, reconcile status. Every configured rail reports a support bucket
        (never silent) via the commerce rail matrix.
    GET /v1/admin/kyber/tenants/{tenant_id}/campaigns?limit&offset
    GET /v1/admin/kyber/tenants/{tenant_id}/decisions?limit&offset
    GET /v1/admin/kyber/tenants/{tenant_id}/actions?limit&offset
    GET /v1/admin/kyber/tenants/{tenant_id}/audit?limit&offset

All endpoints are fail-closed: ``require_kyber_operator`` denies any Aether
tenant and any unauthenticated caller. All are read-only.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Query, Request
from shared.decorators import api_response
from shared.logger.logger import get_logger

from services.rewards.repositories import (
    RewardActionRepository,
    RewardAuditRepository,
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardProofRepository,
    RewardReceiptRepository,
)

logger = get_logger("aether.service.rewards.operator")

router = APIRouter(prefix="/v1/admin/kyber", tags=["Kyber Operator"])


def _require_kyber_operator(request: Request):
    from services.security.request_context import require_kyber_operator as _canonical_kyber_gate
    return _canonical_kyber_gate(request)


# ═══════════════════════════════════════════════════════════════════════════
# REWARD HEALTH
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/rewards/health", response_model=None)
@api_response
async def rewards_health(request: Request):
    """Platform reward-enablement health snapshot for the Kyber operator page."""
    _require_kyber_operator(request)

    # Rail support matrix: every configured rail reports one of four buckets.
    try:
        from services.commerce.rail_matrix import (
            RailSupport,
            all_declared_rails,
            classify_rail,
            unsupported_reason,
        )
        rail_matrix = [
            {
                "rail": rail,
                "support": classify_rail(rail).value,
                "reason": unsupported_reason(rail),
            }
            for rail in all_declared_rails()
        ]
        rail_summary: dict[str, int] = {}
        for entry in rail_matrix:
            bucket = entry["support"]
            rail_summary[bucket] = rail_summary.get(bucket, 0) + 1
    except Exception as exc:  # pragma: no cover - matrix is internal
        rail_matrix = []
        rail_summary = {"error": str(exc)}

    proof_repo = RewardProofRepository()
    proofs = await proof_repo.find_many(filters={}, limit=10000)
    proofs_by_status: dict[str, int] = {}
    for p in proofs:
        s = p.get("status", "unknown")
        proofs_by_status[s] = proofs_by_status.get(s, 0) + 1

    receipts = await RewardReceiptRepository().find_many(filters={}, limit=10000)

    # Claim reconciliation status (proofs used vs receipts confirmed).
    from services.rewards.reconcile import get_reward_claim_reconciler
    reconcile_status = {
        "proofs_by_status": proofs_by_status,
        "receipts_total": len(receipts),
    }
    try:
        reconcile_status = await get_reward_claim_reconciler().claim_reconciliation_status(
            os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")
        )
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        reconcile_status["error"] = str(exc)

    env = os.getenv("AETHER_ENV", "local").lower()
    return {
        "env": env,
        "status": "ok",
        "rails": {
            "matrix": rail_matrix,
            "summary": rail_summary,
        },
        "proofs_by_status": proofs_by_status,
        "receipts_total": len(receipts),
        "claim_reconciliation": reconcile_status,
        "healthy": True,
    }


# ═══════════════════════════════════════════════════════════════════════════
# TENANT-SCOPED REWARD DATA (read-only, limit/offset paginated)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/tenants/{tenant_id}/campaigns", response_model=None)
@api_response
async def tenant_campaigns(
    request: Request,
    tenant_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List reward campaigns for a tenant (operator)."""
    _require_kyber_operator(request)
    return await RewardCampaignRepository().list(tenant_id, limit=limit, offset=offset)


@router.get("/tenants/{tenant_id}/decisions", response_model=None)
@api_response
async def tenant_decisions(
    request: Request,
    tenant_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List eligibility decisions for a tenant (operator)."""
    _require_kyber_operator(request)
    return await RewardDecisionRepository().list(tenant_id, limit=limit, offset=offset)


@router.get("/tenants/{tenant_id}/actions", response_model=None)
@api_response
async def tenant_actions(
    request: Request,
    tenant_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List reward action payloads for a tenant (operator)."""
    _require_kyber_operator(request)
    return await RewardActionRepository().list(tenant_id, limit=limit, offset=offset)


@router.get("/tenants/{tenant_id}/audit", response_model=None)
@api_response
async def tenant_audit(
    request: Request,
    tenant_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    target_type: Optional[str] = Query(None),
):
    """List the append-only reward audit log for a tenant (operator)."""
    _require_kyber_operator(request)
    filters: dict = {"tenant_id": tenant_id}
    if target_type:
        filters["target_type"] = target_type
    return await RewardAuditRepository().find_many(filters=filters, limit=limit, offset=offset)


__all__ = ["router"]
