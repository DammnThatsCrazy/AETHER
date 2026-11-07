"""Run the repository contract against Postgres when ``AGENT_LINEAGE_TEST_DSN`` is set."""
from __future__ import annotations

import importlib.util
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261105_principal_agent_lineage.py"
)
DSN = os.environ.get("AGENT_LINEAGE_TEST_DSN")


def _migration_statements() -> tuple[list[str], list[str]]:
    """Capture the migration's real SQL instead of duplicating its schema here."""
    source = MIGRATION.read_text()
    statements: dict[str, list[str]] = {"up": [], "down": []}

    class _Op:
        current = "up"

        @staticmethod
        def execute(sql: str) -> None:
            statements[_Op.current].append(sql)

    spec = importlib.util.spec_from_file_location("lineage_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    import sys
    import types

    alembic = types.ModuleType("alembic")
    alembic.op = _Op
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = alembic
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            del sys.modules["alembic"]
    module.op = _Op
    _Op.current = "up"
    module.upgrade()
    _Op.current = "down"
    module.downgrade()
    assert source
    return statements["up"], statements["down"]


@asynccontextmanager
async def migrated_pool():
    if not DSN:
        pytest.skip("AGENT_LINEAGE_TEST_DSN not set")
    import asyncpg

    up, down = _migration_statements()
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    try:
        async with pool.acquire() as conn:
            for sql in down:
                await conn.execute(sql)
            for sql in up:
                await conn.execute(sql)
        yield pool
    finally:
        await pool.close()
