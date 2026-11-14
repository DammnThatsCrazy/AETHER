"""Persist tenant-scoped commerce approval decisions and execution links.

Revision ID: 20261022_execution_approval_decisions
Revises: 20261022_journey_handoffs
Create Date: 2026-10-22

ApprovalRequest remains the mutable current lifecycle authority. This table
retains each typed decision event, including its exact execution reference,
for audit and Execution360 reads.
"""
from __future__ import annotations

from alembic import op

revision = "20261022_execution_approval_decisions"
down_revision = "20261022_journey_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_approval_decisions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_commerce_approval_decisions_tenant
            ON commerce_approval_decisions (tenant_id);
        CREATE INDEX IF NOT EXISTS ix_commerce_approval_decisions_execution_time
            ON commerce_approval_decisions
                (tenant_id, (data->>'execution_id'), (data->>'decided_at'));
        CREATE INDEX IF NOT EXISTS ix_commerce_approval_decisions_approval
            ON commerce_approval_decisions (tenant_id, (data->>'approval_id'));
        CREATE INDEX IF NOT EXISTS ix_commerce_approvals_tenant_execution
            ON commerce_approvals (tenant_id, (data->>'execution_id'));
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_commerce_approvals_tenant_execution;")
    op.execute("DROP TABLE IF EXISTS commerce_approval_decisions;")
