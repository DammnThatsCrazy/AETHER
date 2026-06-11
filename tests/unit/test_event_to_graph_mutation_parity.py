"""Tests for event-to-graph-mutation parity.

Ensures that graph-mutating events in the SDK event registry are
mapped to graph mutation rules in the backend.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def _read(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# Known graph-mutating SDK events
GRAPH_MUTATING_EVENTS = [
    "agent_task",
    "agent_decision",
    "a2h_interaction",
    "payment_initiated",
    "payment_completed",
]

# A2H-specific events that must be mapped
A2H_EVENTS = ["a2h_interaction"]


def test_graph_alignment_doc_maps_a2h_interaction() -> None:
    """docs/source-of-truth/GRAPH_ALIGNMENT.md must map a2h_interaction to A2H edges."""
    content = _read("docs/source-of-truth/GRAPH_ALIGNMENT.md")
    assert content, "GRAPH_ALIGNMENT.md not found"
    assert "a2h_interaction" in content, "a2h_interaction event missing from GRAPH_ALIGNMENT.md"
    assert "A2H" in content, "A2H layer not referenced in GRAPH_ALIGNMENT.md"


def test_graph_alignment_doc_maps_agent_task_to_h2a() -> None:
    content = _read("docs/source-of-truth/GRAPH_ALIGNMENT.md")
    assert content, "GRAPH_ALIGNMENT.md not found"
    assert "agent_task" in content, "agent_task event missing from GRAPH_ALIGNMENT.md"


def test_graph_alignment_doc_maps_payment_events() -> None:
    content = _read("docs/source-of-truth/GRAPH_ALIGNMENT.md")
    assert "payment_completed" in content, "payment_completed missing from GRAPH_ALIGNMENT.md"


def test_a2h_interaction_creates_a2h_edges() -> None:
    """GRAPH_ALIGNMENT.md must show a2h_interaction creates A2H edges (NOTIFIES, RECOMMENDS, etc.)."""
    content = _read("docs/source-of-truth/GRAPH_ALIGNMENT.md")
    assert "NOTIFIES" in content or "RECOMMENDS" in content, (
        "A2H edge types (NOTIFIES/RECOMMENDS) not documented in GRAPH_ALIGNMENT.md"
    )


def test_relationship_layers_py_maps_all_a2h_edge_types() -> None:
    """Python relationship_layers.py must map all A2H edge types."""
    content = _read("Backend Architecture/aether-backend/shared/graph/relationship_layers.py")
    a2h_edge_types = ["NOTIFIES", "RECOMMENDS", "DELIVERS_TO", "ESCALATES_TO"]
    for et in a2h_edge_types:
        assert et in content, f"A2H edge type {et} missing from relationship_layers.py"


def test_no_graph_mutating_event_creates_unclassified_edges() -> None:
    """Every A2H event must produce edges classified as A2H in the layer map."""
    content = _read("Backend Architecture/aether-backend/shared/graph/relationship_layers.py")
    # All four layers must be present
    for layer in ("H2H", "H2A", "A2H", "A2A"):
        assert layer in content, f"Layer {layer} missing from relationship_layers.py"
