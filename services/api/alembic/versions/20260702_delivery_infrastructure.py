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


_DELIVERY_REQUIRED_COLUMNS = ("id", "data", "tenant_id", "created_at", "updated_at")


def _create_table_if_missing(name: str, *columns: sa.Column) -> None:
    """Create a delivery table without destroying a partially provisioned DB.

    Staging databases can contain delivery tables created by an earlier
    canonical-image/bootstrap path even when ``20260702_delivery_infra`` is
    still the next Alembic revision.  A plain ``op.create_table`` then aborts
    the entire migration on ``DuplicateTable``.  Reusing an existing table is
    safe only when it has the generic repository shape this migration owns;
    fail closed on a different shape instead of silently declaring an unknown
    schema compatible.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(name):
        op.create_table(name, *columns)
        return

    expected = set(_DELIVERY_REQUIRED_COLUMNS)
    present = {column["name"] for column in inspector.get_columns(name)}
    missing = sorted(expected - present)
    if missing:
        raise RuntimeError(
            f"pre-existing delivery table {name!r} is missing required columns: "
            + ", ".join(missing)
        )


def _index_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT to_regclass(:qualified_name)"),
            {"qualified_name": f"public.{name}"},
        ).scalar()
    )


def _create_index_if_missing(name: str, table: str, columns, **kwargs) -> None:
    """Create a named delivery index once, including on resumed migrations."""
    if not _index_exists(name):
        op.create_index(name, table, columns, **kwargs)


def upgrade() -> None:
    # ── delivery_intents ─────────────────────────────────────────────────────
    _create_table_if_missing(
        "delivery_intents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing(
        "idx_delivery_intents_tenant", "delivery_intents", ["tenant_id"]
    )
    _create_index_if_missing(
        "idx_delivery_intents_status",
        "delivery_intents",
        [sa.text("(data->>'status')")],
    )
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_intents_idempotency
           ON delivery_intents ((data->>'idempotency_key'))
           WHERE data->>'idempotency_key' IS NOT NULL"""
    )

    # ── delivery_jobs ────────────────────────────────────────────────────────
    _create_table_if_missing(
        "delivery_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing("idx_delivery_jobs_tenant", "delivery_jobs", ["tenant_id"])
    _create_index_if_missing(
        "idx_delivery_jobs_state",
        "delivery_jobs",
        [sa.text("(data->>'state')")],
    )
    _create_index_if_missing(
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
        """CREATE INDEX IF NOT EXISTS idx_delivery_jobs_runnable
           ON delivery_jobs (
               ((data->>'priority')::int) ASC,
               (data->>'next_attempt_at') ASC
           )
           WHERE data->>'state' IN ('queued', 'failed')"""
    )

    # ── delivery_attempts ────────────────────────────────────────────────────
    _create_table_if_missing(
        "delivery_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing("idx_delivery_attempts_tenant", "delivery_attempts", ["tenant_id"])
    _create_index_if_missing(
        "idx_delivery_attempts_job",
        "delivery_attempts",
        [sa.text("(data->>'job_id')")],
    )

    # ── provider_receipts ────────────────────────────────────────────────────
    _create_table_if_missing(
        "provider_receipts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing("idx_provider_receipts_tenant", "provider_receipts", ["tenant_id"])
    _create_index_if_missing(
        "idx_provider_receipts_intent",
        "provider_receipts",
        [sa.text("(data->>'intent_id')")],
    )
    _create_index_if_missing(
        "idx_provider_receipts_external",
        "provider_receipts",
        [sa.text("(data->>'external_id')"), sa.text("(data->>'provider_adapter')")],
    )

    # ── external_resource_links ───────────────────────────────────────────────
    _create_table_if_missing(
        "external_resource_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing(
        "idx_external_resource_links_tenant", "external_resource_links", ["tenant_id"]
    )
    _create_index_if_missing(
        "idx_external_resource_links_intent",
        "external_resource_links",
        [sa.text("(data->>'intent_id')")],
    )

    # ── external_outcome_events ───────────────────────────────────────────────
    _create_table_if_missing(
        "external_outcome_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing(
        "idx_external_outcome_events_tenant", "external_outcome_events", ["tenant_id"]
    )
    _create_index_if_missing(
        "idx_external_outcome_events_external_id",
        "external_outcome_events",
        [sa.text("(data->>'external_id')"), sa.text("(data->>'provider')")],
    )

    # ── webhook_inbox ────────────────────────────────────────────────────────
    _create_table_if_missing(
        "webhook_inbox",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing("idx_webhook_inbox_tenant", "webhook_inbox", ["tenant_id"])
    op.execute(
        """CREATE INDEX IF NOT EXISTS idx_webhook_inbox_unprocessed
           ON webhook_inbox ((data->>'provider'))
           WHERE data->>'processed' = 'false'"""
    )

    # ── connector_cursors ────────────────────────────────────────────────────
    _create_table_if_missing(
        "connector_cursors",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    _create_index_if_missing("idx_connector_cursors_tenant", "connector_cursors", ["tenant_id"])
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_connector_cursors_unique
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
