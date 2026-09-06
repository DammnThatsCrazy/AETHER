"""Unit tests for shared/relationship_spine/influence_propagation.py — Wave 4a
read-side influence-path decomposition (blueprint §70–§80 nine-way attention
decomposition).

Covers:
  1. determinism — identical inputs twice => equal output objects;
  2. honesty — insufficient/absent evidence => None / insufficient_data (never 0),
     unidirectional/partial evidence never yields a low influence claim, and no
     universal influence scalar is emitted;
  3. blueprint fidelity — a realistic multi-hop measured path materialises the
     components the blueprint defines for a measured case, and the two categories
     this repo cannot yet measure (earned downstream amplification §75, novel
     attention §77) degrade with reasons;
  4. edge cases — empty path, unknown (ungoverned) hops => epistemic ceiling,
     stale / unknown-staleness / expired hops per the staleness policy, and
     NON_PROPAGATING chain rejection / downweight;
  5. propagation-authority selection (direct vs multi-hop, per registry class).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from shared.relationship_spine.influence_propagation import (
    ATTENTION_COMPONENTS,
    ComponentEstimate,
    InfluencePropagationDecomposition,
    R_DOWNSTREAM_UNSUPPLIED,
    R_EMPTY_PATH,
    R_NOVELTY_UNSUPPLIED,
    assess_hop_propagation_authority,
    decompose_influence_propagation,
)
from shared.relationship_spine.path_fidelity import (
    CEILING_INFERENTIAL_ONLY,
    CEILING_NON_TRANSITIVE_MISUSE,
    CEILING_PATH_COMPOSABLE,
    CEILING_PROPAGATION_ONLY,
)

AS_OF = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Minimal Edge stub (mirrors tests/graph/test_path_fidelity.py conventions).
# ---------------------------------------------------------------------------

@dataclass
class StubEdge:
    edge_id: str
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    properties: dict[str, Any] = field(default_factory=dict)


def _edge(
    *,
    edge_type: str,
    from_vertex: str = "a",
    to_vertex: str = "b",
    confidence: float = 1.0,
    observed_at: str = "",
    valid_from: str = "",
    valid_to: str = "",
) -> StubEdge:
    props: dict[str, Any] = {"confidence": confidence}
    if observed_at:
        props["observed_at"] = observed_at
    if valid_from:
        props["valid_from"] = valid_from
    if valid_to:
        props["valid_to"] = valid_to
    return StubEdge(
        edge_id=f"{edge_type}:{from_vertex}:{to_vertex}",
        edge_type=edge_type,
        from_vertex_id=from_vertex,
        to_vertex_id=to_vertex,
        properties=props,
    )


def _full_measurements() -> dict[int, dict[str, float]]:
    """A 'measured case': every material hop carries an M7-fidelity-vector slice.

    hop0: interaction .5/.4, persistence .8, reciprocity .6, incentive assessed 0,
          independence .9, outcome .7, coordination .1
    hop1: interaction .6/.3, persistence .9, reciprocity .8, incentive assessed 0,
          independence 1.0, outcome .6, coordination .2
    """
    return {
        0: {
            "interaction_frequency": 0.5,
            "interaction_depth": 0.4,
            "persistence": 0.8,
            "reciprocity": 0.6,
            "incentive_exposure": 0.0,
            "incentive_independence_support": 0.9,
            "outcome_support": 0.7,
            "coordination_indicator_strength": 0.1,
        },
        1: {
            "interaction_frequency": 0.6,
            "interaction_depth": 0.3,
            "persistence": 0.9,
            "reciprocity": 0.8,
            "incentive_exposure": 0.0,
            "incentive_independence_support": 1.0,
            "outcome_support": 0.6,
            "coordination_indicator_strength": 0.2,
        },
    }


def _measured_two_hop_path():
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="PAYS", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    return edges, _full_measurements()


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------

def test_determinism_identical_inputs_equal_outputs():
    edges, measurements = _measured_two_hop_path()
    a = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    b = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    assert a == b
    assert a.as_dict().keys() == b.as_dict().keys()
    assert a.all_components == b.all_components


def test_determinism_is_order_independent_for_measurement_mapping_equivalence():
    # Two different but equivalent mappings (index-keyed vs signature-keyed) must
    # resolve to the same per-hop values, and equal inputs still give equal output.
    edges, _ = _measured_two_hop_path()
    by_signature = {
        f"a:x:PAYS": dict(_full_measurements()[0]),
        f"x:b:PAYS": dict(_full_measurements()[1]),
    }
    r1 = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop=_full_measurements(),
    )
    r2 = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop=by_signature,
    )
    assert r1 == r2


# ---------------------------------------------------------------------------
# 2. Honesty — unknown is never 0, never fabricated, no universal scalar
# ---------------------------------------------------------------------------

def test_empty_path_decomposes_to_no_components():
    r = decompose_influence_propagation([], source_ref="a", target_ref="b", as_of=AS_OF)
    assert r.decision == "empty"
    assert r.hop_count == 0
    assert r.propagation_certified is False
    assert R_EMPTY_PATH in r.reason_codes
    assert len(r.all_components) == 9
    for c in r.all_components:
        assert c.state == "insufficient_data"
        assert c.value is None  # never 0


def test_no_fidelity_evidence_never_yields_zero_or_low_values():
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="PAYS", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    r = decompose_influence_propagation(edges, source_ref="a", target_ref="b", as_of=AS_OF)
    # The path itself is a governed, composable channel; but no component may be
    # fabricated from absent measurements.
    assert r.decision == "pass"
    assert any("influence_inputs_absent" in rc for rc in r.reason_codes)
    for c in r.all_components:
        assert c.value is None
        assert c.state in ("insufficient_data", "not_applicable")


def test_partial_hop_measurement_is_insufficient_not_low():
    # Only one of two material hops carries persistence => the path-level
    # persistent-attention claim is insufficient (never a low number).
    edges, full = _measured_two_hop_path()
    partial = {0: {"persistence": 0.1}, 1: {}}
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=partial
    )
    assert r.persistent_attention.state == "insufficient_data"
    assert r.persistent_attention.value is None
    assert r.persistent_attention.reason_code == "insufficient_hop_measurement_coverage"


def test_absent_or_single_direction_relationship_evidence_never_yields_low_weight():
    # M7 reciprocity is NULL for single-direction evidence (never a low 0). Model
    # that honestly: hops whose measured vectors omit the relationship-strength
    # dimensions entirely must not let the path surface a fabricated low weight.
    edges, _ = _measured_two_hop_path()
    no_strength = {
        0: {"interaction_frequency": 0.9, "interaction_depth": 0.9},  # volume, no weight dims
        1: {"interaction_frequency": 0.9, "interaction_depth": 0.9},
    }
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop=no_strength,
    )
    c = r.relationship_weighted_attention
    assert c.state == "insufficient_data"
    assert c.value is None  # never a fabricated low
    # Raw volume is measured; relationship-weight is not invented from it.
    assert r.raw_attention.state == "available"

    # Even when ONE leg is measured strong and the other is not measured at all,
    # the path-level weight stays insufficient (the unmeasured leg could be weak).
    partial = {0: {"reciprocity": 0.9, "persistence": 0.9}, 1: {}}
    r2 = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=partial
    )
    assert r2.relationship_weighted_attention.state == "insufficient_data"
    assert r2.relationship_weighted_attention.value is None


def test_no_universal_influence_scalar_is_emitted():
    edges, measurements = _measured_two_hop_path()
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    assert not hasattr(r, "influence")
    assert not hasattr(r, "influence_score")
    assert not hasattr(r, "overall")
    # The only numeric surface is per-component.
    for c in r.all_components:
        if c.state == "available":
            assert 0.0 <= c.value <= 1.0


def test_assessed_zero_incentive_exposure_is_evidence_backed_not_unknown():
    # 0.0 is only acceptable where the measurement was actually assessed on every
    # hop and none was incentivized (blueprint §73); it stays [0,1] and available.
    edges, measurements = _measured_two_hop_path()
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    assert r.incentive_exposed_attention.state == "available"
    assert r.incentive_exposed_attention.value == pytest.approx(0.0)
    assert r.incentive_exposed_attention.measured_hops == 2


# ---------------------------------------------------------------------------
# 3. Blueprint fidelity — the nine-way decomposition of a measured path
# ---------------------------------------------------------------------------

def test_measured_multi_hop_path_materialises_measured_components():
    edges, measurements = _measured_two_hop_path()
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    assert r.decision == "pass"
    assert r.propagation_certified is True
    assert r.hop_count == 2
    assert r.min_epistemic_ceiling == pytest.approx(CEILING_PATH_COMPOSABLE)
    assert r.staleness_status == "fresh"

    expected = {
        "raw_attention": 0.45,
        "incentive_exposed_attention": 0.0,
        "independence_supported_attention": 0.9,
        "persistent_attention": 0.8,
        "relationship_weighted_attention": 0.7,
        "outcome_linked_attention": 0.6,
        "coordination_adjusted_attention": 0.2,
    }
    measured = {c.component_id for c in r.all_components if c.state == "available"}
    assert measured == set(expected)

    for component_id, value in expected.items():
        c: ComponentEstimate = r.as_dict()[component_id]
        assert c.state == "available"
        assert c.value == pytest.approx(value, abs=1e-6)
        assert c.measured_hops == 2
        assert c.material_hops == 2
        assert len(c.per_hop_values) == 2

    # Degraded categories (not produced by any current surface) stay None with a
    # reason that names the missing producer.
    assert r.earned_downstream_amplification.state == "insufficient_data"
    assert r.earned_downstream_amplification.value is None
    assert r.earned_downstream_amplification.reason_code == R_DOWNSTREAM_UNSUPPLIED
    assert r.novel_attention.state == "insufficient_data"
    assert r.novel_attention.value is None
    assert R_NOVELTY_UNSUPPLIED == r.novel_attention.reason_code

    # Exactly nine canonical component ids in blueprint §71 order.
    assert ATTENTION_COMPONENTS == tuple(r.as_dict().keys())
    assert len(r.as_dict()) == 9


def test_relationship_weighted_attention_is_capped_by_weakest_propagation_authority():
    # A two-hop FOLLOWS chain is PROPAGATION_ELIGIBLE but NON_TRANSITIVE as a
    # relationship identity, so the relationship-weighting basis is capped at the
    # propagation ceiling (0.55), never at the measured weight.
    edges = [
        _edge(edge_type="FOLLOWS_SOCIAL", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="FOLLOWS_SOCIAL", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop=_full_measurements(),
    )
    assert r.decision == "pass"  # influence PROPAGATION is certified
    assert r.min_epistemic_ceiling == pytest.approx(CEILING_PROPAGATION_ONLY)
    c = r.relationship_weighted_attention
    assert c.state == "available"
    # measured min weight is 0.7 but capped at 0.55
    assert c.value == pytest.approx(CEILING_PROPAGATION_ONLY)


# ---------------------------------------------------------------------------
# 4. Edge cases — empty, epistemic ceiling, staleness, non-propagation
# ---------------------------------------------------------------------------

def test_unknown_ungoverned_hop_is_uncertified_not_fabricated():
    edges = [
        _edge(edge_type="SOME_UNREGISTERED_EDGE", from_vertex="a", to_vertex="x"),
        _edge(edge_type="SOME_UNREGISTERED_EDGE", from_vertex="x", to_vertex="b"),
    ]
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=_full_measurements()
    )
    assert r.decision == "uncertified"
    assert r.propagation_certified is False
    assert all(c.state == "insufficient_data" for c in r.all_components)
    assert all(c.value is None for c in r.all_components)


def test_inferential_only_direct_hop_caps_relationship_weighted():
    # A single direct SHARES_AFFINITY_WITH hop is INFERENTIAL_ONLY: even measured
    # at full weight, the relationship weighting basis cannot exceed 0.4.
    edge = _edge(
        edge_type="SHARES_AFFINITY_WITH",
        from_vertex="a", to_vertex="b", observed_at="2026-07-31T00:00:00Z",
    )
    measurements = {0: {
        "interaction_frequency": 0.5, "interaction_depth": 0.4,
        "persistence": 0.9, "reciprocity": 0.8,
        "incentive_exposure": 0.0, "incentive_independence_support": 0.8,
        "outcome_support": 0.5, "coordination_indicator_strength": 0.0,
    }}
    r = decompose_influence_propagation(
        [edge], source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    assert r.decision == "pass"
    assert r.min_epistemic_ceiling == pytest.approx(CEILING_INFERENTIAL_ONLY)
    c = r.relationship_weighted_attention
    assert c.state == "available"
    assert c.value == pytest.approx(CEILING_INFERENTIAL_ONLY)


def test_single_hop_path_has_no_downstream_amplification():
    edge = _edge(edge_type="PAYS", from_vertex="a", to_vertex="b", observed_at="2026-07-31T00:00:00Z")
    r = decompose_influence_propagation(
        [edge], source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop={0: {}}
    )
    assert r.decision == "pass"
    assert r.earned_downstream_amplification.state == "not_applicable"
    assert r.earned_downstream_amplification.value is None


def test_stale_observation_is_reported_stale_never_fresh():
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2024-01-01T00:00:00Z"),
        _edge(edge_type="PAYS", from_vertex="x", to_vertex="b", observed_at="2024-01-01T00:00:00Z"),
    ]
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=_full_measurements()
    )
    assert r.staleness_status == "stale"
    assert all(h.status == "stale" for h in r.hop_staleness)
    # stale-but-valid hops still support a measured decomposition; currentness is
    # surfaced via staleness metadata, not fabricated into the values.
    assert r.raw_attention.state == "available"


def test_unknown_staleness_is_never_fabricated_fresh():
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x"),
        _edge(edge_type="PAYS", from_vertex="x", to_vertex="b"),
    ]
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=_full_measurements()
    )
    assert r.staleness_status == "unknown"
    assert all(h.status == "unknown" for h in r.hop_staleness)
    assert all(h.recency_factor is None for h in r.hop_staleness)
    assert r.staleness_status != "fresh"


def test_expired_valid_window_makes_decomposition_invalid():
    edge = _edge(
        edge_type="PAYS",
        from_vertex="a", to_vertex="b",
        observed_at="2024-01-01T00:00:00Z",
        valid_from="2023-01-01T00:00:00Z",
        valid_to="2024-06-01T00:00:00Z",
    )
    r = decompose_influence_propagation(
        [edge], source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop=_full_measurements(),
    )
    assert r.decision == "invalid"
    assert r.propagation_certified is False
    assert r.staleness_status == "expired"
    assert all(c.state == "insufficient_data" for c in r.all_components)
    assert all(c.value is None for c in r.all_components)


def test_non_propagating_relationship_chain_is_rejected_strictly():
    # MUTUAL_SOCIAL_CONNECTION is governed but NON_TRANSITIVE with NO
    # PROPAGATION_ELIGIBLE class: the spine does not authorise influence to flow
    # through a chained chain of such relationships => reject (strict).
    edges = [
        _edge(edge_type="MUTUAL_SOCIAL_CONNECTION", from_vertex="a", to_vertex="x"),
        _edge(edge_type="MUTUAL_SOCIAL_CONNECTION", from_vertex="x", to_vertex="b"),
    ]
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=_full_measurements()
    )
    assert r.decision == "reject"
    assert r.propagation_certified is False
    assert all(c.state == "insufficient_data" for c in r.all_components)
    assert all(c.value is None for c in r.all_components)


def test_non_propagating_chain_downweights_when_tolerated():
    edges = [
        _edge(edge_type="MUTUAL_SOCIAL_CONNECTION", from_vertex="a", to_vertex="x"),
        _edge(edge_type="MUTUAL_SOCIAL_CONNECTION", from_vertex="x", to_vertex="b"),
    ]
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop=_full_measurements(),
        reject_non_propagating=False,
    )
    assert r.decision == "downweight"
    assert r.min_epistemic_ceiling == pytest.approx(CEILING_NON_TRANSITIVE_MISUSE)
    # downweight still never fabricates components: a chain that is only
    # tolerated, not certified, keeps measured components but the relationship
    # weighting basis is capped at the non-propagating ceiling.
    c = r.relationship_weighted_attention
    assert c.state == "available"
    assert c.value == pytest.approx(CEILING_NON_TRANSITIVE_MISUSE)


def test_single_direct_observed_hop_is_self_certifying():
    edge = _edge(edge_type="PAYS", from_vertex="a", to_vertex="b", observed_at="2026-07-31T00:00:00Z")
    r = decompose_influence_propagation(
        [edge], source_ref="a", target_ref="b", as_of=AS_OF,
        fidelity_by_hop={0: {
            "interaction_frequency": 0.6, "interaction_depth": 0.5,
            "persistence": 0.7, "reciprocity": 0.9,
            "incentive_exposure": 0.0, "incentive_independence_support": 1.0,
            "outcome_support": 0.4, "coordination_indicator_strength": 0.0,
        }},
    )
    assert r.decision == "pass"
    assert r.propagation_certified is True
    assert r.hop_authority[0].usage == "direct"
    assert r.hop_authority[0].ceiling == pytest.approx(CEILING_PATH_COMPOSABLE)


# ---------------------------------------------------------------------------
# 5. Propagation-authority selection (pure helper)
# ---------------------------------------------------------------------------

def test_authority_respects_registry_propagation_classes():
    def classify(edge_type: str) -> tuple[str, Optional[float]]:
        edge = _edge(edge_type=edge_type)
        a = assess_hop_propagation_authority(0, edge, path_length=2)
        return a.kind, a.ceiling

    kind, ceiling = classify("PAYS")
    assert kind == "composable"
    assert ceiling == pytest.approx(CEILING_PATH_COMPOSABLE)

    kind, ceiling = classify("FOLLOWS_SOCIAL")
    assert kind == "propagation"
    assert ceiling == pytest.approx(CEILING_PROPAGATION_ONLY)

    kind, ceiling = classify("SHARES_AFFINITY_WITH")
    assert kind == "inferred"
    assert ceiling == pytest.approx(CEILING_INFERENTIAL_ONLY)

    kind, ceiling = classify("MUTUAL_SOCIAL_CONNECTION")
    assert kind == "non_propagating"
    assert ceiling == pytest.approx(CEILING_NON_TRANSITIVE_MISUSE)

    kind, ceiling = classify("NOT_A_GOVERNED_EDGE")
    assert kind == "uncertified"
    assert ceiling == pytest.approx(0.0)


def test_authority_single_hop_is_direct_usage():
    edge = _edge(edge_type="FOLLOWS_SOCIAL", from_vertex="a", to_vertex="b")
    a = assess_hop_propagation_authority(0, edge, path_length=1)
    assert a.usage == "direct"
    assert a.index == 0
    assert a.predicate == "FOLLOWS"


# ---------------------------------------------------------------------------
# 6. Shape/metadata conformance
# ---------------------------------------------------------------------------

def test_result_metadata_shape():
    edges, measurements = _measured_two_hop_path()
    r = decompose_influence_propagation(
        edges, source_ref="a", target_ref="b", as_of=AS_OF, fidelity_by_hop=measurements
    )
    assert isinstance(r, InfluencePropagationDecomposition)
    assert r.algorithm == "aether.relationship_spine.influence_propagation"
    assert r.source_ref == "a"
    assert r.target_ref == "b"
    assert r.as_of is not None
    assert r.hop_count == 2
    assert len(r.hop_authority) == 2
    assert len(r.hop_staleness) == 2
    # Only the two availability groups exist: measured categories carry per-hop
    # detail; degraded categories carry none.
    assert r.available_components == 7
    assert set(r.available_component_ids) == {
        "raw_attention",
        "incentive_exposed_attention",
        "independence_supported_attention",
        "persistent_attention",
        "relationship_weighted_attention",
        "outcome_linked_attention",
        "coordination_adjusted_attention",
    }
