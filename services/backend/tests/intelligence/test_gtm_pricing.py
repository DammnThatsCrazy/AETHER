from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.intelligence import routes
from services.intelligence.solution_packages import (
    BUYER_PERSONAS,
    GTM_MATERIALS,
    PRICING_DIMENSIONS,
    PRICING_MODELS,
    ROI_CALCULATORS,
    SOLUTION_PACKAGES,
    PricingDimension,
    gtm_materials_for_package,
    personas_for_package,
)


class Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"
    def require_permission(self, permission):
        assert permission == "admin"


def req():
    return SimpleNamespace(state=SimpleNamespace(tenant=Tenant()))


def unwrap(resp):
    return resp["data"]


def test_pricing_model_definitions_load_and_dimension_validation():
    assert PRICING_MODELS[0].status == "internal_ready"
    assert {d.dimension_key for d in PRICING_DIMENSIONS} >= {"events_ingested", "action_dispatches", "audit_exports_generated"}
    with pytest.raises(Exception):
        PricingDimension(dimension_key="bad", label="Bad", description="Bad", unit="seat", metering_source="none", included_in_tiers=[], billable=True, notes="bad")


def test_gtm_catalog_personas_and_roi_load():
    assert len(GTM_MATERIALS) == 17
    assert len(BUYER_PERSONAS) == 17
    assert len(ROI_CALCULATORS) == 5
    assert all(c.disclaimer and "guarantee" in c.disclaimer.lower() for c in ROI_CALCULATORS)


def test_safe_status_and_government_planning_materials_no_certification_claims():
    statuses = {m.status for m in GTM_MATERIALS}
    assert statuses <= {"draft", "internal_ready", "sales_ready"}
    gov_text = " ".join(" ".join(m.content_blocks) for m in GTM_MATERIALS if m.market == "government_planning").lower()
    assert "do not claim certifications" in gov_text
    assert "fedramp certified" not in gov_text and "ato granted" not in gov_text


def test_package_material_and_persona_mapping():
    for pkg in SOLUTION_PACKAGES:
        assert gtm_materials_for_package(pkg.package_id), pkg.package_id
        assert personas_for_package(pkg.package_id), pkg.package_id


@pytest.mark.asyncio
async def test_gtm_endpoints_and_sales_readiness_aggregation():
    materials = unwrap(await routes.kyber_gtm_materials(req()))
    assert materials["count"] == 17
    detail = unwrap(await routes.kyber_gtm_material_detail("pricing_architecture_sheet", req()))
    assert detail["material_type"] == "pricing_sheet"
    personas = unwrap(await routes.kyber_gtm_buyer_personas(req()))
    assert personas["count"] == 17
    pricing = unwrap(await routes.kyber_gtm_pricing_models(req()))
    assert pricing["items"][0]["usage_dimensions"]
    roi = unwrap(await routes.kyber_gtm_roi_calculators(req()))
    assert roi["count"] == 5
    readiness = unwrap(await routes.kyber_gtm_sales_readiness(req()))
    assert readiness["items"]
    revenue = next(i for i in readiness["items"] if i["package_id"] == "revenue_intelligence_graph")
    assert revenue["material_count"] > 0 and revenue["persona_count"] > 0
