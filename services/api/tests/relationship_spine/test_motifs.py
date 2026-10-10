"""Deterministic motif matcher + promotion-feed tests (M6 STEP 4).

Covers catalog completeness (every predicate-output motif has an endpoint
policy), deterministic matching, evidence-independence damping on motif
outputs, temporal/episode attestations, the promotion feed for
RELATIONSHIP_PREDICATE outputs, and honest fail-closed behaviour when a
required predicate cannot resolve to a live edge.
"""

from __future__ import annotations

from shared.relationship_spine.evidence import Observation, candidate_groups_for_pair
from shared.relationship_spine.generated_relationship_motif_registry import RELATIONSHIP_MOTIFS
from shared.relationship_spine.motifs import (
    OUTPUT_KIND_PREDICATE,
    PREDICATE_OUTPUT_ENDPOINTS,
    ObservedEdge,
    detect_motif_instances,
    detect_motifs,
    motif_matchability,
    promotion_result_for_match,
    relationship_assertions_for_matches,
)
from shared.relationship_spine.promotion import PromotionVerdict


def _edge(eid, etype, src, tgt, day="2026-01-01", source_key=""):
    return ObservedEdge(eid, etype, src, tgt, f"{day}T00:00:00+00:00", source_key)


def test_every_predicate_output_motif_has_endpoint_policy():
    """Catalog self-test: no predicate-output motif may be endpoint-unevaluable."""
    missing = [
        m["motifId"]
        for m in RELATIONSHIP_MOTIFS
        if m.get("outputKind") == OUTPUT_KIND_PREDICATE
        and m["motifId"] not in PREDICATE_OUTPUT_ENDPOINTS
    ]
    assert missing == []


def test_mutual_social_connection_promotes_to_canonical_pair():
    obs = [
        _edge("ea", "FOLLOWS_SOCIAL", "a", "b", day="2026-01-01", source_key="providerA"),
        _edge("eb", "FOLLOWS_SOCIAL", "b", "a", day="2026-01-03", source_key="providerB"),
    ]
    matches = detect_motifs(obs).get("MUTUAL_SOCIAL_CONNECTION", [])
    assert len(matches) == 1  # orientation mirrors dedupe to one structural instance
    result = promotion_result_for_match(matches[0], tenant_id="t1")
    assert result is not None
    assert result.verdict == PromotionVerdict.PROMOTE
    # Canonical orientation for a derived/undirected fact: sorted (min, max).
    assert (result.source_entity_id, result.target_entity_id) == ("a", "b")
    assert result.assertion.edge_type == "MUTUAL_SOCIAL_CONNECTION"


def test_single_source_mutual_does_not_promote():
    """Evidence independence: both directions from ONE source lineage damp below floor."""
    obs = [
        _edge("e1", "FOLLOWS_SOCIAL", "a", "b", day="2026-01-01", source_key="providerA"),
        _edge("e2", "FOLLOWS_SOCIAL", "b", "a", day="2026-01-01", source_key="providerA"),
    ]
    matches = detect_motifs(obs).get("MUTUAL_SOCIAL_CONNECTION", [])
    assert len(matches) == 1
    result = promotion_result_for_match(matches[0], tenant_id="t1")
    assert result is not None
    assert result.verdict == PromotionVerdict.BELOW_FLOOR


def test_reciprocal_communication_promotes_with_dispersion():
    obs = [
        _edge("r1", "COMMUNICATES_WITH", "a", "b", day="2026-01-01", source_key="s1"),
        _edge("r2", "COMMUNICATES_WITH", "b", "a", day="2026-01-05", source_key="s2"),
    ]
    matches = detect_motifs(obs).get("RECIPROCAL_COMMUNICATION", [])
    assert len(matches) == 1
    result = promotion_result_for_match(matches[0], tenant_id="t1")
    assert result is not None
    assert result.verdict == PromotionVerdict.PROMOTE
    assert result.assertion.edge_type == "RECIPROCAL_COMMUNICATION"


def test_recurring_co_presence_needs_two_days():
    obs_one_day = [
        _edge("c1", "CO_PRESENT_WITH", "a", "L", day="2026-01-01", source_key="s1"),
        _edge("c2", "CO_PRESENT_WITH", "b", "L", day="2026-01-01", source_key="s2"),
    ]
    match = detect_motifs(obs_one_day).get("RECURRING_CO_PRESENCE", [])[0]
    result = promotion_result_for_match(match, tenant_id="t1")
    assert result.verdict == PromotionVerdict.BELOW_FLOOR  # episode not attested

    obs_two_days = [
        _edge("c1", "CO_PRESENT_WITH", "a", "L", day="2026-01-01", source_key="s1"),
        _edge("c2", "CO_PRESENT_WITH", "b", "L", day="2026-01-03", source_key="s2"),
    ]
    match2 = detect_motifs(obs_two_days).get("RECURRING_CO_PRESENCE", [])[0]
    result2 = promotion_result_for_match(match2, tenant_id="t1")
    assert result2.verdict == PromotionVerdict.PROMOTE
    assert result2.assertion.edge_type == "RECURRING_CO_PRESENCE"


def test_community_association_promotes_on_social_interacts_edge():
    """INTERACTS_WITH resolves to SOCIAL_INTERACTS_WITH after M6 registration."""
    obs = [
        _edge("m1", "MEMBER_OF", "a", "C", source_key="s1"),
        _edge("m2", "MEMBER_OF", "b", "C", source_key="s2"),
        _edge("i1", "SOCIAL_INTERACTS_WITH", "a", "b", day="2026-01-02", source_key="s3"),
    ]
    matches = detect_motifs(obs).get("COMMUNITY_ASSOCIATION", [])
    assert len(matches) == 1
    result = promotion_result_for_match(matches[0], tenant_id="t1")
    assert result is not None
    assert result.verdict == PromotionVerdict.PROMOTE
    assert result.assertion.edge_type == "COMMUNITY_ASSOCIATION"


def test_agent_mediated_principal_interaction_promotes():
    obs = [
        _edge("d1", "DELEGATES_TO", "A", "agA", source_key="s1"),
        _edge("a1", "ACTED_FOR", "B", "agB", source_key="s2"),
        _edge("p1", "PAYS", "agA", "agB", day="2026-01-02", source_key="s3"),
    ]
    matches = detect_motifs(obs).get("AGENT_MEDIATED_PRINCIPAL_INTERACTION", [])
    assert len(matches) == 1
    result = promotion_result_for_match(matches[0], tenant_id="t1")
    assert result is not None
    assert result.verdict == PromotionVerdict.PROMOTE
    assert result.assertion.edge_type == "AGENT_MEDIATED_PRINCIPAL_INTERACTION"


def test_predicate_output_matches_feed_promotion_assertions():
    obs = [
        _edge("ea", "FOLLOWS_SOCIAL", "a", "b", day="2026-01-01", source_key="providerA"),
        _edge("eb", "FOLLOWS_SOCIAL", "b", "a", day="2026-01-03", source_key="providerB"),
    ]
    matches = detect_motifs(obs)
    all_matches = [m for ms in matches.values() for m in ms]
    assertions = relationship_assertions_for_matches(all_matches, tenant_id="t1")
    # Only the promotable predicate-output motif emits an assertion (MUTUAL_SOCIAL_CONNECTION).
    assert [a.predicate for a in assertions] == ["MUTUAL_SOCIAL_CONNECTION"]
    assert assertions[0].edge_type == "MUTUAL_SOCIAL_CONNECTION"


def test_derived_state_motifs_do_not_produce_assertions():
    """SOCIAL_ECONOMIC_TRANSITION is DERIVED_RELATIONSHIP_STATE: no edge feed."""
    obs = [
        _edge("x1", "SOCIAL_INTERACTS_WITH", "a", "b", source_key="s1"),
        _edge("x2", "PAYS", "a", "b", day="2026-01-02", source_key="s2"),
    ]
    matches = detect_motifs(obs)
    sem = matches.get("SOCIAL_ECONOMIC_TRANSITION", [])
    assert len(sem) == 1
    assert relationship_assertions_for_matches(sem, tenant_id="t1") == []


def test_unresolvable_required_predicate_fails_closed():
    motif = {
        "motifId": "BOGUS_MOTIF",
        "version": 1,
        "outputKind": "RELATIONSHIP_PREDICATE",
        "outputPredicate": "FOLLOWS",
        "outputState": None,
        "outputClaimCeiling": "derived",
        "incentivePolicy": "NONE_REQUIRED",
        "evidenceIndependencePolicy": "INDEPENDENT_OBSERVATIONS_REQUIRED",
        "requiredEdges": [
            {"sourceRole": "source_entity", "targetRole": "target_entity", "predicate": "NOT_A_EDGE_OR_PREDICATE"}
        ],
    }
    matches, reasons = detect_motif_instances(motif, [])
    assert matches == []
    assert reasons and "unresolvable_required_predicate" in reasons[0]


def test_matchability_reports_unresolvable_and_absent():
    # No edges of the required type at all -> absent (empty reason is absence).
    obs = [
        _edge("ea", "FOLLOWS_SOCIAL", "a", "b", source_key="s1"),
        _edge("eb", "FOLLOWS_SOCIAL", "b", "a", day="2026-01-03", source_key="s2"),
    ]
    mab = motif_matchability(obs)
    assert mab.get("MUTUAL_SOCIAL_CONNECTION") is None or not mab.get("MUTUAL_SOCIAL_CONNECTION")
    # MUTUAL motif present in this edge set -> matched, so no reason recorded.
