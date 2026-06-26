"""Unit tests for shared.graph.path_scoring — scoring, classification, and path ID generation."""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)
    if "jwt" not in sys.modules:
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "stub",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception,
                ExpiredSignatureError=Exception,
                InvalidTokenError=Exception,
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def _make_edge(confidence: float = 1.0, causality_class: str = "") -> object:
    """Return a lightweight Edge-like object with the required .properties dict."""
    props: dict = {"confidence": confidence}
    if causality_class:
        props["causality_class"] = causality_class
    return types.SimpleNamespace(properties=props, edge_id="e1", edge_type="DELEGATES")


def test_geometric_mean_confidence() -> None:
    with backend_path():
        from shared.graph.path_scoring import score_path

        edges = [_make_edge(0.8), _make_edge(0.5)]
        result = score_path(edges, max_depth=6)
        import math
        expected_gm = math.exp((math.log(0.8) + math.log(0.5)) / 2)
        assert abs(result["geometric_mean_confidence"] - expected_gm) < 1e-4


def test_min_edge_confidence() -> None:
    with backend_path():
        from shared.graph.path_scoring import score_path

        edges = [_make_edge(0.9), _make_edge(0.3), _make_edge(0.7)]
        result = score_path(edges, max_depth=6)
        assert abs(result["min_edge_confidence"] - 0.3) < 1e-6


def test_hop_penalty_decreases_with_more_hops() -> None:
    with backend_path():
        from shared.graph.path_scoring import score_path

        one_hop = score_path([_make_edge()], max_depth=6)
        three_hops = score_path([_make_edge(), _make_edge(), _make_edge()], max_depth=6)
        assert one_hop["hop_penalty"] > three_hops["hop_penalty"]


def test_causality_penalty_for_correlation() -> None:
    with backend_path():
        from shared.graph.path_scoring import score_path

        no_penalty = score_path([_make_edge(0.9)], max_depth=6)
        with_penalty = score_path([_make_edge(0.9, causality_class="correlation")], max_depth=6)
        assert with_penalty["causality_penalty"] == 0.2
        assert with_penalty["overall"] < no_penalty["overall"]


def test_classify_path_returns_correlated_for_weakest_edge() -> None:
    with backend_path():
        from shared.graph.path_scoring import classify_path

        edges = [
            _make_edge(causality_class="observed"),
            _make_edge(causality_class="correlation"),
        ]
        assert classify_path(edges) == "correlated"


def test_make_path_id_is_deterministic() -> None:
    with backend_path():
        from shared.graph.path_scoring import make_path_id

        ids = ["node-A", "node-B", "node-C"]
        assert make_path_id(ids) == make_path_id(ids)
        assert len(make_path_id(ids)) == 32


def test_make_path_id_differs_for_different_sequences() -> None:
    with backend_path():
        from shared.graph.path_scoring import make_path_id

        assert make_path_id(["A", "B"]) != make_path_id(["B", "A"])
        assert make_path_id(["A", "B"]) != make_path_id(["A", "C"])
