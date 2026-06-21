"""Tests that every EdgeType value is explicitly mapped in _EDGE_LAYER_MAP.

The exhaustiveness constraint ensures that no new EdgeType can silently default
to H2H in staging/production — it will raise UnknownEdgeTypeError instead.
"""

from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    for prefix in ("shared", "services", "config"):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
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


def test_all_edge_types_are_mapped() -> None:
    """Every EdgeType class attribute must be in _EDGE_LAYER_MAP."""
    with backend_path():
        from shared.graph.graph import EdgeType
        from shared.graph.relationship_layers import _EDGE_LAYER_MAP

        all_values = {
            v for k, v in vars(EdgeType).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        unmapped = all_values - set(_EDGE_LAYER_MAP.keys())
        assert not unmapped, (
            f"{len(unmapped)} EdgeType(s) missing from _EDGE_LAYER_MAP:\n"
            + "\n".join(f"  - {et}" for et in sorted(unmapped))
        )


def test_no_unmapped_edge_type_count() -> None:
    """_EDGE_LAYER_MAP must cover at least as many types as EdgeType defines."""
    with backend_path():
        from shared.graph.graph import EdgeType
        from shared.graph.relationship_layers import _EDGE_LAYER_MAP

        all_values = {
            v for k, v in vars(EdgeType).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        assert len(_EDGE_LAYER_MAP) >= len(all_values), (
            f"_EDGE_LAYER_MAP has {len(_EDGE_LAYER_MAP)} entries but "
            f"EdgeType defines {len(all_values)} values"
        )


def test_classify_edge_type_returns_canonical_layer_for_all_mapped_types() -> None:
    """classify_edge_type must return a RelationshipLayer (not raise) for every mapped type."""
    with backend_path():
        from shared.graph.relationship_layers import RelationshipLayer, _EDGE_LAYER_MAP, classify_edge_type

        known = set(RelationshipLayer)
        for et in _EDGE_LAYER_MAP:
            layer = classify_edge_type(et)
            assert layer in known, f"classify_edge_type({et!r}) returned unknown layer {layer!r}"


def test_unknown_edge_raises_in_strict_mode() -> None:
    """classify_edge_type with a non-existent type must raise UnknownEdgeTypeError in strict mode."""
    with backend_path():
        from shared.graph.relationship_layers import UnknownEdgeTypeError, _is_strict
        # Patch _is_strict at the module level temporarily to simulate production
        import shared.graph.relationship_layers as rl

        original = rl._is_strict
        rl._is_strict = lambda: True
        try:
            raised = False
            try:
                rl.classify_edge_type("__DOES_NOT_EXIST_XYZ__")
            except UnknownEdgeTypeError:
                raised = True
            assert raised, "UnknownEdgeTypeError was NOT raised for unknown edge in strict mode"
        finally:
            rl._is_strict = original


def test_excluded_layer_exists() -> None:
    """RelationshipLayer.EXCLUDED must exist as a valid enum member."""
    with backend_path():
        from shared.graph.relationship_layers import RelationshipLayer
        assert hasattr(RelationshipLayer, "EXCLUDED"), "RelationshipLayer.EXCLUDED is missing"
        assert RelationshipLayer.EXCLUDED.value == "EXCLUDED"


def test_four_canonical_layers_unchanged() -> None:
    """Adding EXCLUDED must not change the count of canonical layers (still 4)."""
    with backend_path():
        from shared.graph.graph_contract import CANONICAL_LAYERS, LAYER_COUNT
        assert LAYER_COUNT == 4, f"LAYER_COUNT must be 4, got {LAYER_COUNT}"
        assert len(CANONICAL_LAYERS) == 4


def test_validate_contract_passes_with_exhaustive_map() -> None:
    """validate_contract() must return no violations after exhaustive mapping."""
    with backend_path():
        from shared.graph.graph_contract import validate_contract
        violations = validate_contract()
        assert not violations, (
            f"graph_contract violations detected:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


def test_h2h_has_most_edge_types() -> None:
    """H2H should have the largest number of edge types (identity + analytics + entity graph)."""
    with backend_path():
        from shared.graph.relationship_layers import RelationshipLayer, _EDGE_LAYER_MAP

        by_layer: dict[str, int] = {}
        for et, layer in _EDGE_LAYER_MAP.items():
            by_layer[layer.value] = by_layer.get(layer.value, 0) + 1

        assert by_layer.get("H2H", 0) > by_layer.get("A2A", 0), (
            "Expected H2H to have more edge types than A2A"
        )


def test_a2a_has_more_edges_than_a2h() -> None:
    """A2A (agent orchestration) should have more edge types than A2H (delivery)."""
    with backend_path():
        from shared.graph.relationship_layers import RelationshipLayer, _EDGE_LAYER_MAP

        a2a = sum(1 for l in _EDGE_LAYER_MAP.values() if l == RelationshipLayer.A2A)
        a2h = sum(1 for l in _EDGE_LAYER_MAP.values() if l == RelationshipLayer.A2H)
        assert a2a > a2h, f"Expected A2A ({a2a}) > A2H ({a2h})"
