"""Cost selection hierarchy: billed → provider_reported → calculated →
estimated → unknown. Unknown stays unknown; currencies never mix."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.economic.ai_costs import select_cost  # noqa: E402
from services.economic.ai_pricing import AIPriceCardRegistry  # noqa: E402
from ai_economics.factories import make_observed  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _card_for(provider: str, model: str, currency: str = "USD") -> AIPriceCardRegistry:
    registry = AIPriceCardRegistry()
    await registry.add_card({
        "provider": provider,
        "model": model,
        "currency": currency,
        "pricing_version": "v-cost-test",
        "rates": {"input_tokens_per_1k": 0.001, "output_tokens_per_1k": 0.002},
        "effective_from": "2026-01-01T00:00:00+00:00",
        "source": "test",
    })
    return registry


class TestHierarchy:
    async def test_billed_wins_over_everything(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model)
        observed = make_observed(
            provider=provider, model=model,
            billed_cost=9.99, actual_cost=5.0, estimated_cost=1.0,
        )
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "billed"
        assert selection.selected_cost == 9.99

    async def test_actual_cost_is_provider_reported(self):
        observed = make_observed(actual_cost=5.5, estimated_cost=1.0)
        selection = await select_cost(observed)
        assert selection.cost_basis == "provider_reported"
        assert selection.selected_cost == 5.5

    async def test_calculated_from_active_card(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model)
        observed = make_observed(
            provider=provider, model=model,
            input_tokens=2000, output_tokens=500, estimated_cost=99.0,
        )
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "calculated"
        # 2000/1000*0.001 + 500/1000*0.002 = 0.002 + 0.001
        assert selection.selected_cost == pytest.approx(0.003)
        assert selection.pricing_version == "v-cost-test"

    async def test_estimated_fallback_without_card(self):
        observed = make_observed(estimated_cost=0.42)
        selection = await select_cost(observed)
        assert selection.cost_basis == "estimated"
        assert selection.selected_cost == 0.42

    async def test_unknown_stays_unknown_never_zero(self):
        observed = make_observed()  # no costs, unique provider → no card
        selection = await select_cost(observed)
        assert selection.cost_basis == "unknown"
        assert selection.selected_cost is None  # NOT 0.0

    async def test_card_without_matching_usage_falls_through(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model)
        observed = make_observed(
            provider=provider, model=model,
            input_tokens=None, output_tokens=None, latency_ms=10.0,
        )
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "unknown"
        assert selection.selected_cost is None


class TestCurrencySafety:
    async def test_mismatch_falls_back_to_unknown_and_flags(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model, currency="USD")
        observed = make_observed(provider=provider, model=model, currency="EUR")
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "unknown"
        assert selection.selected_cost is None
        assert selection.currency_mismatch is True

    async def test_mismatch_with_estimate_uses_estimate_and_flags(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model, currency="USD")
        observed = make_observed(
            provider=provider, model=model, currency="EUR", estimated_cost=0.5
        )
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "estimated"
        assert selection.selected_cost == 0.5
        assert selection.currency_mismatch is True

    async def test_matching_currency_not_flagged(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model, currency="USD")
        observed = make_observed(provider=provider, model=model, currency="USD")
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "calculated"
        assert selection.currency_mismatch is False
