"""DDL parity: the repo's runtime DDL must match the migration verbatim, and the
migration must chain onto the single Alembic head."""

from __future__ import annotations

import re
from pathlib import Path

from services.computation import repositories as repo

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "20260815_computation_substrate.py"
)


def _const(text: str, name: str) -> str:
    m = re.search(rf'{name}\s*=\s*"""(.*?)"""', text, re.S)
    assert m, f"{name} not found"
    return m.group(1).strip()


def test_ddl_matches_migration_verbatim():
    text = MIGRATION.read_text(encoding="utf-8")
    for name in (
        "COMPUTED_RESULTS_DDL",
        "COMPUTATION_RUNS_DDL",
        "COMPUTATION_RESTATEMENTS_DDL",
    ):
        assert _const(text, name) == getattr(repo, name).strip(), f"{name} drift"


def test_migration_chains_onto_single_head():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "20260814_customer_webhook_delivery_claims"' in text
    assert 'revision = "20260815_computation_substrate"' in text
