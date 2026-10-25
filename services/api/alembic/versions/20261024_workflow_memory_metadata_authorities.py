"""Persist registered Workflow360 definitions and Memory360 metadata.

Revision ID: 20261024_workflow_memory_metadata_authorities
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

These append-only JSONB authority tables share the semantic fact storage shape
while retaining tenant, subject, source, and time indexes for bounded reads and
rights propagation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261024_workflow_memory_metadata_authorities"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None

_TABLES = (
    "workflow_definition_revisions",
    "semantic_context_cards",
    "semantic_embedding_metadata",
)


def _create_fact_table(table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("campaign_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        f"idx_{table}_tenant_subject",
        table,
        ["tenant_id", "subject_ref", "occurred_at", "id"],
    )
    op.create_index(f"idx_{table}_tenant_time", table, ["tenant_id", "occurred_at", "id"])
    op.execute(
        f"""CREATE UNIQUE INDEX idx_{table}_idempotency
            ON {table} (tenant_id, (data->>'idempotency_key'))
            WHERE data->>'idempotency_key' IS NOT NULL"""
    )


def upgrade() -> None:
    for table in _TABLES:
        _create_fact_table(table)
    op.execute(
        """CREATE UNIQUE INDEX idx_workflow_definition_revisions_tenant_version
           ON workflow_definition_revisions
              (tenant_id, subject_ref, (data->>'revision'))"""
    )
    op.execute(
        """CREATE INDEX idx_workflow_definition_revisions_latest
           ON workflow_definition_revisions (tenant_id, subject_ref, occurred_at DESC)"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_definition_revisions_latest")
    op.execute("DROP INDEX IF EXISTS idx_workflow_definition_revisions_tenant_version")
    for table in reversed(_TABLES):
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_idempotency")
        op.drop_index(f"idx_{table}_tenant_time", table_name=table)
        op.drop_index(f"idx_{table}_tenant_subject", table_name=table)
        op.drop_table(table)
