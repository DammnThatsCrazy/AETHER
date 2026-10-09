"""Fence concurrent v2 provider raw-revision inserts at the Bronze boundary.

Revision ID: 20261003_provider_raw_revision_unique
Revises: 20261002_provider_object_refs
Create Date: 2026-10-03

V1 Bronze rows retain their historical keys and are not rehashed. A v2 raw
envelope carries a tenant-scoped source account/object/revision digest as its
Bronze provider_record_id. The partial unique index makes a concurrent retry
of that revision fail before a second immutable raw row can be created.
Callers can retry the failed attempt and receive the already persisted row.

The table shape matches BaseRepository's lazy JSONB table creation; creating it
here also ensures the unique index exists before any v2 producer is enabled.
"""

from __future__ import annotations

from alembic import op

revision = "20261003_provider_raw_revision_unique"
down_revision = "20261002_provider_object_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bronze_provider_records (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bronze_provider_records_tenant
        ON bronze_provider_records (tenant_id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_bronze_provider_raw_v2_revision
        ON bronze_provider_records (tenant_id, (data->>'idempotency_key'))
        WHERE data->>'schema_version' = '2'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_bronze_provider_raw_v2_revision")
