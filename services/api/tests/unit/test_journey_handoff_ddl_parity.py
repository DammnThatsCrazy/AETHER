"""DDL parity: repositories/journey_handoff_repo.py <-> alembic 20261022_journey_handoffs."""
from __future__ import annotations

import ast
from pathlib import Path

from repositories.journey_handoff_repo import JOURNEY_HANDOFFS_DDL, JOURNEY_HANDOFF_INDEXES

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261022_journey_handoffs.py"
)


def _consts() -> dict[str, object]:
    out: dict[str, object] = {}
    for node in ast.parse(MIGRATION.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return out


def test_ddl_matches_migration():
    consts = _consts()
    assert consts["JOURNEY_HANDOFFS_DDL"] == JOURNEY_HANDOFFS_DDL
    assert consts["JOURNEY_HANDOFF_INDEXES"] == JOURNEY_HANDOFF_INDEXES


def test_migration_chains_after_spawn_lineage():
    assert _consts()["down_revision"] == "20261022_agent_spawn_lineage"
