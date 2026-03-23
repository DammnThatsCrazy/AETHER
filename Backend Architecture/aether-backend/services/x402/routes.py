"""
Aether Service — x402 Routes (L3b)
x402 payment capture, economic graph querying.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .economic_graph import X402EconomicGraph
from .interceptor import X402Interceptor
from .models import CapturedX402Transaction

logger = get_logger("aether.service.x402.routes")
router = APIRouter(prefix="/v1/x402", tags=["x402"])

_interceptor = X402Interceptor()
_economic_graph = X402EconomicGraph()


@router.post("/capture")
async def capture_payment(body: CapturedX402Transaction, request: Request):
    """Ingest a captured x402 payment from the interceptor proxy."""
    request.state.tenant.require_permission("x402:write")

    # Re-capture through the interceptor for event publishing
    tx = await _interceptor.capture(
        payer_agent_id=body.payer_agent_id,
        payee_service_id=body.payee_service_id,
        terms=body.terms,
        proof=body.proof,
        response=body.response,
        request_url=body.request_url,
        request_method=body.request_method,
    )

    # Add to economic graph (tenant-isolated)
    tenant_id = request.state.tenant.tenant_id
    await _economic_graph.add_payment(tx, tenant_id=tenant_id)

    return APIResponse(data=tx.model_dump()).to_dict()


@router.get("/graph")
async def get_economic_graph(request: Request):
    """Get the current x402 economic graph snapshot."""
    request.state.tenant.require_permission("x402:read")
    tenant_id = request.state.tenant.tenant_id
    snapshot = await _economic_graph.get_graph_snapshot(tenant_id=tenant_id)
    return APIResponse(data=snapshot).to_dict()


@router.get("/agent/{agent_id}")
async def get_agent_x402_history(agent_id: str, request: Request):
    """Get an agent's x402 payment history and spending patterns."""
    request.state.tenant.require_permission("x402:read")
    tenant_id = request.state.tenant.tenant_id
    summary = await _economic_graph.get_spending_patterns(agent_id, tenant_id=tenant_id)
    return APIResponse(data=summary.model_dump()).to_dict()


@router.post("/graph/snapshot")
async def trigger_snapshot(request: Request):
    """Manually trigger a snapshot of the economic graph to Neptune."""
    request.state.tenant.require_permission("admin")
    edges = await _economic_graph.snapshot_to_graph()
    return APIResponse(data={"edges_created": edges}).to_dict()
