"""durable account suspension, recovery, and erasure workflow"""

from __future__ import annotations

from alembic import op

revision = "20260813_account_deletion_workflow"
down_revision = "20260813_account_organization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_deletion_workflows (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL,
            recovery_until TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            reauth_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            idempotency_key TEXT NOT NULL,
            storage_results JSONB NOT NULL DEFAULT '{}'::jsonb,
            retry_count INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            erasure_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_account_deletion_retry_count_nonnegative
                CHECK (retry_count >= 0),
            CONSTRAINT uq_account_deletion_tenant_idempotency
                UNIQUE (tenant_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_account_deletion_tenant_status "
        "ON account_deletion_workflows (tenant_id, status, recovery_until)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_account_deletion_due "
        "ON account_deletion_workflows (status, recovery_until)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_retention_stubs (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_account_retention_stubs_workflow "
        "ON account_retention_stubs ((data->>'workflow_id'))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_retention_stubs")
    op.execute("DROP TABLE IF EXISTS account_deletion_workflows")
