"""Persist exact catalog-keyed cart and checkout Silver observations.

Revision ID: 20261024_commerce_flow_facts
Revises: 20261024_merge_360_wave_heads
"""

from __future__ import annotations

from alembic import op


revision = "20261024_commerce_flow_facts"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS silver_commerce_flow_facts (
            fact_id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            source_event_id UUID NOT NULL,
            source_event_type TEXT NOT NULL,
            actor_id TEXT,
            user_id TEXT,
            anonymous_id TEXT,
            org_id TEXT,
            occurred_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            consent_snapshot_id TEXT,
            privacy_class TEXT NOT NULL DEFAULT 'behavioral',
            idempotency_key TEXT,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            subject_kind TEXT NOT NULL CHECK (subject_kind IN ('product', 'offer')),
            subject_id TEXT NOT NULL,
            cart_id TEXT,
            checkout_id TEXT,
            flow_event_type TEXT NOT NULL,
            PRIMARY KEY (tenant_id, fact_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS silver_commerce_flow_facts_source_event
            ON silver_commerce_flow_facts (tenant_id, source_event_id);
        CREATE INDEX IF NOT EXISTS silver_commerce_flow_facts_subject
            ON silver_commerce_flow_facts
            (tenant_id, subject_kind, subject_id, occurred_at DESC);
        CREATE INDEX IF NOT EXISTS silver_commerce_flow_facts_user
            ON silver_commerce_flow_facts (tenant_id, user_id)
            WHERE user_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_commerce_flow_facts_actor
            ON silver_commerce_flow_facts (tenant_id, actor_id)
            WHERE actor_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS silver_commerce_flow_facts")
