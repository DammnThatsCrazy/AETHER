"""Store agent behavior references on Silver agent execution facts (WO-033).

Revision ID: 20261029_agent_behavior_fact_refs
Revises: 20261024_merge_360_surface_authorities
Create Date: 2026-10-29
"""
from __future__ import annotations

from alembic import op

revision = "20261029_agent_behavior_fact_refs"
down_revision = "20261024_merge_360_surface_authorities"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("objective_ref", "TEXT"),
    ("parent_objective_ref", "TEXT"),
    ("candidate_ref", "TEXT"),
    ("previous_tool_name", "TEXT"),
    ("attempt", "INTEGER"),
    ("latency_ms", "INTEGER"),
    ("memory_ref", "TEXT"),
    ("information_source_ref", "TEXT"),
    ("authorization_ref", "TEXT"),
    ("amount", "NUMERIC"),
    ("currency", "TEXT"),
)


def upgrade() -> None:
    adds = ",\n            ".join(f"ADD COLUMN IF NOT EXISTS {name} {kind}" for name, kind in _COLUMNS)
    op.execute(f"ALTER TABLE silver_agent_execution_facts\n            {adds}")
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_objective_ref "
        "ON silver_agent_execution_facts (tenant_id, objective_ref) "
        "WHERE objective_ref IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_decision_ref "
        "ON silver_agent_execution_facts (tenant_id, decision_ref) "
        "WHERE decision_ref IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_decision_ref")
    op.execute("DROP INDEX IF EXISTS silver_agent_exec_objective_ref")
    drops = ",\n            ".join(f"DROP COLUMN IF EXISTS {name}" for name, _ in _COLUMNS)
    op.execute(f"ALTER TABLE silver_agent_execution_facts\n            {drops}")
