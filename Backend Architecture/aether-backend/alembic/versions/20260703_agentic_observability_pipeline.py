"""Agentic observability Bronze/Silver/outbox tables.

Revision ID: 20260703_agentic_obs_pipeline
Revises: 20260702_semantic_sentiment
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260703_agentic_obs_pipeline"
down_revision = "20260702_semantic_sentiment"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    ]


def _agentic_fact_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("source_provider", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("runtime_id", sa.Text(), nullable=True),
        sa.Column("connection_id", sa.Text(), nullable=True),
        sa.Column("server_id", sa.Text(), nullable=True),
        sa.Column("tool_id", sa.Text(), nullable=True),
        sa.Column("invocation_id", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("authorization_id", sa.Text(), nullable=True),
        sa.Column("external_account_id", sa.Text(), nullable=True),
        sa.Column("provider_request_id", sa.Text(), nullable=True),
        sa.Column("external_object_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="observed"),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default="unverified"),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="1.0"),
        sa.Column("privacy_class", sa.Text(), nullable=False, server_default="metadata"),
        sa.Column("retention_class", sa.Text(), nullable=False, server_default="standard"),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        *_timestamp_columns(),
    )
    op.create_index(f"idx_{name}_tenant_observed", name, ["tenant_id", "observed_at"])
    op.create_index(f"idx_{name}_tenant_agent", name, ["tenant_id", "agent_id"])
    op.create_index(f"idx_{name}_tenant_trace", name, ["tenant_id", "trace_id"])
    op.create_index(f"idx_{name}_tenant_authorization", name, ["tenant_id", "authorization_id"])
    op.create_index(f"idx_{name}_tenant_provider_request", name, ["tenant_id", "provider_request_id"])
    op.create_unique_constraint(f"uq_{name}_tenant_idempotency", name, ["tenant_id", "idempotency_key"])


def upgrade() -> None:
    op.create_table(
        "bronze_agentic_observations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="1.0"),
        sa.Column("source_provider", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("integration_id", sa.Text(), nullable=True),
        sa.Column("sdk_name", sa.Text(), nullable=True),
        sa.Column("sdk_version", sa.Text(), nullable=True),
        sa.Column("connector_name", sa.Text(), nullable=True),
        sa.Column("connector_version", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("signature_status", sa.Text(), nullable=False, server_default="not_provided"),
        sa.Column("secret_scan_status", sa.Text(), nullable=False, server_default="redacted"),
        sa.Column("redaction_policy_version", sa.Text(), nullable=False, server_default="agentic-v1"),
        sa.Column("raw_payload_ref", sa.Text(), nullable=True),
        sa.Column("privacy_class", sa.Text(), nullable=False, server_default="metadata"),
        sa.Column("retention_class", sa.Text(), nullable=False, server_default="standard"),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        *_timestamp_columns(),
    )
    op.create_index("idx_bronze_agentic_tenant_received", "bronze_agentic_observations", ["tenant_id", "received_at"])
    op.create_index("idx_bronze_agentic_tenant_event_type", "bronze_agentic_observations", ["tenant_id", "event_type"])
    op.create_unique_constraint("uq_bronze_agentic_tenant_source_event", "bronze_agentic_observations", ["tenant_id", "source_event_id"])

    for table in [
        "silver_agent_registry_facts",
        "silver_agent_runtime_facts",
        "silver_mcp_server_facts",
        "silver_mcp_connection_facts",
        "silver_mcp_capability_facts",
        "silver_mcp_tool_definition_facts",
        "silver_agent_tool_invocation_facts",
        "silver_external_account_facts",
        "silver_authorization_grant_facts",
        "silver_permission_scope_facts",
        "silver_provider_action_facts",
        "silver_provider_verification_facts",
        "silver_agent_risk_facts",
        "silver_agent_message_facts",
        "silver_agent_protocol_facts",
        "silver_agent_activity_facts",
    ]:
        _agentic_fact_table(table)

    op.create_table(
        "agentic_projection_outbox",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("outbox_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("canonical_activity_id", sa.Text(), nullable=True),
        sa.Column("mutation_domain", sa.Text(), nullable=False),
        sa.Column("mutation_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        *_timestamp_columns(),
    )
    op.create_unique_constraint("uq_agentic_outbox_id", "agentic_projection_outbox", ["outbox_id"])
    op.create_unique_constraint("uq_agentic_outbox_tenant_idempotency", "agentic_projection_outbox", ["tenant_id", "idempotency_key"])
    op.create_index("idx_agentic_outbox_tenant_status", "agentic_projection_outbox", ["tenant_id", "status"])
    op.create_index("idx_agentic_outbox_runnable", "agentic_projection_outbox", ["tenant_id", "mutation_domain", "status", "next_attempt_at"])
    op.create_index("idx_agentic_outbox_source_event", "agentic_projection_outbox", ["tenant_id", "source_event_id"])


def downgrade() -> None:
    op.drop_table("agentic_projection_outbox")
    for table in reversed([
        "silver_agent_registry_facts",
        "silver_agent_runtime_facts",
        "silver_mcp_server_facts",
        "silver_mcp_connection_facts",
        "silver_mcp_capability_facts",
        "silver_mcp_tool_definition_facts",
        "silver_agent_tool_invocation_facts",
        "silver_external_account_facts",
        "silver_authorization_grant_facts",
        "silver_permission_scope_facts",
        "silver_provider_action_facts",
        "silver_provider_verification_facts",
        "silver_agent_risk_facts",
        "silver_agent_message_facts",
        "silver_agent_protocol_facts",
        "silver_agent_activity_facts",
    ]):
        op.drop_table(table)
    op.drop_table("bronze_agentic_observations")
