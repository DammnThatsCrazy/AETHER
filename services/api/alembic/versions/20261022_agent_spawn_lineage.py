"""Persist sub-agent spawn lineage on agent execution facts.

Revision ID: 20261022_agent_spawn_lineage
Revises: 20261018_comms_consent_lineage
Create Date: 2026-10-22

Adds parent / child / root agent references and the parent run so an
orchestrator -> sub-agent tree of any depth can be rebuilt from Silver. All
values are source-reported references; historical rows stay NULL.

Also adds the MCP endpoint, object and trade-observation columns the projector
already emits (server_url, object_id, symbol, ...). The generic Silver writer
drops row keys that have no column, so without these the fleet reader would see
no shared-endpoint or target evidence outside local mode.
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
            ADD COLUMN IF NOT EXISTS parent_run_id TEXT,
            ADD COLUMN IF NOT EXISTS server_url TEXT,
            ADD COLUMN IF NOT EXISTS server_name TEXT,
            ADD COLUMN IF NOT EXISTS object_type TEXT,
            ADD COLUMN IF NOT EXISTS object_id TEXT,
            ADD COLUMN IF NOT EXISTS symbol TEXT,
            ADD COLUMN IF NOT EXISTS side TEXT,
            ADD COLUMN IF NOT EXISTS quantity TEXT,
            ADD COLUMN IF NOT EXISTS total_value TEXT,
            ADD COLUMN IF NOT EXISTS external_order_id TEXT,
            ADD COLUMN IF NOT EXISTS account_kind TEXT
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
            DROP COLUMN IF EXISTS account_kind,
            DROP COLUMN IF EXISTS external_order_id,
            DROP COLUMN IF EXISTS total_value,
            DROP COLUMN IF EXISTS quantity,
            DROP COLUMN IF EXISTS side,
            DROP COLUMN IF EXISTS symbol,
            DROP COLUMN IF EXISTS object_id,
            DROP COLUMN IF EXISTS object_type,
            DROP COLUMN IF EXISTS server_name,
            DROP COLUMN IF EXISTS server_url,
            DROP COLUMN IF EXISTS parent_run_id,
            DROP COLUMN IF EXISTS root_agent_ref,
            DROP COLUMN IF EXISTS child_agent_ref,
            DROP COLUMN IF EXISTS parent_agent_ref
    """)
