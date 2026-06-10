"""Tests for IntelligenceAggregator — the 14 previously-stubbed Profile 360
intelligence extension endpoints plus the campaigns aggregator method.

These tests verify:
  * Each method returns the standard SubResourceEnvelope shape.
  * Window filtering correctly excludes stale records.
  * Cross-tenant rows are excluded.
  * Empty gold-tier stores yield empty-but-shaped responses (never raise).
  * Consent enforcement gates the /web2 endpoint.
  * Aggregations (avg_roas, device conversion_rate, funnel stages, etc.) are correct.
  * Repository failures degrade gracefully (empty list, not 500).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.profile.intelligence import IntelligenceAggregator


def _run(coro):
    return asyncio.run(coro)


# ── Gold repo stub ────────────────────────────────────────────────────


class _GoldRepo:
    """Minimal stand-in matching the GoldRepository surface used by IntelligenceAggregator."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = list(rows or [])

    async def get_metrics(self, entity_id: str, entity_type: str = "", metric_name: str = "") -> list[dict]:
        return [r for r in self._rows if r.get("entity_id") == entity_id]


class _BrokenRepo:
    """Repo that always raises — used to verify graceful degradation."""

    async def get_metrics(self, *_, **__):
        raise RuntimeError("injected failure")


class _ConsentRepo:
    def __init__(self, *, granted: bool = False, purposes: list[str] | None = None) -> None:
        self._granted = granted
        self._purposes = purposes or []

    async def get_consent(self, tenant_id: str, user_id: str) -> Optional[dict]:
        if not self._granted:
            return None
        return {"granted_purposes": self._purposes, "tenant_id": tenant_id, "user_id": user_id}


# ── Helpers ───────────────────────────────────────────────────────────


def _utc(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _gold_row(entity_id: str, tenant_id: str, value: Any = None, dimensions: dict | None = None, days_ago: int = 5) -> dict:
    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "metric_name": "test_metric",
        "value": value or {},
        "dimensions": dimensions or {},
        "materialized_at": _utc(days_ago),
    }


def _make_intel(
    *,
    entity_tiers=None,
    asset_composition=None,
    pnl=None,
    trading_profile=None,
    location_history=None,
    temporal_heatmap=None,
    social_intelligence=None,
    journey_economics=None,
    ad_spend=None,
    credit_signals=None,
    tradfi_portfolio=None,
    web3_daily_metrics=None,
    governance=None,
    consent=None,
) -> IntelligenceAggregator:
    return IntelligenceAggregator(
        entity_tiers_repo=entity_tiers or _GoldRepo(),
        asset_composition_repo=asset_composition or _GoldRepo(),
        pnl_repo=pnl or _GoldRepo(),
        trading_profile_repo=trading_profile or _GoldRepo(),
        location_history_repo=location_history or _GoldRepo(),
        temporal_heatmap_repo=temporal_heatmap or _GoldRepo(),
        social_intelligence_repo=social_intelligence or _GoldRepo(),
        journey_economics_repo=journey_economics or _GoldRepo(),
        ad_spend_repo=ad_spend or _GoldRepo(),
        credit_signals_repo=credit_signals or _GoldRepo(),
        tradfi_portfolio_repo=tradfi_portfolio or _GoldRepo(),
        web3_daily_metrics_repo=web3_daily_metrics or _GoldRepo(),
        governance_repo=governance or _GoldRepo(),
        consent_repo=consent or _ConsentRepo(),
    )


# ── Envelope shape helper ─────────────────────────────────────────────


def _assert_envelope(result: dict, kind: str, entity_id: str = "u-1", tenant_id: str = "t-a") -> None:
    assert result["entity_id"] == entity_id, f"entity_id mismatch: {result}"
    assert result["kind"] == kind, f"kind mismatch: {result}"
    assert "items" in result, f"no items key: {result}"
    assert "summary" in result, f"no summary key: {result}"
    assert "provenance" in result, f"no provenance key: {result}"
    assert "computed_at" in result, f"no computed_at key: {result}"


# ══════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════


class TestTier:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.tier("u-1", "t-a"))
        _assert_envelope(result, "tier")
        assert result["items"] == []
        assert result["summary"]["tier"] is None

    def test_returns_tier_data(self):
        row = _gold_row("u-1", "t-a", dimensions={"tier": "Whale", "percentile": 0.95, "score": 0.88})
        intel = _make_intel(entity_tiers=_GoldRepo([row]))
        result = _run(intel.tier("u-1", "t-a"))
        assert len(result["items"]) == 1
        assert result["items"][0]["tier"] == "Whale"
        assert result["items"][0]["percentile"] == 0.95
        assert result["summary"]["tier"] == "Whale"

    def test_cross_tenant_excluded(self):
        row = _gold_row("u-1", "t-other", dimensions={"tier": "Shark"})
        intel = _make_intel(entity_tiers=_GoldRepo([row]))
        result = _run(intel.tier("u-1", "t-a"))
        assert result["items"] == []

    def test_window_filters_stale(self):
        stale = _gold_row("u-1", "t-a", dimensions={"tier": "Fish"}, days_ago=45)
        fresh = _gold_row("u-1", "t-a", dimensions={"tier": "Dolphin"}, days_ago=5)
        intel = _make_intel(entity_tiers=_GoldRepo([stale, fresh]))
        result = _run(intel.tier("u-1", "t-a", window="30d"))
        assert len(result["items"]) == 1
        assert result["items"][0]["tier"] == "Dolphin"

    def test_lifetime_window_includes_all(self):
        old = _gold_row("u-1", "t-a", dimensions={"tier": "Fish"}, days_ago=365)
        intel = _make_intel(entity_tiers=_GoldRepo([old]))
        result = _run(intel.tier("u-1", "t-a", window="lifetime"))
        assert len(result["items"]) == 1

    def test_broken_repo_degrades(self):
        intel = _make_intel(entity_tiers=_BrokenRepo())
        result = _run(intel.tier("u-1", "t-a"))
        _assert_envelope(result, "tier")
        assert result["items"] == []


class TestAssetComposition:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.asset_composition("u-1", "t-a"))
        _assert_envelope(result, "asset_composition")
        assert result["summary"]["total_value_usd"] == 0.0

    def test_percentage_computed(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"category": "stablecoin", "value_usd": 1000.0}),
            _gold_row("u-1", "t-a", dimensions={"category": "eth", "value_usd": 1000.0}),
        ]
        intel = _make_intel(asset_composition=_GoldRepo(rows))
        result = _run(intel.asset_composition("u-1", "t-a"))
        assert len(result["items"]) == 2
        for item in result["items"]:
            assert item["percentage"] == 0.5
        assert result["summary"]["total_value_usd"] == 2000.0

    def test_cross_tenant_excluded(self):
        row = _gold_row("u-1", "t-other", dimensions={"category": "btc", "value_usd": 500})
        intel = _make_intel(asset_composition=_GoldRepo([row]))
        result = _run(intel.asset_composition("u-1", "t-a"))
        assert result["items"] == []

    def test_broken_repo_degrades(self):
        intel = _make_intel(asset_composition=_BrokenRepo())
        result = _run(intel.asset_composition("u-1", "t-a"))
        assert result["items"] == []


class TestPnl:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.pnl("u-1", "t-a"))
        _assert_envelope(result, "pnl")
        assert result["summary"]["total_realized_pnl"] == 0.0

    def test_pnl_items_and_summary(self):
        row = _gold_row("u-1", "t-a", dimensions={"realized_pnl": 500.0, "unrealized_pnl": -100.0})
        intel = _make_intel(pnl=_GoldRepo([row]))
        result = _run(intel.pnl("u-1", "t-a"))
        assert len(result["items"]) == 1
        assert result["items"][0]["realized_pnl"] == 500.0
        assert result["summary"]["total_realized_pnl"] == 500.0
        assert result["summary"]["total_unrealized_pnl"] == -100.0

    def test_cross_tenant_excluded(self):
        row = _gold_row("u-1", "t-other", dimensions={"realized_pnl": 999.0})
        intel = _make_intel(pnl=_GoldRepo([row]))
        result = _run(intel.pnl("u-1", "t-a"))
        assert result["items"] == []


class TestTradingProfile:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.trading_profile("u-1", "t-a"))
        _assert_envelope(result, "trading_profile")
        assert result["summary"]["profile_computed"] is False

    def test_returns_data(self):
        row = _gold_row("u-1", "t-a", dimensions={"favorite_pairs": ["ETH/USDC"], "trade_count": 42})
        intel = _make_intel(trading_profile=_GoldRepo([row]))
        result = _run(intel.trading_profile("u-1", "t-a"))
        assert result["summary"]["trade_count"] == 42
        assert result["summary"]["profile_computed"] is True


class TestLocationHistory:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.location_history("u-1", "t-a"))
        _assert_envelope(result, "location_history")
        assert "pagination" in result

    def test_returns_locations_with_limit(self):
        rows = [_gold_row("u-1", "t-a", dimensions={"city": f"City{i}", "classification": "secondary"}) for i in range(25)]
        intel = _make_intel(location_history=_GoldRepo(rows))
        result = _run(intel.location_history("u-1", "t-a", limit=10))
        assert len(result["items"]) == 10

    def test_primary_location_in_summary(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"city": "SF", "classification": "primary"}),
            _gold_row("u-1", "t-a", dimensions={"city": "NYC", "classification": "secondary"}),
        ]
        intel = _make_intel(location_history=_GoldRepo(rows))
        result = _run(intel.location_history("u-1", "t-a"))
        assert result["summary"]["primary_location"] == "SF"


class TestTemporalHeatmap:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.temporal_heatmap("u-1", "t-a"))
        _assert_envelope(result, "temporal_heatmap")
        assert result["summary"]["peak_hour_utc"] is None

    def test_peak_hour_detected(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"day_of_week": "monday", "hour_utc": 14, "activity_count": 10}),
            _gold_row("u-1", "t-a", dimensions={"day_of_week": "tuesday", "hour_utc": 9, "activity_count": 3}),
        ]
        intel = _make_intel(temporal_heatmap=_GoldRepo(rows))
        result = _run(intel.temporal_heatmap("u-1", "t-a"))
        assert result["summary"]["peak_hour_utc"] == 14


class TestSocialIntelligence:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.social_intelligence("u-1", "t-a"))
        _assert_envelope(result, "social_intelligence")
        assert result["summary"]["platforms"] == []

    def test_platforms_in_summary(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"platform": "twitter", "handle": "@alice", "followers": 1000}),
            _gold_row("u-1", "t-a", dimensions={"platform": "farcaster", "handle": "alice.eth", "followers": 500}),
        ]
        intel = _make_intel(social_intelligence=_GoldRepo(rows))
        result = _run(intel.social_intelligence("u-1", "t-a"))
        assert set(result["summary"]["platforms"]) == {"twitter", "farcaster"}
        assert result["summary"]["platform_count"] == 2


class TestJourneyEconomics:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.journey_economics("u-1", "t-a"))
        _assert_envelope(result, "journey_economics")
        assert result["summary"]["avg_roas"] is None

    def test_avg_roas_computed(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"journey_id": "j-1", "roas": 2.0, "cpa": 1.0}),
            _gold_row("u-1", "t-a", dimensions={"journey_id": "j-2", "roas": 4.0, "cpa": 0.5}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.journey_economics("u-1", "t-a"))
        assert result["summary"]["avg_roas"] == 3.0

    def test_limit_applied(self):
        rows = [_gold_row("u-1", "t-a", dimensions={"journey_id": f"j-{i}", "roas": 1.0}) for i in range(30)]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.journey_economics("u-1", "t-a", limit=5))
        assert len(result["items"]) == 5


class TestDevicePerformance:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.device_performance("u-1", "t-a"))
        _assert_envelope(result, "device_performance")

    def test_conversion_rate_computed(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"device_type": "mobile", "converted": True, "conversion_value": "50.0"}),
            _gold_row("u-1", "t-a", dimensions={"device_type": "mobile", "converted": False}),
            _gold_row("u-1", "t-a", dimensions={"device_type": "desktop", "converted": True, "conversion_value": "200.0"}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.device_performance("u-1", "t-a"))
        by_device = {i["device_type"]: i for i in result["items"]}
        assert by_device["mobile"]["conversion_rate"] == 0.5
        assert by_device["desktop"]["conversion_rate"] == 1.0
        assert by_device["desktop"]["avg_conversion_value"] == 200.0


class TestFunnel:
    def test_empty_returns_all_stages(self):
        intel = _make_intel()
        result = _run(intel.funnel("u-1", "t-a"))
        _assert_envelope(result, "funnel")
        stages = [i["stage"] for i in result["items"]]
        assert stages == ["Impression", "Click", "Visit", "Connect", "Swap", "Liquidity"]
        assert all(i["count"] == 0 for i in result["items"])

    def test_stage_counts_aggregated(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"funnel_stage": "Impression"}),
            _gold_row("u-1", "t-a", dimensions={"funnel_stage": "Impression"}),
            _gold_row("u-1", "t-a", dimensions={"funnel_stage": "Click"}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.funnel("u-1", "t-a"))
        by_stage = {i["stage"]: i for i in result["items"]}
        assert by_stage["Impression"]["count"] == 2
        assert by_stage["Click"]["count"] == 1

    def test_campaign_id_filters(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"funnel_stage": "Click", "campaign_id": "camp-1"}),
            _gold_row("u-1", "t-a", dimensions={"funnel_stage": "Click", "campaign_id": "camp-2"}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.funnel("u-1", "t-a", campaign_id="camp-1"))
        by_stage = {i["stage"]: i for i in result["items"]}
        assert by_stage["Click"]["count"] == 1


class TestTimeToConvert:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.time_to_convert("u-1", "t-a"))
        _assert_envelope(result, "time_to_convert")
        assert result["items"] == []

    def test_median_computed(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"from_stage": "Click", "to_stage": "Visit", "time_seconds": 100}),
            _gold_row("u-1", "t-a", dimensions={"from_stage": "Click", "to_stage": "Visit", "time_seconds": 200}),
            _gold_row("u-1", "t-a", dimensions={"from_stage": "Click", "to_stage": "Visit", "time_seconds": 300}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.time_to_convert("u-1", "t-a"))
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["from_stage"] == "Click"
        assert item["to_stage"] == "Visit"
        assert item["median_seconds"] == 200
        assert item["sample_size"] == 3


class TestRetargetRecommendations:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.retarget_recommendations("u-1", "t-a"))
        _assert_envelope(result, "retarget_recommendations")
        assert "pagination" in result

    def test_sorted_by_score(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"retarget_score": 0.3, "retarget_status": "pending"}),
            _gold_row("u-1", "t-a", dimensions={"retarget_score": 0.9, "retarget_status": "pending"}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.retarget_recommendations("u-1", "t-a"))
        assert result["items"][0]["score"] == 0.9

    def test_status_filter(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"retarget_score": 0.8, "retarget_status": "pending"}),
            _gold_row("u-1", "t-a", dimensions={"retarget_score": 0.7, "retarget_status": "actioned"}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.retarget_recommendations("u-1", "t-a", status="pending"))
        assert len(result["items"]) == 1
        assert result["items"][0]["status"] == "pending"

    def test_rows_without_retarget_score_excluded(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"retarget_score": 0.5, "retarget_status": "pending"}),
            _gold_row("u-1", "t-a", dimensions={}),
        ]
        intel = _make_intel(journey_economics=_GoldRepo(rows))
        result = _run(intel.retarget_recommendations("u-1", "t-a"))
        assert len(result["items"]) == 1


class TestWeb2:
    def test_no_consent_returns_empty(self):
        intel = _make_intel(consent=_ConsentRepo(granted=False))
        result = _run(intel.web2("u-1", "t-a"))
        _assert_envelope(result, "web2")
        assert result["items"] == []
        assert result["summary"]["consent_required"] is True
        assert result["summary"]["granted"] is False

    def test_consent_without_credit_purpose_blocks(self):
        intel = _make_intel(consent=_ConsentRepo(granted=True, purposes=["analytics"]))
        result = _run(intel.web2("u-1", "t-a"))
        assert result["items"] == []
        assert result["summary"]["consent_required"] is True

    def test_credit_consent_returns_data(self):
        tradfi_row = _gold_row("u-1", "t-a", dimensions={"account_type": "checking", "balance_usd": 5000, "institution": "Chase"})
        intel = _make_intel(
            consent=_ConsentRepo(granted=True, purposes=["credit"]),
            tradfi_portfolio=_GoldRepo([tradfi_row]),
        )
        result = _run(intel.web2("u-1", "t-a"))
        assert result["summary"]["consent_granted"] is True
        assert result["summary"]["tradfi_accounts"] == 1
        assert result["items"][0]["account_type"] == "checking"

    def test_cross_tenant_tradfi_excluded(self):
        tradfi_row = _gold_row("u-1", "t-other", dimensions={"account_type": "savings", "balance_usd": 9000})
        intel = _make_intel(
            consent=_ConsentRepo(granted=True, purposes=["credit"]),
            tradfi_portfolio=_GoldRepo([tradfi_row]),
        )
        result = _run(intel.web2("u-1", "t-a"))
        assert result["items"] == []


class TestProtocolMetrics:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.protocol_metrics("u-1", "t-a"))
        _assert_envelope(result, "protocol_metrics")
        assert result["summary"]["avg_tvl_usd"] is None

    def test_sorted_newest_first(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"date": "2026-01-01", "tvl_usd": 1000000}),
            _gold_row("u-1", "t-a", dimensions={"date": "2026-02-01", "tvl_usd": 2000000}),
        ]
        intel = _make_intel(web3_daily_metrics=_GoldRepo(rows))
        result = _run(intel.protocol_metrics("u-1", "t-a"))
        assert result["items"][0]["date"] == "2026-02-01"

    def test_avg_tvl_computed(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"date": "2026-01-01", "tvl_usd": 1000}),
            _gold_row("u-1", "t-a", dimensions={"date": "2026-01-02", "tvl_usd": 3000}),
        ]
        intel = _make_intel(web3_daily_metrics=_GoldRepo(rows))
        result = _run(intel.protocol_metrics("u-1", "t-a"))
        assert result["summary"]["avg_tvl_usd"] == 2000.0


class TestGovernanceActivity:
    def test_empty_returns_envelope(self):
        intel = _make_intel()
        result = _run(intel.governance_activity("u-1", "t-a"))
        _assert_envelope(result, "governance_activity")
        assert "pagination" in result

    def test_vote_counts_in_summary(self):
        rows = [
            _gold_row("u-1", "t-a", dimensions={"proposal_id": "p-1", "vote": "for", "protocol": "uniswap"}),
            _gold_row("u-1", "t-a", dimensions={"proposal_id": "p-2", "vote": "against", "protocol": "uniswap"}),
            _gold_row("u-1", "t-a", dimensions={"proposal_id": "p-3", "vote": "for", "protocol": "aave"}),
        ]
        intel = _make_intel(governance=_GoldRepo(rows))
        result = _run(intel.governance_activity("u-1", "t-a"))
        assert result["summary"]["proposal_count"] == 3
        assert result["summary"]["votes_for"] == 2
        assert result["summary"]["votes_against"] == 1

    def test_limit_applied(self):
        rows = [_gold_row("u-1", "t-a", dimensions={"proposal_id": f"p-{i}", "vote": "for"}) for i in range(30)]
        intel = _make_intel(governance=_GoldRepo(rows))
        result = _run(intel.governance_activity("u-1", "t-a", limit=5))
        assert len(result["items"]) == 5

    def test_cross_tenant_excluded(self):
        row = _gold_row("u-1", "t-other", dimensions={"proposal_id": "p-99", "vote": "for"})
        intel = _make_intel(governance=_GoldRepo([row]))
        result = _run(intel.governance_activity("u-1", "t-a"))
        assert result["items"] == []

    def test_broken_repo_degrades(self):
        intel = _make_intel(governance=_BrokenRepo())
        result = _run(intel.governance_activity("u-1", "t-a"))
        _assert_envelope(result, "governance_activity")
        assert result["items"] == []


class TestCampaignsViaAggregator:
    """Verify campaigns method was added to Profile360Aggregator correctly."""

    def test_campaigns_method_exists(self):
        from services.profile.aggregator import Profile360Aggregator
        assert hasattr(Profile360Aggregator, "campaigns"), "campaigns method missing from Profile360Aggregator"

    def test_campaigns_returns_envelope(self):
        from services.profile.aggregator import Profile360Aggregator

        class _Analytics:
            async def query_events(self, tenant_id, filters, limit=50):
                return [
                    {"user_id": "u-1", "campaign_id": "camp-A", "created_at": "2026-01-01T00:00:00Z", "tenant_id": "t-a"},
                    {"user_id": "u-1", "campaign_id": "camp-A", "created_at": "2026-01-02T00:00:00Z", "tenant_id": "t-a"},
                    {"user_id": "u-1", "campaign_id": "camp-B", "created_at": "2026-01-03T00:00:00Z", "tenant_id": "t-a"},
                ]

        agg = Profile360Aggregator(analytics_repo=_Analytics())
        result = _run(agg.campaigns("u-1", "t-a"))
        assert result["kind"] == "campaigns"
        assert "items" in result
        by_id = {i["id"]: i for i in result["items"]}
        assert "camp-A" in by_id
        assert by_id["camp-A"]["interactionCount"] == 2
