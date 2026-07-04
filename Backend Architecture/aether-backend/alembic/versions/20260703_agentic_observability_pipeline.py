"""Agentic Observability Pipeline Tables.

Creates the medallion pipeline tables: bronze, silver fact tables, and outbox.

Revision ID: 20260703_agentic_obs
Revises: 20260703_comms_intel
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260703_agentic_obs"
down_revision = "20260703_comms_intel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bronze_agentic_observations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance_status", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_tag", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bronze_agentic_obs_tenant", "bronze_agentic_observations", ["tenant_id"])
    op.create_index(
        "ix_bronze_agentic_obs_observation", "bronze_agentic_observations", ["observation_id"]
    )

    op.create_table(
        "silver_agent_activity_facts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.Text(), nullable=True),
        sa.Column("silver_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_silver_agent_activity_tenant", "silver_agent_activity_facts", ["tenant_id"]
    )
    op.create_index(
        "ix_silver_agent_activity_agent", "silver_agent_activity_facts", ["agent_id"]
    )

    op.create_table(
        "silver_agent_tool_invocation_facts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.Text(), nullable=True),
        sa.Column("silver_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_silver_tool_invoc_tenant", "silver_agent_tool_invocation_facts", ["tenant_id"]
    )

    op.create_table(
        "silver_mcp_connection_facts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.Text(), nullable=True),
        sa.Column("silver_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_silver_mcp_conn_tenant", "silver_mcp_connection_facts", ["tenant_id"])

    op.create_table(
        "silver_agent_risk_facts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.Text(), nullable=True),
        sa.Column("silver_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_silver_risk_tenant", "silver_agent_risk_facts", ["tenant_id"])

    op.create_table(
        "agentic_projection_outbox",
        sa.Column("outbox_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("mutation_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("outbox_id"),
    )
    op.create_index(
        "ix_agentic_outbox_tenant_status", "agentic_projection_outbox", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_agentic_outbox_observation", "agentic_projection_outbox", ["observation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agentic_outbox_observation", table_name="agentic_projection_outbox")
    op.drop_index("ix_agentic_outbox_tenant_status", table_name="agentic_projection_outbox")
    op.drop_table("agentic_projection_outbox")
    op.drop_index("ix_silver_risk_tenant", table_name="silver_agent_risk_facts")
    op.drop_table("silver_agent_risk_facts")
    op.drop_index("ix_silver_mcp_conn_tenant", table_name="silver_mcp_connection_facts")
    op.drop_table("silver_mcp_connection_facts")
    op.drop_index("ix_silver_tool_invoc_tenant", table_name="silver_agent_tool_invocation_facts")
    op.drop_table("silver_agent_tool_invocation_facts")
    op.drop_index("ix_silver_agent_activity_agent", table_name="silver_agent_activity_facts")
    op.drop_index("ix_silver_agent_activity_tenant", table_name="silver_agent_activity_facts")
    op.drop_table("silver_agent_activity_facts")
    op.drop_index("ix_bronze_agentic_obs_observation", table_name="bronze_agentic_observations")
    op.drop_index("ix_bronze_agentic_obs_tenant", table_name="bronze_agentic_observations")
    op.drop_table("bronze_agentic_observations")
