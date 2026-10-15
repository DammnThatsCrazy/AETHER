"""DDL parity: repositories/client_sync_repo.py <-> the alembic migration."""
from __future__ import annotations

import ast
from pathlib import Path

from repositories.client_sync_repo import (
    SYNC_CHANGE_LOG_DDL,
    SYNC_CURSOR_COUNTER_DDL,
    SYNC_INDEXES,
)

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "20260821_client_sync.py"


def _migration_constants() -> dict[str, object]:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return out


def test_ddl_matches_migration():
    c = _migration_constants()
    assert c["SYNC_CHANGE_LOG_DDL"] == SYNC_CHANGE_LOG_DDL
    assert c["SYNC_CURSOR_COUNTER_DDL"] == SYNC_CURSOR_COUNTER_DDL
    assert c["SYNC_INDEXES"] == SYNC_INDEXES


def test_migration_chains_from_continuation():
    c = _migration_constants()
    assert c["revision"] == "20260821_client_sync"
    assert c["down_revision"] == "20260820_continuation_plane"
