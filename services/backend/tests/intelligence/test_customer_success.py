from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.intelligence import customer_success as cs


class Tenant:
    def __init__(self, tenant_id="tenant-a", permissions=None):
        self.tenant_id = tenant_id
        self.permissions = set(permissions or {"read", "write", "admin"})
        self.user_id = "user-1"

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


async def seed(tenant_id="tenant-a", good=True):
    await cs._tenants.insert(tenant_id, {"tenant_id": tenant_id, "name": "Acme", "plan": "enterprise"})
    await cs._recommendations.insert(f"rec-{tenant_id}", {"recommendation_id": f"rec-{tenant_id}", "tenant_id": tenant_id, "recommendation_type": "expansion", "status": "viewed" if good else "generated", "expected_value": 10000, "created_at": "2026-06-01T00:00:00Z"})
    if good:
        await cs._decisions.insert(f"dec-{tenant_id}", {"decision_id": f"dec-{tenant_id}", "tenant_id": tenant_id, "recommendation_id": f"rec-{tenant_id}", "created_at": "2026-06-01T00:01:00Z"})
        await cs._outcomes.insert(f"out-{tenant_id}", {"outcome_id": f"out-{tenant_id}", "tenant_id": tenant_id, "recommendation_id": f"rec-{tenant_id}", "value": 10000, "label": "success", "computed_at": "2026-06-02T00:00:00Z"})
        await cs._playbooks.insert(f"pb-{tenant_id}", {"playbook_id": f"pb-{tenant_id}", "tenant_id": tenant_id})
        await cs._runs.insert(f"run-{tenant_id}", {"run_id": f"run-{tenant_id}", "tenant_id": tenant_id, "status": "completed"})
    else:
        await cs._dispatches.insert(f"disp-{tenant_id}", {"dispatch_id": f"disp-{tenant_id}", "tenant_id": tenant_id, "status": "failed"})


@pytest.mark.asyncio
async def test_customer_health_expansion_and_renewal_scoring():
    await seed(good=True)
    metrics = await cs.usage_metrics("tenant-a")
    health, stage, _ = cs.CustomerHealthScorer().score(metrics)
    expansion, _ = cs.ExpansionScorer().score(metrics)
    risk, failure, _ = cs.RenewalRiskScorer().score(metrics, "2026-06-01T00:00:00Z")
    assert health > 0.7
    assert stage == "value_proven"
    assert expansion >= 0.55
    assert risk < 0.4
    assert failure in {"low_outcome_capture", "low_decision_rate", "stale_loops", "failed_integrations", "onboarding_blockers"}


@pytest.mark.asyncio
async def test_trigger_generation_and_duplicate_prevention():
    await seed(good=True)
    first = await cs.generate_for_tenant("tenant-a")
    second = await cs.generate_for_tenant("tenant-a")
    assert {t["trigger_type"] for t in first["created_triggers"]} >= {"value_proven", "expansion_ready", "executive_proof_ready"}
    assert second["created_triggers"] == []


@pytest.mark.asyncio
async def test_ebr_generation_and_account_plan_create_update():
    await seed(good=True)
    await cs.generate_for_tenant("tenant-a")
    ebr = await cs.EBRGenerator().generate("tenant-a")
    assert ebr.value_created_summary["observed_value_total"] == 10000
    created = unwrap(await cs.create_account_plan("tenant-a", cs.AccountPlanInput(strategic_objectives=["prove value"]), req()))
    assert created["strategic_objectives"] == ["prove value"]
    updated = unwrap(await cs.patch_account_plan("tenant-a", cs.AccountPlanInput(risks=["renewal sponsor gap"]), req()))
    assert updated["risks"] == ["renewal sponsor gap"]


@pytest.mark.asyncio
async def test_tenant_value_review_isolation_and_empty_state():
    await seed("tenant-a", good=True)
    await seed("tenant-b", good=False)
    value = unwrap(await cs.value_review(req("tenant-a", {"read"})))
    assert value["tenant_id"] == "tenant-a"
    assert value["observed_value"] == 10000
    other = unwrap(await cs.value_review(req("tenant-b", {"read"})))
    assert other["tenant_id"] == "tenant-b"
    assert other["observed_value"] == 0


@pytest.mark.asyncio
async def test_admin_permission_enforcement_and_risk_generation():
    await seed(good=False)
    with pytest.raises(AssertionError):
        await cs.overview(req(permissions={"read"}))
    result = await cs.generate_for_tenant("tenant-a")
    assert any(t["trigger_type"] in {"renewal_risk", "integration_gap", "outcome_gap"} for t in result["created_triggers"])
    risks = await cs._renewal_risks.find_many(filters={"tenant_id": "tenant-a"}, limit=10)
    assert risks
