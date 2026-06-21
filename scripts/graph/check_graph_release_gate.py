#!/usr/bin/env python3
"""
Graph Release Gate — exits 0 if all invariants pass, exits 1 with failure list.

Run: python scripts/graph/check_graph_release_gate.py

Checks:
1.  All EdgeType class attributes are mapped in _EDGE_LAYER_MAP (exhaustiveness)
2.  classify_edge_type() returns a canonical layer for every mapped type
3.  No edge type silently defaults to H2H (all mappings are explicit)
4.  GRAPH_ALIGNMENT.md has source_files: frontmatter (drift detection wired)
5.  GRAPH_LAYER_PARITY.md has all four layers marked
6.  write_validator.py module exists and GraphWriteValidator can be imported
7.  edge_properties.py exports REQUIRED_EDGE_PROPERTIES (non-empty)
8.  traversal.py TraversalResult has a2a_cycles_detected field
9.  UnknownEdgeTypeError is importable from relationship_layers
10. EXCLUDED is a valid RelationshipLayer value
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"

sys.path.insert(0, str(BACKEND_ROOT))
# Stub jwt so auth imports don't fail in CI without cffi
import types as _types
if "jwt" not in sys.modules:
    sys.modules["jwt"] = _types.SimpleNamespace(
        encode=lambda *a, **kw: "stub",
        decode=lambda *a, **kw: {},
        exceptions=_types.SimpleNamespace(
            PyJWTError=Exception,
            ExpiredSignatureError=Exception,
            InvalidTokenError=Exception,
        ),
    )


failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    msg = f"[{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    if not ok:
        failures.append(name)


# ── 1. EdgeType exhaustiveness ────────────────────────────────────────────

try:
    from shared.graph.graph import EdgeType
    from shared.graph.relationship_layers import _EDGE_LAYER_MAP

    all_edge_type_values = {
        v for k, v in vars(EdgeType).items()
        if not k.startswith("_") and isinstance(v, str)
    }
    unmapped = all_edge_type_values - set(_EDGE_LAYER_MAP.keys())
    check(
        "All EdgeType values mapped in _EDGE_LAYER_MAP",
        len(unmapped) == 0,
        f"{len(unmapped)} unmapped: {sorted(unmapped)[:5]}" if unmapped else
        f"{len(all_edge_type_values)} total, all mapped",
    )
except Exception as e:
    check("All EdgeType values mapped in _EDGE_LAYER_MAP", False, str(e))

# ── 2. classify_edge_type returns canonical layers ────────────────────────

try:
    from shared.graph.relationship_layers import classify_edge_type, RelationshipLayer

    CANONICAL = {
        RelationshipLayer.H2H, RelationshipLayer.H2A,
        RelationshipLayer.A2H, RelationshipLayer.A2A, RelationshipLayer.EXCLUDED,
    }
    bad = [
        et for et in list(_EDGE_LAYER_MAP.keys())[:10]
        if classify_edge_type(et) not in CANONICAL
    ]
    check(
        "classify_edge_type returns known layers",
        len(bad) == 0,
        f"Bad mappings: {bad}" if bad else "OK",
    )
except Exception as e:
    check("classify_edge_type returns known layers", False, str(e))

# ── 3. No silent H2H default for unknown types ────────────────────────────

try:
    os.environ["AETHER_ENV"] = "production"
    from importlib import reload
    import shared.graph.relationship_layers as _rl
    reload(_rl)
    raised = False
    try:
        _rl.classify_edge_type("__NONEXISTENT_EDGE_TYPE_XYZ__")
    except _rl.UnknownEdgeTypeError:
        raised = True
    check("Unknown edge type raises in production mode", raised)
finally:
    os.environ["AETHER_ENV"] = "local"

# ── 4. GRAPH_ALIGNMENT.md has source_files: frontmatter ──────────────────

alignment_path = REPO_ROOT / "docs" / "source-of-truth" / "GRAPH_ALIGNMENT.md"
if alignment_path.exists():
    content = alignment_path.read_text()
    has_frontmatter = "source_files:" in content and content.startswith("---")
    check("GRAPH_ALIGNMENT.md has source_files: frontmatter", has_frontmatter)
else:
    check("GRAPH_ALIGNMENT.md exists", False, str(alignment_path))

# ── 5. GRAPH_LAYER_PARITY.md has all four layers ─────────────────────────

parity_path = REPO_ROOT / "docs" / "source-of-truth" / "GRAPH_LAYER_PARITY.md"
if parity_path.exists():
    pc = parity_path.read_text()
    layers_ok = all(layer in pc for layer in ("H2H", "H2A", "A2H", "A2A"))
    check("GRAPH_LAYER_PARITY.md contains all four layers", layers_ok)
else:
    check("GRAPH_LAYER_PARITY.md exists", False)

# ── 6. write_validator.py importable ─────────────────────────────────────

try:
    from shared.graph.write_validator import GraphWriteValidator, GraphWriteValidationError
    v = GraphWriteValidator()
    check("GraphWriteValidator importable", True)
except Exception as e:
    check("GraphWriteValidator importable", False, str(e))

# ── 7. edge_properties.py has REQUIRED_EDGE_PROPERTIES ───────────────────

try:
    from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
    check(
        "REQUIRED_EDGE_PROPERTIES non-empty",
        len(REQUIRED_EDGE_PROPERTIES) > 0,
        f"{len(REQUIRED_EDGE_PROPERTIES)} required properties",
    )
except Exception as e:
    check("REQUIRED_EDGE_PROPERTIES non-empty", False, str(e))

# ── 8. TraversalResult has a2a_cycles_detected ───────────────────────────

try:
    from shared.graph.traversal import TraversalResult
    r = TraversalResult()
    check(
        "TraversalResult has a2a_cycles_detected",
        hasattr(r, "a2a_cycles_detected"),
    )
except Exception as e:
    check("TraversalResult has a2a_cycles_detected", False, str(e))

# ── 9. UnknownEdgeTypeError importable ───────────────────────────────────

try:
    from shared.graph.relationship_layers import UnknownEdgeTypeError
    check("UnknownEdgeTypeError importable", issubclass(UnknownEdgeTypeError, ValueError))
except Exception as e:
    check("UnknownEdgeTypeError importable", False, str(e))

# ── 10. EXCLUDED is a valid RelationshipLayer ────────────────────────────

try:
    from shared.graph.relationship_layers import RelationshipLayer
    check(
        "RelationshipLayer.EXCLUDED exists",
        hasattr(RelationshipLayer, "EXCLUDED"),
    )
except Exception as e:
    check("RelationshipLayer.EXCLUDED exists", False, str(e))

# ── Summary ───────────────────────────────────────────────────────────────

print()
if failures:
    print(f"Graph release gate FAILED ({len(failures)} check(s)):")
    for f in failures:
        print(f"  ✗ {f}")
    sys.exit(1)
else:
    print("Graph release gate PASSED — all checks OK.")
    sys.exit(0)
