"""Five deterministic efficiency detectors: positive + negative case each."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.economic import ai_efficiency  # noqa: E402
from services.economic.ai_pricing import AIPriceCardRegistry  # noqa: E402
from ai_economics.factories import fact_record, new_tenant  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _registry() -> AIPriceCardRegistry:
    return AIPriceCardRegistry()


async def _add_card(registry, provider, model, input_rate, output_rate, cached_rate=None):
    rates = {"input_tokens_per_1k": input_rate, "output_tokens_per_1k": output_rate}
    if cached_rate is not None:
        rates["cached_input_tokens_per_1k"] = cached_rate
    await registry.add_card({
        "provider": provider, "model": model, "currency": "USD",
        "pricing_version": "v-det", "rates": rates,
        "effective_from": "2026-01-01T00:00:00+00:00", "source": "test",
    })


def _by_detector(findings, detector):
    return [f for f in findings if f["detector"] == detector]


class TestRetryWaste:
    async def test_positive(self):
        tenant = new_tenant()
        provider, model = _unique("prov"), _unique("model")
        facts = (
            [fact_record(provider=provider, model=model, selected_cost=1.0, retry_count=2)
             for _ in range(3)]
            + [fact_record(provider=provider, model=model, selected_cost=1.0, retry_count=0)
               for _ in range(2)]
        )
        findings = await ai_efficiency.detect_retry_waste(tenant, facts, _registry())
        assert len(findings) == 1
        finding = findings[0]
        assert finding["detector"] == "retry_waste"
        assert finding["tenant_id"] == tenant
        assert len(finding["evidence_refs"]) == 3
        assert finding["estimated_monthly_waste"] is not None
        assert "USD" in finding["estimated_monthly_waste"]
        assert "proposal" in finding["candidate_action"].lower() or finding["candidate_action"]

    async def test_negative_no_retries(self):
        tenant = new_tenant()
        provider, model = _unique("prov"), _unique("model")
        facts = [fact_record(provider=provider, model=model, selected_cost=1.0, retry_count=0)
                 for _ in range(5)]
        assert await ai_efficiency.detect_retry_waste(tenant, facts, _registry()) == []


class TestModelOverqualification:
    async def test_positive_cheaper_card_exists(self):
        tenant = new_tenant()
        provider = _unique("prov")
        big, small = _unique("big"), _unique("small")
        registry = _registry()
        await _add_card(registry, provider, big, 0.01, 0.03)
        await _add_card(registry, provider, small, 0.001, 0.002)
        facts = [
            fact_record(provider=provider, model=big, task_type="classify",
                        quality_score=0.97, input_tokens=1000, output_tokens=200)
            for _ in range(5)
        ]
        findings = await ai_efficiency.detect_model_overqualification(tenant, facts, registry)
        assert len(findings) == 1
        assert findings[0]["detector"] == "model_overqualification"
        assert small in findings[0]["description"] or small in findings[0]["candidate_action"]
        assert findings[0]["estimated_monthly_waste"] is not None

    async def test_negative_quality_below_threshold(self):
        tenant = new_tenant()
        provider = _unique("prov")
        big, small = _unique("big"), _unique("small")
        registry = _registry()
        await _add_card(registry, provider, big, 0.01, 0.03)
        await _add_card(registry, provider, small, 0.001, 0.002)
        facts = [
            fact_record(provider=provider, model=big, task_type="classify",
                        quality_score=0.8, input_tokens=1000, output_tokens=200)
            for _ in range(5)
        ]
        assert await ai_efficiency.detect_model_overqualification(tenant, facts, registry) == []

    async def test_negative_no_cheaper_card(self):
        tenant = new_tenant()
        provider, big = _unique("prov"), _unique("big")
        registry = _registry()
        await _add_card(registry, provider, big, 0.01, 0.03)
        facts = [
            fact_record(provider=provider, model=big, task_type="classify",
                        quality_score=0.99, input_tokens=1000, output_tokens=200)
            for _ in range(5)
        ]
        assert await ai_efficiency.detect_model_overqualification(tenant, facts, registry) == []


class TestDeterministicReplacement:
    async def test_positive_repeated_perfect_prompt(self):
        tenant = new_tenant()
        prompt_hash = uuid.uuid4().hex
        facts = [
            fact_record(task_type="lookup", prompt_hash=prompt_hash,
                        quality_score=1.0, selected_cost=0.5)
            for _ in range(5)
        ]
        findings = await ai_efficiency.detect_deterministic_replacement(tenant, facts, _registry())
        assert len(findings) == 1
        assert findings[0]["detector"] == "deterministic_replacement_candidate"
        assert len(findings[0]["evidence_refs"]) == 5
        assert findings[0]["estimated_monthly_waste"] is not None

    async def test_negative_imperfect_quality(self):
        tenant = new_tenant()
        prompt_hash = uuid.uuid4().hex
        facts = [
            fact_record(task_type="lookup", prompt_hash=prompt_hash,
                        quality_score=0.9, selected_cost=0.5)
            for _ in range(6)
        ]
        assert await ai_efficiency.detect_deterministic_replacement(
            tenant, facts, _registry()
        ) == []

    async def test_negative_too_few_repeats(self):
        tenant = new_tenant()
        prompt_hash = uuid.uuid4().hex
        facts = [
            fact_record(task_type="lookup", prompt_hash=prompt_hash,
                        quality_score=1.0, selected_cost=0.5)
            for _ in range(4)
        ]
        assert await ai_efficiency.detect_deterministic_replacement(
            tenant, facts, _registry()
        ) == []


class TestCacheOpportunity:
    async def test_positive_repeated_input_low_cache(self):
        tenant = new_tenant()
        provider, model = _unique("prov"), _unique("model")
        registry = _registry()
        await _add_card(registry, provider, model, 0.001, 0.002, cached_rate=0.0001)
        prompt_hash = uuid.uuid4().hex
        facts = [
            fact_record(provider=provider, model=model, prompt_hash=prompt_hash,
                        input_tokens=30_000, cached_input_tokens=0)
            for _ in range(3)  # 60k repeated tokens beyond the first occurrence
        ]
        findings = await ai_efficiency.detect_cache_opportunity(tenant, facts, registry)
        assert len(findings) == 1
        assert findings[0]["detector"] == "cache_opportunity"
        assert len(findings[0]["evidence_refs"]) == 2
        assert findings[0]["estimated_monthly_waste"] is not None

    async def test_negative_high_cache_utilization(self):
        tenant = new_tenant()
        provider, model = _unique("prov"), _unique("model")
        prompt_hash = uuid.uuid4().hex
        facts = [
            fact_record(provider=provider, model=model, prompt_hash=prompt_hash,
                        input_tokens=30_000, cached_input_tokens=30_000)
            for _ in range(3)
        ]
        assert await ai_efficiency.detect_cache_opportunity(tenant, facts, _registry()) == []

    async def test_negative_low_repeated_volume(self):
        tenant = new_tenant()
        provider, model = _unique("prov"), _unique("model")
        facts = [
            fact_record(provider=provider, model=model, prompt_hash=uuid.uuid4().hex,
                        input_tokens=30_000, cached_input_tokens=0)
            for _ in range(3)  # unique prompts → no repeated volume
        ]
        assert await ai_efficiency.detect_cache_opportunity(tenant, facts, _registry()) == []


class TestFailedWorkflowConcentration:
    async def test_positive_failing_workflow_with_cost(self):
        tenant = new_tenant()
        run_id = f"wf-{uuid.uuid4().hex[:8]}"
        facts = [
            fact_record(workflow_run_id=run_id, task_type="pipeline",
                        status="failed", selected_cost=2.0),
            fact_record(workflow_run_id=run_id, task_type="pipeline",
                        status="failed", selected_cost=2.0),
            fact_record(workflow_run_id=run_id, task_type="pipeline",
                        status="succeeded", selected_cost=1.0),
        ]
        findings = await ai_efficiency.detect_failed_workflow_concentration(
            tenant, facts, _registry()
        )
        workflow_findings = [f for f in findings if run_id in f["title"]]
        assert workflow_findings, "expected a workflow-level finding"
        finding = workflow_findings[0]
        assert finding["detector"] == "failed_workflow_concentration"
        assert len(finding["evidence_refs"]) == 2
        assert finding["estimated_monthly_waste"] is not None

    async def test_negative_failure_rate_at_threshold(self):
        tenant = new_tenant()
        run_id = f"wf-{uuid.uuid4().hex[:8]}"
        facts = [
            fact_record(workflow_run_id=run_id, task_type="pipeline",
                        status="failed", selected_cost=1.0),
            fact_record(workflow_run_id=run_id, task_type="pipeline",
                        status="succeeded", selected_cost=1.0),
        ]
        # exactly 50% is NOT above the strict threshold
        assert await ai_efficiency.detect_failed_workflow_concentration(
            tenant, facts, _registry()
        ) == []

    async def test_negative_zero_cost_failures(self):
        tenant = new_tenant()
        run_id = f"wf-{uuid.uuid4().hex[:8]}"
        facts = [
            fact_record(workflow_run_id=run_id, task_type="pipeline", status="failed",
                        selected_cost=None, cost_basis="unknown"),
            fact_record(workflow_run_id=run_id, task_type="pipeline", status="failed",
                        selected_cost=None, cost_basis="unknown"),
        ]
        assert await ai_efficiency.detect_failed_workflow_concentration(
            tenant, facts, _registry()
        ) == []


class TestRunDetectors:
    async def test_run_all_isolated(self):
        tenant = new_tenant()
        provider, model = _unique("prov"), _unique("model")
        facts = [
            fact_record(provider=provider, model=model, selected_cost=1.0, retry_count=3)
            for _ in range(3)
        ]
        findings = await ai_efficiency.run_detectors(tenant, facts=facts)
        assert _by_detector(findings, "retry_waste")
        for finding in findings:
            for key in ("detector", "tenant_id", "severity", "title", "description",
                        "evidence_refs", "estimated_monthly_waste", "candidate_action"):
                assert key in finding
