"""AI invocation projector: idempotency, flag gating, data quality, wiring."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.store import get_store  # noqa: E402
from services.economic.ai_pricing import AIPriceCardRegistry  # noqa: E402
from services.silver.projectors.ai_invocation_projector import (  # noqa: E402
    AI_EXECUTION_FACTS_STORE,
    AIInvocationProjector,
    DISPOSITION_CONFLICT,
    DISPOSITION_DUPLICATE,
    DISPOSITION_FLAG_OFF,
    DISPOSITION_INVALID,
    DISPOSITION_WRITTEN,
    fact_key,
    project_ai_invocation_event,
    write_execution_fact,
)
from ai_economics.factories import (  # noqa: E402
    bronze_event,
    make_observed,
    new_tenant,
    observed_payload,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


class TestIdempotency:
    async def test_write_then_duplicate_same_hash_skips(self, ai_flags_on):
        observed = make_observed(billed_cost=1.25)
        disposition, fact = await write_execution_fact(observed)
        assert disposition == DISPOSITION_WRITTEN
        assert fact is not None and fact.selected_cost == 1.25

        replay, replay_fact = await write_execution_fact(observed)
        assert replay == DISPOSITION_DUPLICATE
        assert replay_fact is None

    async def test_duplicate_different_hash_rejected(self, ai_flags_on):
        observed = make_observed(billed_cost=1.25)
        await write_execution_fact(observed)

        conflicting = make_observed(
            invocation_id=observed.invocation_id,
            tenant_id=observed.tenant_id,
            billed_cost=999.0,
        )
        assert conflicting.provenance.raw_event_hash != observed.provenance.raw_event_hash
        disposition, fact = await write_execution_fact(conflicting)
        assert disposition == DISPOSITION_CONFLICT
        assert fact is None

        # Original record untouched
        store = get_store(AI_EXECUTION_FACTS_STORE)
        stored = await store.get(fact_key(observed.tenant_id, observed.invocation_id))
        assert stored is not None and stored["selected_cost"] == 1.25


class TestFlagGating:
    async def test_flag_off_event_is_noop(self, ai_flags_off):
        payload = observed_payload(billed_cost=1.0)
        disposition, fact = await project_ai_invocation_event(bronze_event(payload))
        assert disposition == DISPOSITION_FLAG_OFF
        assert fact is None
        store = get_store(AI_EXECUTION_FACTS_STORE)
        assert await store.get(fact_key(payload["tenant_id"], payload["invocation_id"])) is None

    async def test_flag_off_sync_projector_skips(self, ai_flags_off):
        result = AIInvocationProjector().project(bronze_event(observed_payload()))
        assert result is not None and result.skipped
        assert result.skip_reason == "ai_execution_facts_disabled"

    async def test_flag_on_event_written(self, ai_flags_on):
        payload = observed_payload(billed_cost=2.0)
        disposition, fact = await project_ai_invocation_event(bronze_event(payload))
        assert disposition == DISPOSITION_WRITTEN
        assert fact is not None and fact.cost_basis == "billed"

    async def test_invalid_payload_rejected(self, ai_flags_on):
        payload = observed_payload(input_tokens=-5)
        disposition, fact = await project_ai_invocation_event(bronze_event(payload))
        assert disposition == DISPOSITION_INVALID
        assert fact is None

    async def test_prompt_content_payload_rejected(self, ai_flags_on):
        payload = observed_payload()
        payload["prompt"] = "never store me"
        disposition, _ = await project_ai_invocation_event(bronze_event(payload))
        assert disposition == DISPOSITION_INVALID


class TestDataQuality:
    async def test_complete_when_usage_and_cost_known(self, ai_flags_on):
        _, fact = await write_execution_fact(make_observed(billed_cost=1.0))
        assert fact is not None and fact.data_quality_status == "complete"

    async def test_partial_when_usage_missing(self, ai_flags_on):
        _, fact = await write_execution_fact(make_observed(
            billed_cost=1.0, input_tokens=None, output_tokens=None,
        ))
        assert fact is not None and fact.data_quality_status == "partial"

    async def test_partial_when_cost_unknown(self, ai_flags_on):
        _, fact = await write_execution_fact(make_observed())
        assert fact is not None
        assert fact.cost_basis == "unknown"
        assert fact.selected_cost is None  # unknown never becomes zero
        assert fact.data_quality_status == "partial"

    async def test_estimated_when_estimated_basis(self, ai_flags_on):
        _, fact = await write_execution_fact(make_observed(estimated_cost=0.7))
        assert fact is not None and fact.data_quality_status == "estimated"

    async def test_suspect_on_currency_mismatch(self, ai_flags_on):
        provider, model = f"prov-{uuid.uuid4().hex[:8]}", f"model-{uuid.uuid4().hex[:8]}"
        registry = AIPriceCardRegistry()
        await registry.add_card({
            "provider": provider, "model": model, "currency": "USD",
            "pricing_version": "v-dq", "rates": {"input_tokens_per_1k": 0.001},
            "effective_from": "2026-01-01T00:00:00+00:00", "source": "test",
        })
        _, fact = await write_execution_fact(make_observed(
            provider=provider, model=model, currency="EUR",
        ))
        assert fact is not None and fact.data_quality_status == "suspect"

    async def test_calculated_cost_uses_card_pricing_version(self, ai_flags_on):
        provider, model = f"prov-{uuid.uuid4().hex[:8]}", f"model-{uuid.uuid4().hex[:8]}"
        registry = AIPriceCardRegistry()
        await registry.add_card({
            "provider": provider, "model": model, "currency": "USD",
            "pricing_version": "v-calc",
            "rates": {"input_tokens_per_1k": 0.001, "output_tokens_per_1k": 0.002},
            "effective_from": "2026-01-01T00:00:00+00:00", "source": "test",
        })
        _, fact = await write_execution_fact(make_observed(provider=provider, model=model))
        assert fact is not None
        assert fact.cost_basis == "calculated"
        assert fact.pricing_version == "v-calc"
        assert fact.data_quality_status == "complete"


class TestWiring:
    async def test_projector_registered_in_dispatcher(self):
        from services.silver.dispatcher import SilverDispatcher
        dispatcher = SilverDispatcher()
        assert dispatcher.handles("ai_invocation_observed")
        assert "AIInvocationProjector" in dispatcher.projectors_for("ai_invocation_observed")

    async def test_tenant_prefixed_key(self, ai_flags_on):
        tenant = new_tenant()
        observed = make_observed(tenant_id=tenant, billed_cost=0.1)
        await write_execution_fact(observed)
        store = get_store(AI_EXECUTION_FACTS_STORE)
        assert await store.get(f"{tenant}:{observed.invocation_id}") is not None
