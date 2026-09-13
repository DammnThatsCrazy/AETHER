"""AI Outcome Efficiency / AI Economics routes.

* ``ai_router`` (``/v1/economic/ai``) — tenant-authenticated reads over AI
  execution facts, workflow economics, model rollups, price cards, and
  efficiency findings. Observation and governed proposals only — nothing
  here changes production models, prompts, or routing.
* ``kyber_router`` (``/v1/admin/kyber/ai-efficiency``) — operator-gated
  fleet health. Cross-tenant aggregates never expose raw tenant content.

Every route is flag-gated: tenant routes on ``settings.ai_economics.enabled``;
Kyber routes accept ``enabled`` OR ``kyber_enabled``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from services.economic import ai_aggregation, ai_efficiency
from services.economic.ai_models import (
    AI_INVOCATION_STATUSES,
    AIPriceCardRates,
    COST_BASES,
)
from services.economic.ai_pricing import (
    PLATFORM_TENANT_ID,
    get_price_card_registry,
    utc_now_iso,
)

logger = get_logger("aether.economic.ai_routes")

ai_router = APIRouter(prefix="/v1/economic/ai", tags=["AI Economics"])
kyber_router = APIRouter(
    prefix="/v1/admin/kyber/ai-efficiency", tags=["Admin — Kyber AI Efficiency"]
)

_MAX_LIMIT = 500


def _require_ai_economics_enabled() -> None:
    if not settings.ai_economics.enabled:
        raise BadRequestError(
            "AI Economics is not enabled (AETHER_AI_OUTCOME_EFFICIENCY_ENABLED=false)"
        )


def _require_kyber_enabled() -> None:
    flags = settings.ai_economics
    if not (flags.enabled or flags.kyber_enabled):
        raise BadRequestError(
            "Kyber AI efficiency surfaces are not enabled (KYBER_AI_EFFICIENCY_HEALTH_ENABLED=false)"
        )


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


# ── Tenant routes ──────────────────────────────────────────────────────────

@ai_router.get("/summary")
async def ai_economics_summary(request: Request):
    """Aggregate AI economics for the tenant: per-currency totals + coverage."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request)
    summary = await ai_aggregation.tenant_summary(tenant_id)
    return APIResponse(data=summary).to_dict()


@ai_router.get("/invocations")
async def list_ai_invocations(
    request: Request,
    workflow_run_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    cost_basis: Optional[str] = None,
    agent_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
):
    """Filterable AI execution fact listing (tenant-scoped)."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request)
    if status is not None and status not in AI_INVOCATION_STATUSES:
        raise BadRequestError(f"Unknown status: {status}")
    if cost_basis is not None and cost_basis not in COST_BASES:
        raise BadRequestError(f"Unknown cost_basis: {cost_basis}")
    facts = await ai_aggregation.list_facts(
        tenant_id,
        workflow_run_id=workflow_run_id,
        provider=provider,
        model=model,
        task_type=task_type,
        status=status,
        cost_basis=cost_basis,
        agent_id=agent_id,
        campaign_id=campaign_id,
        since=since,
        until=until,
        limit=max(1, min(limit, _MAX_LIMIT)),
    )
    return APIResponse(data={"invocations": facts, "count": len(facts)}).to_dict()


@ai_router.get("/workflows")
async def list_ai_workflows(request: Request, limit: int = 100):
    """Persisted workflow economics for the tenant."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request)
    workflows = await ai_aggregation.list_workflow_economics(
        tenant_id, limit=max(1, min(limit, _MAX_LIMIT))
    )
    return APIResponse(data={"workflows": workflows, "count": len(workflows)}).to_dict()


@ai_router.post("/workflows/{workflow_run_id}/recompute")
async def recompute_ai_workflow(workflow_run_id: str, request: Request):
    """Recompute workflow economics from facts (404 when no facts exist)."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request, "write")
    economics = await ai_aggregation.recompute_workflow(tenant_id, workflow_run_id)
    if economics is None:
        raise NotFoundError(f"No AI execution facts for workflow_run_id {workflow_run_id}")
    return APIResponse(data={"workflow": economics.model_dump(mode="json")}).to_dict()


@ai_router.get("/models")
async def ai_model_rollup(request: Request):
    """Per provider+model rollup: invocations, per-currency cost, latency,
    success rate, average quality."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request)
    facts = await ai_aggregation.list_facts(tenant_id)
    return APIResponse(data={"models": ai_aggregation.model_rollup(facts)}).to_dict()


@ai_router.get("/waste")
async def ai_waste_findings(request: Request):
    """Deterministic efficiency detector findings (evidence-backed, proposals only)."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request)
    findings = await ai_efficiency.run_detectors(tenant_id)
    return APIResponse(data={"findings": findings, "count": len(findings)}).to_dict()


class PriceCardCreate(BaseModel):
    """Tenant-scoped price card creation payload."""

    provider: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=256)
    region: Optional[str] = Field(default=None, max_length=256)
    service_tier: Optional[str] = Field(default=None, max_length=256)
    currency: str = Field(min_length=1, max_length=16)
    pricing_version: str = Field(min_length=1, max_length=256)
    rates: AIPriceCardRates
    effective_from: str = Field(min_length=1)
    effective_to: Optional[str] = None


@ai_router.get("/price-cards")
async def list_price_cards(
    request: Request,
    provider: Optional[str] = None,
    model: Optional[str] = None,
):
    """Tenant + platform price cards (platform defaults seeded idempotently)."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request)
    registry = get_price_card_registry()
    await registry.ensure_seed_cards()
    cards = await registry.list_cards(tenant_id=tenant_id, provider=provider, model=model)
    return APIResponse(data={"price_cards": cards, "count": len(cards)}).to_dict()


@ai_router.post("/price-cards")
async def create_price_card(body: PriceCardCreate, request: Request):
    """Create a tenant-scoped, effective-dated price card."""
    _require_ai_economics_enabled()
    tenant_id = _tenant_id(request, "write")
    registry = get_price_card_registry()
    payload: dict[str, Any] = body.model_dump(mode="json")
    payload["id"] = f"pc-{uuid.uuid4().hex[:12]}"
    payload["source"] = "tenant"
    payload["created_at"] = utc_now_iso()
    try:
        card = await registry.add_card(payload, tenant_id=tenant_id)
    except (ValidationError, ValueError) as exc:
        raise BadRequestError(f"Invalid price card: {exc}")
    metrics.increment("ai_price_card_created_total", labels={"provider": card.provider})
    return APIResponse(data={"price_card": card.model_dump(mode="json")}).to_dict()


@ai_router.get("/recommendations")
async def ai_efficiency_recommendations(request: Request):
    """Detector findings shaped as governed proposals — never auto-executed."""
    _require_ai_economics_enabled()
    if not settings.ai_economics.recommendations_enabled:
        raise BadRequestError(
            "AI efficiency recommendations are not enabled "
            "(AETHER_AI_EFFICIENCY_RECOMMENDATIONS_ENABLED=false)"
        )
    tenant_id = _tenant_id(request)
    findings = await ai_efficiency.run_detectors(tenant_id)
    proposals = [
        {
            "proposal_id": f"ai-eff-{uuid.uuid4().hex[:12]}",
            "family": "ai_outcome_efficiency",
            "tenant_id": tenant_id,
            "detector": finding["detector"],
            "severity": finding["severity"],
            "title": finding["title"],
            "description": finding["description"],
            "candidate_action": finding["candidate_action"],
            "evidence_refs": finding["evidence_refs"],
            "estimated_monthly_waste": finding["estimated_monthly_waste"],
            "requires_approval": True,
            "required_approval_level": "standard",
            "execution": "proposal_only",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        for finding in findings
    ]
    return APIResponse(data={"recommendations": proposals, "count": len(proposals)}).to_dict()


# ── Kyber operator routes ──────────────────────────────────────────────────

@kyber_router.get("/health")
async def ai_efficiency_fleet_health(request: Request):
    """Cross-tenant AI economics aggregates — counters only, no tenant content."""
    _require_kyber_enabled()
    _require_operator(request)

    store = get_store(ai_aggregation.AI_EXECUTION_FACTS_STORE)
    facts = await store.find()
    tenants = sorted({f.get("tenant_id") for f in facts if f.get("tenant_id")})

    known = sum(1 for f in facts if f.get("cost_basis") != "unknown")
    unknown = len(facts) - known
    quality_counts: dict[str, int] = defaultdict(int)
    basis_counts: dict[str, int] = defaultdict(int)
    for fact in facts:
        quality_counts[fact.get("data_quality_status", "unknown")] += 1
        basis_counts[fact.get("cost_basis", "unknown")] += 1

    detector_counts: dict[str, int] = defaultdict(int)
    for tenant in tenants:
        tenant_facts = [f for f in facts if f.get("tenant_id") == tenant]
        for finding in await ai_efficiency.run_detectors(tenant, facts=tenant_facts):
            detector_counts[finding["detector"]] += 1

    return APIResponse(data={
        "tenants_observed": len(tenants),
        "fact_count": len(facts),
        "cost_coverage_rate": (known / len(facts)) if facts else None,
        "unknown_cost_share": (unknown / len(facts)) if facts else None,
        "facts_by_cost_basis": dict(basis_counts),
        "facts_by_data_quality": dict(quality_counts),
        "detector_finding_counts": dict(detector_counts),
    }).to_dict()


@kyber_router.get("/{tenant_id}")
async def ai_efficiency_tenant_diagnostics(tenant_id: str, request: Request):
    """Per-tenant AI economics drilldown for operators."""
    _require_kyber_enabled()
    _require_operator(request)

    summary = await ai_aggregation.tenant_summary(tenant_id)
    findings = await ai_efficiency.run_detectors(tenant_id)
    workflows = await ai_aggregation.list_workflow_economics(tenant_id, limit=50)
    registry = get_price_card_registry()
    tenant_cards = await registry.list_cards(tenant_id=tenant_id, include_platform=False)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "summary": summary,
        "findings": findings,
        "workflow_count": len(workflows),
        "tenant_price_card_count": len(
            [c for c in tenant_cards if c.get("tenant_id") != PLATFORM_TENANT_ID]
        ),
    }).to_dict()
