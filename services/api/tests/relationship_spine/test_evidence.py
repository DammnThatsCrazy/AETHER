"""Evidence grouping + contradiction tests (M6 STEP 2).

Verifies the correlation-damping discipline (0.4), independent-source counting,
contradiction detection and the dimension-style honest output (unknown never
zero) of ``shared/relationship_spine/evidence.py``.
"""

from __future__ import annotations

from shared.relationship_spine.evidence import (
    CORRELATION_DAMPING,
    CandidateState,
    Observation,
    candidate_groups_for_pair,
    distinct_active_days,
    effective_independent_sources,
    group_observations,
    temporal_span_days,
)


def _obs(
    oid: str,
    source: str = "a",
    target: str = "b",
    source_key: str = "src",
    family=None,
    day: str = "2026-01-01",
    supports: bool = True,
    predicate: str = "FOLLOWS",
):
    return Observation(
        observation_id=oid,
        predicate=predicate,
        source_entity_id=source,
        target_entity_id=target,
        source_key=source_key,
        observed_at=f"{day}T00:00:00+00:00",
        supports_predicate=supports,
        correlation_family=family,
    )


def test_correlation_damping_constant_is_0_4_discipline():
    assert CORRELATION_DAMPING == 0.4


def test_same_source_key_counts_once():
    obs = [
        _obs("e1", source_key="A"),
        _obs("e2", source_key="A"),   # duplicate from the same source lineage
        _obs("e3", source_key="B"),
    ]
    assert effective_independent_sources(obs) == 2.0


def test_correlated_siblings_damped():
    """3 distinct keys in one correlation family = 1 + 0.4 + 0.4 = 1.8."""
    obs = [
        _obs("e1", source_key="k1", family="campaign1"),
        _obs("e2", source_key="k2", family="campaign1"),
        _obs("e3", source_key="k3", family="campaign1"),
    ]
    assert effective_independent_sources(obs) == 1 + 2 * CORRELATION_DAMPING


def test_independent_families_sum_at_full_weight():
    obs = [
        _obs("e1", source_key="k1", family="campaign1"),
        _obs("e2", source_key="k2", family="campaign2"),
        _obs("e3", source_key="k3"),  # no family -> own bucket
    ]
    assert effective_independent_sources(obs) == 3.0


def test_grouping_buckets_by_predicate_and_pair():
    obs = [
        _obs("e1", source="a", target="b", predicate="FOLLOWS"),
        _obs("e2", source="a", target="b", predicate="INTERACTS_WITH"),
        _obs("e3", source="b", target="a", predicate="FOLLOWS"),
    ]
    groups = group_observations(obs)
    assert set(groups) == {
        ("FOLLOWS", "a", "b"),
        ("INTERACTS_WITH", "a", "b"),
        ("FOLLOWS", "b", "a"),
    }
    assert groups[("FOLLOWS", "a", "b")].raw_support_count == 1


def test_contradiction_present_when_support_and_counter_both_exist():
    obs = [
        _obs("e1", source_key="A"),
        _obs("e2", source_key="B", supports=False),  # one provider says NOT connected
    ]
    group = candidate_groups_for_pair(obs, "FOLLOWS", "a", "b")
    # Both sides are retained honestly (counter never erases support).
    assert group.raw_support_count == 1
    assert group.contradicting_count == 1
    # Supporting AND contradicting present -> CONTRADICTED (never auto-resolved).
    assert group.has_contradiction is True
    assert group.contradiction_state() == CandidateState.CONTRADICTED.value


def test_contradicted_when_both_present():
    obs = [
        _obs("e1", source_key="A"),
        _obs("e2", source_key="B"),
        _obs("e3", source_key="C", supports=False),
    ]
    group = candidate_groups_for_pair(obs, "FOLLOWS", "a", "b")
    assert group.has_contradiction is True
    assert group.contradiction_state() == CandidateState.CONTRADICTED.value


def test_missing_candidate_is_unknown_not_zero():
    """No observations for a pair -> honest unknown state, never a negative."""
    group = candidate_groups_for_pair([], "FOLLOWS", "a", "b")
    assert group.raw_support_count == 0
    assert group.contradicting_count == 0
    assert group.contradiction_state() == CandidateState.UNKNOWN.value
    assert group.evidence_state() == CandidateState.UNKNOWN.value


def test_only_contradicting_is_contested():
    group = candidate_groups_for_pair(
        [_obs("e1", source_key="A", supports=False)], "FOLLOWS", "a", "b"
    )
    assert group.contradiction_state() == CandidateState.CONTESTED.value


def test_temporal_dispersion():
    obs = [
        _obs("e1", source_key="A", day="2026-01-01"),
        _obs("e2", source_key="B", day="2026-01-01"),
        _obs("e3", source_key="C", day="2026-01-03"),
    ]
    assert distinct_active_days(obs) == 2
    assert temporal_span_days(obs) == 2


def test_temporal_span_needs_two_stamps():
    obs = [_obs("e1", source_key="A", day="2026-01-01")]
    assert temporal_span_days(obs) is None
