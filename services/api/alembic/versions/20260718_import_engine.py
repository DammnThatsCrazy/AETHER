"""tenant import engine: files (BYTEA) + session/schema/mapping/validation tables

Creates the durable storage for the Tenant Import Engine's ingest → analyze →
map → validate half:

- ``import_files`` — the uploaded bytes (BYTEA), a sha256 checksum, size, and
  MIME. Direct-SQL (BYTEA is inexpressible through the JSONB BaseRepository
  API), so ``repositories/import_files.py`` owns a string-identical copy of
  ``IMPORT_FILES_DDL`` for runtime auto-creation, and
  ``tests/unit/test_import_files_repo.py`` asserts parity.
- ``import_sessions`` / ``import_schemas`` / ``import_mappings`` /
  ``import_templates`` / ``import_validations`` / ``import_row_errors`` —
  JSONB BaseRepository-shaped tables (``id, data JSONB, tenant_id,
  created_at, updated_at``). The shape below is byte-for-byte what
  ``repositories/repos.py::BaseRepository._ensure_table`` auto-creates, so a
  deploy that runs ``alembic upgrade head`` and a runtime that lazily
  auto-creates converge on the same schema (guards the migration/runtime
  shape-split class of bug).

The commit / replay / rollback tables land in a later migration alongside the
code that writes them — this migration matches the upload/analyze/validate
code shipped in the same change.

Revision ID: 20260718_import_engine
Revises: 20260716_measurement_integrity
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op

revision = "20260718_import_engine"
down_revision = "20260716_measurement_integrity"
branch_labels = None
depends_on = None

# Must stay string-identical to IMPORT_FILES_DDL in
# repositories/import_files.py (parity-tested).
IMPORT_FILES_DDL = """
CREATE TABLE IF NOT EXISTS import_files (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content BYTEA,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_import_files_tenant_import
    ON import_files (tenant_id, import_id);
"""

# BaseRepository-shaped JSONB tables. Kept identical to
# BaseRepository._ensure_table so alembic and runtime auto-create agree.
_JSONB_TABLES = (
    "import_sessions",
    "import_schemas",
    "import_mappings",
    "import_templates",
    "import_validations",
    "import_row_errors",
)


def _jsonb_ddl(name: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {name} (
        id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{{}}',
        tenant_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_{name}_tenant ON {name} (tenant_id);
    """


def upgrade() -> None:
    op.execute(IMPORT_FILES_DDL)
    for name in _JSONB_TABLES:
        op.execute(_jsonb_ddl(name))


def downgrade() -> None:
    for name in reversed(_JSONB_TABLES):
        op.execute(f"DROP INDEX IF EXISTS idx_{name}_tenant")
        op.execute(f"DROP TABLE IF EXISTS {name}")
    op.execute("DROP INDEX IF EXISTS ix_import_files_tenant_import")
    op.execute("DROP TABLE IF EXISTS import_files")
