"""Tests ensuring all four relationship layers appear in key documentation files.

No doc that mentions relationship layers may omit A2H.
Forbidden pattern: 'H2H, H2A, and A2A' without A2H listed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]

# Docs that must list all four layers when they mention relationship layers
LAYER_DOCS = [
    "README.md",
    "Backend Architecture/README.md",
    "docs/INTELLIGENCE-GRAPH.md",
    "docs/UNIFIED-ECONOMIC-GRAPH.md",
    "docs/ECONOMIC-OBSERVABILITY.md",
    "docs/KYBER-ECONOMIC-OBSERVABILITY.md",
    "docs/OPERATIONAL-INTELLIGENCE-AUDIT.md",
    "docs/PRODUCTION-READINESS.md",
    "docs/productization/aether_productization_audit.md",
]

FOUR_LAYERS = ["H2H", "H2A", "A2H", "A2A"]

# Pattern that would incorrectly list only three layers
THREE_LAYER_PATTERN = re.compile(r"H2H,\s*H2A,\s*and\s*A2A\b")


def _read(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def test_no_doc_uses_three_layer_pattern() -> None:
    """No doc may say 'H2H, H2A, and A2A' omitting A2H."""
    violations: list[str] = []
    for rel_path in LAYER_DOCS:
        content = _read(rel_path)
        if THREE_LAYER_PATTERN.search(content):
            violations.append(rel_path)
    assert not violations, (
        f"Docs use three-layer pattern (omitting A2H): {violations}\n"
        "Fix: replace 'H2H, H2A, and A2A' with 'H2H, H2A, A2H, and A2A'"
    )


def test_backend_readme_has_a2h_in_relationship_table() -> None:
    """Backend Architecture/README.md must include A2H in the Relationship Layers table."""
    content = _read("Backend Architecture/README.md")
    assert content, "Backend Architecture/README.md not found"
    assert "A2H" in content, "A2H missing from Backend Architecture/README.md"
    assert "Agent-to-Human" in content, "Agent-to-Human description missing from Backend Architecture/README.md"


def test_intelligence_graph_doc_has_all_four_layers() -> None:
    """docs/INTELLIGENCE-GRAPH.md must document all four layers."""
    content = _read("docs/INTELLIGENCE-GRAPH.md")
    assert content, "docs/INTELLIGENCE-GRAPH.md not found"
    for layer in FOUR_LAYERS:
        assert layer in content, f"Layer {layer} missing from docs/INTELLIGENCE-GRAPH.md"


def test_production_readiness_doc_has_all_four_layers() -> None:
    """docs/PRODUCTION-READINESS.md must list all four relationship layers."""
    content = _read("docs/PRODUCTION-READINESS.md")
    assert content, "docs/PRODUCTION-READINESS.md not found"
    assert "A2H" in content, "A2H missing from docs/PRODUCTION-READINESS.md"


def test_operational_intelligence_audit_has_a2h() -> None:
    """docs/OPERATIONAL-INTELLIGENCE-AUDIT.md must reference A2H layer."""
    content = _read("docs/OPERATIONAL-INTELLIGENCE-AUDIT.md")
    assert content, "docs/OPERATIONAL-INTELLIGENCE-AUDIT.md not found"
    assert "A2H" in content, "A2H missing from docs/OPERATIONAL-INTELLIGENCE-AUDIT.md"


def test_graph_contract_source_of_truth_exists() -> None:
    """docs/source-of-truth/GRAPH_CONTRACT.md must exist and contain all four layers."""
    content = _read("docs/source-of-truth/GRAPH_CONTRACT.md")
    assert content, "docs/source-of-truth/GRAPH_CONTRACT.md not found or empty"
    for layer in FOUR_LAYERS:
        assert layer in content, f"Layer {layer} missing from GRAPH_CONTRACT.md"


def test_graph_layer_parity_doc_exists() -> None:
    """docs/source-of-truth/GRAPH_LAYER_PARITY.md must exist."""
    path = REPO_ROOT / "docs/source-of-truth/GRAPH_LAYER_PARITY.md"
    assert path.exists(), "docs/source-of-truth/GRAPH_LAYER_PARITY.md not found"


def test_no_placeholder_in_operational_intelligence_routes() -> None:
    """operational_intelligence/routes.py must not contain placeholder overlay strings."""
    content = _read("Backend Architecture/aether-backend/services/operational_intelligence/routes.py")
    assert content, "operational_intelligence/routes.py not found"
    assert "placeholder" not in content.lower(), (
        "Placeholder overlay string found in operational_intelligence/routes.py"
    )
    assert "future release" not in content.lower(), (
        "'future release' string found in operational_intelligence/routes.py — remove it"
    )


def test_no_contract_stage_skeleton_in_routes() -> None:
    """contractStage: 'skeleton' must not be in production code routes."""
    content = _read("Backend Architecture/aether-backend/services/operational_intelligence/routes.py")
    assert content, "routes.py not found"
    # skeleton stage must not be set on production nodes
    assert '"contractStage": "skeleton"' not in content, (
        "contractStage: skeleton found in routes.py — remove it from production paths"
    )
    assert "'contractStage': 'skeleton'" not in content, (
        "contractStage: skeleton found in routes.py — remove it from production paths"
    )
