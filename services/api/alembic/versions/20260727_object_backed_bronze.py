"""object-backed bronze — externalized-payload markers + storage legal holds (FT-8)

Additive schema for object-backed Bronze compaction and the cross-store
storage lifecycle:

- ``bronze_sdk_events`` gains two nullable-safe marker columns the compactor
  (shared/storage/compaction.py) flips when a row's payload is packed into an
  externalized object: ``payload_externalized`` (defaults FALSE — every
  existing row keeps its hot payload) and ``payload_descriptor_id`` (the
  storage_descriptors row holding the object's locator/checksum). All typed
  searchable columns are untouched — compaction never deletes hot metadata.
  A partial index backs the compaction candidate scan (cold rows with a hot
  payload) and a descriptor index backs hydration/lifecycle row lookups.

- ``storage_legal_holds`` — legal holds over storage-plane data. Active holds
  block the lifecycle's deletion paths (retention sweeps and DSR erasure in
  shared/storage/lifecycle.py) until released. Follows the BaseRepository
  shape (id TEXT PK, data JSONB, tenant_id, created_at, updated_at) so
  repositories.repos.StorageLegalHoldRepository and this migration agree,
  plus nullable typed convenience columns for indexing. Lookups run against
  the JSONB ``data`` field (BaseRepository filters via ``data->>'key'``), so
  the status lookup is backed by an expression index.

Purely additive; no destructive changes. Fully reversible.

Revision ID: 20260727_object_backed_bronze
Revises: 20260726_storage_descriptors
Create Date: 2026-07-27
"""

from __future__ import annotations

from alembic import op

revision = "20260727_object_backed_bronze"
down_revision = "20260726_storage_descriptors"
branch_labels = None
depends_on = None

_TABLES = {
    # Legal holds over storage-plane data. `resource_type` "" scopes the hold
    # to every type; `subject_ref` "" to every subject. `status` is
    # active | released — active holds fail-closed block retention + DSR
    # deletion in shared/storage/lifecycle.py until released.
    "storage_legal_holds": """
        CREATE TABLE IF NOT EXISTS storage_legal_holds (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            resource_type TEXT,
            subject_ref TEXT,
            status TEXT,
            reason TEXT,
            placed_by TEXT,
            placed_at TIMESTAMPTZ,
            released_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}

# Marker columns the compactor flips after a row's payload is externalized.
# ADD COLUMN IF NOT EXISTS keeps the migration correct whether the table came
# from the 20260724_ingestion_v2 migration or a runtime auto-create.
_BRONZE_MARKER_COLUMNS = {
    "payload_externalized": "BOOLEAN NOT NULL DEFAULT FALSE",
    "payload_descriptor_id": "TEXT",
}


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)
    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
    # Hold checks filter on data->>'status' (BaseRepository JSONB filters).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_storage_legal_holds_status "
        "ON storage_legal_holds ((data->>'status'));"
    )

    for column, ddl_type in _BRONZE_MARKER_COLUMNS.items():
        op.execute(
            f"ALTER TABLE bronze_sdk_events ADD COLUMN IF NOT EXISTS {column} {ddl_type};"
        )
    # Compaction candidate scan: cold rows whose payload is still hot. Partial
    # index keeps it cheap at Bronze scale (externalized rows drop out).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bronze_sdk_events_compaction "
        "ON bronze_sdk_events (received_at) "
        "WHERE payload_externalized = FALSE;"
    )
    # Hydration + lifecycle lookups: rows referencing one descriptor.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bronze_sdk_events_payload_descriptor "
        "ON bronze_sdk_events (payload_descriptor_id) "
        "WHERE payload_descriptor_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_bronze_sdk_events_payload_descriptor;")
    op.execute("DROP INDEX IF EXISTS ix_bronze_sdk_events_compaction;")
    for column in _BRONZE_MARKER_COLUMNS:
        op.execute(f"ALTER TABLE bronze_sdk_events DROP COLUMN IF EXISTS {column};")
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
