"""Unit tests for shared/graph/path_scoring.py — 7 tests."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from shared.graph.path_scoring import (
    classify_path,
    compute_evidence_coverage,
    make_path_id,
    score_path,
)


# ---------------------------------------------------------------------------
# Minimal Edge stub so tests don't need a full GraphClient
# ---------------------------------------------------------------------------

@dataclass
class StubEdge:
    edge_id: str
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = "2024-01-01T00:00:00Z"


def _edge(
    *,
    edge_id: str = "e1",
    confidence: float = 1.0,
    causality_class: str = "",
    source_event_id: str = "",
) -> StubEdge:
    props: dict[str, Any] = {"confidence": confidence}
    if causality_class:
        props["causality_class"] = causality_class
    if source_event_id:
        props["source_event_id"] = source_event_id
    return StubEdge(
        edge_id=edge_id,
        edge_type="RELATED_TO",
        from_vertex_id="a",
        to_vertex_id="b",
        properties=props,
    )


# ---------------------------------------------------------------------------
# Test 1: geometric mean confidence calculation
# ---------------------------------------------------------------------------

def test_score_path_geometric_mean():
    edges = [_edge(confidence=0.8), _edge(edge_id="e2", confidence=0.5)]
    result = score_path(edges, max_depth=6)
    expected_geom = math.exp((math.log(0.8) + math.log(0.5)) / 2)
    assert abs(result["geometric_mean_confidence"] - expected_geom) < 1e-4


# ---------------------------------------------------------------------------
# Test 2: min_edge_confidence field
# ---------------------------------------------------------------------------

def test_score_path_min_edge_confidence():
    edges = [_edge(confidence=0.9), _edge(edge_id="e2", confidence=0.3)]
    result = score_path(edges, max_depth=6)
    assert abs(result["min_edge_confidence"] - 0.3) < 1e-6


# ---------------------------------------------------------------------------
# Test 3: hop_penalty decreases overall confidence for long paths
# ---------------------------------------------------------------------------

def test_score_path_hop_penalty():
    # 4 hops, max_depth=6 → penalty = 1 - 4/6 * 0.15 = 1 - 0.1 = 0.9
    edges = [_edge(edge_id=f"e{i}", confidence=1.0) for i in range(4)]
    result = score_path(edges, max_depth=6)
    expected_penalty = 1.0 - 4 / 6 * 0.15
    assert abs(result["hop_penalty"] - expected_penalty) < 1e-4


# ---------------------------------------------------------------------------
# Test 4: causality_penalty is applied for 'correlation'
# ---------------------------------------------------------------------------

def test_score_path_causality_penalty():
    edges = [_edge(confidence=1.0, causality_class="correlation")]
    result = score_path(edges, max_depth=6)
    assert result["causality_penalty"] == pytest.approx(0.2)
    # overall = 1.0 * hop_penalty * (1 - 0.2) < 1.0
    assert result["overall"] < 1.0


# ---------------------------------------------------------------------------
# Test 5: classify_path returns worst-case classification
# ---------------------------------------------------------------------------

def test_classify_path_worst_case():
    edges = [
        _edge(causality_class="observed"),
        _edge(edge_id="e2", causality_class="correlation"),
        _edge(edge_id="e3", causality_class="causal_supported"),
    ]
    # Worst is correlation → should return "correlated"
    result = classify_path(edges)
    assert result == "correlated"


# ---------------------------------------------------------------------------
# Test 6: make_path_id is deterministic for the same sequence
# ---------------------------------------------------------------------------

def test_make_path_id_deterministic():
    ids = ["node-A", "node-B", "node-C"]
    expected = hashlib.sha256(":".join(ids).encode()).hexdigest()[:32]
    assert make_path_id(ids) == expected
    assert make_path_id(ids) == expected  # idempotent


# ---------------------------------------------------------------------------
# Test 7: make_path_id is unique for different sequences
# ---------------------------------------------------------------------------

def test_make_path_id_uniqueness():
    ids_forward = ["X", "Y", "Z"]
    ids_reversed = ["Z", "Y", "X"]
    assert make_path_id(ids_forward) != make_path_id(ids_reversed)
    ids_different = ["A", "B", "C"]
    assert make_path_id(ids_forward) != make_path_id(ids_different)
