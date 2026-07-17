"""DDL parity: repositories/graph_mutation_ledger.py duplicates the ledger DDL
from alembic migration 20260729_graph_mutation_ledger.py verbatim (the alembic
versions directory is not an importable package and alembic itself is not a
runtime backend dependency).

These tests AST-extract the migration's module constants — without importing
it, so no alembic install is needed — and assert exact string equality with
the repository's copies. If one of these fails: fix the migration first, then
mirror it in graph_mutation_ledger.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"

MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260729_graph_mutation_ledger.py"
)

from repositories import graph_mutation_ledger  # noqa: E402


def _extract_migration_constants() -> dict:
    """Top-level constant assignments of the migration module, via AST."""
    tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    constants: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    constants[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    continue  # non-literal assignment
    return constants


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revises_object_backed_bronze():
    constants = _extract_migration_constants()
    assert constants["revision"] == "20260729_graph_mutation_ledger"
    assert constants["down_revision"] == "20260727_object_backed_bronze"


def test_ledger_table_ddl_matches_migration():
    constants = _extract_migration_constants()
    assert graph_mutation_ledger.GRAPH_MUTATION_LEDGER_DDL == constants["GRAPH_MUTATION_LEDGER_DDL"]


def test_fact_versions_table_ddl_matches_migration():
    constants = _extract_migration_constants()
    assert graph_mutation_ledger.GRAPH_FACT_VERSIONS_DDL == constants["GRAPH_FACT_VERSIONS_DDL"]


def test_checkpoints_table_ddl_matches_migration():
    constants = _extract_migration_constants()
    assert graph_mutation_ledger.GRAPH_CHECKPOINTS_DDL == constants["GRAPH_CHECKPOINTS_DDL"]


def test_ledger_indexes_match_migration_exactly():
    """Runtime auto-creation (fresh local DB) must match migrated shape."""
    constants = _extract_migration_constants()
    assert graph_mutation_ledger.GRAPH_LEDGER_INDEXES == constants["GRAPH_LEDGER_INDEXES"]


def test_ledger_columns_cover_mutation_record_fields():
    """Every MutationRecord field maps to a ledger column of the same name."""
    from shared.graph.mutation_models import MutationRecord

    ddl = graph_mutation_ledger.GRAPH_MUTATION_LEDGER_DDL
    for field_name in MutationRecord.model_fields:
        assert f"\n    {field_name} " in ddl, f"ledger DDL missing column {field_name!r}"


def test_bitemporal_columns_use_canonical_names():
    from shared.graph.edge_properties import BITEMPORAL_EDGE_PROPERTIES

    for table_ddl in (
        graph_mutation_ledger.GRAPH_MUTATION_LEDGER_DDL,
        graph_mutation_ledger.GRAPH_FACT_VERSIONS_DDL,
    ):
        for name in BITEMPORAL_EDGE_PROPERTIES:
            assert f"\n    {name} " in table_ddl, f"missing bitemporal column {name!r}"
