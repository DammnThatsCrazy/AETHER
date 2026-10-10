"""Semantic replay jobs — durable historical reprocessing bookkeeping.

Backs the real ``POST /v1/semantic/reprocess`` replay (replacing the 501 stub):
tenant-scoped jobs with dry-run, event-family/time/model filters, and durable
progress so runs can be inspected, paused, resumed and cancelled.

Additive + reversible.

Revision ID: 20260732_semantic_replay
Revises: 20260731_semantic_productization
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260732_semantic_replay"
down_revision = "20260731_semantic_productization"
branch_labels = None
depends_on = None

# Kept as a list constant so the storage-policy coverage gate discovers the table.
_CONTROL_TABLES = ["semantic_replay_jobs"]


def upgrade() -> None:
    table = _CONTROL_TABLES[0]
    op.create_table(
        table,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("filters", JSONB(), nullable=False, server_default="{}"),
        sa.Column("progress", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_semantic_replay_jobs_tenant_status", table, ["tenant_id", "status"])


def downgrade() -> None:
    table = _CONTROL_TABLES[0]
    op.drop_index("idx_semantic_replay_jobs_tenant_status", table_name=table)
    op.drop_table(table)
