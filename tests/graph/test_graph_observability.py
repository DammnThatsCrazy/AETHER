"""Tests for graph observability — release gate script, metrics module existence,
health endpoint structure, and layer stats completeness."""

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
    for prefix in ("shared",):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    if "jwt" not in sys.modules:
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "stub",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception, ExpiredSignatureError=Exception, InvalidTokenError=Exception
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_release_gate_script_exists() -> None:
    gate = REPO_ROOT / "scripts" / "graph" / "check_graph_release_gate.py"
    assert gate.exists(), "check_graph_release_gate.py must exist in scripts/graph/"


def test_replay_workload_script_exists() -> None:
    script = REPO_ROOT / "scripts" / "graph" / "replay_relationship_layers.py"
    assert script.exists()


def test_graph_rebuild_validation_script_exists() -> None:
    script = REPO_ROOT / "scripts" / "graph" / "graph_rebuild_validation.py"
    assert script.exists()


def test_get_layer_stats_returns_all_four_canonical_layers() -> None:
    """get_layer_stats must include H2H, H2A, A2H, A2A keys even for empty input."""
    with backend_path():
        from shared.graph.relationship_layers import get_layer_stats
        stats = get_layer_stats([])
        for layer in ("H2H", "H2A", "A2H", "A2A"):
            assert layer in stats, f"{layer} missing from get_layer_stats result"


def test_get_layer_stats_unknown_key_present() -> None:
    """get_layer_stats must include an 'unknown' key for unmapped edge tracking."""
    with backend_path():
        from shared.graph.relationship_layers import get_layer_stats
        stats = get_layer_stats([])
        assert "unknown" in stats


def test_get_layer_stats_includes_excluded() -> None:
    """get_layer_stats must include EXCLUDED key since it's a RelationshipLayer value."""
    with backend_path():
        from shared.graph.relationship_layers import get_layer_stats
        stats = get_layer_stats([])
        assert "EXCLUDED" in stats


def test_makefile_has_graph_test_target() -> None:
    content = _read("Makefile")
    assert "graph-test" in content, "Makefile missing 'graph-test' target"


def test_makefile_has_graph_release_check_target() -> None:
    content = _read("Makefile")
    assert "graph-release-check" in content, "Makefile missing 'graph-release-check' target"


def test_makefile_has_graph_replay_target() -> None:
    content = _read("Makefile")
    assert "graph-replay" in content, "Makefile missing 'graph-replay' target"


def test_graph_alignment_doc_has_source_files_frontmatter() -> None:
    content = _read("docs/source-of-truth/GRAPH_ALIGNMENT.md")
    assert content, "GRAPH_ALIGNMENT.md not found"
    assert "source_files:" in content, (
        "GRAPH_ALIGNMENT.md is missing source_files: frontmatter"
    )


def test_write_validator_module_exists() -> None:
    path = BACKEND_ROOT / "shared" / "graph" / "write_validator.py"
    assert path.exists(), "write_validator.py must exist in shared/graph/"


def test_edge_properties_module_exists() -> None:
    path = BACKEND_ROOT / "shared" / "graph" / "edge_properties.py"
    assert path.exists(), "edge_properties.py must exist in shared/graph/"
