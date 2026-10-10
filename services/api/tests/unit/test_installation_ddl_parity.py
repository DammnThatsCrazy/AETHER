"""DDL parity: repositories/installation_repo.py <-> the alembic migration."""
from __future__ import annotations

import ast
from pathlib import Path

from repositories.installation_repo import (
    MOBILE_INSTALLATION_INDEXES,
    MOBILE_INSTALLATIONS_DDL,
    PUSH_SUBSCRIPTIONS_DDL,
)

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "20260822_mobile_installations.py"


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
    assert c["MOBILE_INSTALLATIONS_DDL"] == MOBILE_INSTALLATIONS_DDL
    assert c["PUSH_SUBSCRIPTIONS_DDL"] == PUSH_SUBSCRIPTIONS_DDL
    assert c["MOBILE_INSTALLATION_INDEXES"] == MOBILE_INSTALLATION_INDEXES


def test_migration_chains_from_client_sync():
    c = _migration_constants()
    assert c["revision"] == "20260822_mobile_installations"
    assert c["down_revision"] == "20260821_client_sync"
