"""Store external agent payment and settlement correlation references.

Revision ID: 20261010_agent_economic_correlation_refs
Revises: 20261010_agent_execution_lineage
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_agent_economic_correlation_refs"
down_revision = "20261010_agent_execution_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            ADD COLUMN IF NOT EXISTS payment_intent_ref TEXT,
            ADD COLUMN IF NOT EXISTS settlement_event_ref TEXT
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_payment_ref "
        "ON silver_agent_execution_facts (tenant_id, payment_intent_ref) "
        "WHERE payment_intent_ref IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_settlement_ref "
        "ON silver_agent_execution_facts (tenant_id, settlement_event_ref) "
        "WHERE settlement_event_ref IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_settlement_ref")
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_payment_ref")
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            DROP COLUMN IF EXISTS payment_intent_ref,
            DROP COLUMN IF EXISTS settlement_event_ref
    """)
