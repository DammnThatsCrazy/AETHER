"""external agent deployment registry durable tables

Store-backing tables for get_store("agent_deployments") and
get_store("agent_deployment_audit") — External Agent Telemetry Plane V1.

Revision ID: 20260708_agent_deploy
Revises: 20260703_agentic_obs
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "20260708_agent_deploy"
down_revision = "20260703_agentic_obs"
branch_labels = None
depends_on = None

TABLES = [
    "agent_deployments",
    "agent_deployment_audit",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            status TEXT,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_status ON {table} (tenant_id, status)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_deployments_tenant_updated ON agent_deployments (tenant_id, updated_at DESC)")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
