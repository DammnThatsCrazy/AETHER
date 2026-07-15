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

from datetime import datetime, timedelta, timezone
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

    @pytest.mark.asyncio
    async def test_historical_lookback_uses_conversion_timestamp(self):
        from services.attribution.resolver import AttributionConfig, AttributionResolver

        resolver = AttributionResolver(AttributionConfig(lookback_window_hours=48))
        result = await resolver.resolve(
            user_id="historical-user",
            event={"event_type": "purchase", "timestamp": "2020-01-02T00:00:00Z"},
            touchpoints=[{
                "channel": "referral",
                "source": "chatgpt.com",
                "timestamp": "2020-01-01T00:00:00Z",
                "properties": {"touchpoint_id": str(uuid4())},
            }],
            model_name="last_touch",
        )

        assert len(result.credits) == 1


def test_credit_metadata_matches_exact_touchpoint_id():
    from services.measurement.engine.attribution_engine import _find_touchpoint_by_id

    first_id = str(uuid4())
    second_id = str(uuid4())
    touches = [
        {"touchpoint_id": first_id, "channel": "referral", "source": "chatgpt", "campaign_id": "campaign-a"},
        {"touchpoint_id": second_id, "channel": "referral", "source": "chatgpt", "campaign_id": "campaign-b"},
    ]

    assert _find_touchpoint_by_id(touches, first_id)["campaign_id"] == "campaign-a"
    assert _find_touchpoint_by_id(touches, second_id)["campaign_id"] == "campaign-b"


def test_resolver_payload_carries_source_classification_snapshot():
    from services.measurement.engine.attribution_engine import _touchpoint_to_resolver_dict

    payload = _touchpoint_to_resolver_dict({
        "touchpoint_id": str(uuid4()),
        "actor_type": "agent",
        "source_class": "ai_referral",
        "referral_mediation_type": "agent_mediated_referral",
        "ai_provider": "anthropic",
        "ai_product": "claude",
        "journey_role": "assist",
        "evidence_confidence": 0.88,
        "verification_level": "verified_link",
        "source_classifier_version": "2.0",
        "attribution_eligible": True,
    })

    assert payload["properties"]["actor_type"] == "agent"
    assert payload["properties"]["ai_provider"] == "anthropic"
    assert payload["properties"]["ai_product"] == "claude"
    assert payload["properties"]["source_classifier_version"] == "2.0"


@pytest.mark.asyncio
async def test_atomic_run_switch_and_referral_rollups_local():
    from services.measurement.repositories.attribution_run_repo import (
        AttributionRunRepository,
        _local_credits,
        _local_runs,
    )

    _local_runs.clear()
    _local_credits.clear()
    repo = AttributionRunRepository()
    repo._pool = AsyncMock(return_value=None)
    conversion_id = str(uuid4())

    first = await repo.create_run({
        "tenant_id": "tenant-a",
        "conversion_id": conversion_id,
        "model_type": "last_touch",
    })
    await repo.complete_run_atomically(
        first["attribution_run_id"],
        "tenant-a",
        conversion_id,
        [],
        {"credit_total": "0", "unattributed_credit": "1"},
    )

    touchpoint_id = str(uuid4())
    second = await repo.create_run({
        "tenant_id": "tenant-a",
        "conversion_id": conversion_id,
        "model_type": "last_touch",
        "prior_attribution_run_id": first["attribution_run_id"],
    })
    credit = {
        "touchpoint_id": touchpoint_id,
        "campaign_id": "campaign-a",
        "source_class": "ai_referral",
        "referral_mediation_type": "ai_mediated_human_referral",
        "ai_provider": "openai",
        "ai_product": "chatgpt",
        "actor_type": "human",
        "journey_role": "entry",
        "verification_level": "domain_verified",
        "credit_weight": "1",
        "attributed_conversion_count": "1",
        "attributed_gross_revenue": "120",
        "attributed_net_revenue": "100",
    }
    completed = await repo.complete_run_atomically(
        second["attribution_run_id"],
        "tenant-a",
        conversion_id,
        [credit],
        {
            "credit_total": "1",
            "unattributed_credit": "0",
            "input_touchpoint_ids": [touchpoint_id],
            "trigger_reason": "source_reclassification",
            "source_classifier_version": "2.0",
        },
    )

    assert completed["is_active"] is True
    assert first["is_active"] is False
    assert completed["input_touchpoint_ids"] == [touchpoint_id]

    summary = await repo.campaign_credit_summary("tenant-a", "campaign-a")
    assert summary["dimension_rollups"]["ai_provider"][0]["value"] == "openai"
    performance = await repo.referral_performance("tenant-a", ai_provider="openai")
    assert performance["row_count"] == 1
    assert performance["rows"][0]["ai_product"] == "chatgpt"


@pytest.mark.asyncio
async def test_recompute_reuses_prior_model_config_snapshot_semantics():
    from services.measurement.engine.attribution_engine import AttributionEngine

    conversion_id = str(uuid4())
    conversion_at = datetime(2026, 7, 10, tzinfo=timezone.utc)
    run_id = str(uuid4())
    run_repo = MagicMock()
    run_repo.get_active_run = AsyncMock(return_value={
        "attribution_run_id": str(uuid4()),
        "model_type": "last_touch",
        "model_version": "7",
        "model_config_id": str(uuid4()),
        "model_config_snapshot": {
            "model_type": "last_touch",
            "model_version": "7",
            "click_lookback_window": 24,
            "view_lookback_window": 6,
            "identity_confidence_min": 0.8,
            "fraud_policy": "exclude",
            "direct_traffic_policy": "exclude",
        },
    })
    run_repo.create_run = AsyncMock(
        side_effect=lambda row: {**row, "attribution_run_id": run_id}
    )
    run_repo.update_run = AsyncMock()
    run_repo.complete_run_atomically = AsyncMock(
        side_effect=lambda _run_id, _tenant, _conversion, _credits, updates: {
            "attribution_run_id": run_id,
            **updates,
        }
    )
    conversion_repo = MagicMock()
    conversion_repo.get = AsyncMock(return_value={
        "conversion_id": conversion_id,
        "profile_id": "profile-1",
        "occurred_at": conversion_at.isoformat(),
        "attribution_eligible": True,
        "gross_value": "100",
        "net_value": "80",
        "currency": "USD",
    })
    touchpoint_repo = MagicMock()
    direct_id = str(uuid4())
    old_id = str(uuid4())
    touchpoint_repo.list_by_profile = AsyncMock(return_value=[
        {
            "touchpoint_id": direct_id,
            "profile_id": "profile-1",
            "occurred_at": (conversion_at - timedelta(hours=1)).isoformat(),
            "source_class": "direct",
            "referral_mediation_type": "direct_entry",
            "attribution_eligible": True,
        },
        {
            "touchpoint_id": old_id,
            "profile_id": "profile-1",
            "occurred_at": (conversion_at - timedelta(hours=30)).isoformat(),
            "source_class": "ai_referral",
            "attribution_eligible": True,
        },
    ])
    journey_repo = MagicMock()
    journey_repo.find_current_for_profile = AsyncMock(return_value=[])

    engine = AttributionEngine()
    engine._run_repo = run_repo
    engine._conversion_repo = conversion_repo
    engine._touchpoint_repo = touchpoint_repo
    engine._journey_repo = journey_repo

    await engine.run_for_conversion(
        "tenant-a", conversion_id, trigger_reason="source_classifier:2.0"
    )

    created = run_repo.create_run.await_args.args[0]
    assert created["model_version"] == "7"
    assert created["model_config_snapshot"]["click_lookback_window"] == 24
    completed_updates = run_repo.complete_run_atomically.await_args.args[4]
    assert completed_updates["exclusion_reasons"] == {
        direct_id: "direct_traffic_policy",
        old_id: "outside_lookback",
    }


@pytest.mark.asyncio
async def test_snapshot_lookback_longer_than_resolver_default_is_preserved():
    from services.measurement.engine.attribution_engine import AttributionEngine

    conversion_id = str(uuid4())
    conversion_at = datetime(2026, 7, 10, tzinfo=timezone.utc)
    touchpoint_id = str(uuid4())
    run_id = str(uuid4())

    run_repo = MagicMock()
    run_repo.get_active_run = AsyncMock(return_value={
        "attribution_run_id": str(uuid4()),
        "model_type": "last_touch",
        "model_version": "7",
        "model_config_id": str(uuid4()),
        "model_config_snapshot": {
            "model_type": "last_touch",
            "model_version": "7",
            # Forty-one days is inside this snapshot but outside the
            # process-wide resolver default of 720 hours (30 days).
            "click_lookback_window": 1440,
            "view_lookback_window": 168,
        },
    })
    run_repo.create_run = AsyncMock(
        side_effect=lambda row: {**row, "attribution_run_id": run_id}
    )
    run_repo.update_run = AsyncMock()
    run_repo.complete_run_atomically = AsyncMock(
        side_effect=lambda _run_id, _tenant, _conversion, _credits, updates: {
            "attribution_run_id": run_id,
            **updates,
        }
    )

    conversion_repo = MagicMock()
    conversion_repo.get = AsyncMock(return_value={
        "conversion_id": conversion_id,
        "profile_id": "profile-long-lookback",
        "occurred_at": conversion_at.isoformat(),
        "attribution_eligible": True,
        "gross_value": "100",
        "net_value": "80",
        "currency": "USD",
    })
    touchpoint_repo = MagicMock()
    touchpoint_repo.list_by_profile = AsyncMock(return_value=[{
        "touchpoint_id": touchpoint_id,
        "profile_id": "profile-long-lookback",
        "occurred_at": (conversion_at - timedelta(hours=1000)).isoformat(),
        "channel": "referral",
        "source": "partner.example",
        "touchpoint_type": "click",
        "is_click_through": True,
        "attribution_eligible": True,
    }])
    journey_repo = MagicMock()
    journey_repo.find_current_for_profile = AsyncMock(return_value=[])

    engine = AttributionEngine()
    engine._run_repo = run_repo
    engine._conversion_repo = conversion_repo
    engine._touchpoint_repo = touchpoint_repo
    engine._journey_repo = journey_repo

    await engine.run_for_conversion("tenant-a", conversion_id)

    created = run_repo.create_run.await_args.args[0]
    assert created["model_config_snapshot"]["click_lookback_window"] == 1440
    credits = run_repo.complete_run_atomically.await_args.args[3]
    completed_updates = run_repo.complete_run_atomically.await_args.args[4]
    assert [credit["touchpoint_id"] for credit in credits] == [touchpoint_id]
    assert completed_updates["credit_total"] == "1.0"
    assert completed_updates["excluded_touchpoint_ids"] == []
