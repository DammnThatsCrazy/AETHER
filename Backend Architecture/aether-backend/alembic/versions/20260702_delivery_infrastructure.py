"""Delivery infrastructure — 8 tables for durable provider dispatch.

Tables (created in FK-dependency order):
  delivery_intents, delivery_jobs, delivery_attempts, provider_receipts,
  external_resource_links, external_outcome_events, webhook_inbox,
  connector_cursors

Revision ID: 20260702_delivery_infra
Revises: ca001b2c3d4e
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260702_delivery_infra"
down_revision = "ca001b2c3d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── delivery_intents ─────────────────────────────────────────────────────
    op.create_table(
        "delivery_intents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_delivery_intents_tenant", "delivery_intents", ["tenant_id"]
    )
    op.create_index(
        "idx_delivery_intents_status",
        "delivery_intents",
        [sa.text("(data->>'status')")],
    )
    op.execute(
        """CREATE UNIQUE INDEX idx_delivery_intents_idempotency
           ON delivery_intents ((data->>'idempotency_key'))
           WHERE data->>'idempotency_key' IS NOT NULL"""
    )

    # ── delivery_jobs ────────────────────────────────────────────────────────
    op.create_table(
        "delivery_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_delivery_jobs_tenant", "delivery_jobs", ["tenant_id"])
    op.create_index(
        "idx_delivery_jobs_state",
        "delivery_jobs",
        [sa.text("(data->>'state')")],
    )
    op.create_index(
        "idx_delivery_jobs_intent",
        "delivery_jobs",
        [sa.text("(data->>'intent_id')")],
    )
    # Partial index for the worker poll query — only runnable jobs.
    #
    # Two corrections against the original form, which was invalid Postgres and
    # therefore made this migration — and `alembic upgrade head` from a clean
    # database — fail outright:
    #   1. a cast expression in an index column list needs its own parentheses;
    #      bare `(expr)::type ASC` is a syntax error.
    #   2. `text::timestamptz` is STABLE, not IMMUTABLE (it depends on the
    #      TimeZone setting), so it cannot appear in an index expression at all.
    #      `next_attempt_at` is stored as a Z-suffixed ISO-8601 string, which
    #      orders lexicographically exactly as it orders chronologically, so
    #      indexing the raw text preserves the intended poll ordering.
    # `(data->>'priority')::int` is IMMUTABLE and is kept as a cast so numeric
    # priorities do not sort as strings.
    op.execute(
        """CREATE INDEX idx_delivery_jobs_runnable
           ON delivery_jobs (
               ((data->>'priority')::int) ASC,
               (data->>'next_attempt_at') ASC
           )
           WHERE data->>'state' IN ('queued', 'failed')"""
    )

    # ── delivery_attempts ────────────────────────────────────────────────────
    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_delivery_attempts_tenant", "delivery_attempts", ["tenant_id"])
    op.create_index(
        "idx_delivery_attempts_job",
        "delivery_attempts",
        [sa.text("(data->>'job_id')")],
    )

    # ── provider_receipts ────────────────────────────────────────────────────
    op.create_table(
        "provider_receipts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_provider_receipts_tenant", "provider_receipts", ["tenant_id"])
    op.create_index(
        "idx_provider_receipts_intent",
        "provider_receipts",
        [sa.text("(data->>'intent_id')")],
    )
    op.create_index(
        "idx_provider_receipts_external",
        "provider_receipts",
        [sa.text("(data->>'external_id')"), sa.text("(data->>'provider_adapter')")],
    )

    # ── external_resource_links ───────────────────────────────────────────────
    op.create_table(
        "external_resource_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_external_resource_links_tenant", "external_resource_links", ["tenant_id"]
    )
    op.create_index(
        "idx_external_resource_links_intent",
        "external_resource_links",
        [sa.text("(data->>'intent_id')")],
    )

    # ── external_outcome_events ───────────────────────────────────────────────
    op.create_table(
        "external_outcome_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_external_outcome_events_tenant", "external_outcome_events", ["tenant_id"]
    )
    op.create_index(
        "idx_external_outcome_events_external_id",
        "external_outcome_events",
        [sa.text("(data->>'external_id')"), sa.text("(data->>'provider')")],
    )

    # ── webhook_inbox ────────────────────────────────────────────────────────
    op.create_table(
        "webhook_inbox",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_webhook_inbox_tenant", "webhook_inbox", ["tenant_id"])
    op.execute(
        """CREATE INDEX idx_webhook_inbox_unprocessed
           ON webhook_inbox ((data->>'provider'))
           WHERE data->>'processed' = 'false'"""
    )

    # ── connector_cursors ────────────────────────────────────────────────────
    op.create_table(
        "connector_cursors",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_connector_cursors_tenant", "connector_cursors", ["tenant_id"])
    op.execute(
        """CREATE UNIQUE INDEX idx_connector_cursors_unique
           ON connector_cursors (tenant_id, (data->>'connector_type'))
           WHERE tenant_id IS NOT NULL"""
    )


def downgrade() -> None:
    # Drop in reverse creation order
    op.drop_table("connector_cursors")
    op.drop_table("webhook_inbox")
    op.drop_table("external_outcome_events")
    op.drop_table("external_resource_links")
    op.drop_table("provider_receipts")
    op.drop_table("delivery_attempts")
    op.drop_table("delivery_jobs")
    op.drop_table("delivery_intents")
