"""silver import facts — Silver projection of committed tenant imports

Creates ``silver_import_facts``, the Silver-layer analytical projection of the
Tenant Import Engine's committed primitive records (one row per commit/file/row/
primitive). Populated inline by ``services/silver/projectors/import_projector.py``
from the import commit; ``SilverFactWriter`` inserts with
``ON CONFLICT DO NOTHING`` for idempotent replay.

Shape mirrors the common Silver-fact columns, except ``source_event_id`` is
``TEXT`` (an import fact synthesizes a deterministic id — it has no SDK message
UUID). The unique index on ``(tenant_id, idempotency_key)`` gives idempotent
replay; a re-commit/replay uses a fresh commit id, so its keys differ.

Revision ID: 20260720_silver_import_facts
Revises: 20260719_import_commit
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op

revision = "20260720_silver_import_facts"
down_revision = "20260719_import_commit"
branch_labels = None
depends_on = None

SILVER_IMPORT_FACTS_DDL = """
CREATE TABLE IF NOT EXISTS silver_import_facts (
    fact_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    source_event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    privacy_class TEXT NOT NULL DEFAULT 'behavioral',
    idempotency_key TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    commit_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    mapping_version INTEGER,
    primitive TEXT,
    row_index INTEGER,
    bronze_source_tag TEXT,
    bronze_record_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, fact_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS silver_import_facts_idem
    ON silver_import_facts (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_silver_import_facts_import
    ON silver_import_facts (tenant_id, import_id);
CREATE INDEX IF NOT EXISTS ix_silver_import_facts_commit
    ON silver_import_facts (tenant_id, commit_id);
"""


def upgrade() -> None:
    op.execute(SILVER_IMPORT_FACTS_DDL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_silver_import_facts_commit")
    op.execute("DROP INDEX IF EXISTS ix_silver_import_facts_import")
    op.execute("DROP INDEX IF EXISTS silver_import_facts_idem")
    op.execute("DROP TABLE IF EXISTS silver_import_facts")
