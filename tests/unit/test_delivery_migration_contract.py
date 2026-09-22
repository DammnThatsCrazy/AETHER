"""Static contract checks for the resumable delivery migration.

The staging Aurora database may already contain delivery tables from an older
bootstrap path while Alembic still has the delivery revision pending.  These
checks keep the migration's resume behavior explicit without requiring a live
database in the fast unit lane.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "backend"
    / "alembic"
    / "versions"
    / "20260702_delivery_infrastructure.py"
)


def _upgrade_calls(source: str) -> list[str]:
    tree = ast.parse(source)
    upgrade = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    names: list[str] = []
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id in {"op_create_table", "op_create_index", "op"}:
            names.append(node.func.id)
        if node.func.id in {"_create_table_if_missing", "_create_index_if_missing"}:
            names.append(node.func.id)
    return names


def test_delivery_upgrade_uses_resumable_table_and_index_helpers() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    calls = _upgrade_calls(source)

    assert calls.count("_create_table_if_missing") == 8
    assert calls.count("_create_index_if_missing") == 16
    assert "op_create_table" not in calls
    assert "op_create_index" not in calls
    assert "_DELIVERY_REQUIRED_COLUMNS = (\"id\", \"data\", \"tenant_id\", \"created_at\", \"updated_at\")" in source


def test_delivery_raw_indexes_are_idempotent() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    statements = re.findall(
        r"CREATE (?:UNIQUE )?INDEX(?: IF NOT EXISTS)?\s+idx_[^\n]+",
        source,
        flags=re.IGNORECASE,
    )

    assert len(statements) == 4
    assert all("IF NOT EXISTS" in statement.upper() for statement in statements)
