"""Customer success and expansion automation for Kyber.

The module only uses tenant-scoped operational aggregates. Cross-tenant Kyber
views contain account scores and rollups, not raw tenant-private evidence.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from repositories.repos import AdminRepository
from shared.common.common import APIResponse, ForbiddenError, NotFoundError, utc_now
from services.intelligence.repositories import (
    AccountPlanRepository,
    ActionDispatchRepository,
    ActionIntegrationConfigRepository,
    CustomerSuccessAccountRepository,
    CustomerSuccessTriggerRepository,
    DecisionRepository,
    ExecutiveBusinessReviewRepository,
    ExpansionOpportunityRepository,
    OutcomeRepository,
    PlaybookRepository,
    PlaybookRunRepository,
    RecommendationFeedbackRepository,
    RecommendationRepository,
    RenewalRiskRepository,
)

CustomerLifecycleStage = Literal["signed", "implementing", "activated", "value_proven", "adopting", "expanding", "renewal_ready", "at_risk", "churned"]
TriggerType = Literal["value_proven", "expansion_ready", "renewal_risk", "playbook_underused", "integration_gap", "outcome_gap", "executive_proof_ready", "package_fit_detected", "implementation_intervention_needed"]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "in_progress", "resolved", "dismissed"]
OpportunityType = Literal["module_expansion", "usage_expansion", "integration_expansion", "services_expansion", "deployment_expansion", "audit_export_expansion", "enterprise_upgrade", "government_planning_path"]
OpportunityStatus = Literal["open", "in_progress", "won", "lost", "dismissed"]
OwnerType = Literal["olympus", "tenant", "shared"]
NextActionSource = Literal["onboarding", "outcome_ledger", "playbook_roi", "integration_health", "package_fit", "renewal_risk", "expansion_opportunity", "manual"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


class CustomerSuccessAccount(BaseModel):
    account_id: str
    tenant_id: str
    account_name: str | None = None
    lifecycle_stage: CustomerLifecycleStage
    assigned_csm_id: str | None = None
    assigned_account_exec_id: str | None = None
    package_id: str | None = None
    plan_tier: str | None = None
    renewal_date: str | None = None
    health_score: float
    expansion_score: float
    renewal_risk_score: float
    observed_value_total: float
    pending_value_total: float
    outcome_capture_rate: float
    playbook_adoption_rate: float
    integration_adoption_rate: float
    last_value_review_at: str | None = None
    next_recommended_action: str | None = None
    created_at: str
    updated_at: str


class CustomerSuccessTrigger(BaseModel):
    trigger_id: str
    tenant_id: str
    trigger_type: TriggerType
    severity: Severity
    reason: str
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str
    owner_id: str | None = None
    status: Status = "open"
    created_at: str
    resolved_at: str | None = None


class ExpansionOpportunity(BaseModel):
    opportunity_id: str
    tenant_id: str
    opportunity_type: OpportunityType
    recommended_package_id: str | None = None
    recommended_module: str | None = None
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    estimated_revenue_potential: float | None = None
    confidence: float
    recommended_sales_motion: str
    next_step: str
    status: OpportunityStatus = "open"
    created_at: str
    updated_at: str


class RenewalRisk(BaseModel):
    renewal_risk_id: str
    tenant_id: str
    risk_score: float
    primary_failure_mode: str
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    recommended_intervention: str
    owner_id: str | None = None
    renewal_date: str | None = None
    status: Status = "open"
    created_at: str
    updated_at: str


class ExecutiveBusinessReview(BaseModel):
    ebr_id: str
    tenant_id: str
    time_window: dict[str, str]
    account_summary: dict[str, Any]
    package_summary: dict[str, Any]
    implementation_summary: dict[str, Any]
    usage_summary: dict[str, Any]
    outcome_ledger_summary: dict[str, Any]
    playbook_roi_summary: dict[str, Any]
    recommendation_family_summary: dict[str, Any]
    integration_summary: dict[str, Any]
    value_created_summary: dict[str, Any]
    open_gaps: list[str]
    recommended_next_modules: list[str]
    expansion_opportunities: list[ExpansionOpportunity]
    next_90_day_plan: list[str]
    generated_at: str


class AccountNextAction(BaseModel):
    action_id: str
    tenant_id: str
    title: str
    description: str
    owner_type: OwnerType
    owner_id: str | None = None
    due_date: str | None = None
    status: Status = "open"
    source: NextActionSource
    created_at: str
    completed_at: str | None = None


class AccountPlan(BaseModel):
    account_plan_id: str
    tenant_id: str
    current_package_id: str | None = None
    target_package_id: str | None = None
    current_arr_estimate: float | None = None
    expansion_arr_estimate: float | None = None
    renewal_date: str | None = None
    strategic_objectives: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    next_actions: list[AccountNextAction] = Field(default_factory=list)
    created_at: str
    updated_at: str


class AccountPatch(BaseModel):
    account_name: str | None = None
    lifecycle_stage: CustomerLifecycleStage | None = None
    assigned_csm_id: str | None = None
    assigned_account_exec_id: str | None = None
    package_id: str | None = None
    plan_tier: str | None = None
    renewal_date: str | None = None
    last_value_review_at: str | None = None
    next_recommended_action: str | None = None


class AccountPlanInput(BaseModel):
    current_package_id: str | None = None
    target_package_id: str | None = None
    current_arr_estimate: float | None = None
    expansion_arr_estimate: float | None = None
    renewal_date: str | None = None
    strategic_objectives: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    next_actions: list[AccountNextAction] = Field(default_factory=list)


_recommendations = RecommendationRepository()
_decisions = DecisionRepository()
_feedback = RecommendationFeedbackRepository()
_outcomes = OutcomeRepository()
_playbooks = PlaybookRepository()
_runs = PlaybookRunRepository()
_integrations = ActionIntegrationConfigRepository()
_dispatches = ActionDispatchRepository()
_tenants = AdminRepository()
_accounts = CustomerSuccessAccountRepository()
_triggers = CustomerSuccessTriggerRepository()
_opportunities = ExpansionOpportunityRepository()
_renewal_risks = RenewalRiskRepository()
_ebrs = ExecutiveBusinessReviewRepository()
_account_plans = AccountPlanRepository()


async def tenant_ids() -> list[str]:
    rows = await _tenants.find_many(limit=500)
    ids = {str(r.get("tenant_id") or r.get("id")) for r in rows if r.get("tenant_id") or r.get("id")}
    for repo in (_recommendations, _decisions, _outcomes, _playbooks, _integrations):
        for row in await repo.find_many(limit=1000):
            if row.get("tenant_id"):
                ids.add(str(row["tenant_id"]))
    return sorted(ids)


async def usage_metrics(tenant_id: str) -> dict[str, Any]:
    recs = await _recommendations.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    decs = await _decisions.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    outs = await _outcomes.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    fb = await _feedback.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    playbooks = await _playbooks.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    runs = await _runs.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    integrations = await _integrations.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    dispatches = await _dispatches.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    viewed = sum(1 for r in recs if r.get("status") in {"viewed", "decided", "approved", "acted"})
    success = sum(1 for o in outs if o.get("label") == "success")
    observed = round(sum(num(o.get("value")) for o in outs), 2)
    expected = round(sum(num(r.get("expected_value")) for r in recs), 2)
    pending = round(max(expected - observed, 0), 2)
    stale = sum(1 for r in recs if r.get("status") in {"generated", "viewed"} and not any(d.get("recommendation_id") == r.get("recommendation_id") for d in decs))
    incomplete = max(len(recs) - len(outs), 0)
    failed_integrations = sum(1 for d in dispatches if d.get("status") in {"failed", "error"})
    blocker_count = sum(1 for r in runs if r.get("status") in {"blocked", "failed"})
    avg_delta = rate(sum(num(f.get("confidence_delta")) for f in fb), len(fb))
    return {
        "recommendations_generated": len(recs), "recommendations_viewed": viewed, "decisions_recorded": len(decs),
        "outcomes_observed": len(outs), "outcome_capture_rate": rate(len(outs), len(recs)), "decision_rate": rate(len(decs), len(recs)),
        "view_rate": rate(viewed, len(recs)), "success_rate": rate(success, len(outs)), "observed_value_total": observed,
        "expected_value_total": expected, "pending_value_total": pending, "playbook_adoption_rate": rate(len([r for r in runs if r.get("status") == "completed"]), max(len(playbooks), 1)),
        "integration_adoption_rate": rate(len([i for i in integrations if i.get("enabled") is not False]), 1), "recommendation_family_depth": len({r.get("recommendation_type") for r in recs if r.get("recommendation_type")}),
        "stale_loop_count": stale, "incomplete_loop_count": incomplete, "failed_integrations": failed_integrations, "blocker_count": blocker_count,
        "average_confidence_delta": avg_delta, "usage_growth": min(1.0, len(recs) / 20), "playbooks_total": len(playbooks), "runs_total": len(runs),
    }


class CustomerHealthScorer:
    def score(self, metrics: dict[str, Any]) -> tuple[float, CustomerLifecycleStage, str]:
        score = 0.18 * metrics["view_rate"] + 0.2 * metrics["decision_rate"] + 0.24 * metrics["outcome_capture_rate"] + 0.18 * metrics["success_rate"] + 0.1 * metrics["playbook_adoption_rate"] + 0.1 * metrics["integration_adoption_rate"]
        penalty = min(0.4, metrics["stale_loop_count"] * 0.03 + metrics["incomplete_loop_count"] * 0.02 + metrics["failed_integrations"] * 0.05 + metrics["blocker_count"] * 0.08)
        health = round(max(0, min(1, score - penalty)), 4)
        if metrics["recommendations_generated"] == 0:
            return health, "signed", "Complete onboarding and generate first recommendations."
        if health < 0.3 or metrics["blocker_count"]:
            return health, "at_risk", "Schedule implementation intervention and remove blockers."
        if metrics["observed_value_total"] > 0 and metrics["outcome_capture_rate"] >= 0.4:
            return health, "value_proven", "Prepare value review and executive proof points."
        if metrics["decision_rate"] >= 0.5:
            return health, "adopting", "Increase outcome capture and playbook adoption."
        return health, "activated", "Drive first decisions and action loops."


class ExpansionScorer:
    def score(self, metrics: dict[str, Any]) -> tuple[float, list[ExpansionOpportunity]]:
        value = min(1, metrics["observed_value_total"] / 10000)
        score = round(max(0, min(1, 0.34 * value + 0.2 * metrics["outcome_capture_rate"] + 0.16 * metrics["playbook_adoption_rate"] + 0.14 * metrics["integration_adoption_rate"] + 0.1 * min(1, metrics["recommendation_family_depth"] / 4) + 0.06 * metrics["usage_growth"])), 4)
        return score, []

    def opportunities(self, tenant_id: str, metrics: dict[str, Any], score: float) -> list[ExpansionOpportunity]:
        now = now_iso(); rows: list[ExpansionOpportunity] = []
        if score >= 0.55:
            rows.append(ExpansionOpportunity(opportunity_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:enterprise_upgrade")), tenant_id=tenant_id, opportunity_type="enterprise_upgrade", recommended_package_id="decision_intelligence_pro", supporting_metrics={"expansion_score": score, "observed_value_total": metrics["observed_value_total"]}, estimated_revenue_potential=max(5000, round(metrics["observed_value_total"] * 0.25, 2)), confidence=score, recommended_sales_motion="CSM-led value review with AE expansion follow-up", next_step="Package observed value proof and propose enterprise modules.", created_at=now, updated_at=now))
        if metrics["failed_integrations"] == 0 and metrics["integration_adoption_rate"] < 0.5 and metrics["outcome_capture_rate"] >= 0.3:
            rows.append(ExpansionOpportunity(opportunity_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:integration_expansion")), tenant_id=tenant_id, opportunity_type="integration_expansion", recommended_module="integration_actions", supporting_metrics={"integration_adoption_rate": metrics["integration_adoption_rate"], "outcome_capture_rate": metrics["outcome_capture_rate"]}, estimated_revenue_potential=2500, confidence=max(0.5, score), recommended_sales_motion="Implementation consult", next_step="Recommend next integration that closes outcome capture gaps.", created_at=now, updated_at=now))
        return rows


class RenewalRiskScorer:
    def score(self, metrics: dict[str, Any], last_value_review_at: str | None = None) -> tuple[float, str, str]:
        risk = (1 - metrics["view_rate"]) * 0.16 + (1 - metrics["decision_rate"]) * 0.18 + (1 - metrics["outcome_capture_rate"]) * 0.22 + min(0.22, metrics["stale_loop_count"] * 0.04 + metrics["incomplete_loop_count"] * 0.025) + min(0.12, metrics["failed_integrations"] * 0.06) + min(0.1, metrics["blocker_count"] * 0.05)
        if not last_value_review_at:
            risk += 0.08
        score = round(max(0, min(1, risk)), 4)
        failures = [("low_outcome_capture", 1 - metrics["outcome_capture_rate"]), ("low_decision_rate", 1 - metrics["decision_rate"]), ("stale_loops", metrics["stale_loop_count"]), ("failed_integrations", metrics["failed_integrations"]), ("onboarding_blockers", metrics["blocker_count"])]
        primary = max(failures, key=lambda x: x[1])[0]
        interventions = {
            "low_outcome_capture": "Run outcome ledger clean-up and tenant value capture workshop.",
            "low_decision_rate": "CSM to review recommendations with tenant owner and unblock decisions.",
            "stale_loops": "Repair stale OODA loops and assign next actions.",
            "failed_integrations": "Escalate integration failures to implementation engineering.",
            "onboarding_blockers": "Schedule implementation intervention for unresolved blockers.",
        }
        return score, primary, interventions[primary]


class EBRGenerator:
    async def generate(self, tenant_id: str, time_window: dict[str, str] | None = None) -> ExecutiveBusinessReview:
        metrics = await usage_metrics(tenant_id)
        account = await get_or_build_account(tenant_id)
        opportunities = [ExpansionOpportunity(**o) for o in await _opportunities.find_many(filters={"tenant_id": tenant_id}, limit=50)]
        gaps = []
        if metrics["outcome_capture_rate"] < 0.5: gaps.append("Outcome capture below target")
        if metrics["playbook_adoption_rate"] < 0.5: gaps.append("Playbook adoption below target")
        if metrics["failed_integrations"]: gaps.append("Integration failures require repair")
        next_modules = [o.recommended_module or o.recommended_package_id for o in opportunities if o.recommended_module or o.recommended_package_id]
        now = now_iso()
        return ExecutiveBusinessReview(
            ebr_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:ebr:{time_window or 'lifetime'}")), tenant_id=tenant_id,
            time_window=time_window or {"start": "lifetime", "end": now}, account_summary=account.model_dump(),
            package_summary={"package_id": account.package_id, "plan_tier": account.plan_tier}, implementation_summary={"blocker_count": metrics["blocker_count"]},
            usage_summary={k: metrics[k] for k in ("recommendations_generated", "decisions_recorded", "outcomes_observed", "runs_total")},
            outcome_ledger_summary={"outcomes_observed": metrics["outcomes_observed"], "outcome_capture_rate": metrics["outcome_capture_rate"]},
            playbook_roi_summary={"playbook_adoption_rate": metrics["playbook_adoption_rate"], "pending_value_total": metrics["pending_value_total"]},
            recommendation_family_summary={"family_depth": metrics["recommendation_family_depth"]}, integration_summary={"integration_adoption_rate": metrics["integration_adoption_rate"], "failed_integrations": metrics["failed_integrations"]},
            value_created_summary={"observed_value_total": metrics["observed_value_total"], "expected_value_total": metrics["expected_value_total"], "pending_value_total": metrics["pending_value_total"]},
            open_gaps=gaps, recommended_next_modules=list(dict.fromkeys([m for m in next_modules if m])), expansion_opportunities=opportunities,
            next_90_day_plan=["Capture remaining outcomes", "Review expansion fit", "Assign next actions for open gaps"], generated_at=now,
        )


async def get_or_build_account(tenant_id: str) -> CustomerSuccessAccount:
    existing = await _accounts.find_by_id(tenant_id)
    metrics = await usage_metrics(tenant_id)
    health, stage, action = CustomerHealthScorer().score(metrics)
    expansion, _ = ExpansionScorer().score(metrics)
    risk, _, _ = RenewalRiskScorer().score(metrics, existing.get("last_value_review_at") if existing else None)
    tenant = await _tenants.find_by_id(tenant_id) or {}
    now = now_iso()
    account = CustomerSuccessAccount(
        account_id=existing.get("account_id", tenant_id) if existing else tenant_id, tenant_id=tenant_id,
        account_name=(existing or {}).get("account_name") or tenant.get("name"), lifecycle_stage=(existing or {}).get("lifecycle_stage") or stage,
        assigned_csm_id=(existing or {}).get("assigned_csm_id"), assigned_account_exec_id=(existing or {}).get("assigned_account_exec_id"),
        package_id=(existing or {}).get("package_id"), plan_tier=(existing or {}).get("plan_tier") or tenant.get("plan") or tenant.get("plan_tier"), renewal_date=(existing or {}).get("renewal_date"),
        health_score=health, expansion_score=expansion, renewal_risk_score=risk, observed_value_total=metrics["observed_value_total"], pending_value_total=metrics["pending_value_total"],
        outcome_capture_rate=metrics["outcome_capture_rate"], playbook_adoption_rate=metrics["playbook_adoption_rate"], integration_adoption_rate=metrics["integration_adoption_rate"],
        last_value_review_at=(existing or {}).get("last_value_review_at"), next_recommended_action=(existing or {}).get("next_recommended_action") or action,
        created_at=(existing or {}).get("created_at") or now, updated_at=now,
    )
    await _accounts.insert(tenant_id, account.model_dump())
    return account


def severity(score: float) -> Severity:
    if score >= 0.8: return "critical"
    if score >= 0.6: return "high"
    if score >= 0.4: return "medium"
    return "low"


async def generate_for_tenant(tenant_id: str) -> dict[str, Any]:
    account = await get_or_build_account(tenant_id)
    metrics = await usage_metrics(tenant_id)
    exp_score, _ = ExpansionScorer().score(metrics)
    opportunities = ExpansionScorer().opportunities(tenant_id, metrics, exp_score)
    for op in opportunities:
        await _opportunities.insert(op.opportunity_id, op.model_dump())
    risk_score, failure, intervention = RenewalRiskScorer().score(metrics, account.last_value_review_at)
    if risk_score >= 0.55:
        risk = RenewalRisk(renewal_risk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:renewal_risk")), tenant_id=tenant_id, risk_score=risk_score, primary_failure_mode=failure, supporting_metrics=metrics, recommended_intervention=intervention, renewal_date=account.renewal_date, created_at=now_iso(), updated_at=now_iso())
        await _renewal_risks.insert(risk.renewal_risk_id, risk.model_dump())
    candidates: list[tuple[TriggerType, float, str, str]] = []
    if account.observed_value_total > 0 and account.outcome_capture_rate >= 0.4: candidates.append(("value_proven", account.health_score, "Tenant has measurable observed value.", "Prepare value review proof points."))
    if exp_score >= 0.55: candidates.append(("expansion_ready", exp_score, "Expansion score crossed readiness threshold.", "Open AE/CSM expansion motion."))
    if risk_score >= 0.55: candidates.append(("renewal_risk", risk_score, f"Renewal risk detected: {failure}.", intervention))
    if metrics["playbook_adoption_rate"] < 0.3 and metrics["recommendations_generated"] > 0: candidates.append(("playbook_underused", 0.45, "Playbook adoption is below target.", "Recommend top playbook templates."))
    if metrics["failed_integrations"] > 0: candidates.append(("integration_gap", 0.65, "Integration failures detected.", "Repair failing integration actions."))
    if metrics["outcome_capture_rate"] < 0.35 and metrics["recommendations_generated"] > 0: candidates.append(("outcome_gap", 0.55, "Recommendations are not becoming observed outcomes.", "Run outcome ledger capture workflow."))
    if account.observed_value_total >= 1000: candidates.append(("executive_proof_ready", 0.5, "Observed value is ready for executive proof.", "Generate EBR."))
    if exp_score >= 0.45: candidates.append(("package_fit_detected", exp_score, "Package/module fit indicated by usage and value.", "Review recommended package fit."))
    if metrics["blocker_count"] > 0: candidates.append(("implementation_intervention_needed", 0.7, "Implementation blockers remain open.", "Assign CSM/implementation intervention."))
    created = []
    for trigger_type, sev_score, reason, action in candidates:
        open_existing = await _triggers.open_for_tenant_type(tenant_id, trigger_type)
        if open_existing:
            continue
        trigger = CustomerSuccessTrigger(trigger_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{trigger_type}:{reason}")), tenant_id=tenant_id, trigger_type=trigger_type, severity=severity(sev_score), reason=reason, supporting_metrics=metrics, recommended_action=action, created_at=now_iso())
        await _triggers.insert(trigger.trigger_id, trigger.model_dump())
        created.append(trigger.model_dump())
    return {"account": account.model_dump(), "created_triggers": created, "expansion_opportunities": [o.model_dump() for o in opportunities]}


def require_admin(request: Request) -> None:
    request.state.tenant.require_permission("admin")


def current_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state.tenant, "tenant_id", None)
    if not tenant_id:
        raise ForbiddenError("Tenant context is required")
    return tenant_id


admin_router = APIRouter(prefix="/v1/admin/kyber/customer-success", tags=["Admin — Customer Success"])
tenant_router = APIRouter(prefix="/v1/value-review", tags=["Value Review"])


@admin_router.get("/overview")
async def overview(request: Request):
    require_admin(request)
    ids = await tenant_ids()
    accounts = [await get_or_build_account(tid) for tid in ids]
    triggers = await _triggers.find_many(limit=1000)
    risks = await _renewal_risks.find_many(limit=1000)
    ops = await _opportunities.find_many(limit=1000)
    data = {"total_customers": len(accounts), "active_customers": sum(1 for a in accounts if a.lifecycle_stage != "churned"), "value_proven_customers": sum(1 for a in accounts if a.lifecycle_stage == "value_proven"), "expansion_ready_customers": sum(1 for a in accounts if a.expansion_score >= 0.55), "at_risk_customers": sum(1 for a in accounts if a.renewal_risk_score >= 0.55 or a.lifecycle_stage == "at_risk"), "open_triggers": sum(1 for t in triggers if t.get("status") == "open"), "open_renewal_risks": sum(1 for r in risks if r.get("status") == "open"), "open_expansion_opportunities": sum(1 for o in ops if o.get("status") == "open"), "estimated_expansion_pipeline": round(sum(num(o.get("estimated_revenue_potential")) for o in ops if o.get("status") == "open"), 2), "generated_at": now_iso()}
    return APIResponse(data=data).to_dict()


@admin_router.get("/accounts")
async def accounts(request: Request):
    require_admin(request)
    return APIResponse(data={"items": [a.model_dump() for a in [await get_or_build_account(tid) for tid in await tenant_ids()]]}).to_dict()


@admin_router.get("/accounts/{tenant_id}")
async def account_detail(tenant_id: str, request: Request):
    require_admin(request)
    return APIResponse(data=(await get_or_build_account(tenant_id)).model_dump()).to_dict()


@admin_router.patch("/accounts/{tenant_id}")
async def patch_account(tenant_id: str, body: AccountPatch, request: Request):
    require_admin(request)
    account = (await get_or_build_account(tenant_id)).model_dump()
    account.update(body.model_dump(exclude_none=True)); account["updated_at"] = now_iso()
    return APIResponse(data=await _accounts.update(tenant_id, account)).to_dict()


@admin_router.get("/triggers")
async def triggers(request: Request):
    require_admin(request)
    return APIResponse(data={"items": await _triggers.find_many(limit=1000)}).to_dict()


@admin_router.post("/triggers/{trigger_id}/resolve")
async def resolve_trigger(trigger_id: str, request: Request):
    require_admin(request)
    row = await _triggers.find_by_id_or_fail(trigger_id)
    row.update({"status": "resolved", "resolved_at": now_iso()})
    return APIResponse(data=await _triggers.update(trigger_id, row)).to_dict()


@admin_router.post("/triggers/generate")
async def generate_triggers(request: Request):
    require_admin(request)
    results = [await generate_for_tenant(tid) for tid in await tenant_ids()]
    return APIResponse(data={"items": results, "count": len(results)}).to_dict()


@admin_router.get("/expansion-opportunities")
async def expansion_opportunities(request: Request):
    require_admin(request)
    return APIResponse(data={"items": await _opportunities.find_many(limit=1000)}).to_dict()


@admin_router.get("/renewal-risks")
async def renewal_risks(request: Request):
    require_admin(request)
    return APIResponse(data={"items": await _renewal_risks.find_many(limit=1000)}).to_dict()


@admin_router.get("/ebr/{tenant_id}")
async def get_ebr(tenant_id: str, request: Request):
    require_admin(request)
    rows = await _ebrs.find_many(filters={"tenant_id": tenant_id}, limit=1)
    if not rows:
        raise NotFoundError("executive_business_review")
    return APIResponse(data=rows[0]).to_dict()


@admin_router.post("/ebr/{tenant_id}/generate")
async def generate_ebr(tenant_id: str, request: Request):
    require_admin(request)
    ebr = await EBRGenerator().generate(tenant_id)
    await _ebrs.insert(ebr.ebr_id, ebr.model_dump())
    return APIResponse(data=ebr.model_dump()).to_dict()


@admin_router.get("/account-plans")
async def account_plans(request: Request):
    require_admin(request)
    return APIResponse(data={"items": await _account_plans.find_many(limit=1000)}).to_dict()


@admin_router.get("/account-plans/{tenant_id}")
async def account_plan(tenant_id: str, request: Request):
    require_admin(request)
    row = await _account_plans.find_by_id(tenant_id)
    if not row:
        raise NotFoundError("account_plan")
    return APIResponse(data=row).to_dict()


@admin_router.post("/account-plans/{tenant_id}")
async def create_account_plan(tenant_id: str, body: AccountPlanInput, request: Request):
    require_admin(request)
    now = now_iso()
    plan = AccountPlan(account_plan_id=tenant_id, tenant_id=tenant_id, created_at=now, updated_at=now, **body.model_dump())
    return APIResponse(data=await _account_plans.insert(tenant_id, plan.model_dump())).to_dict()


@admin_router.patch("/account-plans/{tenant_id}")
async def patch_account_plan(tenant_id: str, body: AccountPlanInput, request: Request):
    require_admin(request)
    existing = await _account_plans.find_by_id_or_fail(tenant_id)
    patch = body.model_dump(exclude_unset=True); patch["updated_at"] = now_iso(); existing.update(patch)
    return APIResponse(data=await _account_plans.update(tenant_id, existing)).to_dict()


async def value_review_payload(tenant_id: str) -> dict[str, Any]:
    account = await get_or_build_account(tenant_id)
    metrics = await usage_metrics(tenant_id)
    triggers = await _triggers.find_many(filters={"tenant_id": tenant_id}, limit=100)
    source_counts = Counter([t.get("trigger_type") for t in triggers])
    return {"tenant_id": tenant_id, "observed_value": metrics["observed_value_total"], "expected_value": metrics["expected_value_total"], "pending_value": metrics["pending_value_total"], "recommendations_acted_upon": metrics["decisions_recorded"], "outcomes_observed": metrics["outcomes_observed"], "top_playbooks": [], "outcome_capture_rate": metrics["outcome_capture_rate"], "incomplete_loops": metrics["incomplete_loop_count"], "recommended_next_steps": [account.next_recommended_action] if account.next_recommended_action else [], "setup_gaps": ["complete onboarding blockers"] if metrics["blocker_count"] else [], "integration_gaps": ["repair failed integrations"] if metrics["failed_integrations"] else [], "trigger_summary": dict(source_counts)}


@tenant_router.get("")
async def value_review(request: Request):
    request.state.tenant.require_permission("read")
    return APIResponse(data=await value_review_payload(current_tenant_id(request))).to_dict()


@tenant_router.get("/summary")
async def value_review_summary(request: Request):
    request.state.tenant.require_permission("read")
    payload = await value_review_payload(current_tenant_id(request))
    return APIResponse(data={k: payload[k] for k in ("observed_value", "expected_value", "pending_value", "outcome_capture_rate", "outcomes_observed")}).to_dict()


@tenant_router.get("/recommendations")
async def value_review_recommendations(request: Request):
    request.state.tenant.require_permission("read")
    tid = current_tenant_id(request); metrics = await usage_metrics(tid)
    return APIResponse(data={"recommendations_acted_upon": metrics["decisions_recorded"], "incomplete_loops": metrics["incomplete_loop_count"]}).to_dict()


@tenant_router.get("/playbooks")
async def value_review_playbooks(request: Request):
    request.state.tenant.require_permission("read")
    tid = current_tenant_id(request); metrics = await usage_metrics(tid)
    return APIResponse(data={"top_playbooks": [], "playbook_adoption_rate": metrics["playbook_adoption_rate"]}).to_dict()


@tenant_router.get("/next-steps")
async def value_review_next_steps(request: Request):
    request.state.tenant.require_permission("read")
    payload = await value_review_payload(current_tenant_id(request))
    return APIResponse(data={"recommended_next_steps": payload["recommended_next_steps"], "setup_gaps": payload["setup_gaps"], "integration_gaps": payload["integration_gaps"]}).to_dict()
