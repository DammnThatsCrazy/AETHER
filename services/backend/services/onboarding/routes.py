"""Tenant and Kyber routes for customer onboarding implementation lifecycle."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, utc_now
from services.security.request_context import require_kyber_operator
from .models import (
    BlockerStatus,
    CustomerSuccessTrigger,
    ImplementationBlocker,
    ImplementationStep,
    ImplementationStepStatus,
    TenantImplementationPlan,
)
from .repositories import (
    CustomerSuccessTriggerRepository,
    ImplementationBlockerRepository,
    ImplementationStepRepository,
    OnboardingTemplateRepository,
    TenantImplementationPlanRepository,
)
from .scoring import (
    expansion_readiness_score,
    generate_customer_success_triggers,
    go_live_readiness_score,
    implementation_health_score,
    infer_stage,
    value_readiness_score,
)
from .templates import ONBOARDING_TEMPLATES

router = APIRouter(prefix="/v1/onboarding", tags=["Customer Onboarding"])
admin_router = APIRouter(
    prefix="/v1/admin/kyber/onboarding",
    tags=["Admin — Kyber Customer Implementation"],
    dependencies=[Depends(require_kyber_operator)],
)

_plans = TenantImplementationPlanRepository()
_steps = ImplementationStepRepository()
_blockers = ImplementationBlockerRepository()
_templates = OnboardingTemplateRepository()
_triggers = CustomerSuccessTriggerRepository()


class StepPatch(BaseModel):
    status: ImplementationStepStatus | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    completed_at: str | None = None


class PlanCreate(BaseModel):
    package_id: str | None = None
    deployment_mode: str | None = None
    owner_id: str | None = None
    target_go_live_date: str | None = None
    template_id: str | None = None


class AdminStepPatch(StepPatch):
    title: str | None = None
    description: str | None = None
    owner_type: str | None = None
    due_date: str | None = None


class BlockerCreate(BaseModel):
    tenant_id: str
    step_id: str | None = None
    severity: str = "medium"
    title: str
    description: str = ""
    owner_type: str = "shared"


class BlockerPatch(BaseModel):
    severity: str | None = None
    title: str | None = None
    description: str | None = None
    owner_type: str | None = None
    status: BlockerStatus | None = None
    resolved_at: str | None = None


def _tenant(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return tenant


def _admin(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("admin")
    return tenant


async def ensure_templates() -> None:
    for tpl in ONBOARDING_TEMPLATES:
        if not await _templates.find_by_id(tpl["template_id"]):
            await _templates.insert(tpl["template_id"], dict(tpl))


async def _get_plan_or_404(tenant_id: str) -> dict:
    plan = await _plans.get_for_tenant(tenant_id)
    if not plan:
        raise HTTPException(status_code=404, detail="implementation plan not found")
    return plan


async def _rollup(tenant_id: str, metrics: dict[str, Any] | None = None) -> dict:
    plan = await _get_plan_or_404(tenant_id)
    steps = await _steps.list_for_tenant(tenant_id)
    blockers = await _blockers.list_for_tenant(tenant_id)
    criteria = plan.get("success_criteria", {})
    updated = dict(plan)
    updated["implementation_health_score"] = implementation_health_score(steps, blockers, metrics)
    updated["go_live_readiness_score"] = go_live_readiness_score(steps, blockers, criteria, metrics)
    updated["value_readiness_score"] = value_readiness_score(steps, criteria, metrics)
    updated["expansion_readiness_score"] = expansion_readiness_score(updated, steps, blockers, metrics)
    updated["onboarding_stage"] = infer_stage(steps, updated)
    if any(b.get("status") in {"open", "in_progress"} for b in blockers):
        updated["status"] = "blocked"
    elif updated["expansion_readiness_score"] >= 80:
        updated["status"] = "expansion_ready"
    elif updated["value_readiness_score"] >= 80:
        updated["status"] = "value_proven"
    elif updated["go_live_readiness_score"] >= 85:
        updated["status"] = "live"
    elif steps:
        updated["status"] = "in_progress"
    updated["blockers"] = [b["blocker_id"] for b in blockers if b.get("status") in {"open", "in_progress"}]
    if updated != plan:
        plan = await _plans.update(plan["implementation_plan_id"], updated)
    return {"plan": plan, "steps": steps, "blockers": blockers}


async def create_plan_from_template(tenant_id: str, body: PlanCreate) -> dict:
    await ensure_templates()
    template = None
    if body.template_id:
        template = await _templates.find_by_id(body.template_id)
    if template is None and body.package_id:
        template = await _templates.get_by_package(body.package_id)
    if template is None:
        template = ONBOARDING_TEMPLATES[0]
    now = utc_now().isoformat()
    plan_id = f"impl_{uuid.uuid4().hex[:12]}"
    created_steps = []
    for idx, step in enumerate(template.get("default_steps", []), 1):
        step_id = f"step_{uuid.uuid4().hex[:12]}"
        record = ImplementationStep(
            step_id=step_id,
            tenant_id=tenant_id,
            title=step["title"],
            description=step.get("description", step["title"]),
            category=step["category"],
            owner_type=step.get("owner_type", "shared"),
            required=step.get("required", True),
            created_at=now,
            updated_at=now,
        ).model_dump()
        record["sort_order"] = idx
        created_steps.append(await _steps.insert(step_id, record))
    plan = TenantImplementationPlan(
        implementation_plan_id=plan_id,
        tenant_id=tenant_id,
        package_id=body.package_id or template.get("package_id"),
        deployment_mode=body.deployment_mode,
        status="in_progress",
        onboarding_stage="signed",
        owner_id=body.owner_id,
        target_go_live_date=body.target_go_live_date,
        required_steps=[s["step_id"] for s in created_steps if s.get("required", True)],
        success_criteria=template.get("default_success_criteria", {}),
        created_at=now,
        updated_at=now,
    ).model_dump()
    await _plans.insert(plan_id, plan)
    return (await _rollup(tenant_id))["plan"]


def _tenant_visible_blocker(b: dict) -> dict:
    return {k: v for k, v in b.items() if k not in {"internal_notes"}}


@router.get("/status")
async def onboarding_status(request: Request):
    tenant = _tenant(request)
    rollup = await _rollup(tenant.tenant_id)
    triggers = await _triggers.list_for_tenant(tenant.tenant_id)
    return APIResponse(data={**rollup, "customer_success_triggers": triggers}).to_dict()


@router.get("/checklist")
async def onboarding_checklist(request: Request):
    tenant = _tenant(request)
    rollup = await _rollup(tenant.tenant_id)
    tenant_actions = [s for s in rollup["steps"] if s.get("owner_type") in {"tenant", "shared"} and s.get("status") not in {"completed", "skipped"}]
    return APIResponse(data={"items": rollup["steps"], "tenant_actions": tenant_actions, "blockers": [_tenant_visible_blocker(b) for b in rollup["blockers"]]}).to_dict()


@router.patch("/steps/{step_id}")
async def patch_tenant_step(step_id: str, patch: StepPatch, request: Request):
    tenant = _tenant(request)
    step = await _steps.find_by_id(step_id)
    if not step or step.get("tenant_id") != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="implementation step not found")
    if step.get("owner_type") == "olympus":
        raise HTTPException(status_code=403, detail="Olympus-owned step cannot be changed by tenant")
    data = patch.model_dump(exclude_none=True)
    if data.get("status") == "completed" and not data.get("completed_at"):
        data["completed_at"] = utc_now().isoformat()
    updated = await _steps.update(step_id, data)
    await _rollup(tenant.tenant_id)
    return APIResponse(data=updated).to_dict()


@router.get("/sdk-instructions")
async def sdk_instructions(request: Request):
    tenant = _tenant(request)
    return APIResponse(data={"tenant_id": tenant.tenant_id, "steps": ["Install the Aether SDK for your platform.", "Initialize with a tenant-scoped API key; never share keys across tenants.", "Send identify, commerce, decision, action, and outcome events according to your package template.", "Verify /v1/onboarding/event-requirements before go-live."], "security": ["Use environment secret storage.", "Preserve consent and purpose metadata on all events.", "Route production events only after go-live approval."]}).to_dict()


@router.get("/event-requirements")
async def event_requirements(request: Request):
    tenant = _tenant(request)
    plan = await _get_plan_or_404(tenant.tenant_id)
    return APIResponse(data={"required_events": plan.get("success_criteria", {}).get("required_events_received", []), "minimum_event_volume": plan.get("success_criteria", {}).get("minimum_event_volume", 0), "identity_requirements": ["tenant_id on every event", "stable user/entity identifiers", "consent and lawful basis metadata where applicable"], "outcome_requirements": ["recommendation_id when attributable", "decision_id/action_id when available", "observed value and label"]}).to_dict()


@router.get("/go-live-readiness")
async def go_live_readiness(request: Request):
    tenant = _tenant(request)
    rollup = await _rollup(tenant.tenant_id)
    return APIResponse(data={"score": rollup["plan"].get("go_live_readiness_score", 0), "plan": rollup["plan"], "required_steps_remaining": [s for s in rollup["steps"] if s.get("required", True) and s.get("status") not in {"completed", "skipped"}], "blocking_blockers": [b for b in rollup["blockers"] if b.get("status") in {"open", "in_progress"}]}).to_dict()


@admin_router.get("/overview")
async def admin_overview(request: Request):
    _admin(request)
    plans = await _plans.list_all_admin()
    blockers = await _blockers.list_open_admin()
    by_stage = Counter(p.get("onboarding_stage") for p in plans)
    avg = lambda field: round(sum(p.get(field, 0) for p in plans) / len(plans), 1) if plans else 0
    return APIResponse(data={"tenants_by_stage": dict(by_stage), "average_days_in_stage": {stage: 0 for stage in by_stage}, "blocked_tenants": len({b.get("tenant_id") for b in blockers}), "go_live_readiness": avg("go_live_readiness_score"), "value_readiness": avg("value_readiness_score"), "expansion_readiness": avg("expansion_readiness_score"), "count": len(plans)}).to_dict()


@admin_router.get("/tenants")
async def admin_tenants(request: Request):
    _admin(request)
    plans = await _plans.list_all_admin()
    blockers = await _blockers.list_open_admin()
    blocker_counts = Counter(b.get("tenant_id") for b in blockers)
    items = [{**p, "blockers": blocker_counts.get(p.get("tenant_id"), 0), "recommended_action": "Resolve blockers" if blocker_counts.get(p.get("tenant_id"), 0) else "Advance next onboarding step"} for p in plans]
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@admin_router.get("/tenants/{tenant_id}")
async def admin_tenant_detail(tenant_id: str, request: Request):
    _admin(request)
    rollup = await _rollup(tenant_id)
    triggers = await _triggers.list_for_tenant(tenant_id)
    return APIResponse(data={**rollup, "customer_success_triggers": triggers}).to_dict()


@admin_router.post("/tenants/{tenant_id}/plan")
async def admin_create_plan(tenant_id: str, body: PlanCreate, request: Request):
    _admin(request)
    existing = await _plans.get_for_tenant(tenant_id)
    if existing:
        return APIResponse(data=existing).to_dict()
    plan = await create_plan_from_template(tenant_id, body)
    return APIResponse(data=plan).to_dict()


@admin_router.patch("/steps/{step_id}")
async def admin_patch_step(step_id: str, patch: AdminStepPatch, request: Request):
    _admin(request)
    step = await _steps.find_by_id(step_id)
    if not step:
        raise HTTPException(status_code=404, detail="implementation step not found")
    data = patch.model_dump(exclude_none=True)
    if data.get("status") == "completed" and not data.get("completed_at"):
        data["completed_at"] = utc_now().isoformat()
    updated = await _steps.update(step_id, data)
    await _rollup(updated["tenant_id"])
    return APIResponse(data=updated).to_dict()


@admin_router.get("/blockers")
async def admin_blockers(request: Request):
    _admin(request)
    blockers = await _blockers.find_many(filters={}, limit=1000)
    return APIResponse(data={"items": blockers, "count": len(blockers)}).to_dict()


@admin_router.post("/blockers")
async def admin_create_blocker(body: BlockerCreate, request: Request):
    _admin(request)
    blocker_id = f"blocker_{uuid.uuid4().hex[:12]}"
    record = ImplementationBlocker(blocker_id=blocker_id, created_at=utc_now().isoformat(), **body.model_dump()).model_dump()
    created = await _blockers.insert(blocker_id, record)
    await _rollup(body.tenant_id)
    return APIResponse(data=created).to_dict()


@admin_router.patch("/blockers/{blocker_id}")
async def admin_patch_blocker(blocker_id: str, patch: BlockerPatch, request: Request):
    _admin(request)
    blocker = await _blockers.find_by_id(blocker_id)
    if not blocker:
        raise HTTPException(status_code=404, detail="implementation blocker not found")
    data = patch.model_dump(exclude_none=True)
    if data.get("status") in {"resolved", "waived"} and not data.get("resolved_at"):
        data["resolved_at"] = utc_now().isoformat()
    updated = await _blockers.update(blocker_id, data)
    await _rollup(updated["tenant_id"])
    return APIResponse(data=updated).to_dict()


@admin_router.get("/readiness")
async def admin_readiness(request: Request):
    _admin(request)
    plans = await _plans.list_all_admin()
    return APIResponse(data={"items": [{"tenant_id": p.get("tenant_id"), "stage": p.get("onboarding_stage"), "health_score": p.get("implementation_health_score"), "go_live_readiness_score": p.get("go_live_readiness_score"), "value_readiness_score": p.get("value_readiness_score"), "expansion_readiness_score": p.get("expansion_readiness_score")} for p in plans]}).to_dict()


@admin_router.get("/customer-success-triggers")
async def admin_customer_success_triggers(request: Request):
    _admin(request)
    plans = await _plans.list_all_admin()
    all_created = []
    for p in plans:
        rollup = await _rollup(p["tenant_id"])
        generated = generate_customer_success_triggers(rollup["plan"], rollup["steps"], rollup["blockers"])
        existing_types = {t.get("trigger_type") for t in await _triggers.list_for_tenant(p["tenant_id"])}
        for trig in generated:
            if trig["trigger_type"] in existing_types:
                continue
            trigger_id = f"cst_{uuid.uuid4().hex[:12]}"
            record = CustomerSuccessTrigger(trigger_id=trigger_id, tenant_id=p["tenant_id"], created_at=utc_now().isoformat(), **trig).model_dump()
            all_created.append(await _triggers.insert(trigger_id, record))
    open_items = await _triggers.list_open_admin()
    return APIResponse(data={"items": open_items, "generated": all_created, "count": len(open_items)}).to_dict()
