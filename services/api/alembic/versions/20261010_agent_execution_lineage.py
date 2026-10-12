"""Preserve tenant-scoped execution and decision lineage for external agents.

Revision ID: 20261010_agent_execution_lineage
Revises: 20261010_economic_operation_journey_refs
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_agent_execution_lineage"
down_revision = "20261010_economic_operation_journey_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            ADD COLUMN IF NOT EXISTS deployment_id TEXT,
            ADD COLUMN IF NOT EXISTS run_id TEXT,
            ADD COLUMN IF NOT EXISTS run_correlation_source TEXT,
            ADD COLUMN IF NOT EXISTS trace_id TEXT,
            ADD COLUMN IF NOT EXISTS span_id TEXT,
            ADD COLUMN IF NOT EXISTS correlation_id TEXT,
            ADD COLUMN IF NOT EXISTS causation_id TEXT,
            ADD COLUMN IF NOT EXISTS delegation_id TEXT,
            ADD COLUMN IF NOT EXISTS delegated_to_ref TEXT,
            ADD COLUMN IF NOT EXISTS principal_id TEXT,
            ADD COLUMN IF NOT EXISTS task_ref TEXT,
            ADD COLUMN IF NOT EXISTS outcome_ref TEXT,
            ADD COLUMN IF NOT EXISTS action_ref TEXT,
            ADD COLUMN IF NOT EXISTS action_type TEXT,
            ADD COLUMN IF NOT EXISTS trigger_ref TEXT,
            ADD COLUMN IF NOT EXISTS trigger_type TEXT,
            ADD COLUMN IF NOT EXISTS decision_ref TEXT,
            ADD COLUMN IF NOT EXISTS policy_id TEXT,
            ADD COLUMN IF NOT EXISTS policy_version TEXT,
            ADD COLUMN IF NOT EXISTS policy_decision TEXT,
            ADD COLUMN IF NOT EXISTS policy_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS status TEXT,
            ADD COLUMN IF NOT EXISTS tool_name TEXT
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_deployment "
        "ON silver_agent_execution_facts (tenant_id, deployment_id, occurred_at DESC) "
        "WHERE deployment_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_run "
        "ON silver_agent_execution_facts (tenant_id, deployment_id, run_id, occurred_at) "
        "WHERE deployment_id IS NOT NULL AND run_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_causality "
        "ON silver_agent_execution_facts (tenant_id, deployment_id, causation_id) "
        "WHERE deployment_id IS NOT NULL AND causation_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_causality")
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_run")
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_deployment")
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            DROP COLUMN IF EXISTS deployment_id,
            DROP COLUMN IF EXISTS run_id,
            DROP COLUMN IF EXISTS run_correlation_source,
            DROP COLUMN IF EXISTS trace_id,
            DROP COLUMN IF EXISTS span_id,
            DROP COLUMN IF EXISTS correlation_id,
            DROP COLUMN IF EXISTS causation_id,
            DROP COLUMN IF EXISTS delegation_id,
            DROP COLUMN IF EXISTS delegated_to_ref,
            DROP COLUMN IF EXISTS principal_id,
            DROP COLUMN IF EXISTS task_ref,
            DROP COLUMN IF EXISTS outcome_ref,
            DROP COLUMN IF EXISTS action_ref,
            DROP COLUMN IF EXISTS action_type,
            DROP COLUMN IF EXISTS trigger_ref,
            DROP COLUMN IF EXISTS trigger_type,
            DROP COLUMN IF EXISTS decision_ref,
            DROP COLUMN IF EXISTS policy_id,
            DROP COLUMN IF EXISTS policy_version,
            DROP COLUMN IF EXISTS policy_decision,
            DROP COLUMN IF EXISTS policy_reason_codes,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS tool_name
    """)
