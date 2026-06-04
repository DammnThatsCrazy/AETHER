"""agent control plane durable tables

Revision ID: 20260604_agent_control_plane
Revises: 20260529_notification_intelligence
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op

revision = "20260604_agent_control_plane"
down_revision = "20260529_notif_intel"
branch_labels = None
depends_on = None

TABLES = [
    "agent_objectives",
    "agent_plans",
    "agent_plan_steps",
    "agent_checkpoints",
    "agent_events",
    "agent_review_batches",
    "agent_staged_mutations",
    "agent_controller_heartbeats",
    "agent_worker_runs",
    "catalyst_wake_triggers",
    # Backs get_store("agent_control"); without it POST /v1/agent/kill-switch
    # has no durable table to persist tenant emergency-stop state.
    "agent_control",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            objective_id TEXT,
            status TEXT,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_status ON {table} (tenant_id, status)")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_objective ON {table} (tenant_id, objective_id)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_events_tenant_created ON agent_events (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_worker_runs_tenant_updated ON agent_worker_runs (tenant_id, updated_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_controller_heartbeats_tenant_updated ON agent_controller_heartbeats (tenant_id, updated_at DESC)")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
