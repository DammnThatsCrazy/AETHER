"""Aether Shared — @aether/graph/path_scoring
Versioned path-scoring system for canonical RelationshipPath confidence computation.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

from shared.computation.types import GraphMetric

if TYPE_CHECKING:
    from shared.graph.graph import Edge

# Canonical identifier for the path-scoring algorithm. Emitted on every governed
# GraphMetric so a stored score can be traced back to the algorithm that made it.
PATH_SCORING_ALGORITHM = "aether.graph.path_scoring.score_path"

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


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH-METRIC GOVERNANCE
#
# A raw path/graph score (e.g. score_path(...)["overall"]) is a bare float. Two
# such floats computed over different graph snapshots — or over different node/
# edge populations, or with a different normalization basis — are NOT safely
# comparable, yet nothing about the float itself says so. The sanctioned way to
# *emit* a graph-derived score for storage, comparison, or transport is to wrap
# it with graph_metric_envelope(...) into a shared.computation.types.GraphMetric,
# which binds the score to:
#   • the graph snapshot / bitemporal ``as_of`` coordinate it was read at,
#   • the node + edge population and the included edge types,
#   • the normalization basis, and
#   • the scoring algorithm + version.
# GraphMetric requires graph_snapshot_id, so a score with no snapshot cannot be
# emitted through this envelope at all.
# ═══════════════════════════════════════════════════════════════════════════


def _population_descriptor(
    node_population: Optional[int],
    edge_population: Optional[int],
    included_edge_types: Optional[Iterable[str]],
) -> Optional[str]:
    """Pack node/edge population and included edge types into one stable string.

    GraphMetric exposes a single free-form ``node_population`` field; this folds
    the node count, the edge count, and the sorted, de-duplicated set of edge
    types that were in scope into a deterministic descriptor so two metrics are
    only comparable when they were computed over the same population.
    """
    parts: list[str] = []
    if node_population is not None:
        parts.append(f"nodes={node_population}")
    if edge_population is not None:
        parts.append(f"edges={edge_population}")
    if included_edge_types is not None:
        types = sorted({str(t) for t in included_edge_types})
        parts.append(f"edge_types=[{','.join(types)}]")
    return ";".join(parts) if parts else None


def graph_metric_envelope(
    value: Optional[float],
    *,
    graph_snapshot_id: str,
    node_population: Optional[int] = None,
    edge_population: Optional[int] = None,
    included_edge_types: Optional[Iterable[str]] = None,
    normalization_basis: Optional[str] = None,
    algorithm: str = PATH_SCORING_ALGORITHM,
    algorithm_version: Optional[str] = None,
) -> GraphMetric:
    """Wrap a raw graph score into a governed :class:`GraphMetric` — the sanctioned
    way to emit any graph-derived scalar from this module.

    A raw score float carries none of the provenance that makes it comparable, so
    callers should never persist or compare a bare graph score; they should pass
    it through here. The returned metric records the graph snapshot / ``as_of``
    coordinate, the node + edge population and included edge types (via
    ``node_population``), the normalization basis (via ``normalization_population``),
    and the algorithm + version.

    ``graph_snapshot_id`` must be non-empty: a graph-derived score is not
    comparable without the snapshot it was computed over, so an absent/blank
    snapshot is rejected here rather than silently emitted. (GraphMetric itself
    additionally makes ``graph_snapshot_id`` a required field.)
    """
    if not graph_snapshot_id or not str(graph_snapshot_id).strip():
        raise ValueError(
            "graph_metric_envelope requires a non-empty graph_snapshot_id: a "
            "graph-derived score is not comparable across snapshots without the "
            "snapshot / as_of coordinate it was computed over."
        )
    return GraphMetric(
        value=value,
        graph_snapshot_id=str(graph_snapshot_id),
        node_population=_population_descriptor(
            node_population, edge_population, included_edge_types
        ),
        normalization_population=normalization_basis,
        algorithm=algorithm,
        algorithm_version=algorithm_version,
    )


def score_path_metric(
    edges: list["Edge"],
    max_depth: int,
    *,
    graph_snapshot_id: Optional[str] = None,
    as_of: Optional[str] = None,
    node_population: Optional[int] = None,
    included_edge_types: Optional[Iterable[str]] = None,
    scoring_version: str = "1",
) -> GraphMetric:
    """Score a path and expose its ``overall`` confidence as a governed GraphMetric.

    This is the governed companion to :func:`score_path`. ``score_path`` stays the
    numeric source of truth and its returned dict is unchanged (fully backward
    compatible); this *additionally* exposes the same ``overall`` score inside a
    :class:`GraphMetric` envelope so the score travels with the graph snapshot /
    bitemporal ``as_of`` coordinate it was computed at, the node + edge population
    and included edge types, the normalization basis, and the scoring algorithm +
    version. Without that envelope, ``overall`` scores from two different snapshots
    look comparable when they are not.

    The snapshot is taken from ``graph_snapshot_id`` when given, otherwise from the
    ``as_of`` read coordinate used by temporal traversal (see
    ``GraphTraversalEngine.temporal_bfs``). One of the two is required: a graph
    score with no snapshot is rejected, not silently emitted.
    """
    breakdown = score_path(edges, max_depth, scoring_version=scoring_version)

    snapshot = graph_snapshot_id or as_of
    edge_types = (
        included_edge_types
        if included_edge_types is not None
        else {edge.edge_type for edge in edges}
    )
    node_count = node_population
    if node_count is None:
        # A simple path over N edges spans N+1 nodes (empty path == single node).
        node_count = len(edges) + 1 if edges else 1

    return graph_metric_envelope(
        breakdown["overall"],
        graph_snapshot_id=snapshot or "",
        node_population=node_count,
        edge_population=len(edges),
        included_edge_types=edge_types,
        normalization_basis=(
            "geometric_mean*hop_penalty*(1-causality_penalty); "
            f"max_depth={max_depth}; scoring_version={scoring_version}"
        ),
        algorithm_version=scoring_version,
    )
