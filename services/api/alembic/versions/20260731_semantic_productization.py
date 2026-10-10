"""Semantic productization — source-event/stable-hash indexes + review queue.

Adds the lookup indexes the durable semantic repositories, worker and reconciler
rely on (source-event join, supersession by stable hash) to the 20 semantic
Silver/Gold fact tables created by ``20260702_semantic_sentiment``, and creates
the durable ``semantic_review_queue`` table backing the Kyber operator surface.

Additive + reversible; every statement uses IF (NOT) EXISTS so it is safe to
re-run and the fact tables are assumed to already exist.

Revision ID: 20260731_semantic_productization
Revises: 20260730_consent_control_plane_seed
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260731_semantic_productization"
down_revision = "20260730_consent_control_plane_seed"
branch_labels = None
depends_on = None


_FACT_TABLES = [
    "silver_semantic_observations",
    "silver_sentiment_observations",
    "silver_semantic_entity_mentions",
    "silver_semantic_subject_links",
    "silver_semantic_claims",
    "silver_semantic_narrative_facts",
    "silver_semantic_exposure_facts",
    "silver_semantic_adoption_facts",
    "silver_semantic_retransmission_facts",
    "silver_agent_semantic_facts",
    "gold_entity_semantic_state",
    "gold_entity_sentiment_state",
    "gold_relationship_semantic_state",
    "gold_relationship_sentiment_state",
    "gold_campaign_semantic_impact",
    "gold_campaign_sentiment_impact",
    "gold_narrative_state",
    "gold_semantic_episodes",
    "gold_semantic_cascades",
    "gold_agent_alignment_state",
]

# Control-plane tables created by this migration (kept as a list constant so the
# storage-policy coverage gate discovers them alongside the fact tables).
_CONTROL_TABLES = ["semantic_review_queue"]


def upgrade() -> None:
    for table in _FACT_TABLES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_source_event "
            f"ON {table} (tenant_id, source_event_id)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_stable_hash "
            f"ON {table} (tenant_id, (data->>'stable_hash'))"
        )

    review_queue = _CONTROL_TABLES[0]
    op.create_table(
        review_queue,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("queue_type", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_semantic_review_queue_tenant_status", review_queue, ["tenant_id", "status"]
    )
    op.create_index(
        "idx_semantic_review_queue_tenant_type", review_queue, ["tenant_id", "queue_type"]
    )


def downgrade() -> None:
    review_queue = _CONTROL_TABLES[0]
    op.drop_index("idx_semantic_review_queue_tenant_type", table_name=review_queue)
    op.drop_index("idx_semantic_review_queue_tenant_status", table_name=review_queue)
    op.drop_table(review_queue)
    for table in _FACT_TABLES:
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_tenant_stable_hash")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_tenant_source_event")
