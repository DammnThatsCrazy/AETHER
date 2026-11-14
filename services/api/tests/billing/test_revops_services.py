from datetime import datetime, timedelta, timezone

import pytest

from repositories.repos import reset_in_memory_stores
from billing.billing.revops import (
    EntitlementService,
    ExpansionBillingService,
    InvoicePreviewService,
    MeteringService,
    RevenueLeakageService,
    TenantContractProfile,
    TenantContractProfileRepository,
    TenantEntitlement,
    TenantEntitlementRepository,
    UsageMeteringEvent,
    UsageSummaryService,
    ValueCreatedEvent,
    ValueCreatedEventService,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()


async def test_contract_entitlement_metering_summary_invoice_leakage_and_expansion():
    contracts = TenantContractProfileRepository()
    entitlements = TenantEntitlementRepository()
    await contracts.insert("contract_t1", TenantContractProfile(
        contract_profile_id="contract_t1", tenant_id="t1", package_id="pkg_growth", contract_status="active", billing_model="usage_based"
    ).model_dump())
    await entitlements.insert("ent_audit", TenantEntitlement(
        entitlement_id="ent_audit", tenant_id="t1", feature_key="audit_export_generated", included_quantity=1, overage_allowed=True
    ).model_dump())
    await entitlements.insert("ent_premium", TenantEntitlement(
        entitlement_id="ent_premium", tenant_id="t1", feature_key="premium_connector_used", enabled=False
    ).model_dump())

    metering = MeteringService()
    first = await metering.record_event(UsageMeteringEvent(
        tenant_id="t1", event_type="audit_export_generated", source_type="audit", source_id="a1", metadata={"api_key": "secret", "safe": "ok"}
    ))
    duplicate = await metering.record_event(UsageMeteringEvent(
        tenant_id="t1", event_type="audit_export_generated", source_type="audit", source_id="a1"
    ))
    await metering.record_event(UsageMeteringEvent(tenant_id="t1", event_type="audit_export_generated", source_type="audit", source_id="a2"))
    await metering.record_event(UsageMeteringEvent(tenant_id="t1", event_type="premium_connector_used", source_type="connector", source_id="c1"))

    assert first == duplicate
    assert first["metadata"] == {"safe": "ok"}

    # Window derived from the clock — a hardcoded month is a time bomb that
    # silently empties the summary once the calendar passes it.
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).isoformat()
    end = (now + timedelta(days=1)).isoformat()
    summary = await UsageSummaryService().calculate("t1", start, end)
    assert summary["usage_by_dimension"]["audit_export_generated"] == 2
    assert summary["overage_by_dimension"]["audit_export_generated"] == 1

    evaluation = await EntitlementService().evaluate("t1", summary["usage_by_dimension"])
    assert "premium_connector_used" in evaluation["disabled_feature_usage"]

    value = await ValueCreatedEventService().create(ValueCreatedEvent(
        tenant_id="t1", source_type="outcome", source_id="out1", value_type="retained_revenue", value_amount=25000, confidence=0.8
    ))
    assert value["billable_under_contract"] is False

    preview = await InvoicePreviewService().generate("t1", start, end)
    assert preview["status"] == "draft"
    assert any(item["dimension_key"] == "audit_export_generated" for item in preview["line_items"])

    signals = await RevenueLeakageService().detect("t1", start, end)
    assert {s["leakage_type"] for s in signals} >= {"overage_not_priced", "connector_unpriced", "value_created_unmonetized"}

    opportunities = await ExpansionBillingService().opportunities("t1")
    assert opportunities

class Tenant:
    def __init__(self, tenant_id="t_route", perms=None):
        self.tenant_id = tenant_id
        self.perms = set(perms or [])
    def require_permission(self, permission):
        from shared.common.common import ForbiddenError
        if permission not in self.perms:
            raise ForbiddenError(f"Missing permission: {permission}")

class Request:
    def __init__(self, tenant):
        self.state = type("State", (), {"tenant": tenant})()


async def test_tenant_safe_routes_and_admin_permission():
    from shared.common.common import ForbiddenError
    from billing.billing.routes import get_billing_plan, kyber_revops_overview
    await TenantContractProfileRepository().insert("contract_route", TenantContractProfile(
        contract_profile_id="contract_route", tenant_id="t_route", package_id="pkg", internal_notes="do not expose"
    ).model_dump())
    response = await get_billing_plan(Request(Tenant("t_route")))
    assert response["data"]["plan"]["package_id"] == "pkg"
    assert "internal_notes" not in response["data"]["plan"]
    with pytest.raises(ForbiddenError):
        await kyber_revops_overview(Request(Tenant("operator", perms=[])))


async def test_value_created_route_reads_a_period_without_crashing():
    from billing.billing.routes import list_value_created
    from billing.billing.revops import ValueCreatedEventRepository

    repo = ValueCreatedEventRepository()
    for event_id, when in (("v_in", "2026-05-10T00:00:00+00:00"), ("v_out", "2026-01-01T00:00:00+00:00")):
        await repo.insert(event_id, ValueCreatedEvent(
            value_event_id=event_id, tenant_id="t_value", source_type="outcome", source_id=event_id,
            value_type="retained_revenue", value_amount=10.0, occurred_at=when,
        ).model_dump())

    request = Request(Tenant("t_value"))
    windowed = await list_value_created(request, start="2026-05-01T00:00:00+00:00", end="2026-06-01T00:00:00+00:00")
    assert [i["value_event_id"] for i in windowed["data"]["items"]] == ["v_in"]
    assert windowed["data"]["truncated"] is False

    unbounded = await list_value_created(request)
    assert unbounded["data"]["count"] == 2
    assert unbounded["data"]["truncated"] is False
