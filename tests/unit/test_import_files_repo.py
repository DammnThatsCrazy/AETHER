"""Import-file BYTEA repository — DDL parity + tenant-scoped byte I/O.

The repo owns a runtime copy of ``IMPORT_FILES_DDL`` (the alembic versions dir
is not importable). This test fails if that copy drifts from the migration, and
exercises the store/read/checksum/tenant-isolation semantics.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from contextlib import contextmanager  # noqa: E402

from repositories.import_files import (  # noqa: E402
    IMPORT_FILES_DDL,
    get_import_file_repository,
)

MIGRATION_PATH = BACKEND / "alembic" / "versions" / "20260718_import_engine.py"

TENANT = "t-files"


@contextmanager
def raises_named(*names: str):
    """Assert an exception whose class NAME is in ``names`` (identity-agnostic,
    so the suite's ``sys.modules`` churn can't spuriously fail the match)."""
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        yield excinfo
    got = type(excinfo.value).__name__
    assert got in names, f"expected one of {names}, got {got}: {excinfo.value}"


@pytest.fixture()
def repo():
    r = get_import_file_repository()
    r._store.clear()
    return r


def test_ddl_parity_with_migration():
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    match = re.search(r'IMPORT_FILES_DDL = """\n(.*?)"""', migration, re.DOTALL)
    assert match, "migration lost its IMPORT_FILES_DDL constant"
    assert match.group(1).strip() == IMPORT_FILES_DDL.strip()


def test_ddl_shape():
    assert "CREATE TABLE IF NOT EXISTS import_files" in IMPORT_FILES_DDL
    assert "content BYTEA" in IMPORT_FILES_DDL
    assert "sha256 TEXT NOT NULL" in IMPORT_FILES_DDL
    assert "ix_import_files_tenant_import" in IMPORT_FILES_DDL


async def test_put_get_verify(repo):
    content = b"email,amount\nalice@example.com,10\n"
    stored = await repo.put(
        TENANT, import_id="imp1", filename="d.csv", content=content, content_type="text/csv"
    )
    assert stored["size_bytes"] == len(content)
    meta, got = await repo.get_content(TENANT, stored["id"])
    assert got == content
    assert await repo.verify(TENANT, stored["id"]) is True
    files = await repo.list_for_import(TENANT, "imp1")
    assert len(files) == 1 and "content" not in files[0]


async def test_tenant_isolation(repo):
    stored = await repo.put(
        TENANT, import_id="imp1", filename="d.csv", content=b"x", content_type="text/csv"
    )
    with raises_named("NotFoundError"):
        await repo.get_meta("other", stored["id"])
    with raises_named("NotFoundError"):
        await repo.get_content("other", stored["id"])


async def test_oversize_rejected(repo):
    from repositories.import_files import MAX_IMPORT_FILE_BYTES

    with raises_named("BadRequestError"):
        await repo.put(
            TENANT, import_id="imp1", filename="big",
            content=b"x" * (MAX_IMPORT_FILE_BYTES + 1), content_type="text/csv",
        )
