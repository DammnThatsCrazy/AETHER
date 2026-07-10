"""Database checks for the staging preflight gate.

Three checks against the live database named by DATABASE_URL:

- ``db:connect``            asyncpg connect + ``SELECT 1``
- ``db:migrations-current`` alembic head revision (alembic.script.ScriptDirectory
                            over "Backend Architecture/aether-backend/alembic")
                            vs ``SELECT version_num FROM alembic_version``
- ``db:table-shape``        migration-vs-runtime column parity. This repo has a
                            known divergence class: BaseRepository
                            (repositories/repos.py) auto-creates JSONB tables
                            with a ``data`` column, while some early migrations
                            created ``payload`` columns instead. The parity
                            migration alembic/versions/20260713_platform_control_plane.py
                            pins the runtime shape; this check catches databases
                            whose tables drifted from it.

All three SKIP in ``--dry-run`` (no live services are touched).
"""

from __future__ import annotations

import re
from pathlib import Path

from .preflight_results import CheckResult, failed, passed, skipped

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_DIR = ROOT / "Backend Architecture" / "aether-backend" / "alembic"

CHECK_NAMES = ("db:connect", "db:migrations-current", "db:table-shape")

MIGRATE_REMEDIATION = (
    'cd "Backend Architecture/aether-backend" && alembic upgrade head '
    "(with DATABASE_URL exported)"
)

# Runtime-required columns per table. identity_subjects / notification_inbox
# are BaseRepository JSONB tables (must expose ``data``); jobs is a direct-SQL
# table whose claim/lease sweep paths require ``status`` and
# ``lease_expires_at`` (see alembic/versions/20260713_platform_control_plane.py).
REQUIRED_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "identity_subjects": ("data",),
    "notification_inbox": ("data",),
    "jobs": ("status", "lease_expires_at"),
}

TABLE_SHAPE_REMEDIATION = (
    "run the migration chain to head (alembic upgrade head); if the table exists "
    "with the wrong shape, the migrations have diverged from the runtime shape — "
    "add a parity migration matching repositories/repos.py::BaseRepository and "
    "alembic/versions/20260713_platform_control_plane.py instead of editing "
    "tables by hand"
)


def normalize_dsn(url: str) -> str:
    """Normalise SQLAlchemy-style driver prefixes for asyncpg.connect
    (mirrors alembic/env.py)."""
    url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)
    url = re.sub(r"^asyncpg://", "postgresql://", url)
    return url


def get_head_revision(alembic_dir: Path = ALEMBIC_DIR) -> str:
    """Resolve the alembic head revision from the migration scripts on disk."""
    from alembic.script import ScriptDirectory

    return ScriptDirectory(str(alembic_dir)).get_current_head()


async def run_db_checks(
    env: dict,
    *,
    dry_run: bool = False,
    alembic_dir: Path = ALEMBIC_DIR,
) -> list[CheckResult]:
    if dry_run:
        return [
            skipped(name, "dry-run: live database checks are not executed")
            for name in CHECK_NAMES
        ]

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        return [
            failed(
                name,
                "DATABASE_URL is not set in the candidate environment",
                "set DATABASE_URL (see env:database-url)",
            )
            for name in CHECK_NAMES
        ]

    try:
        import asyncpg
    except ImportError as exc:
        return [
            failed(
                name,
                f"asyncpg is not installed: {exc}",
                "pip install -e '.[backend]' (or pip install asyncpg)",
            )
            for name in CHECK_NAMES
        ]

    results: list[CheckResult] = []
    try:
        conn = await asyncpg.connect(normalize_dsn(database_url), timeout=10)
    except Exception as exc:
        results.append(failed(
            "db:connect",
            f"connect failed: {exc}",
            "verify DATABASE_URL credentials/host and the network path to the staging database",
        ))
        for name in CHECK_NAMES[1:]:
            results.append(failed(
                name, "not checked: database connection failed", "fix db:connect first"
            ))
        return results

    try:
        # -- db:connect ------------------------------------------------------
        try:
            value = await conn.fetchval("SELECT 1")
            if value == 1:
                results.append(passed("db:connect", "SELECT 1 succeeded"))
            else:
                results.append(failed(
                    "db:connect",
                    f"SELECT 1 returned {value!r}",
                    "verify DATABASE_URL points at a healthy PostgreSQL instance",
                ))
        except Exception as exc:
            results.append(failed(
                "db:connect",
                f"SELECT 1 failed: {exc}",
                "verify DATABASE_URL points at a healthy PostgreSQL instance",
            ))

        # -- db:migrations-current --------------------------------------------
        try:
            head = get_head_revision(alembic_dir)
        except Exception as exc:
            results.append(failed(
                "db:migrations-current",
                f"could not resolve alembic head revision: {exc}",
                "pip install alembic and verify "
                '"Backend Architecture/aether-backend/alembic/versions" is intact',
            ))
        else:
            try:
                current = await conn.fetchval("SELECT version_num FROM alembic_version")
            except asyncpg.exceptions.UndefinedTableError:
                results.append(failed(
                    "db:migrations-current",
                    "alembic_version table is missing — migrations have never "
                    "been applied to this database",
                    MIGRATE_REMEDIATION,
                ))
            except Exception as exc:
                results.append(failed(
                    "db:migrations-current",
                    f"could not read alembic_version: {exc}",
                    MIGRATE_REMEDIATION,
                ))
            else:
                if current == head:
                    results.append(passed(
                        "db:migrations-current", f"database is at head revision {head}"
                    ))
                else:
                    results.append(failed(
                        "db:migrations-current",
                        f"database at revision {current!r}, alembic head is {head!r}",
                        MIGRATE_REMEDIATION,
                    ))

        # -- db:table-shape ----------------------------------------------------
        problems: list[str] = []
        try:
            for table in sorted(REQUIRED_TABLE_COLUMNS):
                required = REQUIRED_TABLE_COLUMNS[table]
                rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = $1",
                    table,
                )
                present = {row["column_name"] for row in rows}
                if not present:
                    problems.append(f"table '{table}' is missing")
                    continue
                missing_cols = [c for c in required if c not in present]
                if missing_cols:
                    problems.append(
                        f"table '{table}' is missing column(s): {', '.join(missing_cols)}"
                    )
        except Exception as exc:
            results.append(failed(
                "db:table-shape",
                f"information_schema query failed: {exc}",
                "verify the DATABASE_URL role can read information_schema",
            ))
        else:
            if problems:
                results.append(failed(
                    "db:table-shape",
                    "; ".join(problems),
                    TABLE_SHAPE_REMEDIATION,
                ))
            else:
                results.append(passed(
                    "db:table-shape",
                    "identity_subjects/notification_inbox expose 'data'; "
                    "jobs exposes 'status' and 'lease_expires_at'",
                ))
    finally:
        await conn.close()

    return results
