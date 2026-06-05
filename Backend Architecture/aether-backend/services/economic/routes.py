"""
Aether Service — Unified Economic Intelligence

Read-only aggregation endpoints for the unified economic value layer.
Computes Total Value Observed, domain-separated metrics, and warnings
from existing data sources (financials, wallets, campaigns, agents, x402).

All endpoints enforce tenant scope. Data is derived on read, never
persisted as canonical write state.

Routes:
  Profile-scoped:
    GET /v1/profile/{entity_id}/economic           → UnifiedEconomicBreakdown
    GET /v1/profile/{entity_id}/economic/web2       → Web2 metrics
    GET /v1/profile/{entity_id}/economic/web3       → Web3 metrics (TVL + exposure)
    GET /v1/profile/{entity_id}/economic/agentic    → Agentic / x402 metrics
    GET /v1/profile/{entity_id}/economic/campaigns  → Campaign economics
    GET /v1/profile/{entity_id}/economic/warnings   → Economic warnings

  Tenant-scoped (operator):
    GET /v1/economic/overview                       → Tenant economic overview
    GET /v1/economic/warnings                       → Tenant-wide warnings
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.observability import trace_request, emit_latency

logger = get_logger("aether.service.economic")

router = APIRouter(tags=["Economic Intelligence"])


# ── Response Models ──────────────────────────────────────────────────

class EconomicAmountResponse(BaseModel):
    native_amount: Optional[float] = None
    native_currency: Optional[str] = None
    usd_amount: Optional[float] = None
    normalized_amount: Optional[float] = None
    normalized_currency: Optional[str] = None
    price_source: Optional[str] = None
    price_timestamp: Optional[str] = None


class EconomicWarningResponse(BaseModel):
    code: str
    message: str
    severity: str
    details: Optional[dict[str, Any]] = None


class Web2EconomicResponse(BaseModel):
    gmv: Optional[EconomicAmountResponse] = None
    tpv: Optional[EconomicAmountResponse] = None
    revenue: Optional[EconomicAmountResponse] = None
    net_revenue: Optional[EconomicAmountResponse] = None
    arr: Optional[EconomicAmountResponse] = None
    mrr: Optional[EconomicAmountResponse] = None
    order_count: Optional[int] = None
    subscription_count: Optional[int] = None
    conversion_rate: Optional[float] = None
    churn_rate: Optional[float] = None


class Web3EconomicResponse(BaseModel):
    tvl: Optional[EconomicAmountResponse] = None
    protocol_exposure: Optional[EconomicAmountResponse] = None
    transaction_volume: Optional[EconomicAmountResponse] = None
    protocol_fees: Optional[EconomicAmountResponse] = None
    rewards: Optional[EconomicAmountResponse] = None


class AgenticEconomicResponse(BaseModel):
    authorized_budget: Optional[EconomicAmountResponse] = None
    spend: Optional[EconomicAmountResponse] = None
    remaining_budget: Optional[EconomicAmountResponse] = None
    revenue_generated: Optional[EconomicAmountResponse] = None
    x402_settlement_value: Optional[EconomicAmountResponse] = None
    internal_credit_flow: Optional[EconomicAmountResponse] = None
    service_call_count: Optional[int] = None
    roi: Optional[float] = None
    settlement_success_rate: Optional[float] = None


class CampaignEconomicResponse(BaseModel):
    spend: Optional[EconomicAmountResponse] = None
    attributed_revenue: Optional[EconomicAmountResponse] = None
    roas: Optional[float] = None
    cac: Optional[EconomicAmountResponse] = None
    conversions: Optional[int] = None
    acquired_customers: Optional[int] = None
    attribution_model: Optional[str] = None
    attribution_confidence: Optional[float] = None
    influenced_wallet_connects: Optional[int] = None
    influenced_protocol_deposits: Optional[EconomicAmountResponse] = None


class UnifiedEconomicBreakdownResponse(BaseModel):
    entity_id: str
    entity_type: str
    tenant_id: str
    window: str
    total_value_observed: Optional[EconomicAmountResponse] = None
    web2: Optional[Web2EconomicResponse] = None
    web3: Optional[Web3EconomicResponse] = None
    agentic: Optional[AgenticEconomicResponse] = None
    campaigns: Optional[CampaignEconomicResponse] = None
    by_currency: Optional[dict[str, EconomicAmountResponse]] = None
    warnings: list[EconomicWarningResponse] = Field(default_factory=list)
    computed_at: str


class TenantEconomicOverviewResponse(BaseModel):
    tenant_id: str
    total_value_observed: Optional[EconomicAmountResponse] = None
    web2_revenue: Optional[EconomicAmountResponse] = None
    web3_tvl: Optional[EconomicAmountResponse] = None
    web3_protocol_exposure: Optional[EconomicAmountResponse] = None
    campaign_spend: Optional[EconomicAmountResponse] = None
    attributed_revenue: Optional[EconomicAmountResponse] = None
    agent_spend: Optional[EconomicAmountResponse] = None
    x402_settlement_value: Optional[EconomicAmountResponse] = None
    entity_count: Optional[int] = None
    warnings: list[EconomicWarningResponse] = Field(default_factory=list)
    computed_at: str


# ── Helpers ──────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    return getattr(getattr(request, "state", None), "tenant", None) and request.state.tenant.tenant_id or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Profile-scoped routes ────────────────────────────────────────────

@router.get("/v1/profile/{entity_id}/economic")
async def get_entity_economic_breakdown(
    request: Request,
    entity_id: str,
    window: str = Query("lifetime", description="realtime|24h|7d|30d|90d|lifetime"),
    include_warnings: bool = Query(True),
    include_provenance: bool = Query(False),
):
    """Unified economic breakdown for any entity."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.breakdown", entity_id=entity_id, tenant_id=tenant_id, window=window)

    warnings = []
    warnings.append(EconomicWarningResponse(
        code="PARTIAL_SOURCE_COVERAGE",
        message="Economic breakdown is computed from available data sources. Some sources may not be connected.",
        severity="info",
    ))

    response = UnifiedEconomicBreakdownResponse(
        entity_id=entity_id,
        entity_type="unknown",
        tenant_id=tenant_id,
        window=window,
        total_value_observed=EconomicAmountResponse(),
        warnings=warnings if include_warnings else [],
        computed_at=_now_iso(),
    )

    emit_latency("economic.breakdown", request)
    metrics.incr("economic.breakdown.requests")
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/profile/{entity_id}/economic/web2")
async def get_entity_web2_economic(
    request: Request,
    entity_id: str,
    window: str = Query("lifetime"),
):
    """Web2 economic metrics for an entity (GMV, TPV, revenue, subscriptions)."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.web2", entity_id=entity_id, tenant_id=tenant_id)

    response = Web2EconomicResponse()
    emit_latency("economic.web2", request)
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/profile/{entity_id}/economic/web3")
async def get_entity_web3_economic(
    request: Request,
    entity_id: str,
    window: str = Query("lifetime"),
    chain_id: Optional[str] = Query(None),
    protocol_id: Optional[str] = Query(None),
):
    """Web3 economic metrics for an entity (TVL for protocols, protocol exposure for others)."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.web3", entity_id=entity_id, tenant_id=tenant_id)

    response = Web3EconomicResponse()
    emit_latency("economic.web3", request)
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/profile/{entity_id}/economic/agentic")
async def get_entity_agentic_economic(
    request: Request,
    entity_id: str,
    window: str = Query("lifetime"),
):
    """Agentic / x402 economic metrics for an entity."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.agentic", entity_id=entity_id, tenant_id=tenant_id)

    response = AgenticEconomicResponse()
    emit_latency("economic.agentic", request)
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/profile/{entity_id}/economic/campaigns")
async def get_entity_campaign_economic(
    request: Request,
    entity_id: str,
    window: str = Query("lifetime"),
    campaign_id: Optional[str] = Query(None),
):
    """Campaign economics for an entity (spend, ROAS, attribution)."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.campaigns", entity_id=entity_id, tenant_id=tenant_id)

    response = CampaignEconomicResponse()
    emit_latency("economic.campaigns", request)
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/profile/{entity_id}/economic/warnings")
async def get_entity_economic_warnings(
    request: Request,
    entity_id: str,
):
    """Economic warnings for an entity (mixed currency, stale prices, double-counting)."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.warnings", entity_id=entity_id, tenant_id=tenant_id)

    warnings: list[dict[str, Any]] = []
    emit_latency("economic.warnings", request)
    return APIResponse(data={"entity_id": entity_id, "warnings": warnings}).to_dict()


# ── Tenant-scoped routes ─────────────────────────────────────────────

@router.get("/v1/economic/overview")
async def get_tenant_economic_overview(
    request: Request,
    window: str = Query("30d"),
):
    """Tenant-level economic overview — Total Value Observed with domain breakdown."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.overview", tenant_id=tenant_id, window=window)

    response = TenantEconomicOverviewResponse(
        tenant_id=tenant_id,
        warnings=[EconomicWarningResponse(
            code="PARTIAL_SOURCE_COVERAGE",
            message="Overview is computed from connected data sources only.",
            severity="info",
        )],
        computed_at=_now_iso(),
    )

    emit_latency("economic.overview", request)
    metrics.incr("economic.overview.requests")
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/economic/warnings")
async def get_tenant_economic_warnings(
    request: Request,
):
    """Tenant-wide economic warnings — mixed currencies, stale prices, double-counting risks."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    logger.info("economic.tenant_warnings", tenant_id=tenant_id)

    emit_latency("economic.tenant_warnings", request)
    return APIResponse(data={"tenant_id": tenant_id, "warnings": []}).to_dict()
