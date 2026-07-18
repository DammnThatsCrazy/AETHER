"""Versioned baseline resolution — 8 registry types, honest unresolved states."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from comparison_fakes import FakeAnalytics, make_events

from services.intelligence.comparison.baselines import (
    STORED_BASELINE_SUBJECT_TYPE,
    BaselineResolver,
    StoredBaselineRepository,
)
from services.intelligence.comparison.collection import AnalyticsDimensionCollector
from services.intelligence.comparison.contracts import BaselineSpec, ComparisonSubject

TENANT = "t1"
SUBJECT = ComparisonSubject(subject_type="entity", subject_id="user-a")


def resolver(fake: FakeAnalytics) -> BaselineResolver:
    return BaselineResolver(AnalyticsDimensionCollector(fake))


class TestEntityAndHistory:
    async def test_entity_baseline_collects_peer(self, fake_analytics):
        fake_analytics.seed(TENANT, "user-b", make_events(10))
        spec = BaselineSpec(
            baseline_type="entity",
            subject=ComparisonSubject(subject_type="entity", subject_id="user-b"),
        )
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert res.resolved and res.source == "analytics_events"
        assert res.observations["behavior"].observation_count == 10
        assert len(res.baseline_version) == 16

    async def test_entity_baseline_without_subject_unresolved(self, fake_analytics):
        spec = BaselineSpec(baseline_type="entity")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved
        assert "requires a baseline subject" in res.reason

    async def test_historical_prior_period_window(self, fake_analytics):
        now = datetime.now(timezone.utc)
        # 8 daily events ending 33.5d ago: the two most recent (33.5d, 34.5d)
        # fall AFTER window_end (too recent) and must be excluded; the other six
        # land inside the [now-60d, now-35d] window.
        prior = make_events(8, end=now - timedelta(days=33, hours=12), spacing_hours=24)
        fake_analytics.seed(TENANT, "user-a", prior)
        spec = BaselineSpec(
            baseline_type="historical",
            window_start=now - timedelta(days=60),
            window_end=now - timedelta(days=35),
        )
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert res.resolved
        assert res.observations["behavior"].observation_count == 6  # 2 too-recent excluded

    async def test_historical_requires_ordered_window(self, fake_analytics):
        now = datetime.now(timezone.utc)
        spec = BaselineSpec(
            baseline_type="historical", window_start=now, window_end=now
        )
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved

    async def test_rolling_history(self, fake_analytics):
        fake_analytics.seed(TENANT, "user-a", make_events(14, spacing_hours=12))
        spec = BaselineSpec(baseline_type="rolling_history", rolling_window_days=7)
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert res.resolved
        assert res.observations["behavior"].observation_count == 14

    async def test_versions_differ_when_as_of_differs(self, fake_analytics):
        spec = BaselineSpec(baseline_type="rolling_history", rolling_window_days=7)
        r = resolver(fake_analytics)
        now = datetime.now(timezone.utc)
        a = await r.resolve(TENANT, spec, SUBJECT, ["behavior"], as_of=now)
        b = await r.resolve(
            TENANT, spec, SUBJECT, ["behavior"], as_of=now - timedelta(days=1)
        )
        assert a.baseline_version != b.baseline_version


class TestStatisticalDelegation:
    async def test_cohort_delegates_to_expectations_peer_builder(self, fake_analytics):
        spec = BaselineSpec(baseline_type="cohort", cohort_definition_id="tier-pro")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert res.resolved
        assert res.source == "expectations.peer_cohort"
        assert res.statistical_quality is not None
        obs = res.observations["behavior"]
        assert obs.metric("events_per_day") is not None

    async def test_predicted_needs_history(self, fake_analytics):
        spec = BaselineSpec(baseline_type="predicted")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved
        assert "insufficient self-history" in res.reason

    async def test_predicted_projects_self_history(self, fake_analytics):
        fake_analytics.seed(TENANT, "user-a", make_events(30, spacing_hours=6))
        spec = BaselineSpec(baseline_type="predicted")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert res.resolved
        assert res.source == "expectations.self_history_projection"
        rate = res.observations["behavior"].metric("events_per_day")
        assert rate is not None and rate.value > 0


class TestStoredBaselines:
    async def test_manual_baseline_versioning_and_resolution(self, fake_analytics):
        repo = StoredBaselineRepository()
        metrics = {"behavior": [{"name": "events_per_day", "value": 4.0, "unit": "count_per_day"}]}
        v1 = await repo.put_version(TENANT, "bl-1", "manual", metrics)
        v2 = await repo.put_version(
            TENANT, "bl-1", "manual",
            {"behavior": [{"name": "events_per_day", "value": 6.0, "unit": "count_per_day"}]},
        )
        assert (v1["version"], v2["version"]) == (1, 2)

        spec = BaselineSpec(
            baseline_type="manual",
            subject=ComparisonSubject(
                subject_type=STORED_BASELINE_SUBJECT_TYPE, subject_id="bl-1"
            ),
        )
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert res.resolved
        assert res.baseline_version == "bl-1@v2"  # latest version wins
        assert res.observations["behavior"].metric("events_per_day").value == 6.0

    async def test_policy_baseline_missing_is_unresolved(self, fake_analytics):
        spec = BaselineSpec(baseline_type="policy", policy_id="pol-1")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved
        assert "no stored baseline versions" in res.reason

    async def test_kind_mismatch_is_unresolved(self, fake_analytics):
        await StoredBaselineRepository().put_version(TENANT, "pol-1", "manual", {})
        spec = BaselineSpec(baseline_type="policy", policy_id="pol-1")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved and "kind" in res.reason

    async def test_stored_baseline_is_tenant_scoped(self, fake_analytics):
        await StoredBaselineRepository().put_version("other-tenant", "bl-9", "manual", {})
        spec = BaselineSpec(
            baseline_type="manual",
            subject=ComparisonSubject(
                subject_type=STORED_BASELINE_SUBJECT_TYPE, subject_id="bl-9"
            ),
        )
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved


class TestScenarioType:
    async def test_scenario_without_params_is_unresolved(self, fake_analytics):
        spec = BaselineSpec(baseline_type="scenario", scenario_id="s1")
        res = await resolver(fake_analytics).resolve(TENANT, spec, SUBJECT, ["behavior"])
        assert not res.resolved
        assert "read-only scenario path" in res.reason

    async def test_scenario_with_inline_params_resolves(self, fake_analytics):
        spec = BaselineSpec(baseline_type="scenario", scenario_id="s1")
        res = await resolver(fake_analytics).resolve(
            TENANT, spec, SUBJECT, ["behavior"],
            scenario_params={
                "behavior": [{"name": "events_per_day", "value": 2.0, "unit": "count_per_day"}]
            },
        )
        assert res.resolved and res.source == "scenario_parameters"
