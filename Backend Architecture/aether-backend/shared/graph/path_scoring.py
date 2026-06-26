"""Aether Shared — @aether/graph/path_scoring
Versioned path-scoring system for canonical RelationshipPath confidence computation.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.graph.graph import Edge

# Causality class penalty weights applied during path scoring.
_CAUSALITY_PENALTIES: dict[str, float] = {
    "correlation": 0.2,
    "correlated": 0.2,
    "inferred_influence": 0.1,
    "inferred": 0.1,
}

# PathClassification precedence: earlier = weaker (worst-case wins).
_CLASSIFICATION_PRECEDENCE: list[str] = [
    "correlated",
    "inferred",
    "attributed",
    "causal_supported",
    "observed",
]

# Map causality_class values on edges → PathClassification values.
_CAUSALITY_TO_CLASSIFICATION: dict[str, str] = {
    "correlation": "correlated",
    "correlated": "correlated",
    "inferred_influence": "inferred",
    "inferred": "inferred",
    "attributed": "attributed",
    "causal_supported": "causal_supported",
    "observed": "observed",
}


def score_path(
    edges: list["Edge"],
    max_depth: int,
    scoring_version: str = "1",
) -> dict:
    """Compute a PathScoreBreakdown dict for a sequence of edges.

    Formula (version 1):
      geometric_mean = exp(mean(log(max(c, 1e-9)) for c in confidences))
      hop_penalty    = max(0.0, 1.0 - len(edges) / max_depth * 0.15)
      causality_pen  = max penalty across all edges (0.2 for correlation, 0.1 for inferred)
      overall        = clamp(geometric_mean * hop_penalty * (1 - causality_pen), 0, 1)
    """
    if not edges:
        return {
            "geometric_mean_confidence": 1.0,
            "min_edge_confidence": 1.0,
            "hop_penalty": 1.0,
            "causality_penalty": 0.0,
            "overall": 1.0,
            "scoring_version": scoring_version,
            "components": {},
        }

    confidences = [
        float(e.properties.get("confidence", 1.0)) if e.properties else 1.0
        for e in edges
    ]
    confidences_clamped = [max(c, 1e-9) for c in confidences]

    geometric_mean = math.exp(
        sum(math.log(c) for c in confidences_clamped) / len(confidences_clamped)
    )
    geometric_mean = min(max(geometric_mean, 0.0), 1.0)
    min_edge_confidence = min(confidences)

    hop_count = len(edges)
    hop_penalty = max(0.0, 1.0 - hop_count / max(max_depth, 1) * 0.15)

    causality_penalty = 0.0
    for edge in edges:
        cc = edge.properties.get("causality_class", "") if edge.properties else ""
        pen = _CAUSALITY_PENALTIES.get(cc, 0.0)
        if pen > causality_penalty:
            causality_penalty = pen

    overall = min(max(geometric_mean * hop_penalty * (1.0 - causality_penalty), 0.0), 1.0)

    return {
        "geometric_mean_confidence": round(geometric_mean, 6),
        "min_edge_confidence": round(min_edge_confidence, 6),
        "hop_penalty": round(hop_penalty, 6),
        "causality_penalty": round(causality_penalty, 6),
        "overall": round(overall, 6),
        "scoring_version": scoring_version,
        "components": {
            "raw_geometric_mean": round(geometric_mean, 6),
            "hop_count": hop_count,
            "max_depth": max_depth,
        },
    }


def classify_path(edges: list["Edge"]) -> str:
    """Return PathClassification string for a path using worst-case (weakest) edge causality.

    Precedence (weakest first): correlated > inferred > attributed > causal_supported > observed.
    Defaults to 'observed' when no causality_class is set on any edge.
    """
    if not edges:
        return "observed"

    worst_rank = len(_CLASSIFICATION_PRECEDENCE) - 1  # start at strongest
    for edge in edges:
        cc = edge.properties.get("causality_class", "") if edge.properties else ""
        classification = _CAUSALITY_TO_CLASSIFICATION.get(cc, "observed")
        rank = _CLASSIFICATION_PRECEDENCE.index(classification)
        if rank < worst_rank:
            worst_rank = rank

    return _CLASSIFICATION_PRECEDENCE[worst_rank]


def make_path_id(ordered_node_ids: list[str]) -> str:
    """Return a stable 32-char hex path identifier from ordered node IDs."""
    raw = ":".join(ordered_node_ids)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def compute_evidence_coverage(edges: list["Edge"]) -> float:
    """Return fraction of edges with a source_event_id or evidence reference in properties."""
    if not edges:
        return 1.0
    count = 0
    for edge in edges:
        props = edge.properties or {}
        if props.get("source_event_id") or props.get("evidence_ref") or props.get("evidence_id"):
            count += 1
    return round(count / len(edges), 6)
