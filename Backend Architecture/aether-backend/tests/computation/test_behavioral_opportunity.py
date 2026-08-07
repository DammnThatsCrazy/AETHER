"""Opportunity / observation-coverage, event-time windowing, heuristic labelling,
and honest peer-baseline behavior for the behavioral + expectations engines.

Companion to ``test_behavioral_staleness.py`` (which pins the dynamic-freshness
``_is_source_stale`` fix). This file pins the follow-on debt fixes:

1. ``detect_missing_actions`` windows by EVENT-TIME (``window_days`` vs parsed
   timestamps), never by list position (``events[:20]``).
2. Probability-labelled heuristics carry an explicit ``*_kind: "heuristic"`` /
   ``calibrated: False`` marker in the emitted signal.
3. An absence is only read as "no behavior" when there was an OPPORTUNITY to
   observe it (source available + observation spans window + min sample);
   otherwise it is "no opportunity / no observation".
4. ``build_peer_baseline`` reports ``status="unavailable"`` instead of fabricated
   constants, and derives real numbers only from supplied peer data.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from shared.common.common import utc_now
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from repositories.repos import AnalyticsRepository, reset_in_memory_stores
from repositories.lake import silver_identity

from services.expectations.engine import ExpectationEngine, MIN_OBSERVATION_SAMPLE
from services.expectations.baseline_builder import BaselineBuilder, MIN_PEER_COHORT
from services.behavioral.engines import (
    compute_intent_residue,
    compute_reward_near_miss,
    compute_source_shadow,
)


@pytest.fixture(autouse=True)
def _clean_stores():
    """Isolate the shared in-memory backing stores per test."""
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _iso(days_ago: float) -> str:
    return (utc_now() - timedelta(days=days_ago)).isoformat()


def _engine():
    cache = CacheClient()
    analytics = AnalyticsRepository(cache)
    engine = ExpectationEngine(graph=GraphClient(), cache=cache, analytics=analytics)
    return engine, analytics


async def _seed_events(analytics: AnalyticsRepository, tenant: str, user_id: str, events: list[dict]) -> None:
    """Insert events, overriding ``created_at`` (insert() stamps it to now) so
    tests can control real event-time."""
    for i, ev in enumerate(events):
        data = {
            "user_id": user_id,
            "tenant_id": tenant,
            "event_type": ev.get("event_type", ""),
            "properties": ev.get("properties", {}),
        }
        rec = await analytics.record_event(f"{user_id}-{i}", data)
        if "created_at" in ev:
            # rec is the stored dict object (in-memory backend) — mutate in place.
            rec["created_at"] = ev["created_at"]


# ─────────────────────────────────────────────────────────────────────────────
# Observation-coverage / opportunity gate
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_eligible_when_sample_window_and_history_present():
    events = [{"created_at": _iso(d)} for d in (0.5, 1, 2, 20, 30)]
    cov = ExpectationEngine._observation_coverage(events, window_days=7)
    assert cov["eligible"] is True
    assert cov["reason"] == "eligible"
    assert cov["observed_in_window"] is True
    assert cov["history_before_window"] is True


def test_coverage_insufficient_sample():
    events = [{"created_at": _iso(1)} for _ in range(MIN_OBSERVATION_SAMPLE - 1)]
    cov = ExpectationEngine._observation_coverage(events, window_days=7)
    assert cov["eligible"] is False
    assert cov["reason"] == "insufficient_sample"


def test_coverage_no_observation_in_window_is_source_silence():
    # Everything is older than the window -> the window itself was never observed.
    events = [{"created_at": _iso(d)} for d in (60, 62, 64, 66, 68)]
    cov = ExpectationEngine._observation_coverage(events, window_days=7)
    assert cov["eligible"] is False
    assert cov["reason"] == "no_observation_in_window"
    assert cov["observed_in_window"] is False


def test_coverage_no_baseline_before_window():
    # All activity sits inside the window -> no pre-window baseline to compare to.
    events = [{"created_at": _iso(d)} for d in (1, 2, 3, 4, 5)]
    cov = ExpectationEngine._observation_coverage(events, window_days=7)
    assert cov["eligible"] is False
    assert cov["reason"] == "no_baseline_before_window"
    assert cov["history_before_window"] is False


def test_coverage_unparseable_times():
    events = [{"created_at": "not-a-timestamp"} for _ in range(6)]
    cov = ExpectationEngine._observation_coverage(events, window_days=7)
    assert cov["eligible"] is False
    assert cov["reason"] == "no_parseable_observation_times"


# ─────────────────────────────────────────────────────────────────────────────
# detect_missing_actions: event-time window (not list position) + opportunity gate
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_action_uses_event_time_window_not_list_position():
    engine, analytics = _engine()
    tenant, user = "t-win", "u-win"
    # 10 events total (< 20), so a positional events[:20] slice would include the
    # OLD 'swap' events and wrongly conclude it is "still happening". The
    # event-time window (7d) must instead flag 'swap' as missing.
    events = (
        [{"event_type": "page", "created_at": _iso(d)} for d in (1, 2, 3, 20, 25)]
        + [{"event_type": "swap", "created_at": _iso(d)} for d in (20, 22, 24, 26, 28)]
    )
    await _seed_events(analytics, tenant, user, events)

    signals = await engine.detect_missing_actions(user, tenant, window_days=7)

    # Exactly one missing-action signal: 'swap' (no in-window occurrence).
    assert len(signals) == 1
    sig = signals[0]
    assert "swap" in str(sig["expected"])
    assert "page" not in str(sig["expected"])  # page recurred in-window
    cov = sig["metadata"]["observation_coverage"]
    assert cov["eligible"] is True
    assert cov["reason"] == "eligible"


@pytest.mark.asyncio
async def test_missing_action_suppressed_when_no_observation_in_window():
    engine, analytics = _engine()
    tenant, user = "t-stale", "u-stale"
    # All activity predates the window -> no opportunity/observation, not "no
    # behavior". No missing-action signal must be fabricated.
    events = [{"event_type": "swap", "created_at": _iso(d)} for d in (60, 62, 64, 66, 68, 70)]
    await _seed_events(analytics, tenant, user, events)

    signals = await engine.detect_missing_actions(user, tenant, window_days=7)
    assert signals == []


@pytest.mark.asyncio
async def test_missing_action_suppressed_on_insufficient_sample():
    engine, analytics = _engine()
    tenant, user = "t-thin", "u-thin"
    events = [{"event_type": "swap", "created_at": _iso(d)} for d in (1, 20)]  # < MIN_OBSERVATION_SAMPLE
    await _seed_events(analytics, tenant, user, events)

    signals = await engine.detect_missing_actions(user, tenant, window_days=7)
    assert signals == []


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic (uncalibrated) relabelling of probability-named outputs
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intent_residue_probability_marked_heuristic():
    cache = CacheClient()
    analytics = AnalyticsRepository(cache)
    tenant, user = "t-ir", "u-ir"
    await _seed_events(
        analytics, tenant, user,
        [{"event_type": "page", "properties": {"url": "/checkout"}} for _ in range(5)],
    )
    sig = await compute_intent_residue(user, analytics, tenant)
    assert sig is not None
    out = sig["outputs"]
    assert out["return_to_intent_probability_kind"] == "heuristic"
    assert out["calibrated"] is False
    # Numeric transform is unchanged (min(0.9, residue*0.8) with residue==1.0).
    assert out["return_to_intent_probability"] == 0.8


@pytest.mark.asyncio
async def test_reward_near_miss_probability_marked_heuristic():
    cache = CacheClient()
    analytics = AnalyticsRepository(cache)
    tenant, user = "t-rnm", "u-rnm"
    await _seed_events(
        analytics, tenant, user,
        [{"event_type": "track", "properties": {"action": "claim reward"}} for _ in range(5)],
    )
    sig = await compute_reward_near_miss(user, analytics, tenant)
    assert sig is not None
    out = sig["outputs"]
    assert out["recovery_probability_kind"] == "heuristic"
    assert out["calibrated"] is False


@pytest.mark.asyncio
async def test_source_shadow_absence_confidence_marked_heuristic():
    tenant, user = "", "u-shadow"
    await silver_identity.upsert_record(
        entity_id=user,
        entity_type="wallet",
        source="etherscan",
        source_tag="test",
        normalized={"chain": "eth"},
        tenant_id=tenant,
    )
    # Backdate the record past the freshness SLA (insert() stamps updated_at=now).
    for rec in await silver_identity.get_entity(user, "wallet"):
        rec["updated_at"] = _iso(120)

    sig = await compute_source_shadow(user, tenant)
    assert sig is not None
    out = sig["outputs"]
    assert out["behavior_absence_confidence_kind"] == "heuristic"
    assert out["calibrated"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Peer baseline: honest "unavailable" vs derived-from-data
# ─────────────────────────────────────────────────────────────────────────────

def test_peer_baseline_unavailable_when_no_data():
    base = BaselineBuilder.build_peer_baseline(tenant_id="acme", tier="pro")
    assert base.status == "unavailable"
    assert base.cohort_size == 0
    assert base.avg_rpm == 0.0
    assert base.quality == 0.0
    # No fabricated constants leak through the serialized form either.
    d = base.to_dict()
    assert d["status"] == "unavailable"
    assert d["cohort_size"] == 0
    assert d["avg_rpm"] == 0.0


def test_peer_baseline_derived_from_supplied_history():
    peers = [
        {"usual_rpm": 10.0, "usual_models": ["a", "b"], "usual_batch_size": 2.0}
        for _ in range(MIN_PEER_COHORT + 1)
    ]
    base = BaselineBuilder.build_peer_baseline(tenant_id="acme", tier="pro", peer_history=peers)
    assert base.status == "ok"
    assert base.cohort_size == MIN_PEER_COHORT + 1
    assert base.avg_rpm == 10.0
    assert base.avg_models_per_day == 2.0
    assert base.quality > 0.0


def test_peer_baseline_insufficient_when_below_min_cohort():
    peers = [{"usual_rpm": 5.0} for _ in range(MIN_PEER_COHORT - 1)]
    base = BaselineBuilder.build_peer_baseline(peer_history=peers)
    assert base.status == "insufficient"
    assert base.cohort_size == MIN_PEER_COHORT - 1
