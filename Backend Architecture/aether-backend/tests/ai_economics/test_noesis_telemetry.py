"""Noesis AI telemetry: emits facts, flag-gated, fail-open, no prompt content."""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.noesis.ai_telemetry import record_noesis_invocation  # noqa: E402
from services.economic import ai_aggregation  # noqa: E402
from ai_economics.factories import new_tenant  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestRecordNoesisInvocation:
    async def test_records_fact_when_enabled(self, ai_flags_on):
        tenant = new_tenant()
        await record_noesis_invocation(
            tenant_id=tenant, provider="anthropic", model="claude-haiku-4-5",
            status="succeeded", input_tokens=640, output_tokens=120,
            latency_ms=850.0, retry_count=0,
        )
        facts = await ai_aggregation.list_facts(tenant)
        assert len(facts) == 1
        fact = facts[0]
        assert fact["task_type"] == "noesis_plan"
        assert fact["provider"] == "anthropic"
        assert fact["provenance"]["source"] == "noesis"
        assert fact["input_tokens"] == 640
        assert fact["output_tokens"] == 120
        assert fact["contains_prompt_content"] is False
        assert fact["contains_completion_content"] is False

    async def test_seeded_card_prices_noesis_invocation(self, ai_flags_on):
        from services.economic.ai_pricing import get_price_card_registry
        await get_price_card_registry().ensure_seed_cards()
        tenant = new_tenant()
        await record_noesis_invocation(
            tenant_id=tenant, provider="anthropic", model="claude-haiku-4-5",
            input_tokens=1000, output_tokens=1000, latency_ms=100.0,
        )
        fact = (await ai_aggregation.list_facts(tenant))[0]
        assert fact["cost_basis"] == "calculated"
        assert fact["selected_cost"] == pytest.approx(0.006)  # 0.001 + 0.005
        assert fact["currency"] == "USD"

    async def test_flag_off_writes_nothing(self, ai_flags_off):
        tenant = new_tenant()
        await record_noesis_invocation(
            tenant_id=tenant, provider="anthropic", model="claude-haiku-4-5",
            input_tokens=100, output_tokens=10,
        )
        assert await ai_aggregation.list_facts(tenant) == []

    async def test_fail_open_never_raises(self, ai_flags_on, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("store down")

        monkeypatch.setattr(
            "services.silver.projectors.ai_invocation_projector.write_execution_fact",
            _boom,
        )
        # Must not raise despite the write failing
        await record_noesis_invocation(
            tenant_id=new_tenant(), provider="anthropic", model="claude-haiku-4-5",
            input_tokens=1, output_tokens=1,
        )

    async def test_no_prompt_content_anywhere_in_fact(self, ai_flags_on):
        tenant = new_tenant()
        await record_noesis_invocation(
            tenant_id=tenant, provider="openai", model="gpt-4o-mini",
            input_tokens=10, output_tokens=5,
        )
        fact = (await ai_aggregation.list_facts(tenant))[0]
        flat = json.dumps(fact).lower()
        for banned in ("prompt_text", "completion_text", "chain_of_thought", '"messages"'):
            assert banned not in flat

    async def test_unknown_status_recorded_as_failed(self, ai_flags_on):
        tenant = new_tenant()
        await record_noesis_invocation(
            tenant_id=tenant, provider="openai", model="gpt-4o-mini", status="exploded",
        )
        fact = (await ai_aggregation.list_facts(tenant))[0]
        assert fact["status"] == "failed"


class TestProviderIntegration:
    async def test_anthropic_provider_records_invocation(self, ai_flags_on, monkeypatch):
        monkeypatch.setenv("NOESIS_LLM_ENABLED", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        from services.noesis.provider import AnthropicNoesisPlanProvider
        from services.noesis.models import NoesisQueryRequest

        class FakeBudget:
            async def check_and_reserve(self, tenant_id, tokens):
                return True

            async def release(self, tenant_id, tokens):
                return None

            async def charge(self, tenant_id, tokens):
                return None

        provider = AnthropicNoesisPlanProvider(budget=FakeBudget())

        async def _fake_call_api(user_message):
            return {
                "text": "not-a-plan",
                "tokens_used": 100,
                "input_tokens": 80,
                "output_tokens": 20,
            }

        monkeypatch.setattr(provider, "_call_api", _fake_call_api)
        tenant = new_tenant()
        request = NoesisQueryRequest(message="how many entities do we have?", surface="aether")
        plan = await provider.plan(request, tenant)
        assert plan is None  # invalid JSON → no plan, planning unaffected

        facts = await ai_aggregation.list_facts(tenant)
        assert len(facts) == 1
        assert facts[0]["provider"] == "anthropic"
        assert facts[0]["input_tokens"] == 80
        assert facts[0]["output_tokens"] == 20
        assert facts[0]["status"] == "succeeded"
        assert facts[0]["latency_ms"] is not None
