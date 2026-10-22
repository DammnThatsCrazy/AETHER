"""Persist sub-agent spawn lineage on agent execution facts.

Revision ID: 20261022_agent_spawn_lineage
Revises: 20261018_comms_consent_lineage
Create Date: 2026-10-22

Adds parent / child / root agent references and the parent run so an
orchestrator -> sub-agent tree of any depth can be rebuilt from Silver. All
values are source-reported references; historical rows stay NULL.
"""
from __future__ import annotations

from alembic import op

revision = "20261022_agent_spawn_lineage"
down_revision = "20261018_comms_consent_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            ADD COLUMN IF NOT EXISTS parent_agent_ref TEXT,
            ADD COLUMN IF NOT EXISTS child_agent_ref TEXT,
            ADD COLUMN IF NOT EXISTS root_agent_ref TEXT,
            ADD COLUMN IF NOT EXISTS parent_run_id TEXT
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_spawn_root "
        "ON silver_agent_execution_facts (tenant_id, root_agent_ref, occurred_at) "
        "WHERE root_agent_ref IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_spawn_parent "
        "ON silver_agent_execution_facts (tenant_id, parent_agent_ref, occurred_at) "
        "WHERE parent_agent_ref IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_spawn_parent")
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_spawn_root")
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            DROP COLUMN IF EXISTS parent_run_id,
            DROP COLUMN IF EXISTS root_agent_ref,
            DROP COLUMN IF EXISTS child_agent_ref,
            DROP COLUMN IF EXISTS parent_agent_ref
    """)
