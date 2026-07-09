"""Workflow economics + aggregate metric helpers."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.economic import ai_aggregation  # noqa: E402
from services.silver.projectors.ai_invocation_projector import write_execution_fact  # noqa: E402
from ai_economics.factories import fact_record, make_observed, new_tenant  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def _seed_fact(tenant: str, **overrides):
    _, fact = await write_execution_fact(make_observed(tenant_id=tenant, **overrides))
    assert fact is not None
    return fact


class TestCurrencySeparation:
    async def test_totals_never_sum_across_currencies(self):
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=1.0, currency="USD")
        await _seed_fact(tenant, billed_cost=2.0, currency="USD")
        await _seed_fact(tenant, billed_cost=5.0, currency="EUR")
        facts = await ai_aggregation.list_facts(tenant)
        totals = ai_aggregation.total_cost_by_currency(facts)
        assert totals == {"USD": 3.0, "EUR": 5.0}

    async def test_unknown_cost_excluded_not_zeroed(self):
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=1.0)
        await _seed_fact(tenant)  # unknown cost
        facts = await ai_aggregation.list_facts(tenant)
        assert ai_aggregation.total_cost_by_currency(facts) == {"USD": 1.0}
        assert ai_aggregation.cost_coverage(facts) == 0.5


class TestWorkflowEconomics:
    async def test_facts_without_workflow_id_never_fabricated(self):
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=1.0)  # no workflow_run_id
        assert await ai_aggregation.recompute_workflow(tenant, "wf-missing") is None
        assert await ai_aggregation.list_workflow_economics(tenant) == []

    async def test_recompute_metrics(self):
        tenant, run_id = new_tenant(), f"wf-{uuid.uuid4().hex[:8]}"
        await _seed_fact(tenant, workflow_run_id=run_id, billed_cost=1.0,
                         retry_count=2, latency_ms=100.0, quality_score=0.8,
                         outcome_id="out-1")
        await _seed_fact(tenant, workflow_run_id=run_id, billed_cost=2.0,
                         status="failed", latency_ms=50.0, quality_score=0.6)
        await _seed_fact(tenant, workflow_run_id=run_id)  # unknown cost

        economics = await ai_aggregation.recompute_workflow(tenant, run_id)
        assert economics is not None
        assert economics.total_invocations == 3
        assert economics.successful_invocations == 2
        assert economics.failed_invocations == 1
        assert economics.total_retries == 2
        assert economics.total_latency_ms == pytest.approx(270.0)
        assert economics.total_model_cost == pytest.approx(3.0)
        assert economics.fully_loaded_cost == pytest.approx(3.0)
        assert economics.currency == "USD"
        assert economics.cost_coverage == pytest.approx(2 / 3)
        assert economics.quality_score == pytest.approx(0.7)
        assert economics.technical_success is False
        assert economics.qualified_outcome_count == 1

        persisted = await ai_aggregation.list_workflow_economics(tenant)
        assert len(persisted) == 1
        assert persisted[0]["workflow_run_id"] == run_id

    async def test_mixed_currency_workflow_total_stays_unknown(self):
        tenant, run_id = new_tenant(), f"wf-{uuid.uuid4().hex[:8]}"
        await _seed_fact(tenant, workflow_run_id=run_id, billed_cost=1.0, currency="USD")
        await _seed_fact(tenant, workflow_run_id=run_id, billed_cost=1.0, currency="EUR")
        economics = await ai_aggregation.recompute_workflow(tenant, run_id)
        assert economics is not None
        assert economics.total_model_cost is None  # never mixed
        assert economics.fully_loaded_cost is None


class TestMetricHelpers:
    async def test_retry_waste_cost(self):
        facts = [
            fact_record(selected_cost=3.0, retry_count=2),   # waste 3 * 2/3 = 2.0
            fact_record(selected_cost=5.0, retry_count=0),   # no waste
            fact_record(retry_count=4, cost_basis="unknown", selected_cost=None),  # unknown → skip
        ]
        assert ai_aggregation.retry_waste_cost(facts) == {"USD": 2.0}

    async def test_cache_utilization_rate(self):
        facts = [
            fact_record(input_tokens=800, cached_input_tokens=200),
            fact_record(input_tokens=0, cached_input_tokens=0),
        ]
        assert ai_aggregation.cache_utilization_rate(facts) == pytest.approx(0.2)
        assert ai_aggregation.cache_utilization_rate(
            [fact_record(input_tokens=None, cached_input_tokens=None)]
        ) is None

    async def test_human_correction_and_outcome_coverage(self):
        facts = [
            fact_record(human_corrected=True, outcome_id="o-1"),
            fact_record(human_corrected=False),
            fact_record(human_corrected=False),
            fact_record(human_corrected=False, outcome_id="o-2"),
        ]
        assert ai_aggregation.human_correction_rate(facts) == pytest.approx(0.25)
        assert ai_aggregation.outcome_attribution_coverage(facts) == pytest.approx(0.5)

    async def test_quality_adjusted_cost(self):
        facts = [
            fact_record(selected_cost=1.0, quality_score=0.5),  # 2.0
            fact_record(selected_cost=1.0, quality_score=1.0),  # 1.0
            fact_record(selected_cost=1.0),                     # unscored → excluded
        ]
        assert ai_aggregation.quality_adjusted_cost(facts) == {"USD": 3.0}

    async def test_cost_per_invocation_and_completed_workflow(self):
        facts = [
            fact_record(selected_cost=1.0, workflow_run_id="wf-ok"),
            fact_record(selected_cost=3.0, workflow_run_id="wf-ok"),
            fact_record(selected_cost=10.0, workflow_run_id="wf-bad", status="failed"),
            fact_record(selected_cost=2.0),  # no workflow — excluded from workflow math
        ]
        assert ai_aggregation.cost_per_invocation(facts) == {"USD": 4.0}
        # Only wf-ok fully succeeded: cost 4.0 across 1 completed workflow
        assert ai_aggregation.cost_per_completed_workflow(facts) == {"USD": 4.0}

    async def test_failed_execution_cost(self):
        facts = [
            fact_record(selected_cost=1.0, status="failed"),
            fact_record(selected_cost=2.0, status="timeout"),
            fact_record(selected_cost=4.0, status="succeeded"),
        ]
        assert ai_aggregation.failed_execution_cost(facts) == {"USD": 3.0}

    async def test_tenant_summary_shape(self):
        tenant = new_tenant()
        await _seed_fact(tenant, billed_cost=1.0)
        summary = await ai_aggregation.tenant_summary(tenant)
        for key in (
            "fact_count", "total_cost_by_currency", "cost_per_invocation",
            "cost_per_completed_workflow", "failed_execution_cost",
            "retry_waste_cost", "quality_adjusted_cost", "cost_coverage",
            "cache_utilization_rate", "human_correction_rate",
            "outcome_attribution_coverage",
        ):
            assert key in summary
        assert summary["fact_count"] == 1
