"""DDL parity: repositories/jobs_repo.py duplicates the jobs-platform DDL
from alembic migration 20260713_platform_control_plane.py verbatim (the
alembic versions directory is not an importable package and alembic itself
is not a runtime backend dependency).

These tests AST-extract the migration's module constants — without importing
it, so no alembic install is needed — and assert exact string equality with
the repository's copies. If one of these fails: fix the migration first,
then mirror it in jobs_repo.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260713_platform_control_plane.py"
)

from repositories import jobs_repo  # noqa: E402


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
                    continue  # non-literal assignment (e.g. dict of Names)
    return constants


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_jobs_table_ddl_matches_migration():
    constants = _extract_migration_constants()
    assert jobs_repo.JOBS_DDL == constants["JOBS_DDL"]


def test_job_events_table_ddl_matches_migration():
    constants = _extract_migration_constants()
    assert jobs_repo.JOB_EVENTS_DDL == constants["JOB_EVENTS_DDL"]


def test_job_schedules_table_ddl_matches_migration():
    constants = _extract_migration_constants()
    assert jobs_repo.JOB_SCHEDULES_DDL == constants["JOB_SCHEDULES_DDL"]


def test_repo_indexes_are_a_subset_of_migration_indexes():
    """Every index the repository auto-creates must exist verbatim in the
    migration's INDEXES list (the migration remains the source of truth)."""
    constants = _extract_migration_constants()
    migration_indexes = set(constants["INDEXES"])
    for idx in jobs_repo.JOBS_INDEXES:
        assert idx in migration_indexes, f"repo-only index not in migration: {idx!r}"


def test_repo_covers_all_jobs_platform_indexes_from_migration():
    """Inverse direction: every migration index touching the three
    jobs-platform tables must be mirrored in the repository so runtime
    auto-creation (fresh local DB) matches migrated production shape."""
    constants = _extract_migration_constants()
    repo_indexes = set(jobs_repo.JOBS_INDEXES)
    for idx in constants["INDEXES"]:
        on_clause = idx.split(" ON ", 1)[1]
        table = on_clause.split(" ", 1)[0].split("(", 1)[0]
        if table in {"jobs", "job_events", "job_schedules"}:
            assert idx in repo_indexes, f"migration index missing from repo: {idx!r}"
