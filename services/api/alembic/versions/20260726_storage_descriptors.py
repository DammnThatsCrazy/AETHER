"""storage descriptors — Elastic Data Plane descriptor index (FT-7)

Additive table for the universal storage-descriptor layer. Each row is the
queryable metadata handle (resource_type, locator, sha256 checksum, size,
record count, lineage, codec/format actually used) for one object externalized
to the object store; payload bytes never live in this table. The storage
reconciler (shared/storage/reconciler.py) diffs this index against the object
store to detect missing objects, orphan objects, and checksum drift.

Follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) so repositories.repos.StorageDescriptorRepository and
this migration agree, plus nullable typed convenience columns for indexing.
Lookups run against the JSONB ``data`` field (BaseRepository filters via
``data->>'key'``), so resource_type/locator lookups are backed by expression
indexes. Purely additive; no destructive changes. Fully reversible.

Revision ID: 20260726_storage_descriptors
Revises: 20260725_ai_referral_attribution
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision = "20260726_storage_descriptors"
down_revision = "20260725_ai_referral_attribution"
branch_labels = None
depends_on = None

_TABLES = {
    # Descriptor index for externalized objects. `locator` is the object-store
    # key; `checksum_sha256` pins the stored bytes so hydration and the
    # reconciler can detect corruption/tamper; `codec` records the compression
    # ACTUALLY applied (zstd | gzip | none) — never assumed from policy.
    "storage_descriptors": """
        CREATE TABLE IF NOT EXISTS storage_descriptors (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            resource_type TEXT,
            locator TEXT,
            codec TEXT,
            format TEXT,
            checksum_sha256 TEXT,
            size_bytes BIGINT,
            record_count BIGINT,
            schema_version INTEGER,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)
    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
    # Reconciler and hydration lookups run against the JSONB `data` field
    # (BaseRepository filters via data->>'key'); index those expressions so
    # per-type scans and locator lookups stay fast at object-store scale.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_storage_descriptors_resource_type "
        "ON storage_descriptors ((data->>'resource_type'));"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_storage_descriptors_locator "
        "ON storage_descriptors ((data->>'locator'));"
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
