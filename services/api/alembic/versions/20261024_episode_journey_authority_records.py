"""Persist explicit Episode360 links and Journey360 action intents.

Revision ID: 20261024_episode_journey_authority_records
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

Rows are append-only relationship/evidence facts. The referenced execution,
delegation, conversion, attribution, journey, and step authorities remain the
source of truth for their own records.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261024_episode_journey_authority_records"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "episode_journey_authority_records",
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
        "idx_episode_journey_authority_subject_time",
        "episode_journey_authority_records",
        ["tenant_id", "subject_ref", "occurred_at", "id"],
    )
    op.create_index(
        "idx_episode_journey_authority_tenant_time",
        "episode_journey_authority_records",
        ["tenant_id", "occurred_at", "id"],
    )
    op.execute(
        """CREATE UNIQUE INDEX idx_episode_journey_authority_idempotency
           ON episode_journey_authority_records
              (tenant_id, (data->>'idempotency_key'))
           WHERE data->>'idempotency_key' IS NOT NULL"""
    )
    op.execute(
        """CREATE INDEX idx_episode_journey_authority_record_type
           ON episode_journey_authority_records
              (tenant_id, subject_ref, (data->>'record_type'), occurred_at, id)"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_episode_journey_authority_record_type")
    op.execute("DROP INDEX IF EXISTS idx_episode_journey_authority_idempotency")
    op.drop_index(
        "idx_episode_journey_authority_tenant_time",
        table_name="episode_journey_authority_records",
    )
    op.drop_index(
        "idx_episode_journey_authority_subject_time",
        table_name="episode_journey_authority_records",
    )
    op.drop_table("episode_journey_authority_records")
