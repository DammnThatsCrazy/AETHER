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


def _const_strs(value: ast.expr) -> list[str]:
    """Extract non-null string constants from a revision/down_revision RHS.

    Handles both a plain ``"id"`` and a merge migration's ``("a", "b")`` tuple.
    """
    if isinstance(value, ast.Constant):
        return [] if value.value is None else [str(value.value)]
    if isinstance(value, (ast.Tuple, ast.List)):
        return [str(e.value) for e in value.elts
                if isinstance(e, ast.Constant) and e.value is not None]
    return []


def _collect_revisions() -> tuple[set[str], list[tuple[str, str]]]:
    """Return (revision ids, [(file, down_revision id)]) across all migrations."""
    revisions: set[str] = set()
    down_refs: list[tuple[str, str]] = []
    for path in _migration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "revision":
                    revisions.update(_const_strs(node.value))
                elif target.id == "down_revision":
                    down_refs.extend((path.name, d) for d in _const_strs(node.value))
    return revisions, down_refs


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


def test_down_revisions_link_to_known_revisions():
    """Every non-null ``down_revision`` must reference a real revision id.

    This is the orphan check the module docstring promises: it catches a
    ``down_revision`` that points at a migration *filename* (e.g.
    ``20260528_cis_canonical_state``) instead of that migration's actual
    revision id (``cis001a2b3c4d``), which would silently break the Alembic
    chain while every file still looks individually well-formed.
    """
    revisions, down_refs = _collect_revisions()
    orphans = sorted(
        f"{name}: down_revision={ref!r}"
        for name, ref in down_refs
        if ref not in revisions
    )
    assert not orphans, "down_revision(s) not matching any known revision: " + "; ".join(orphans)
