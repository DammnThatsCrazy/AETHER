"""Price card registry: effective dating, specificity, validity, seeding."""

from __future__ import annotations

import os
import uuid

import pytest
from pydantic import ValidationError

os.environ.setdefault("AETHER_ENV", "local")

from services.economic.ai_pricing import (  # noqa: E402
    AIPriceCardRegistry,
    SEED_PRICING_VERSION,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _card(provider: str, model: str, **overrides) -> dict:
    base = {
        "provider": provider,
        "model": model,
        "currency": "USD",
        "pricing_version": "v-test",
        "rates": {"input_tokens_per_1k": 0.001, "output_tokens_per_1k": 0.002},
        "effective_from": "2026-01-01T00:00:00+00:00",
        "source": "test",
    }
    base.update(overrides)
    return base


class TestEffectiveDating:
    async def test_window_selection(self):
        registry = AIPriceCardRegistry()
        provider, model = _unique("prov"), _unique("model")
        await registry.add_card(_card(
            provider, model, pricing_version="v-old",
            effective_from="2026-01-01T00:00:00+00:00",
            effective_to="2026-06-01T00:00:00+00:00",
        ))
        await registry.add_card(_card(
            provider, model, pricing_version="v-new",
            effective_from="2026-06-01T00:00:00+00:00",
        ))
        old = await registry.get_active_card(provider, model, at="2026-03-01T00:00:00+00:00")
        new = await registry.get_active_card(provider, model, at="2026-07-01T00:00:00+00:00")
        boundary = await registry.get_active_card(provider, model, at="2026-06-01T00:00:00+00:00")
        assert old is not None and old.pricing_version == "v-old"
        assert new is not None and new.pricing_version == "v-new"
        # effective_from <= at < effective_to: boundary belongs to the new card
        assert boundary is not None and boundary.pricing_version == "v-new"

    async def test_before_effective_from_returns_none(self):
        registry = AIPriceCardRegistry()
        provider, model = _unique("prov"), _unique("model")
        await registry.add_card(_card(provider, model))
        assert await registry.get_active_card(
            provider, model, at="2025-12-31T23:59:59+00:00"
        ) is None

    async def test_after_effective_to_returns_none(self):
        registry = AIPriceCardRegistry()
        provider, model = _unique("prov"), _unique("model")
        await registry.add_card(_card(
            provider, model, effective_to="2026-02-01T00:00:00+00:00"
        ))
        assert await registry.get_active_card(
            provider, model, at="2026-02-01T00:00:00+00:00"
        ) is None


class TestSpecificity:
    async def test_most_specific_match_wins(self):
        registry = AIPriceCardRegistry()
        provider, model = _unique("prov"), _unique("model")
        await registry.add_card(_card(provider, model, pricing_version="base"))
        await registry.add_card(_card(
            provider, model, pricing_version="regional", region="eu-west-1"
        ))
        await registry.add_card(_card(
            provider, model, pricing_version="regional-tiered",
            region="eu-west-1", service_tier="batch",
        ))

        base = await registry.get_active_card(provider, model, at="2026-03-01T00:00:00+00:00")
        regional = await registry.get_active_card(
            provider, model, region="eu-west-1", at="2026-03-01T00:00:00+00:00"
        )
        tiered = await registry.get_active_card(
            provider, model, region="eu-west-1", service_tier="batch",
            at="2026-03-01T00:00:00+00:00",
        )
        assert base is not None and base.pricing_version == "base"
        assert regional is not None and regional.pricing_version == "regional"
        assert tiered is not None and tiered.pricing_version == "regional-tiered"

    async def test_mismatched_region_card_excluded(self):
        registry = AIPriceCardRegistry()
        provider, model = _unique("prov"), _unique("model")
        await registry.add_card(_card(provider, model, region="us-east-1"))
        assert await registry.get_active_card(
            provider, model, region="eu-west-1", at="2026-03-01T00:00:00+00:00"
        ) is None


class TestValidity:
    async def test_inverted_window_rejected(self):
        registry = AIPriceCardRegistry()
        with pytest.raises((ValidationError, ValueError)):
            await registry.add_card(_card(
                _unique("prov"), _unique("model"),
                effective_from="2026-06-01T00:00:00+00:00",
                effective_to="2026-01-01T00:00:00+00:00",
            ))

    async def test_negative_rate_rejected(self):
        registry = AIPriceCardRegistry()
        with pytest.raises((ValidationError, ValueError)):
            await registry.add_card(_card(
                _unique("prov"), _unique("model"),
                rates={"input_tokens_per_1k": -1.0},
            ))


class TestTenantScope:
    async def test_tenant_card_not_visible_to_other_tenant(self):
        registry = AIPriceCardRegistry()
        provider, model = _unique("prov"), _unique("model")
        await registry.add_card(_card(provider, model), tenant_id="tenant-a")
        found_a = await registry.get_active_card(
            provider, model, tenant_id="tenant-a", at="2026-03-01T00:00:00+00:00"
        )
        found_b = await registry.get_active_card(
            provider, model, tenant_id="tenant-b", at="2026-03-01T00:00:00+00:00"
        )
        assert found_a is not None
        assert found_b is None


class TestSeedCards:
    async def test_seed_idempotent_and_active(self):
        registry = AIPriceCardRegistry()
        await registry.ensure_seed_cards()
        second = await registry.ensure_seed_cards()
        assert second == 0  # nothing rewritten

        haiku = await registry.get_active_card("anthropic", "claude-haiku-4-5")
        mini = await registry.get_active_card("openai", "gpt-4o-mini")
        assert haiku is not None and haiku.pricing_version == SEED_PRICING_VERSION
        assert haiku.rates.input_tokens_per_1k == 0.001
        assert haiku.rates.output_tokens_per_1k == 0.005
        assert mini is not None and mini.rates.input_tokens_per_1k == 0.00015
        assert mini.rates.output_tokens_per_1k == 0.0006
        assert haiku.currency == mini.currency == "USD"
