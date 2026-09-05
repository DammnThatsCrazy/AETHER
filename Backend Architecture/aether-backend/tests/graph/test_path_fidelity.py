"""Unit tests for shared/relationship_spine/path_fidelity.py — M8 fidelity-aware path scoring layer.

Covers (targeted, flag-gated module):
  1. epistemic-ceiling hop contract — an INFERENTIAL_ONLY hop caps the path;
  2. NON_TRANSITIVE transitive misuse — rejected (strict) or down-weighted;
  3. snapshot staleness — a stale observation lowers authority; unknown staleness
     is never fabricated as fresh;
  4. fidelity-absent degradation to honest UNKNOWN (epistemic ceiling still on);
  5. M7 fidelity-vector consumption when present (disputed -> reject);
  6. DTO shape conformance (breakdown == PathScoreBreakdown / RelationshipPath);
  7. flag-OFF regression — existing path_scoring/traversal behaviour unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.graph.path_scoring import score_path
from shared.relationship_spine.path_fidelity import (
    CEILING_INFERENTIAL_ONLY,
    CEILING_NON_TRANSITIVE_MISUSE,
    PATH_FIDELITY_ENV,
    DEFAULT_STALE_FLOOR,
    StalenessPolicy,
    assess_hop_epistemic,
    path_fidelity_enabled,
    predicate_entry_for_edge_type,
    score_path_with_fidelity,
)

AS_OF = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Minimal Edge stub (mirrors the existing test_path_scoring.py conventions).
# ---------------------------------------------------------------------------

@dataclass
class StubEdge:
    edge_id: str
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = "2026-01-01T00:00:00Z"


def _edge(
    *,
    edge_type: str,
    from_vertex: str = "a",
    to_vertex: str = "b",
    edge_id: str = "",
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
        edge_id=edge_id or f"{edge_type}:{from_vertex}:{to_vertex}",
        edge_type=edge_type,
        from_vertex_id=from_vertex,
        to_vertex_id=to_vertex,
        properties=props,
    )


def _raw_overall(edges: list[StubEdge], *, max_depth: int = 6) -> float:
    return float(score_path(edges, max_depth=max_depth)["overall"])


# ---------------------------------------------------------------------------
# 1. Epistemic-ceiling hop contract
# ---------------------------------------------------------------------------

def test_inferential_only_hop_caps_multi_hop_path():
    # PAYS is PATH_COMPOSABLE; SHARES_AFFINITY_WITH is INFERENTIAL_ONLY. The
    # weakest material hop (inferential) caps the composite.
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="SHARES_AFFINITY_WITH", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=True)
    raw = _raw_overall(edges)
    assert res.decision == "pass"
    assert res.certified is True
    assert res.epistemic_ceiling is not None
    assert res.epistemic_ceiling == CEILING_INFERENTIAL_ONLY
    assert res.overall <= CEILING_INFERENTIAL_ONLY + 1e-9
    assert res.overall < raw
    assert res.breakdown["overall"] == res.overall
    # weakest hop is the inferential one
    kinds = [h.kind for h in res.hop_epistemic]
    assert "inferred" in kinds


def test_inferential_only_single_hop_is_capped():
    # A single direct hop whose predicate is inference-only cannot outrank its
    # own epistemic authority either.
    edge = _edge(edge_type="SHARES_AFFINITY_WITH", observed_at="2026-07-31T00:00:00Z")
    res = score_path_with_fidelity([edge], max_depth=6, as_of=AS_OF, enabled=True)
    assert res.decision == "pass"
    assert res.overall <= CEILING_INFERENTIAL_ONLY + 1e-9


def test_observed_single_hop_is_not_capped_by_composable_class():
    # A direct observed hop is self-certifying at full authority (ceiling 1.0);
    # the fresh fidelity overall equals the base path_scoring composite.
    edge = _edge(edge_type="PAYS", observed_at="2026-07-31T00:00:00Z")
    res = score_path_with_fidelity([edge], max_depth=6, as_of=AS_OF, enabled=True)
    assert res.decision == "pass"
    assert res.epistemic_ceiling == pytest.approx(1.0)
    assert res.overall == pytest.approx(_raw_overall([edge]))


# ---------------------------------------------------------------------------
# 2. NON_TRANSITIVE misuse -> reject (strict) or down-weight
# ---------------------------------------------------------------------------

def _non_transitive_path():
    return [
        _edge(edge_type="FOLLOWS_SOCIAL", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="FOLLOWS_SOCIAL", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]


def test_non_transitive_transitive_inference_rejected():
    edges = _non_transitive_path()
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=True)
    assert res.decision == "reject"
    assert res.certified is False
    assert res.overall == 0.0
    assert any("non_transitive" in r for r in res.reason_codes)
    assert all(h.kind == "non_transitive_misuse" for h in res.hop_epistemic)


def test_non_transitive_transitive_inference_downweighted_when_tolerated():
    edges = _non_transitive_path()
    res = score_path_with_fidelity(
        edges, max_depth=6, as_of=AS_OF, enabled=True, reject_non_transitive=False
    )
    raw = _raw_overall(edges)
    assert res.decision == "downweight"
    assert res.certified is False
    assert res.epistemic_ceiling == CEILING_NON_TRANSITIVE_MISUSE
    expected = round(min(raw, CEILING_NON_TRANSITIVE_MISUSE), 6)
    assert res.overall == pytest.approx(expected)
    assert res.overall < raw


# ---------------------------------------------------------------------------
# 3. Snapshot staleness
# ---------------------------------------------------------------------------

def test_stale_observation_lowers_authority():
    fresh = _edge(edge_type="PAYS", observed_at="2026-07-31T00:00:00Z")
    stale = _edge(edge_type="PAYS", observed_at="2024-01-01T00:00:00Z")
    fresh_res = score_path_with_fidelity([fresh], max_depth=6, as_of=AS_OF, enabled=True)
    stale_res = score_path_with_fidelity([stale], max_depth=6, as_of=AS_OF, enabled=True)
    base = _raw_overall([fresh])
    assert fresh_res.staleness_status == "fresh"
    assert stale_res.staleness_status == "stale"
    assert fresh_res.overall == pytest.approx(base)
    assert stale_res.overall == pytest.approx(round(base * DEFAULT_STALE_FLOOR, 6))
    assert stale_res.overall < fresh_res.overall
    assert stale_res.hop_staleness[0].recency_factor == pytest.approx(DEFAULT_STALE_FLOOR)


def test_partial_staleness_decays_linearly_between_horizons():
    policy = StalenessPolicy(fresh_horizon_days=7.0, stale_horizon_days=90.0)
    # 48.5 days old => progress (48.5-7)/(90-7) = 0.5 => factor 0.75
    edge = _edge(edge_type="PAYS", observed_at="2026-06-13T12:00:00Z")
    res = score_path_with_fidelity([edge], max_depth=6, as_of=AS_OF, enabled=True,
                                   staleness_policy=policy)
    assert res.staleness_status == "stale"
    assert res.hop_staleness[0].recency_factor == pytest.approx(0.75, abs=1e-4)


def test_unknown_staleness_is_never_fabricated_fresh():
    # No observation instant anywhere on the hop => UNKNOWN, not 'fresh'.
    edge = _edge(edge_type="PAYS")
    res = score_path_with_fidelity([edge], max_depth=6, as_of=AS_OF, enabled=True)
    assert res.staleness_status == "unknown"
    assert res.hop_staleness[0].status == "unknown"
    assert res.hop_staleness[0].recency_factor is None
    # Unknown staleness must not lower the numeric composite into a fabricated
    # number, and it must NOT be reported as fresh.
    assert res.overall == pytest.approx(_raw_overall([edge]))


def test_expired_valid_window_makes_path_invalid_at_as_of():
    edge = _edge(
        edge_type="PAYS",
        observed_at="2024-01-01T00:00:00Z",
        valid_from="2023-01-01T00:00:00Z",
        valid_to="2024-06-01T00:00:00Z",
    )
    res = score_path_with_fidelity([edge], max_depth=6, as_of=AS_OF, enabled=True)
    assert res.decision == "invalid"
    assert res.certified is False
    assert res.overall == 0.0
    assert res.staleness_status == "expired"


# ---------------------------------------------------------------------------
# 4. Fidelity-absent degradation to honest UNKNOWN
# ---------------------------------------------------------------------------

def test_fidelity_absent_degrades_to_unknown_but_ceiling_still_enforced():
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="SHARES_AFFINITY_WITH", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=True)
    # M7 interface absent => honest UNKNOWN, never fabricated support.
    assert res.fidelity_input_status == "unknown"
    assert any("fidelity_inputs_absent" in r for r in res.reason_codes)
    # Even without fidelity inputs, transitivityClasses alone enforce the ceiling.
    assert res.overall <= CEILING_INFERENTIAL_ONLY + 1e-9


def test_fidelity_vector_disputed_rejects_path():
    edge = _edge(edge_type="PAYS", observed_at="2026-07-31T00:00:00Z")
    res = score_path_with_fidelity(
        [edge], max_depth=6, as_of=AS_OF, enabled=True,
        fidelity_by_hop={0: {"status": "disputed"}},
    )
    assert res.fidelity_input_status == "present"
    assert res.decision == "reject"
    assert res.certified is False
    assert res.overall == 0.0
    assert any("disputed" in r for r in res.reason_codes)


# ---------------------------------------------------------------------------
# 5. Registry helpers + honesty around ungoverned predicates
# ---------------------------------------------------------------------------

def test_predicate_entry_resolution_by_name_and_graph_edge_type():
    assert predicate_entry_for_edge_type("PAYS") is not None
    assert predicate_entry_for_edge_type("FOLLOWS_SOCIAL") is not None  # graphEdgeType
    assert predicate_entry_for_edge_type("SHARES_AFFINITY_WITH") is not None
    assert predicate_entry_for_edge_type("NO_SUCH_GOVERNED_EDGE") is None


def test_multi_hop_ungoverned_predicate_is_uncertified_not_fabricated():
    edges = [
        _edge(edge_type="SOME_UNREGISTERED_EDGE", from_vertex="a", to_vertex="x"),
        _edge(edge_type="SOME_UNREGISTERED_EDGE", from_vertex="x", to_vertex="b"),
    ]
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=True)
    assert res.decision == "uncertified"
    assert res.certified is False
    assert res.overall == 0.0
    assert all(h.kind == "uncertified" for h in res.hop_epistemic)


# ---------------------------------------------------------------------------
# 6. DTO shape conformance
# ---------------------------------------------------------------------------

def test_breakdown_conforms_to_path_score_breakdown_dto():
    from services.operational_intelligence.models import PathScoreBreakdown, RelationshipPath  # noqa: PLC0415

    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="PAYS", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=True)
    breakdown = res.breakdown

    required_keys = {
        "geometric_mean_confidence",
        "min_edge_confidence",
        "hop_penalty",
        "causality_penalty",
        "overall",
        "scoring_version",
        "components",
    }
    assert set(breakdown) == required_keys
    assert 0.0 <= breakdown["overall"] <= 1.0
    numeric_keys = set(required_keys) - {"scoring_version", "components"}
    assert all(isinstance(v, float) for k, v in breakdown.items() if k in numeric_keys)
    assert all(isinstance(v, (int, float)) for v in breakdown["components"].values())

    # Pydantic DTO construction must succeed unchanged.
    score_dto = PathScoreBreakdown(**breakdown)
    assert score_dto.overall == res.overall

    # A full RelationshipPath can carry this score_breakdown without error.
    path_dto = RelationshipPath(
        path_id="p1",
        tenant_id="t1",
        source_id="a",
        target_id="b",
        ordered_node_ids=["a", "x", "b"],
        ordered_edge_ids=[e.edge_id for e in edges],
        nodes=[],
        edges=[],
        hop_count=len(edges),
        path_confidence=res.overall,
        evidence_coverage=1.0,
        classification="observed",
        layer_sequence=["SOCIAL", "ECONOMIC"],
        score_breakdown=score_dto,
        computed_at="2026-08-01T00:00:00Z",
    )
    assert path_dto.path_confidence == res.overall


def test_fully_composable_path_is_not_penalized_when_fresh_and_certified():
    edges = [
        _edge(edge_type="PAYS", from_vertex="a", to_vertex="x", observed_at="2026-07-31T00:00:00Z"),
        _edge(edge_type="PAYS", from_vertex="x", to_vertex="b", observed_at="2026-07-31T00:00:00Z"),
    ]
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=True)
    assert res.decision == "pass"
    assert res.certified is True
    assert res.epistemic_ceiling == pytest.approx(1.0)
    assert res.overall == pytest.approx(_raw_overall(edges))


# ---------------------------------------------------------------------------
# 7. Flag-OFF regression: existing path_scoring/traversal behaviour unchanged
# ---------------------------------------------------------------------------

def test_flag_off_returns_unchanged_path_scoring_breakdown():
    edges = _non_transitive_path()  # would be REJECTED when the layer is ON
    res = score_path_with_fidelity(edges, max_depth=6, as_of=AS_OF, enabled=False)
    base = score_path(edges, max_depth=6)
    assert res.decision == "disabled"
    assert res.breakdown == base
    assert res.overall == pytest.approx(base["overall"])


def test_flag_defaults_off_and_env_can_enable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(PATH_FIDELITY_ENV, raising=False)
    assert path_fidelity_enabled() is False
    assert path_fidelity_enabled(enabled=True) is True
    monkeypatch.setenv(PATH_FIDELITY_ENV, "1")
    assert path_fidelity_enabled() is True
