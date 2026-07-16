"""Aether Service — Identity graph↔repo reconciliation API.

Operator + tenant surface over :mod:`services.identity.graph_reconciliation`.
The reconciliation job diffs the repository's non-revoked SAME_AS edges against
the graph backend and reports drift (edges present in one store but missing /
revoked in the other).

Routes:
    GET  /v1/identity/reconciliation                  Tenant-scoped summary
                                                       (latest run or fresh check)
    POST /v1/admin/kyber/identity/reconciliation      Kyber-operator trigger for
                                                       an arbitrary tenant

This module exports only ``router``; mounting is done by the app orchestrator
(main.py), not here. The router carries no prefix — each route declares its full
path — because the two surfaces live under different roots (``/v1/identity`` vs
``/v1/admin/kyber``) yet must ship as a single mountable router.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from services.security.request_context import require_kyber_operator

from .graph_reconciliation import (
    get_latest_reconciliation_run,
    reconcile_identity_edges,
    repair_identity_edges,
)

logger = get_logger("aether.service.identity.reconciliation")

# No prefix: the tenant route lives under /v1/identity and the operator route
# under /v1/admin/kyber, so each declares its full path.
router = APIRouter(tags=["Identity"])


class ReconciliationTriggerRequest(BaseModel):
    """Operator request to reconcile a specific tenant's identity edges."""

    tenant_id: str = Field(..., description="Tenant whose identity edges to reconcile.")
    entity_ids: Optional[list[str]] = Field(
        default=None,
        description="Optional bounded set of canonical entity ids to check; "
        "omit to scan a bounded sample of the tenant's edges.",
    )


class ReconciliationRepairRequest(ReconciliationTriggerRequest):
    """Audited, idempotent repair request; dry-run is intentionally the default."""

    dry_run: bool = Field(
        default=True,
        description="Plan only unless explicitly set false by a Kyber operator.",
    )
    request_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Idempotency key for safe retries.",
    )
    reason: str = Field(
        default="operator requested reconciliation repair",
        min_length=3,
        max_length=500,
    )


@router.get("/v1/identity/reconciliation")
async def get_identity_reconciliation(
    request: Request,
    refresh: bool = Query(
        False,
        description="Force a fresh reconciliation instead of returning the latest run.",
    ),
) -> dict:
    """Return the identity repo↔graph reconciliation summary for this tenant.

    By default returns the most recent persisted run; when none exists (or
    ``refresh=true``) a fresh, tenant-scoped reconciliation is executed and
    persisted. Requires ``read`` permission.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    if not refresh:
        latest = await get_latest_reconciliation_run(tenant.tenant_id)
        if latest is not None:
            return APIResponse(data={**latest, "fresh": False}).to_dict()

    result = await reconcile_identity_edges(tenant.tenant_id)
    return APIResponse(data={**result, "fresh": True}).to_dict()


@router.post("/v1/admin/kyber/identity/reconciliation")
async def trigger_identity_reconciliation(
    body: ReconciliationTriggerRequest,
    request: Request,
) -> dict:
    """Kyber-operator-gated reconciliation trigger for an arbitrary tenant.

    Fail-closed via ``require_kyber_operator``: no Aether tenant (including
    role-admins) may reach this cross-tenant surface. Runs a fresh
    reconciliation for ``body.tenant_id`` and returns the drift summary.
    """
    require_kyber_operator(request)

    result = await reconcile_identity_edges(
        body.tenant_id,
        entity_ids=body.entity_ids,
    )
    logger.info(
        "kyber identity reconciliation: tenant=%s checked=%s drift=%s",
        body.tenant_id, result["checked"], result["drift_count"],
    )
    return APIResponse(data=result).to_dict()


@router.post("/v1/admin/kyber/identity/reconciliation/repair")
async def trigger_identity_reconciliation_repair(
    body: ReconciliationRepairRequest,
    request: Request,
) -> dict:
    """Plan or apply exact repo-authoritative identity graph repairs."""

    require_kyber_operator(request)
    actor_id = (
        getattr(request.state, "operator_id", None)
        or getattr(request.state, "subject_id", None)
        or "kyber-operator"
    )
    result = await repair_identity_edges(
        body.tenant_id,
        dry_run=body.dry_run,
        request_id=body.request_id,
        actor_id=str(actor_id),
        reason=body.reason,
        entity_ids=body.entity_ids,
    )
    logger.info(
        "kyber identity repair tenant=%s run=%s dry_run=%s status=%s",
        body.tenant_id,
        result["id"],
        body.dry_run,
        result["status"],
    )
    return APIResponse(data=result).to_dict()
