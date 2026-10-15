"""Add explicit namespaced external-agent identity bindings.

Revision ID: 20261011_agent_deployment_identity_bindings
Revises: 20261010_agent_economic_correlation_refs
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "20261011_agent_deployment_identity_bindings"
down_revision = "20261010_agent_economic_correlation_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_deployment_identity_bindings (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_deployment_identity_bindings_tenant "
        "ON agent_deployment_identity_bindings (tenant_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_deployment_identity_source "
        "ON agent_deployment_identity_bindings "
        "(tenant_id, (data->>'source_namespace'), (data->>'source_agent_ref')) "
        "WHERE data->>'source_namespace' IS NOT NULL "
        "AND data->>'source_agent_ref' IS NOT NULL"
    )
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            ADD COLUMN IF NOT EXISTS resource_ref TEXT
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_resource_ref "
        "ON silver_agent_execution_facts (tenant_id, resource_ref) "
        "WHERE resource_ref IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_resource_ref")
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            DROP COLUMN IF EXISTS resource_ref
    """)
    op.execute("DROP INDEX IF EXISTS uq_agent_deployment_identity_source")
    op.execute("DROP INDEX IF EXISTS idx_agent_deployment_identity_bindings_tenant")
    op.execute("DROP TABLE IF EXISTS agent_deployment_identity_bindings")
