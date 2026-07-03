"""Semantic-sentiment Silver and Gold fact tables.

Revision ID: 20260702_semantic_sentiment
Revises: 20260702_delivery_infra
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260702_semantic_sentiment"
down_revision = "20260702_delivery_infra"
branch_labels = None
depends_on = None


def _fact_table(name: str) -> None:
    op.create_table(
        name,
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
    op.create_index(f"idx_{name}_tenant_time", name, ["tenant_id", "occurred_at"])
    op.create_index(f"idx_{name}_tenant_subject", name, ["tenant_id", "subject_ref"])
    op.create_index(f"idx_{name}_tenant_campaign", name, ["tenant_id", "campaign_id"])
    op.execute(
        f"""CREATE UNIQUE INDEX idx_{name}_idempotency
            ON {name} (tenant_id, (data->>'idempotency_key'))
            WHERE data->>'idempotency_key' IS NOT NULL"""
    )


def upgrade() -> None:
    for table in [
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
    ]:
        _fact_table(table)


def downgrade() -> None:
    for table in reversed(
        [
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
    ):
        op.drop_table(table)
