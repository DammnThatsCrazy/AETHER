"""tenant import engine: commit + rollback records

Adds the durable record tables for the Import Engine's mutation half — the
commit that stages an approved import into Bronze + the graph, and the
reversible rollback:

- ``import_commits`` — one row per commit attempt: the commit id (also the
  Bronze ``source_tag`` and the graph ``import_commit_id`` lineage handle),
  the mapping version, per-primitive counts, the list of graph edges created
  (so a rollback can revoke exactly them), and the outcome
  (``committed`` / ``partially_committed`` / ``failed``).
- ``import_rollbacks`` — one row per rollback: the commit it reverses, the
  Bronze rows deleted, the graph edges revoked, and a human reason.

Both are BaseRepository-shaped JSONB tables (``id, data JSONB, tenant_id,
created_at, updated_at``) — the shape below is byte-for-byte what
``BaseRepository._ensure_table`` auto-creates, so a deploy that runs
``alembic upgrade head`` and a runtime that lazily auto-creates converge.

Revision ID: 20260719_import_commit
Revises: 20260718_import_engine
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "20260719_import_commit"
down_revision = "20260718_import_engine"
branch_labels = None
depends_on = None

_JSONB_TABLES = (
    "import_commits",
    "import_rollbacks",
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
    for name in _JSONB_TABLES:
        op.execute(_jsonb_ddl(name))


def downgrade() -> None:
    for name in reversed(_JSONB_TABLES):
        op.execute(f"DROP INDEX IF EXISTS idx_{name}_tenant")
        op.execute(f"DROP TABLE IF EXISTS {name}")
