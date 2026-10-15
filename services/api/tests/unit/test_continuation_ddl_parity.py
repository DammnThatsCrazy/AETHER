"""DDL parity: repositories/continuation_repo.py <-> the alembic migration.

The alembic versions directory is not importable at runtime, so the continuation
DDL is duplicated in both the migration and the repository. This test AST-extracts
the migration's module-level DDL constants and asserts exact equality with the
repository's, so the two can never silently diverge.
"""
from __future__ import annotations

import ast
from pathlib import Path

from repositories.continuation_repo import (
    CONTINUATION_INDEXES,
    CONTINUATION_SELECTIONS_DDL,
    CONTINUATIONS_DDL,
)

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "20260820_continuation_plane.py"


def _migration_constants() -> dict[str, object]:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return out


def test_migration_file_exists():
    assert MIGRATION.exists(), f"migration missing: {MIGRATION}"


def test_ddl_constants_match_migration():
    consts = _migration_constants()
    assert consts["CONTINUATIONS_DDL"] == CONTINUATIONS_DDL
    assert consts["CONTINUATION_SELECTIONS_DDL"] == CONTINUATION_SELECTIONS_DDL
    assert consts["CONTINUATION_INDEXES"] == CONTINUATION_INDEXES


def test_migration_chains_single_head():
    consts = _migration_constants()
    assert consts["revision"] == "20260820_continuation_plane"
    # Re-pointed onto the comms-intelligence head after merging origin/main (#499) to
    # preserve the single-alembic-head invariant.
    assert consts["down_revision"] == "20260813_comms_turnkey"
