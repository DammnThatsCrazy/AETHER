"""Unit tests — AttributionEngine per-conversion attribution and credit reconciliation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _make_touchpoints(n: int = 3, channel: str = "paid_search") -> list[dict]:
    return [
        {
            "touchpoint_id": str(uuid4()),
            "channel": channel,
            "source": f"src_{i}",
            "occurred_at": _ts(),
            "touchpoint_type": "click",
            "is_click_through": True,
        }
        for i in range(n)
    ]


class TestAttributionEngineLocal:
    """Tests that run against the local in-memory stores (no DB)."""

    @pytest.mark.asyncio
    async def test_credits_sum_to_one_linear(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(4)
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": 100.0},
            touchpoints=tps,
            model_name="linear",
        )
        total = sum(c.weight for c in result.credits)
        assert abs(total - 1.0) < 0.001, f"Credits sum to {total}, expected 1.0"

    @pytest.mark.asyncio
    async def test_credits_sum_to_one_first_touch(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(3)
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": 50.0},
            touchpoints=tps,
            model_name="first_touch",
        )
        total = sum(c.weight for c in result.credits)
        assert abs(total - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_credits_sum_to_one_last_touch(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(2)
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": 200.0},
            touchpoints=tps,
            model_name="last_touch",
        )
        total = sum(c.weight for c in result.credits)
        assert abs(total - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_credits_sum_to_one_position_based(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(5)
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": 75.0},
            touchpoints=tps,
            model_name="position_based",
        )
        total = sum(c.weight for c in result.credits)
        assert abs(total - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_credits_sum_to_one_time_decay(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(4)
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": 33.33},
            touchpoints=tps,
            model_name="time_decay",
        )
        total = sum(c.weight for c in result.credits)
        assert abs(total - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_empty_touchpoints_returns_empty_credits(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": 50.0},
            touchpoints=[],
            model_name="linear",
        )
        assert result.credits == [] or sum(c.weight for c in result.credits) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_attributed_revenue_reconciles(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        revenue = 149.99
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(3)
        result = await resolver.resolve(
            user_id="u1",
            event={"event_type": "purchase", "revenue": revenue},
            touchpoints=tps,
            model_name="linear",
        )
        total_weight = sum(c.weight for c in result.credits)
        attributed = total_weight * revenue
        assert abs(attributed - revenue) < 0.02, (
            f"Attributed revenue {attributed} does not reconcile with {revenue}"
        )

    @pytest.mark.asyncio
    async def test_single_touchpoint_gets_full_credit(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(1)
        for model in ("first_touch", "last_touch", "linear", "time_decay"):
            result = await resolver.resolve(
                user_id="u1",
                event={"event_type": "purchase", "revenue": 100.0},
                touchpoints=tps,
                model_name=model,
            )
            if result.credits:
                total = sum(c.weight for c in result.credits)
                assert abs(total - 1.0) < 0.001, f"Model {model}: credits sum to {total}"

    @pytest.mark.asyncio
    async def test_no_negative_credits(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver
        resolver = AttributionResolver(AttributionConfig())
        tps = _make_touchpoints(5)
        for model in ("linear", "time_decay", "position_based", "first_touch", "last_touch"):
            result = await resolver.resolve(
                user_id="u1",
                event={"event_type": "purchase", "revenue": 100.0},
                touchpoints=tps,
                model_name=model,
            )
            for c in result.credits:
                assert c.weight >= 0.0, f"Model {model}: negative credit weight {c.weight}"
