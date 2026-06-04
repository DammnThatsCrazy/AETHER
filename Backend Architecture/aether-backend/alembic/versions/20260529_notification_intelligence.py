"""Notification Intelligence — create notification pipeline tables

Revision ID: 20260529_notif_intel
Revises: cis001a2b3c4d
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, TEXT

revision = "20260529_notif_intel"
down_revision = "cis001a2b3c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── notification_intelligence_events ─────────────────────────────────
    op.create_table(
        "notification_intelligence_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("deduplication_key", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text),
        sa.Column("source_topic", sa.Text, nullable=False),
        sa.Column("source_event_id", sa.Text),
        sa.Column("source_service", sa.Text),
        sa.Column("correlation_id", sa.Text),
        sa.Column("lifecycle_state", sa.Text, nullable=False, server_default="detected"),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("notification_class", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("what", sa.Text),
        sa.Column("why", sa.Text),
        sa.Column("impact", sa.Text),
        sa.Column("recommended_action", sa.Text),
        sa.Column("reversible", sa.Boolean),
        sa.Column("deep_link", sa.Text, server_default="/mission"),
        sa.Column("routing_policy", JSONB),
        sa.Column("slack_payload", JSONB),
        sa.Column("operator_context", JSONB, server_default="{}"),
        sa.Column("graph_propagation", JSONB),
        sa.Column("audit_trail", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "detected_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_nie_tenant_state",
        "notification_intelligence_events",
        ["tenant_id", "lifecycle_state"],
    )
    op.create_index(
        "idx_nie_dedup_key",
        "notification_intelligence_events",
        ["deduplication_key"],
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_nie_expires_review
        ON notification_intelligence_events (expires_at)
        WHERE lifecycle_state = 'operator_review'
        """
    )

    # ── tenant_notification_configs ──────────────────────────────────────
    op.create_table(
        "tenant_notification_configs",
        sa.Column("id", sa.Text, primary_key=True),  # = tenant_id
        sa.Column("tenant_id", sa.Text, nullable=False, unique=True),
        sa.Column("slack_bot_token_ref", sa.Text),
        sa.Column("slack_channel_map", JSONB, server_default="{}"),
        sa.Column("rate_limit_per_minute", sa.Integer, server_default="10"),
        sa.Column("quiet_hours", JSONB),
        sa.Column(
            "operator_review_required",
            ARRAY(TEXT),
            server_default="ARRAY['P0','P1']",
        ),
        sa.Column("auto_propagate_on_approve", sa.Boolean, server_default="true"),
        sa.Column("auto_suppress_on_expire", sa.Boolean, server_default="true"),
        sa.Column("sla_minutes", JSONB, server_default='{"P0":5,"P1":15,"P2":60,"P3":240}'),
        sa.Column("rbac_roles", JSONB, server_default="{}"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # ── operator_actions ─────────────────────────────────────────────────
    op.create_table(
        "operator_actions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "notification_id",
            sa.Text,
            sa.ForeignKey("notification_intelligence_events.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("action_type", sa.Text, nullable=False),
        sa.Column("actor_user_id", sa.Text, nullable=False),
        sa.Column("annotation", sa.Text),
        sa.Column("propagated", sa.Boolean, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_oa_notification_id",
        "operator_actions",
        ["notification_id"],
    )
    op.create_index(
        "idx_oa_tenant_id",
        "operator_actions",
        ["tenant_id"],
    )

    # ── user_notification_channels ───────────────────────────────────────
    op.create_table(
        "user_notification_channels",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text),  # NULL = tenant-level channel
        sa.Column("channel_type", sa.Text, nullable=False),
        sa.Column("channel_name", sa.Text),
        sa.Column("credentials_ref", sa.Text, nullable=False),
        sa.Column("channel_config", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "severity_filter",
            ARRAY(TEXT),
            server_default="ARRAY['P0','P1','P2']",
        ),
        sa.Column("event_type_filter", ARRAY(TEXT)),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_unc_tenant_active",
        "user_notification_channels",
        ["tenant_id", "active"],
    )
    op.create_index(
        "idx_unc_tenant_user",
        "user_notification_channels",
        ["tenant_id", "user_id"],
    )

    # ── slack_oauth_states ───────────────────────────────────────────────
    op.create_table(
        "slack_oauth_states",
        sa.Column("id", sa.Text, primary_key=True),  # = state nonce
        sa.Column("state", sa.Text, nullable=False, unique=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("redirect_uri", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("slack_oauth_states")
    op.drop_table("user_notification_channels")
    op.drop_table("operator_actions")
    op.drop_table("tenant_notification_configs")
    op.drop_table("notification_intelligence_events")
