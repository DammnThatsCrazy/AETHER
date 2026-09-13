"""Semantic shadow-mode divergence facts.

Backs the ``semantic.shadow_provider`` candidate-evaluation seam: when the
shadow classifier disagrees with the primary on stance / intent / valence sign,
the service records one divergence fact per (primary observation identity,
candidate model). Mirrors the ``20260702_semantic_sentiment`` fact-table DDL
(JSONB ``data`` payload + partial idempotency index) so
``SemanticFactRepository`` works against it unchanged.

Additive + reversible.

Revision ID: 20260734_semantic_shadow_divergences
Revises: 20260733_canonical_activity_surface
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260734_semantic_shadow_divergences"
down_revision = "20260733_canonical_activity_surface"
branch_labels = None
depends_on = None

# Kept as a list constant so the storage-policy coverage gate discovers the table.
_FACT_TABLES = ["semantic_shadow_divergences"]


def upgrade() -> None:
    table = _FACT_TABLES[0]
    op.create_table(
        table,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("subject_ref", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(f"idx_{table}_tenant_time", table, ["tenant_id", "occurred_at"])
    op.create_index(f"idx_{table}_tenant_subject", table, ["tenant_id", "subject_ref"])
    op.execute(
        f"""CREATE UNIQUE INDEX idx_{table}_idempotency
            ON {table} (tenant_id, (data->>'idempotency_key'))
            WHERE data->>'idempotency_key' IS NOT NULL"""
    )


def downgrade() -> None:
    table = _FACT_TABLES[0]
    op.execute(f"DROP INDEX IF EXISTS idx_{table}_idempotency")
    op.drop_index(f"idx_{table}_tenant_subject", table_name=table)
    op.drop_index(f"idx_{table}_tenant_time", table_name=table)
    op.drop_table(table)
