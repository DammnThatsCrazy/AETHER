"""Graph-metric governance for path scoring (Section 22).

Graph reads carry a bitemporal ``as_of`` coordinate, but a bare path score
(``score_path(...)["overall"]``) is just a float — nothing about it records the
graph snapshot, the node/edge population, the normalization basis, or the
algorithm that produced it, so scores from different snapshots are not safely
comparable.

These tests prove the governed path from ``shared/graph/path_scoring.py``:

  * ``score_path`` stays a plain numeric dict (backward compatible), and
  * ``graph_metric_envelope`` / ``score_path_metric`` now emit a
    ``shared.computation.types.GraphMetric`` that carries snapshot id +
    node/edge population + included edge types + normalization basis + algorithm
    and version, and
  * a ``GraphMetric`` with no snapshot id is rejected (``graph_snapshot_id`` is a
    required field in ``types.py``), and the envelope refuses a blank snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError

from shared.computation.types import GraphMetric, MathType
from shared.graph.path_scoring import (
    PATH_SCORING_ALGORITHM,
    graph_metric_envelope,
    score_path,
    score_path_metric,
)


# ---------------------------------------------------------------------------
# Minimal Edge stub (mirrors shared.graph.graph.Edge fields used by scoring)
# ---------------------------------------------------------------------------

@dataclass
class StubEdge:
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = "2024-01-01T00:00:00Z"


def _edge(edge_type: str, confidence: float = 1.0) -> StubEdge:
    return StubEdge(
        edge_type=edge_type,
        from_vertex_id="a",
        to_vertex_id="b",
        properties={"confidence": confidence},
    )


# ---------------------------------------------------------------------------
# 1. The raw numeric scorer is unchanged / backward compatible.
# ---------------------------------------------------------------------------

def test_score_path_still_returns_plain_numeric_dict():
    edges = [_edge("HIRED", 0.8), _edge("DELEGATES", 0.5)]
    result = score_path(edges, max_depth=6)
    # Existing contract intact: still a dict of floats, no governance leakage.
    assert isinstance(result, dict)
    assert set(result) >= {
        "geometric_mean_confidence",
        "min_edge_confidence",
        "hop_penalty",
        "causality_penalty",
        "overall",
        "scoring_version",
    }
    assert isinstance(result["overall"], float)


# ---------------------------------------------------------------------------
# 2. score_path_metric emits a fully governed GraphMetric.
# ---------------------------------------------------------------------------

def test_score_path_metric_carries_full_governance_envelope():
    edges = [_edge("HIRED", 0.9), _edge("DELEGATES", 0.6)]
    breakdown = score_path(edges, max_depth=6, scoring_version="1")

    metric = score_path_metric(
        edges,
        max_depth=6,
        as_of="2026-08-07T00:00:00Z",
        scoring_version="1",
    )

    assert isinstance(metric, GraphMetric)
    assert metric.math_type is MathType.GRAPH_METRIC

    # Numeric score is preserved exactly — the envelope is additive, not lossy.
    assert metric.value == breakdown["overall"]

    # Snapshot / as_of coordinate is recorded.
    assert metric.graph_snapshot_id == "2026-08-07T00:00:00Z"

    # Node + edge population and the included edge types are recorded.
    assert metric.node_population is not None
    assert "nodes=3" in metric.node_population   # 2 edges -> 3 nodes
    assert "edges=2" in metric.node_population
    assert "DELEGATES" in metric.node_population
    assert "HIRED" in metric.node_population

    # Normalization basis is recorded.
    assert metric.normalization_population is not None
    assert "max_depth=6" in metric.normalization_population

    # Algorithm + version are recorded.
    assert metric.algorithm == PATH_SCORING_ALGORITHM
    assert metric.algorithm_version == "1"


def test_explicit_snapshot_id_beats_as_of():
    edges = [_edge("HIRED", 1.0)]
    metric = score_path_metric(
        edges,
        max_depth=4,
        graph_snapshot_id="snap-42",
        as_of="2026-08-07T00:00:00Z",
    )
    assert metric.graph_snapshot_id == "snap-42"


# ---------------------------------------------------------------------------
# 3. The generic sanctioned helper wraps any raw graph score.
# ---------------------------------------------------------------------------

def test_graph_metric_envelope_wraps_a_raw_score():
    metric = graph_metric_envelope(
        0.73,
        graph_snapshot_id="snap-1",
        node_population=5,
        edge_population=4,
        included_edge_types=["DELEGATES", "HIRED", "HIRED"],
        normalization_basis="tenant-cohort-v1",
        algorithm_version="2",
    )
    assert metric.value == 0.73
    assert metric.graph_snapshot_id == "snap-1"
    assert metric.node_population == "nodes=5;edges=4;edge_types=[DELEGATES,HIRED]"
    assert metric.normalization_population == "tenant-cohort-v1"
    assert metric.algorithm == PATH_SCORING_ALGORITHM
    assert metric.algorithm_version == "2"


# ---------------------------------------------------------------------------
# 4. A graph score with no snapshot is rejected — not silently emitted.
# ---------------------------------------------------------------------------

def test_graph_metric_requires_snapshot_id_in_types():
    # types.py makes graph_snapshot_id a required field.
    ok = GraphMetric(value=0.3, graph_snapshot_id="snap-1")
    assert ok.graph_snapshot_id == "snap-1"
    with pytest.raises(ValidationError):
        GraphMetric(value=0.3)  # missing required snapshot id


def test_envelope_rejects_blank_snapshot():
    with pytest.raises(ValueError):
        graph_metric_envelope(0.5, graph_snapshot_id="")
    with pytest.raises(ValueError):
        graph_metric_envelope(0.5, graph_snapshot_id="   ")


def test_score_path_metric_rejects_missing_snapshot():
    edges = [_edge("HIRED", 1.0)]
    with pytest.raises(ValueError):
        score_path_metric(edges, max_depth=6)  # no snapshot id / no as_of
