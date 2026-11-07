"""Risk360 fan-out: scale is context; acceptance scenarios A, B and C."""
from __future__ import annotations

import pytest

from actions.agent_lineage import synthetic as S
from actions.agent_lineage._common import UNATTRIBUTED
from actions.agent_lineage.engine import LineageEngine
from intelligence.risk360.fanout import (
    assess_principal, fanout_signals, signals_from_assessment, temporal_profile,
)
from shared.agent_lineage import vocabulary as V


@pytest.fixture(scope="module", params=[1000, 10000])
def resolved(request):
    fixture = S.build_fixture(request.param)
    engine = LineageEngine(S.TENANT)
    S.load(engine, fixture)
    result = engine.resolve()
    return {s["principal_entity_id"]: s for s in result.summaries}, result.clusters


def _assess(resolved, principal):
    summaries, clusters = resolved
    return assess_principal(summaries[principal], clusters=clusters.get(principal, []))


def test_scenario_a_a_large_fast_deep_fleet_is_not_classified_as_fraud(resolved):
    assessment = _assess(resolved, S.LEGIT_HUMAN)
    assert assessment["assessment_level"] == "no_behavioral_indicators"
    assert assessment["triggered_signals"] == []
    assert assessment["segments"]["elevated_risk"] == 0
    # The scale is still visible, as context.
    assert assessment["signals"]["agent_spawn_velocity"] > 0
    assert assessment["signals"]["delegation_depth"] >= 3
    assert signals_from_assessment(resolved[0][S.LEGIT_HUMAN], assessment) == []


def test_scenario_b_a_malicious_swarm_is_elevated_on_behaviour_with_links_separated(resolved):
    summary = resolved[0][S.MALICIOUS_HUMAN]
    assessment = _assess(resolved, S.MALICIOUS_HUMAN)
    assert assessment["assessment_level"] == "elevated"
    assert "out_of_scope_execution_rate" in assessment["triggered_signals"]
    attribution = assessment["attribution"]
    assert attribution["verified_links"] > 0 and attribution["inferred_links"] > 0
    assert assessment["verified_external_effects"] > 0
    # Nothing is confirmed until an adjudication says so.
    assert assessment["segments"]["confirmed_abusive"] is None
    assert assessment["attribution_kinds"]["confirmed_malicious"] is None
    signals = signals_from_assessment(summary, assessment)
    assert signals and all(s.subject_id == S.MALICIOUS_HUMAN and s.score is None for s in signals)


def test_confirmed_activity_only_comes_from_an_explicit_adjudication(resolved):
    summaries, clusters = resolved
    assessment = assess_principal(
        summaries[S.MALICIOUS_HUMAN], clusters=clusters[S.MALICIOUS_HUMAN], confirmed_malicious_agents=200,
    )
    assert assessment["assessment_level"] == "confirmed_activity"
    assert assessment["segments"]["confirmed_abusive"] == 200


def test_scenario_c_shared_infrastructure_reports_a_suspected_cluster_only(resolved):
    summaries, clusters = resolved
    unattributed = summaries[UNATTRIBUTED]
    assert unattributed["verified_links"] == 0 and unattributed["inferred_links"] == 0
    assessment = assess_principal(unattributed, clusters=clusters[UNATTRIBUTED])
    assert assessment["attribution"]["verified_links"] == 0
    shared = [c for c in clusters[UNATTRIBUTED] if c["bases"][0]["basis"] == "shared_infrastructure"]
    assert shared
    for cluster in shared:
        assert cluster["attribution_class"] == "suspected_cluster"
        assert cluster["implies_common_control"] is False


def test_unknown_signals_stay_unknown_and_vocabulary_is_complete():
    summary = {"tenant_id": "t", "principal_entity_id": "p", "disclosure": {}}
    signals = fanout_signals(summary)
    assert tuple(signals) == V.FANOUT_RISK_SIGNALS
    assert all(value is None for value in signals.values())
    assessment = assess_principal(summary)
    assert assessment["assessment_level"] == "unknown"
    assert assessment["segments"]["attributable_agents"] is None


def test_size_alone_with_no_behavioural_evidence_cannot_trigger():
    summary = {
        "tenant_id": "t", "principal_entity_id": "p", "disclosure": {},
        "max_delegation_depth": 30,
        "activity": {
            "out_of_scope_agents": 0, "revoked_agents": 0,
            "agent_count": 100_000, "event_count": 10_000_000, "denied_event_count": 0,
            "wallet_count": 50_000, "tool_count": 900, "provider_count": 90, "transaction_count": 5_000_000,
            "max_direct_fanout": 50_000, "revoked_agent_activity": 0,
            "spawn_timeline": [[0, 100], [60, 100], [120, 20_000]], "bucket_seconds": 60.0,
        },
    }
    assessment = assess_principal(summary)
    assert assessment["triggered_signals"] == []
    assert assessment["assessment_level"] == "no_behavioral_indicators"
    assert assessment["temporal"]["acceleration"] == 200.0


def test_temporal_profile_compares_a_principal_to_its_own_history():
    profile = temporal_profile({"spawn_timeline": [[0, 10], [60, 10], [120, 10], [180, 500]], "bucket_seconds": 60.0})
    assert profile["baseline_agent_count"] == 10
    assert profile["current_agent_count"] == 500
    assert profile["historical_percentile"] == 1.0


def test_propagation_kinds_are_recorded_separately(resolved):
    kinds = {p["kind"] for p in _assess(resolved, S.MALICIOUS_HUMAN)["propagation"]}
    assert kinds == set(V.RISK_PROPAGATION_KINDS)


def test_the_producer_adapter_is_scoped_to_the_principal_and_stays_silent_on_clean_fleets(resolved):
    from intelligence.risk360.signals import KNOWN_PRODUCERS, adapt_producer_signal

    assert "agent_lineage_fanout" in KNOWN_PRODUCERS
    summaries, clusters = resolved

    def adapt(principal, kind="entity", subject=None):
        return adapt_producer_signal(
            "agent_lineage_fanout", {"summary": summaries[principal], "clusters": clusters[principal]},
            subject_kind=kind, subject_id=subject or principal, tenant_id=S.TENANT,
        )

    assert adapt(S.LEGIT_HUMAN) == []
    assert adapt(S.MALICIOUS_HUMAN)
    with pytest.raises(ValueError):
        adapt(S.MALICIOUS_HUMAN, kind="agent")
    with pytest.raises(ValueError):
        adapt(S.MALICIOUS_HUMAN, subject="human:someone-else")
