from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from repositories.repos import reset_in_memory_stores
from services.onboarding import routes
from services.onboarding.scoring import (
    expansion_readiness_score,
    generate_customer_success_triggers,
    go_live_readiness_score,
    implementation_health_score,
    value_readiness_score,
)
from services.onboarding.templates import ONBOARDING_TEMPLATES


class Tenant:
    def __init__(self, tenant_id="tenant-a", permissions=None):
        self.tenant_id = tenant_id
        self.permissions = set(permissions or {"read", "write", "admin"})

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise AssertionError(f"missing permission {permission}")


def req(tenant_id="tenant-a", permissions=None):
    return SimpleNamespace(state=SimpleNamespace(tenant=Tenant(tenant_id, permissions)))


def unwrap(resp):
    return resp["data"]


@pytest.fixture(autouse=True)
def clean():
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_onboarding_templates_load_and_package_specific_templates():
    await routes.ensure_templates()
    templates = await routes._templates.list_templates()
    assert len(templates) == 6
    assert {t["package_id"] for t in templates} >= {"revenue_intelligence_graph", "agent_governance_graph"}
    assert len(ONBOARDING_TEMPLATES[0]["default_steps"]) >= 10


@pytest.mark.asyncio
async def test_create_implementation_plan_from_package_template():
    plan = unwrap(await routes.admin_create_plan("tenant-a", routes.PlanCreate(package_id="revenue_intelligence_graph", deployment_mode="saas"), req(permissions={"admin"})))
    assert plan["tenant_id"] == "tenant-a"
    assert plan["package_id"] == "revenue_intelligence_graph"
    steps = await routes._steps.list_for_tenant("tenant-a")
    assert any(s["title"] == "SDK installed" for s in steps)
    assert plan["required_steps"]


@pytest.mark.asyncio
async def test_tenant_route_isolation_and_admin_access():
    await routes.admin_create_plan("tenant-a", routes.PlanCreate(package_id="revenue_intelligence_graph"), req(permissions={"admin"}))
    status = unwrap(await routes.onboarding_status(req("tenant-a", permissions={"read"})))
    assert status["plan"]["tenant_id"] == "tenant-a"
    with pytest.raises(HTTPException):
        await routes.onboarding_status(req("tenant-b", permissions={"read"}))
    with pytest.raises(AssertionError):
        await routes.admin_tenants(req(permissions={"read"}))


@pytest.mark.asyncio
async def test_scoring_helpers_and_blocker_update():
    await routes.admin_create_plan("tenant-a", routes.PlanCreate(package_id="operational_decision_intelligence"), req(permissions={"admin"}))
    steps = await routes._steps.list_for_tenant("tenant-a")
    blockers = []
    assert implementation_health_score(steps, blockers) >= 0
    assert go_live_readiness_score(steps, blockers, {"graph_active": True}) >= 0
    assert value_readiness_score(steps, {}, {"recommendations_viewed": 1, "decisions_recorded": 1}) > 0
    plan = await routes._plans.get_for_tenant("tenant-a")
    assert expansion_readiness_score(plan, steps, blockers, {"value_proven": True, "playbook_roi": 1, "observed_value": 10, "value_threshold": 1, "package_fit_signals": 1}) > 50

    blocker = unwrap(await routes.admin_create_blocker(routes.BlockerCreate(tenant_id="tenant-a", severity="critical", title="Legal approval"), req(permissions={"admin"})))
    assert blocker["status"] == "open"
    updated = unwrap(await routes.admin_patch_blocker(blocker["blocker_id"], routes.BlockerPatch(status="resolved"), req(permissions={"admin"})))
    assert updated["status"] == "resolved"
    assert updated["resolved_at"]


@pytest.mark.asyncio
async def test_customer_success_trigger_generation():
    await routes.admin_create_plan("tenant-a", routes.PlanCreate(package_id="revenue_intelligence_graph"), req(permissions={"admin"}))
    feed = unwrap(await routes.admin_customer_success_triggers(req(permissions={"admin"})))
    assert any(t["trigger_type"] == "sdk_stalled" for t in feed["items"])

    plan = await routes._plans.get_for_tenant("tenant-a")
    steps = await routes._steps.list_for_tenant("tenant-a")
    generated = generate_customer_success_triggers(plan, steps, [], {"recommendations_generated": 2, "recommendations_viewed": 0})
    assert any(t["trigger_type"] == "recommendations_not_viewed" for t in generated)
