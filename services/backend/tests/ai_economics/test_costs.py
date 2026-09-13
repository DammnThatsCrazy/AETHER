"""Cost selection hierarchy: billed → provider_reported → calculated →
estimated → unknown. Unknown stays unknown; currencies never mix. Money values
stay Decimal through selection (the float wire shape is produced only at the
Pydantic serialization boundary on ``ai_models``)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.economic import ai_aggregation  # noqa: E402
from services.economic.ai_costs import select_cost  # noqa: E402
from services.economic.ai_models import AIExecutionFact  # noqa: E402
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
        assert selection.selected_cost == Decimal("9.99")

    async def test_actual_cost_is_provider_reported(self):
        observed = make_observed(actual_cost=5.5, estimated_cost=1.0)
        selection = await select_cost(observed)
        assert selection.cost_basis == "provider_reported"
        assert selection.selected_cost == Decimal("5.5")

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
        assert selection.selected_cost == Decimal("0.003")
        assert selection.pricing_version == "v-cost-test"

    async def test_estimated_fallback_without_card(self):
        observed = make_observed(estimated_cost=0.42)
        selection = await select_cost(observed)
        assert selection.cost_basis == "estimated"
        assert selection.selected_cost == Decimal("0.42")

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
        assert selection.selected_cost == Decimal("0.5")
        assert selection.currency_mismatch is True

    async def test_matching_currency_not_flagged(self):
        provider, model = _unique("prov"), _unique("model")
        registry = await _card_for(provider, model, currency="USD")
        observed = make_observed(provider=provider, model=model, currency="USD")
        selection = await select_cost(observed, registry)
        assert selection.cost_basis == "calculated"
        assert selection.currency_mismatch is False


class TestDecimalPrecisionPreserved:
    """Money values stay Decimal through selection and aggregation; the float
    wire shape is produced ONLY at the external serialization boundary."""

    async def test_high_precision_subcent_cost_preserved_until_wire(self):
        precision_cost = Decimal("0.0000001234")
        observed = make_observed(billed_cost=precision_cost)
        selection = await select_cost(observed)
        assert selection.cost_basis == "billed"
        assert isinstance(selection.selected_cost, Decimal)
        assert selection.selected_cost == precision_cost

        # Exact Decimal aggregation — never rounded through float at selection.
        totals = ai_aggregation._total_cost_by_currency([
            {
                "selected_cost": selection.selected_cost,
                "currency": "USD",
                "cost_basis": "billed",
            },
            {
                "selected_cost": Decimal("0.0000002466"),
                "currency": "USD",
                "cost_basis": "billed",
            },
        ])
        assert totals == {"USD": Decimal("0.0000003700")}

        # The fact carries the exact Decimal; only the JSON wire shape is float.
        now = datetime.now(timezone.utc).isoformat()
        fact = AIExecutionFact(
            **observed.model_dump(exclude={"pricing_version"}),
            pricing_version=selection.pricing_version or observed.pricing_version,
            selected_cost=selection.selected_cost,
            cost_basis=selection.cost_basis,
            received_at=now,
            computed_at=now,
            data_quality_status="complete",
        )
        assert fact.selected_cost == precision_cost
        assert isinstance(fact.model_dump(mode="json")["selected_cost"], float)

    async def test_estimated_high_precision_stays_decimal(self):
        precision_cost = Decimal("0.0000001234")
        observed = make_observed(estimated_cost=precision_cost)
        selection = await select_cost(observed)
        assert selection.cost_basis == "estimated"
        assert isinstance(selection.selected_cost, Decimal)
        assert selection.selected_cost == precision_cost
