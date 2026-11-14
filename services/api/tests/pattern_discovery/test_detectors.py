"""Unknown-pattern detectors and the engine on the fraud-ring scenario."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from intelligence.pattern_discovery.baselines import empty_baseline
from intelligence.pattern_discovery.contracts import (
    CONFIDENCE_CAPS, KIND_CROSS_DOMAIN, KIND_LOCKSTEP, KIND_NOVEL_MOTIF, KIND_OUTLIER,
    KIND_SCHEMA_DRIFT, KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, KIND_TEMPORAL_BURST, STATUS_NEEDS_REVIEW,
)
from intelligence.pattern_discovery.detectors.frame import poisson_sf, robust_stats
from intelligence.pattern_discovery.engine import run_discovery

from .scenarios import T, ev, fraud_ring, normal_traffic, ring_keys


def _baselined():
    first = run_discovery(T, normal_traffic(1, 1), baseline=empty_baseline(T))
    return first, first.apply_to_baseline(empty_baseline(T))


def test_normal_traffic_alone_produces_no_patterns():
    first, baseline = _baselined()
    assert first.records == []
    second = run_discovery(T, normal_traffic(2, 2), baseline=baseline)
    assert [r for r in second.records if r["status"] == STATUS_NEEDS_REVIEW] == []


def test_fraud_ring_is_found_independently_by_several_detectors():
    _, baseline = _baselined()
    result = run_discovery(T, normal_traffic(2, 2) + fraud_ring(2), baseline=baseline)
    by_kind = {}
    for r in result.records:
        by_kind.setdefault(r["kind"], []).append(r)
    ring = ring_keys()
    for kind in (KIND_SHARED_ATTRIBUTE, KIND_SEQUENCE, KIND_LOCKSTEP, KIND_TEMPORAL_BURST, KIND_OUTLIER):
        assert kind in by_kind, kind
        assert any(set(r["affected_entity_keys"]) <= ring | {f"user:u{i}" for i in range(200)}
                   and len(set(r["affected_entity_keys"]) & ring) >= 12 for r in by_kind[kind]), kind
    seq = by_kind[KIND_SEQUENCE][0]
    assert seq["signature"]["tokens"] == ["login", "add_card!fail+", "add_card!ok", "withdraw"]
    cluster = by_kind[KIND_SHARED_ATTRIBUTE][0]
    types = {a.split("=", 1)[0] for a in cluster["signature"]["shared_attributes"]}
    assert {"device", "payment_instrument"} <= types or "field:partner_ref" in types
    assert any(c["id"] == "no_identity_merge" for c in cluster["competing_explanations"])


def test_cross_domain_composite_tells_the_whole_story():
    _, baseline = _baselined()
    result = run_discovery(T, normal_traffic(2, 2) + fraud_ring(2), baseline=baseline)
    composite = [r for r in result.records if r["kind"] == KIND_CROSS_DOMAIN]
    assert len(composite) == 1
    c = composite[0]
    assert set(c["affected_entity_keys"]) == ring_keys()
    kinds = c["evidence"][0]["detail"]["kinds"]
    assert len(kinds) >= 4 and KIND_SEQUENCE in kinds and KIND_SHARED_ATTRIBUTE in kinds
    assert len(c["member_pattern_ids"]) >= 4
    assert c["status"] == STATUS_NEEDS_REVIEW


def test_confidence_never_exceeds_the_kind_cap_and_everything_is_inferred():
    _, baseline = _baselined()
    result = run_discovery(T, normal_traffic(2, 2) + fraud_ring(2), baseline=baseline)
    for r in result.records:
        assert r["confidence"] <= CONFIDENCE_CAPS[r["kind"]]
        assert r["claim_state"] == "inferred"
        assert r["competing_explanations"]
        assert r["status"] in ("candidate", "needs_review")


def test_first_run_novelty_is_capped_because_new_means_nothing_without_history():
    result = run_discovery(T, normal_traffic(2, 2) + fraud_ring(2), baseline=empty_baseline(T))
    assert result.records and all(r["novelty"] <= 0.5 for r in result.records)


def test_recurring_pattern_stops_being_novel():
    _, baseline = _baselined()
    rows = normal_traffic(2, 2) + fraud_ring(2)
    for _ in range(4):
        result = run_discovery(T, rows, baseline=baseline)
        baseline = result.apply_to_baseline(baseline)
    seq = next(r for r in result.records if r["kind"] == KIND_SEQUENCE)
    assert seq["novelty"] < 0.3
    assert seq["status"] == "candidate"


def test_schema_drift_reports_new_groups_and_identifier_fields():
    _, baseline = _baselined()
    rows = normal_traffic(2, 2)
    for r in rows:
        if r["event_type"] == "login":
            r["properties"]["session_token_ref"] = "x"  # constant: not an identifier
    result = run_discovery(T, rows + fraud_ring(2), baseline=baseline, kinds=[KIND_SCHEMA_DRIFT])
    groups = {r["signature"]["group"]: r for r in result.records}
    assert "sdk|add_card" in groups
    assert any(c["change"] == "new_event_group" for c in groups["sdk|add_card"]["evidence"][0]["detail"]["changes"])
    login = groups.get("sdk|login")
    assert login and any(c.get("path") == "session_token_ref" for c in login["evidence"][0]["detail"]["changes"])
    assert all(r["kind"] == KIND_SCHEMA_DRIFT for r in result.records)


def test_unregistered_cycles_are_discovered_and_registered_shapes_are_not():
    base = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
    rows = []
    i = 0
    for ring in range(3):
        members = [f"m{ring}_{k}" for k in range(3)]
        for k, m in enumerate(members):
            i += 1
            rows.append(ev(i, "user_id", m, "invite_accepted", base + timedelta(minutes=i),
                           invited_by=members[(k + 1) % 3]))
    result = run_discovery(T, rows, baseline=empty_baseline(T), kinds=[KIND_NOVEL_MOTIF])
    assert len(result.records) == 1
    motif = result.records[0]
    assert motif["signature"]["shape"] == "cycle"
    assert motif["affected_entity_count"] == 9
    assert "relationship" in motif["risk_categories"]


def test_lockstep_requires_repeated_or_large_coordination():
    base = datetime(2026, 11, 6, 9, tzinfo=timezone.utc)
    rows = [ev(i, "user_id", f"x{i}", "claim_reward", base + timedelta(seconds=i)) for i in range(6)]
    rows += [ev(100 + i, "user_id", f"y{i}", "browse", base + timedelta(hours=i)) for i in range(30)]
    result = run_discovery(T, rows, baseline=empty_baseline(T), kinds=[KIND_LOCKSTEP])
    assert result.records == []  # one window, 6 entities: below the single-window bar
    rows += [ev(200 + i, "user_id", f"x{i}", "claim_reward", base + timedelta(hours=2, seconds=i)) for i in range(6)]
    result = run_discovery(T, rows, baseline=empty_baseline(T), kinds=[KIND_LOCKSTEP])
    assert len(result.records) == 1 and result.records[0]["signature"]["repeated"] is True


def test_a_detector_failure_is_isolated(monkeypatch):
    from intelligence.pattern_discovery import detectors

    def boom(frame):
        raise RuntimeError("detector exploded")

    monkeypatch.setitem(detectors.DETECTORS, "sequences", (boom, detectors.DETECTORS["sequences"][1]))
    from intelligence.pattern_discovery import engine

    monkeypatch.setattr(engine, "DETECTORS", detectors.DETECTORS)
    _, baseline = _baselined()
    result = run_discovery(T, normal_traffic(2, 2) + fraud_ring(2), baseline=baseline)
    assert result.stats["detectors"]["sequences"] == {"error": "RuntimeError"}
    assert any(r["kind"] == KIND_SHARED_ATTRIBUTE for r in result.records)


def test_unknown_kind_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        run_discovery(T, [], baseline=empty_baseline(T), kinds=["astrology"])


def test_statistics_helpers():
    assert poisson_sf(0, 3.0) == 1.0
    assert poisson_sf(20, 2.0) < 1e-10
    assert abs(poisson_sf(1, 1.0) - (1 - 0.36787944)) < 1e-6
    med, sigma = robust_stats([1, 1, 1, 1, 50])
    assert med == 1 and sigma > 0
