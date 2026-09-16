"""DDL parity: repositories/graph_mutation_ledger.py duplicates the ledger DDL
from alembic migrations verbatim (the alembic versions directory is not an
importable package and alembic itself is not a runtime backend dependency).

``20260729_graph_mutation_ledger.py`` creates the tables;
``20260914_graph_mutation_rights_ref.py`` adds the ``rights_decision_ref``
column additively (the historical migration is never edited in place), and the
composed base + additive DDL is what a fresh database ends up with.

These tests AST-extract the migrations' module constants — without importing
them, so no alembic install is needed — and assert exact string equality with
the repository's copies. If one of these fails: fix the migration first, then
mirror it in graph_mutation_ledger.py.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "services" / "backend"

MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260729_graph_mutation_ledger.py"
)

# Additive ledger DDL applied by
# ``GraphMutationLedgerRepository._ensure_schema`` AFTER the base CREATE TABLE,
# as (migration path, repository constant name) pairs. The historical migration
# is never edited in place, so a new column arrives as its own additive
# migration mirrored verbatim in the repository.
ADDITIVE_MIGRATIONS = (
    (
        BACKEND_ROOT / "alembic" / "versions" / "20260914_graph_mutation_rights_ref.py",
        "GRAPH_MUTATION_LEDGER_RIGHTS_REF_DDL",
    ),
)

from repositories import graph_mutation_ledger  # noqa: E402


def _extract_migration_constants(migration_path: Path = MIGRATION_PATH) -> dict:
    """Top-level constant assignments of the migration module, via AST."""
    tree = ast.parse(migration_path.read_text(encoding="utf-8"))
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


def _ledger_column_names(ddl: str) -> set:
    """Column names declared by one ledger DDL fragment.

    Handles both a ``CREATE TABLE`` body entry (``    name TYPE,``) and an
    additive ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS name TYPE`` clause, so
    the composed DDL a fresh database actually receives can be checked as a
    whole.
    """
    names = set(re.findall(r"\n    ([a-z_][a-z0-9_]*) ", ddl))
    names |= set(re.findall(r"ADD COLUMN IF NOT EXISTS ([a-z_][a-z0-9_]*) ", ddl))
    return names


def _composed_ledger_ddl() -> str:
    """Base CREATE TABLE plus every additive ALTER the repository applies."""
    fragments = [graph_mutation_ledger.GRAPH_MUTATION_LEDGER_DDL]
    fragments.extend(
        getattr(graph_mutation_ledger, constant_name)
        for _, constant_name in ADDITIVE_MIGRATIONS
    )
    return "\n".join(fragments)


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
    """Every MutationRecord field maps to a ledger column of the same name.

    Checked against the COMPOSED ledger DDL (base CREATE TABLE + additive
    migrations), because that is the shape a fresh database ends up with.
    """
    from shared.graph.mutation_models import MutationRecord

    columns = _ledger_column_names(_composed_ledger_ddl())
    for field_name in MutationRecord.model_fields:
        assert field_name in columns, f"ledger DDL missing column {field_name!r}"


def test_additive_ledger_migrations_exist_and_match_repository_constants():
    """Each additive migration's DDL constant is mirrored verbatim in the repo."""
    for migration_path, constant_name in ADDITIVE_MIGRATIONS:
        assert migration_path.is_file(), f"missing migration: {migration_path}"
        constants = _extract_migration_constants(migration_path)
        assert constants["revision"] == migration_path.stem, (
            f"{migration_path.name}: revision id must match the file stem"
        )
        assert constants["down_revision"], (
            f"{migration_path.name}: must chain onto an existing revision"
        )
        assert getattr(graph_mutation_ledger, constant_name) == constants[constant_name], (
            f"{constant_name} drifted from {migration_path.name}"
        )


def test_rights_decision_ref_column_is_additive_and_nullable():
    """The rights ref arrives as a nullable ADD COLUMN — no backfill, no default.

    Every pre-propagation ledger row therefore keeps exactly the shape it had
    (NULL = "no rights gate ran for this write").
    """
    ddl = graph_mutation_ledger.GRAPH_MUTATION_LEDGER_RIGHTS_REF_DDL
    assert "ADD COLUMN IF NOT EXISTS rights_decision_ref TEXT" in ddl
    assert "NOT NULL" not in ddl
    assert "DEFAULT" not in ddl
    assert "rights_decision_ref" in _ledger_column_names(_composed_ledger_ddl())


def test_bitemporal_columns_use_canonical_names():
    from shared.graph.edge_properties import BITEMPORAL_EDGE_PROPERTIES

    for table_ddl in (
        graph_mutation_ledger.GRAPH_MUTATION_LEDGER_DDL,
        graph_mutation_ledger.GRAPH_FACT_VERSIONS_DDL,
    ):
        for name in BITEMPORAL_EDGE_PROPERTIES:
            assert f"\n    {name} " in table_ddl, f"missing bitemporal column {name!r}"
