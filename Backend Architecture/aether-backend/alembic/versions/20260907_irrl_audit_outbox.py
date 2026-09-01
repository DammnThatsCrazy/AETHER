"""Atomic IRRL decision-to-audit outbox.

Revision ID: 20260907_irrl_audit_outbox
Revises: 20260906_irrl_evidence_remediation
"""

from __future__ import annotations

from alembic import op

revision = "20260907_irrl_audit_outbox"
down_revision = "20260906_irrl_evidence_remediation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS irrl_rights_audit_outbox (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_irrl_rights_audit_outbox_tenant
            ON irrl_rights_audit_outbox (tenant_id);
        CREATE INDEX IF NOT EXISTS ix_irrl_rights_audit_outbox_status
            ON irrl_rights_audit_outbox ((data->>'status'));
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS irrl_rights_audit_outbox")
