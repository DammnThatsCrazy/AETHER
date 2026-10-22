"""Append-only semantic memory records with tenant and subject indexes.

Revision ID: 20261021_semantic_memory_records
Revises: 20261021_commerce_product_offer_catalog
Create Date: 2026-10-21

The new authority uses the generic semantic fact row shape. Memory payloads
remain JSONB domain records; tenant, subject, source, and time are indexed
columns used by the semantic-intelligence repository and its rights/retention
handlers.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261021_semantic_memory_records"
down_revision = "20261021_commerce_product_offer_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_memory_records",
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
        "idx_semantic_memory_records_tenant_subject",
        "semantic_memory_records",
        ["tenant_id", "subject_ref"],
    )
    op.create_index(
        "idx_semantic_memory_records_tenant_time",
        "semantic_memory_records",
        ["tenant_id", "occurred_at", "id"],
    )
    op.create_index(
        "idx_semantic_memory_records_tenant_source_event",
        "semantic_memory_records",
        ["tenant_id", "source_event_id"],
    )
    op.execute(
        """CREATE UNIQUE INDEX idx_semantic_memory_records_idempotency
           ON semantic_memory_records (tenant_id, (data->>'idempotency_key'))
           WHERE data->>'idempotency_key' IS NOT NULL"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_semantic_memory_records_idempotency")
    op.drop_index(
        "idx_semantic_memory_records_tenant_source_event",
        table_name="semantic_memory_records",
    )
    op.drop_index(
        "idx_semantic_memory_records_tenant_time",
        table_name="semantic_memory_records",
    )
    op.drop_index(
        "idx_semantic_memory_records_tenant_subject",
        table_name="semantic_memory_records",
    )
    op.drop_table("semantic_memory_records")
