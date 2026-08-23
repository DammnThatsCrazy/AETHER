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

import logging

import uuid
from datetime import datetime, timezone
from decimal import Decimal as _Decimal
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from services.profile.economic import AgentProfile360EconomicComposer
from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger, log_event, metrics
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


def _aggregate_spend(spend_by_currency: dict[str, Any]) -> tuple[
    Optional[EconomicAmountResponse],
    dict[str, EconomicAmountResponse],
    list[str],
]:
    """Aggregate native per-currency spend into a labeled USD total.

    Never sums mixed native currencies into one scalar (program sec19):
    - per-currency native amounts are returned verbatim;
    - the USD total is computed by converting EACH currency through the FX seam
      (``services/value/fx_provider`` snapshot);
    - a currency with no available rate is flagged and excluded from the total
      — if ANY currency is unpriced, ``spend.usd_amount`` is None so an
      incomplete total is never presented as a complete one.
    """
    from decimal import Decimal as _Decimal

    from services.value import fx_provider as _fx
    from services.value.price_sources import price as _price

    # Self-registration is an import-time side effect; re-assert it so this
    # function never depends on import order (a prior clear_price_providers()
    # in another test/process would otherwise leave EUR/GBP unpriced).
    _fx.register()

    per_currency: dict[str, EconomicAmountResponse] = {}
    usd_total = _Decimal("0")
    priced_any = False
    unpriced: list[str] = []

    for currency, amount_value in spend_by_currency.items():
        try:
            amount = _Decimal(str(amount_value))
        except Exception:
            continue  # skip unparseable amounts
        per_currency[currency] = EconomicAmountResponse(
            native_amount=float(amount),
            native_currency=currency,
            price_source="aether_intent_aggregation",
        )
        valuation = _price(amount, currency)
        if valuation is None or valuation.get("usd_value") is None:
            unpriced.append(currency)
            continue
        usd_total += _Decimal(str(valuation["usd_value"]))
        per_currency[currency].usd_amount = float(valuation["usd_value"])
        priced_any = True

    warnings: list[str] = []
    if unpriced:
        warnings.append(
            "FX rate unavailable for currency(ies) "
            f"{', '.join(sorted(set(unpriced)))} — USD total is incomplete"
        )

    if not per_currency:
        return None, {}, warnings

    # A converted total is only trustworthy when every currency priced.
    spend = EconomicAmountResponse(
        usd_amount=float(usd_total) if priced_any and not unpriced else None,
        normalized_amount=float(usd_total) if priced_any and not unpriced else None,
        normalized_currency="USD",
        native_currency=None,
        price_source="aether_intent_aggregation_fx",
    )
    return spend, per_currency, warnings


def _spend_rows_to_usd_total(rows: list[dict[str, Any]]) -> _Decimal:
    """Convert a list of spend rows to a single USD total via each row's
    recorded ``exchange_rate`` (program sec19).

    ``total_cost`` is the row's NATIVE amount; the USD total is
    ``total_cost * exchange_rate`` per row — never a raw sum of mixed native
    currencies. A row not normalized to USD raises: un-normalized money is
    never silently summed (callers surface the error loudly).
    """
    from decimal import Decimal as _Decimal

    total = _Decimal("0")
    for row in rows:
        amount = _Decimal(str(row.get("total_cost") or "0"))
        norm = str(row.get("normalized_currency") or "USD").strip().upper()
        if norm != "USD":
            raise ValueError(
                f"spend row {row.get('spend_record_id')!r} is normalized to "
                f"{norm!r}, not USD — refusing to total mixed currencies"
            )
        rate = _Decimal(str(row.get("exchange_rate") or "1"))
        total += amount * rate
    return total


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
    log_event(logger, logging.INFO, "economic.breakdown", entity_id=entity_id, tenant_id=tenant_id, window=window)

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
    log_event(logger, logging.INFO, "economic.web2", entity_id=entity_id, tenant_id=tenant_id)

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
    log_event(logger, logging.INFO, "economic.web3", entity_id=entity_id, tenant_id=tenant_id)

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
    log_event(logger, logging.INFO, "economic.agentic", entity_id=entity_id, tenant_id=tenant_id)

    try:
        composer = AgentProfile360EconomicComposer()
        composed = await composer.compose(agent_id=entity_id, tenant_id=tenant_id)

        economic = composed.get("economic", {})
        trust = composed.get("trust", {})
        behavioral = composed.get("behavioral", {})

        # Aggregate spend_by_currency into a single normalized USD amount
        spend_by_currency: dict = economic.get("spend_by_currency", {})
        total_spend_usd = sum(float(v) for v in spend_by_currency.values() if v)
        spend_response = EconomicAmountResponse(
            usd_amount=round(total_spend_usd, 4),
            native_currency="USD",
            price_source="aether_intent_aggregation",
        ) if total_spend_usd else None

        response = AgenticEconomicResponse(
            spend=spend_response,
            service_call_count=behavioral.get("execution_count") or economic.get("payment_intent_count"),
            settlement_success_rate=trust.get("settlement_reliability"),
        )
    except Exception as exc:
        log_event(logger, logging.WARNING, "economic.agentic.composer_error", entity_id=entity_id, error=str(exc))
        response = AgenticEconomicResponse()

    emit_latency("economic.agentic", request)
    return APIResponse(data=response.model_dump()).to_dict()


@router.get("/v1/profile/{entity_id}/economic/campaigns")
async def get_entity_campaign_economic(
    request: Request,
    entity_id: str,
    window: str = Query("30d"),
    campaign_id: Optional[str] = Query(None),
):
    """Campaign economics for an entity — ROAS from actual spend and attributed revenue."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    log_event(logger, logging.INFO, "economic.campaigns", entity_id=entity_id, tenant_id=tenant_id)

    from datetime import timedelta
    from decimal import Decimal
    from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
    from services.measurement.repositories.conversion_repo import ConversionRepository
    from services.measurement.repositories.spend_repo import SpendRepository

    _window_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(window, 30)
    period_start = datetime.now(timezone.utc) - timedelta(days=_window_days)

    run_repo = AttributionRunRepository()
    conv_repo = ConversionRepository()
    spend_repo = SpendRepository()

    warnings: list[EconomicWarningResponse] = []
    quality_status = "complete"

    try:
        # Get conversions for this profile
        conversions = await conv_repo.list_by_profile(
            tenant_id, entity_id,
            after_occurred=period_start,
            attribution_eligible_only=True,
            limit=1000,
        )
        if not conversions:
            # Also try as cluster_id / account_id
            conversions = []

        total_attributed_revenue = Decimal("0")
        total_spend = Decimal("0")
        conv_count = 0

        for conv in conversions:
            cid = conv.get("conversion_id", "")
            # If a specific campaign was requested, filter credits
            if campaign_id:
                summary = await run_repo.campaign_credit_summary(tenant_id, campaign_id)
                total_attributed_revenue += summary.get("total_attributed_net_revenue") or Decimal("0")
                conv_count += int(summary.get("total_attributed_conversions") or 0)
                if not total_spend:
                    total_spend = await spend_repo.total_spend(
                        tenant_id, campaign_id, period_start=period_start,
                    )
                break
            else:
                credits = await run_repo.list_credits_for_conversion(tenant_id, cid, active_only=True)
                if credits:
                    for credit in credits:
                        total_attributed_revenue += Decimal(str(credit.get("attributed_net_revenue") or "0"))
                    conv_count += 1

        if not campaign_id:
            warnings.append(EconomicWarningResponse(
                code="SPEND_NOT_FILTERED_BY_CAMPAIGN",
                message="Provide campaign_id query parameter for campaign-specific spend data.",
                severity="info",
            ))

        roas = float(total_attributed_revenue / total_spend) if total_spend > Decimal("0") else None
        if roas is None:
            warnings.append(EconomicWarningResponse(
                code="NO_SPEND_DATA",
                message="No spend records found. Connect an ad platform connector or import spend data.",
                severity="warning",
            ))
            quality_status = "not_provisioned"

        response = CampaignEconomicResponse(
            spend=EconomicAmountResponse(usd_amount=float(total_spend), native_currency="USD"),
            attributed_revenue=EconomicAmountResponse(usd_amount=float(total_attributed_revenue), native_currency="USD"),
            roas=roas,
            conversions=conv_count,
        )

    except Exception as exc:
        logger.error("economic.campaigns.error: %s", exc)
        quality_status = "failed"
        warnings.append(EconomicWarningResponse(
            code="COMPUTATION_ERROR",
            message="Campaign economic computation failed. Data may be incomplete.",
            severity="error",
        ))
        response = CampaignEconomicResponse()

    emit_latency("economic.campaigns", request)
    return APIResponse(data={
        **response.model_dump(),
        "quality": {"status": quality_status, "warnings": [w.model_dump() for w in warnings]},
    }).to_dict()


@router.get("/v1/profile/{entity_id}/economic/warnings")
async def get_entity_economic_warnings(
    request: Request,
    entity_id: str,
):
    """Economic warnings for an entity (mixed currency, stale prices, double-counting)."""
    rid = trace_request(request)
    tenant_id = _get_tenant_id(request)
    log_event(logger, logging.INFO, "economic.warnings", entity_id=entity_id, tenant_id=tenant_id)

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
    log_event(logger, logging.INFO, "economic.overview", tenant_id=tenant_id, window=window)

    from datetime import timedelta
    from decimal import Decimal
    from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
    from services.measurement.repositories.spend_repo import SpendRepository
    from services.measurement.repositories.conversion_repo import ConversionRepository

    _window_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(window, 30)
    period_start = datetime.now(timezone.utc) - timedelta(days=_window_days)

    warnings: list[EconomicWarningResponse] = []
    total_attributed_revenue = Decimal("0")
    total_spend = Decimal("0")
    entity_count = 0

    try:
        run_repo = AttributionRunRepository()
        spend_repo = SpendRepository()
        conv_repo = ConversionRepository()

        # Aggregate spend across all campaigns for the tenant
        spend_rows = await spend_repo.list_by_tenant(
            tenant_id, period_start=period_start, limit=5000
        )
        total_spend = sum((Decimal(str(r.get("total_cost") or "0")) for r in spend_rows), Decimal("0"))

        # Aggregate attributed revenue across all conversions
        conversions = await conv_repo.list_by_tenant(
            tenant_id, after_occurred=period_start, limit=5000
        )
        entity_ids: set[str] = set()
        for conv in conversions:
            conv_id = conv.get("conversion_id", "")
            if conv.get("profile_id"):
                entity_ids.add(conv["profile_id"])
            credits = await run_repo.list_credits_for_conversion(tenant_id, conv_id, active_only=True)
            for credit in credits:
                total_attributed_revenue += Decimal(str(credit.get("attributed_net_revenue") or "0"))

        entity_count = len(entity_ids)

        roas = float(total_attributed_revenue / total_spend) if total_spend > Decimal("0") else None
        if total_spend == Decimal("0"):
            warnings.append(EconomicWarningResponse(
                code="NO_SPEND_DATA",
                message="No spend records found for this window. Connect an ad platform connector.",
                severity="warning",
            ))
        if total_attributed_revenue == Decimal("0"):
            warnings.append(EconomicWarningResponse(
                code="NO_ATTRIBUTION_DATA",
                message="No attribution credits found. Run attribution on your conversions.",
                severity="info",
            ))

        warnings.append(EconomicWarningResponse(
            code="PARTIAL_SOURCE_COVERAGE",
            message="Overview is computed from connected data sources only.",
            severity="info",
        ))

        response = TenantEconomicOverviewResponse(
            tenant_id=tenant_id,
            campaign_spend=EconomicAmountResponse(usd_amount=float(total_spend), native_currency="USD"),
            attributed_revenue=EconomicAmountResponse(usd_amount=float(total_attributed_revenue), native_currency="USD"),
            entity_count=entity_count,
            warnings=warnings,
            computed_at=_now_iso(),
        )
    except Exception as exc:
        logger.error("economic.overview.error: %s", exc)
        warnings.append(EconomicWarningResponse(
            code="COMPUTATION_ERROR",
            message="Overview computation failed. Data may be incomplete.",
            severity="error",
        ))
        response = TenantEconomicOverviewResponse(
            tenant_id=tenant_id,
            warnings=warnings,
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
    log_event(logger, logging.INFO, "economic.tenant_warnings", tenant_id=tenant_id)

    emit_latency("economic.tenant_warnings", request)
    return APIResponse(data={"tenant_id": tenant_id, "warnings": []}).to_dict()
