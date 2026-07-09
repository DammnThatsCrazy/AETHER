"""Route tests: flag gating, tenant isolation, Kyber operator gating."""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402
from services.economic import ai_routes  # noqa: E402
from services.economic.ai_routes import PriceCardCreate  # noqa: E402
from services.silver.projectors.ai_invocation_projector import write_execution_fact  # noqa: E402
from ai_economics.conftest import FakeRequest  # noqa: E402
from ai_economics.factories import make_observed, new_tenant  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def _seed_fact(tenant: str, **overrides):
    _, fact = await write_execution_fact(make_observed(tenant_id=tenant, **overrides))
    assert fact is not None
    return fact


class TestFlagGating:
    async def test_tenant_routes_reject_when_disabled(self, ai_flags_off):
        request = FakeRequest(new_tenant())
        with pytest.raises(BadRequestError):
            await ai_routes.ai_economics_summary(request)
        with pytest.raises(BadRequestError):
            await ai_routes.list_ai_invocations(request)
        with pytest.raises(BadRequestError):
            await ai_routes.list_price_cards(request)
        with pytest.raises(BadRequestError):
            await ai_routes.ai_waste_findings(request)

    async def test_recommendations_need_sub_flag(self, monkeypatch):
        patched = dataclasses.replace(
            settings.ai_economics, enabled=True, recommendations_enabled=False,
        )
        monkeypatch.setattr(settings, "ai_economics", patched)
        with pytest.raises(BadRequestError):
            await ai_routes.ai_efficiency_recommendations(FakeRequest(new_tenant()))

    async def test_recommendations_when_enabled(self, ai_flags_on):
        response = await ai_routes.ai_efficiency_recommendations(FakeRequest(new_tenant()))
        assert response["data"]["recommendations"] == []


class TestTenantRoutes:
    async def test_summary_and_invocations_tenant_isolated(self, ai_flags_on):
        tenant_a, tenant_b = new_tenant(), new_tenant()
        await _seed_fact(tenant_a, billed_cost=1.5)

        summary_a = await ai_routes.ai_economics_summary(FakeRequest(tenant_a))
        summary_b = await ai_routes.ai_economics_summary(FakeRequest(tenant_b))
        assert summary_a["data"]["fact_count"] == 1
        assert summary_a["data"]["total_cost_by_currency"] == {"USD": 1.5}
        assert summary_b["data"]["fact_count"] == 0

        invocations_b = await ai_routes.list_ai_invocations(FakeRequest(tenant_b))
        assert invocations_b["data"]["invocations"] == []

    async def test_invocation_filters(self, ai_flags_on):
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=1.0, provider="prov-x", status="succeeded")
        await _seed_fact(tenant, billed_cost=1.0, provider="prov-y", status="failed")

        by_provider = await ai_routes.list_ai_invocations(
            FakeRequest(tenant), provider="prov-x"
        )
        assert by_provider["data"]["count"] == 1
        by_status = await ai_routes.list_ai_invocations(
            FakeRequest(tenant), status="failed"
        )
        assert by_status["data"]["count"] == 1
        with pytest.raises(BadRequestError):
            await ai_routes.list_ai_invocations(FakeRequest(tenant), status="bogus")
        with pytest.raises(BadRequestError):
            await ai_routes.list_ai_invocations(FakeRequest(tenant), cost_basis="bogus")

    async def test_workflow_recompute_404_then_success(self, ai_flags_on):
        tenant = new_tenant()
        run_id = f"wf-{uuid.uuid4().hex[:8]}"
        with pytest.raises(NotFoundError):
            await ai_routes.recompute_ai_workflow(run_id, FakeRequest(tenant))

        await _seed_fact(tenant, workflow_run_id=run_id, billed_cost=1.0)
        response = await ai_routes.recompute_ai_workflow(run_id, FakeRequest(tenant))
        assert response["data"]["workflow"]["workflow_run_id"] == run_id

        workflows = await ai_routes.list_ai_workflows(FakeRequest(tenant))
        assert workflows["data"]["count"] == 1

    async def test_models_rollup(self, ai_flags_on):
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=1.0, provider="prov-m", model="m-1",
                         latency_ms=100.0, quality_score=0.9)
        await _seed_fact(tenant, billed_cost=3.0, provider="prov-m", model="m-1",
                         latency_ms=300.0, status="failed")
        response = await ai_routes.ai_model_rollup(FakeRequest(tenant))
        models = response["data"]["models"]
        assert len(models) == 1
        rollup = models[0]
        assert rollup["invocations"] == 2
        assert rollup["cost_by_currency"] == {"USD": 4.0}
        assert rollup["avg_latency_ms"] == pytest.approx(200.0)
        assert rollup["success_rate"] == pytest.approx(0.5)
        assert rollup["avg_quality_score"] == pytest.approx(0.9)

    async def test_price_card_create_and_list(self, ai_flags_on):
        tenant = new_tenant()
        provider, model = f"prov-{uuid.uuid4().hex[:8]}", f"model-{uuid.uuid4().hex[:8]}"
        body = PriceCardCreate(
            provider=provider, model=model, currency="USD", pricing_version="tenant-v1",
            rates={"input_tokens_per_1k": 0.002},
            effective_from="2026-01-01T00:00:00+00:00",
        )
        created = await ai_routes.create_price_card(body, FakeRequest(tenant))
        assert created["data"]["price_card"]["provider"] == provider

        listing = await ai_routes.list_price_cards(
            FakeRequest(tenant), provider=provider, model=model
        )
        cards = listing["data"]["price_cards"]
        assert len(cards) == 1 and cards[0]["tenant_id"] == tenant

        # Another tenant does not see it
        other = await ai_routes.list_price_cards(
            FakeRequest(new_tenant()), provider=provider, model=model
        )
        assert other["data"]["price_cards"] == []

    async def test_price_card_invalid_window_rejected(self, ai_flags_on):
        body = PriceCardCreate(
            provider="p", model="m", currency="USD", pricing_version="v",
            rates={"input_tokens_per_1k": 0.002},
            effective_from="2026-06-01T00:00:00+00:00",
            effective_to="2026-01-01T00:00:00+00:00",
        )
        with pytest.raises(BadRequestError):
            await ai_routes.create_price_card(body, FakeRequest(new_tenant()))

    async def test_waste_findings_route(self, ai_flags_on):
        tenant = new_tenant()
        for _ in range(3):
            await _seed_fact(tenant, billed_cost=1.0, provider="prov-w", model="m-w",
                             retry_count=3)
        response = await ai_routes.ai_waste_findings(FakeRequest(tenant))
        findings = response["data"]["findings"]
        assert any(f["detector"] == "retry_waste" for f in findings)

    async def test_recommendations_are_proposal_only(self, ai_flags_on):
        tenant = new_tenant()
        for _ in range(3):
            await _seed_fact(tenant, billed_cost=1.0, provider="prov-r", model="m-r",
                             retry_count=3)
        response = await ai_routes.ai_efficiency_recommendations(FakeRequest(tenant))
        recommendations = response["data"]["recommendations"]
        assert recommendations
        for rec in recommendations:
            assert rec["requires_approval"] is True
            assert rec["execution"] == "proposal_only"
            assert rec["family"] == "ai_outcome_efficiency"


class TestKyberRoutes:
    async def test_kyber_requires_operator(self, ai_flags_on, monkeypatch):
        calls = []

        def _fake_operator(request):
            calls.append(request)
            return SimpleNamespace(actor_id="op-1")

        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator", _fake_operator
        )
        response = await ai_routes.ai_efficiency_fleet_health(FakeRequest("operator"))
        assert calls, "operator check must run"
        assert "fact_count" in response["data"]

    async def test_kyber_gating_flags(self, ai_flags_off, monkeypatch):
        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator",
            lambda request: SimpleNamespace(actor_id="op-1"),
        )
        with pytest.raises(BadRequestError):
            await ai_routes.ai_efficiency_fleet_health(FakeRequest("operator"))

        # kyber_enabled alone (master off) is sufficient for kyber surfaces
        patched = dataclasses.replace(
            settings.ai_economics, enabled=False, kyber_enabled=True,
        )
        monkeypatch.setattr(settings, "ai_economics", patched)
        response = await ai_routes.ai_efficiency_fleet_health(FakeRequest("operator"))
        assert "tenants_observed" in response["data"]

    async def test_kyber_health_exposes_no_tenant_content(self, ai_flags_on, monkeypatch):
        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator",
            lambda request: SimpleNamespace(actor_id="op-1"),
        )
        tenant = new_tenant()
        sentinel_task = f"SENTINEL-{uuid.uuid4().hex}"
        await _seed_fact(tenant, billed_cost=1.0, task_type=sentinel_task)

        response = await ai_routes.ai_efficiency_fleet_health(FakeRequest("operator"))
        flat = json.dumps(response)
        assert sentinel_task not in flat
        assert response["data"]["fact_count"] >= 1
        assert response["data"]["cost_coverage_rate"] is not None

    async def test_kyber_tenant_drilldown(self, ai_flags_on, monkeypatch):
        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator",
            lambda request: SimpleNamespace(actor_id="op-1"),
        )
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=2.0)
        response = await ai_routes.ai_efficiency_tenant_diagnostics(
            tenant, FakeRequest("operator")
        )
        assert response["data"]["tenant_id"] == tenant
        assert response["data"]["summary"]["fact_count"] == 1
