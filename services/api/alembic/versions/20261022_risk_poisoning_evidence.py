"""Persist tenant-scoped Risk360 poisoning evidence and lifecycle history.

Revision ID: 20261022_risk_poisoning_evidence
Revises: 20261022_execution_approval_decisions
Create Date: 2026-10-22

The risk subsystem owns canonical detector records; Risk360 only reads them.
The JSONB payload holds the validated versioned contract while tenant_id is a
durable, indexed scope column used by every exact read and lifecycle update.
"""

from __future__ import annotations

from alembic import op

revision = "20261022_risk_poisoning_evidence"
down_revision = "20261022_execution_approval_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_poisoning_evidence (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        -- The read orders by recorded_at::timestamptz for chronological
        -- correctness. PostgreSQL cannot index that JSONB text cast because
        -- text-to-timestamptz depends on the session TimeZone setting.
        CREATE INDEX IF NOT EXISTS ix_risk_poisoning_evidence_tenant_subject
            ON risk_poisoning_evidence (
                tenant_id,
                (data->>'subject_kind'),
                (data->>'subject_id'),
                id ASC
            );
        CREATE INDEX IF NOT EXISTS ix_risk_poisoning_evidence_tenant_source_subject
            ON risk_poisoning_evidence (
                tenant_id,
                (data->>'source_id'),
                (data->>'subject_kind'),
                (data->>'subject_id')
            );
        CREATE UNIQUE INDEX IF NOT EXISTS uix_risk_poisoning_evidence_tenant_predecessor
            ON risk_poisoning_evidence (
                tenant_id,
                (data->>'supersedes_evidence_id')
            )
            WHERE data->>'supersedes_evidence_id' IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_poisoning_evidence")
