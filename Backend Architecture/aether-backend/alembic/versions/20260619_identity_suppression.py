"""identity suppression rules table

Revision ID: 20260619_identity_suppression
Revises: 20260612_identity_resolution_tables
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op

revision = "20260619_identity_suppression"
down_revision = "20260612_identity_resolution_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── identity_suppression_rules ─────────────────────────────────────────
    # Operator-created rules that block a specific identifier hash from ever
    # being used to link identities. Append-only semantics: rules are revoked
    # (revoked_at set) rather than deleted.
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_suppression_rules (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        identifier_hash TEXT NOT NULL,
        identifier_type TEXT NOT NULL,
        subject_id TEXT,
        rule_type TEXT NOT NULL DEFAULT 'suppress',
        reason TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT 'system',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ,
        revoked_at TIMESTAMPTZ,
        data JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_suppression_tenant_hash "
        "ON identity_suppression_rules (tenant_id, identifier_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_suppression_tenant_type "
        "ON identity_suppression_rules (tenant_id, identifier_type)"
    )
    # Unique active rule per tenant+type+hash (partial index, revoked excluded)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_identity_suppression_tenant_type_hash "
        "ON identity_suppression_rules (tenant_id, identifier_type, identifier_hash) "
        "WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS identity_suppression_rules")
