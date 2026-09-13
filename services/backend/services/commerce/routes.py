"""
Aether Service — Commerce Routes (L3a)
Payment recording, agent hiring, fee elimination reporting, per-agent economics,
and cross-cutting analytics (revenue, cluster spend, treasury, facilitator performance).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .models import AgentHireRecord, PaymentRecord
from .service import CommerceService
from .economic_analytics import CommerceEconomicAnalytics
from services.agent.economic import AgentEconomicViews

logger = get_logger("aether.service.commerce.routes")
router = APIRouter(prefix="/v1/commerce", tags=["Commerce"])

_service = CommerceService()
_agent_economics = AgentEconomicViews()
_analytics = CommerceEconomicAnalytics()


@router.post("/payments")
async def record_payment(body: PaymentRecord, request: Request):
    """Record a payment and create PAYS edge in the intelligence graph."""
    request.state.tenant.require_permission("commerce:write")
    result = await _service.record_payment(body, request.state.tenant.tenant_id)
    return APIResponse(data=result.model_dump()).to_dict()


@router.post("/hires")
async def record_hire(body: AgentHireRecord, request: Request):
    """Record an agent hiring another agent and create HIRED edge."""
    request.state.tenant.require_permission("commerce:write")
    result = await _service.record_hire(body, request.state.tenant.tenant_id)
    return APIResponse(data=result.model_dump()).to_dict()


@router.get("/fees/report")
async def fee_elimination_report(request: Request, period: str = "all"):
    """Get fee elimination report showing savings from crypto payments vs cards."""
    request.state.tenant.require_permission("commerce:read")
    report = await _service.get_fee_elimination_report(period)
    return APIResponse(data=report.model_dump()).to_dict()


@router.get("/agent/{agent_id}/spend")
async def agent_spend_history(agent_id: str, request: Request):
    """Get spending history for a specific agent."""
    request.state.tenant.require_permission("commerce:read")
    result = await _service.get_agent_spend(agent_id)
    return APIResponse(data=result).to_dict()


@router.get("/agents/{agent_id}/economics")
async def agent_economic_profile(agent_id: str, request: Request):
    """Full economic profile: budget usage, delegation policy, and economic identity."""
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id
    result = await _agent_economics.full_economic_profile(agent_id, tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/revenue/{service_id}")
async def service_revenue(service_id: str, request: Request, period: str = "30d"):
    """Service revenue over a time window (settled payments attributed to service_id)."""
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id
    result = await _analytics.service_revenue(service_id, tenant_id, period)
    return APIResponse(data=result).to_dict()


@router.get("/cluster/{cluster_id}/spend")
async def cluster_spend(cluster_id: str, request: Request, period: str = "30d"):
    """Cluster spend analytics: settled volume and unique agents for a cluster."""
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id
    result = await _analytics.cluster_spend(cluster_id, tenant_id, period)
    return APIResponse(data=result).to_dict()


@router.get("/treasury")
async def treasury_balance(request: Request):
    """Treasury balance, preferred rails, and spend runway estimate."""
    request.state.tenant.require_permission("commerce:admin")
    tenant_id = request.state.tenant.tenant_id
    result = await _analytics.treasury_balance(tenant_id)
    return APIResponse(data=result).to_dict()


@router.get("/facilitators/performance")
async def facilitator_performance(request: Request, period: str = "30d"):
    """Per-facilitator performance matrix: volume, success rate, transaction count."""
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id
    result = await _analytics.facilitator_performance(tenant_id, period)
    return APIResponse(data=result).to_dict()
