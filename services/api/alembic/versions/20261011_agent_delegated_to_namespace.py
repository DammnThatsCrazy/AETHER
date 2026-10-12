"""Persist the source namespace for delegated-to agent references.

Revision ID: 20261011_agent_delegated_to_namespace
Revises: 20261011_agent_deployment_identity_bindings
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "20261011_agent_delegated_to_namespace"
down_revision = "20261011_agent_deployment_identity_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            ADD COLUMN IF NOT EXISTS delegated_to_namespace TEXT
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE silver_agent_execution_facts
            DROP COLUMN IF EXISTS delegated_to_namespace
    """)
