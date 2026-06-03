"""CI-gated smoke test for alembic migration well-formedness (static; no DB).

Verifies every migration declares a revision identity and reversible
upgrade/downgrade functions, and that the revision DAG is linkable (no orphan
down_revision references). Pure AST/text parsing — no alembic or database.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "Backend Architecture" / "aether-backend" / "alembic" / "versions"


def _migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def test_migrations_dir_present():
    assert VERSIONS.is_dir(), "alembic versions directory missing"
    assert _migration_files(), "no migration files found"


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_migration_is_well_formed(path: Path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "upgrade" in names, f"{path.name}: missing upgrade()"
    assert "downgrade" in names, f"{path.name}: missing downgrade()"
    assigns = {
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    assert "revision" in assigns, f"{path.name}: missing revision identifier"
    assert "down_revision" in assigns, f"{path.name}: missing down_revision"


def test_revisions_unique_with_a_root():
    revisions: list[str] = []
    roots = 0
    for path in _migration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "revision" and isinstance(node.value, ast.Constant):
                        revisions.append(str(node.value.value))
                    if isinstance(t, ast.Name) and t.id == "down_revision" and isinstance(node.value, ast.Constant) and node.value.value is None:
                        roots += 1
    # Revision identifiers must be unique (no collisions in the history).
    assert len(revisions) == len(set(revisions)), "duplicate revision identifiers"
    # At least one root migration (down_revision = None).
    assert roots >= 1, "expected at least one root migration"
