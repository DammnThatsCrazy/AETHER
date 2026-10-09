"""Persist canonical data-rights grants and append-only lifecycle events.

Revision ID: 20261004_data_rights_grants
Revises: a900aa5fa8ff
Create Date: 2026-10-04

The table layout matches BaseRepository's JSONB record convention while the
repository uses tenant-scoped transactional writes for grant/event changes.
"""
from __future__ import annotations

from alembic import op

revision = "20261004_data_rights_grants"
down_revision = "a900aa5fa8ff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS data_rights_grants (
               id TEXT PRIMARY KEY,
               data JSONB NOT NULL DEFAULT '{}'::jsonb,
               tenant_id TEXT NOT NULL,
               created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
               updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
           )"""
    )
    op.execute(
        """CREATE INDEX IF NOT EXISTS idx_data_rights_grants_tenant
           ON data_rights_grants (tenant_id)"""
    )
    op.execute(
        """CREATE INDEX IF NOT EXISTS ix_data_rights_grants_tenant_source
           ON data_rights_grants (tenant_id, (data->>'source_id'))"""
    )
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_data_rights_grants_id_tenant
           ON data_rights_grants (id, tenant_id)"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS data_rights_grant_events (
               event_id TEXT PRIMARY KEY,
               grant_ref TEXT NOT NULL,
               tenant_id TEXT NOT NULL,
               event_type TEXT NOT NULL CHECK (event_type IN ('created', 'revoked')),
               actor TEXT NOT NULL,
               reason TEXT NOT NULL,
               occurred_at TIMESTAMPTZ NOT NULL,
               data JSONB NOT NULL,
               FOREIGN KEY (grant_ref, tenant_id)
                   REFERENCES data_rights_grants(id, tenant_id) ON DELETE RESTRICT
           )"""
    )
    op.execute(
        """CREATE INDEX IF NOT EXISTS ix_data_rights_grant_events_scope
           ON data_rights_grant_events (tenant_id, grant_ref, occurred_at)"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION reject_data_rights_grant_event_mutation()
           RETURNS trigger LANGUAGE plpgsql AS $$
           BEGIN
               RAISE EXCEPTION 'data_rights_grant_events is append-only';
           END;
           $$"""
    )
    op.execute(
        """CREATE TRIGGER trg_data_rights_grant_events_immutable
           BEFORE UPDATE OR DELETE ON data_rights_grant_events
           FOR EACH ROW EXECUTE FUNCTION reject_data_rights_grant_event_mutation()"""
    )


def downgrade() -> None:
    # Grant and lifecycle records are canonical rights evidence; code rollback
    # must not delete authorizations or their audit history.
    pass
