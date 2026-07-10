"""one-person ops runtime durable tables

Revision ID: 20260712_ops_runtime
Revises: 20260711_targeting
Create Date: 2026-07-12
"""

from __future__ import annotations

from alembic import op

revision = "20260712_ops_runtime"
down_revision = "20260711_targeting"
branch_labels = None
depends_on = None

# Backs the get_store(...) durable stores used by
# services/agent/briefings.py and services/agent/ops_alerts.py.
TABLES = [
    # Durable operator briefings (replaces the Agent Layer's in-memory
    # BriefingStore as the hosted/Kyber-facing record of operator briefs).
    "agent_briefings",
    # Compressed operator alerts (dedupe_key + count, not one row per event).
    "ops_alerts",
    # Per-channel last-routed markers so alert notification routing can
    # dedupe/throttle across restarts.
    "ops_notification_state",
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
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_status ON {table} (tenant_id, status)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_created "
            f"ON {table} (tenant_id, created_at DESC)"
        )

    # Additive worker-run indexes for the execution bridge. The base
    # (tenant_id, status) index ships with 20260604_agent_control_plane; the
    # IF NOT EXISTS keeps this migration safe to re-run either way, and the
    # status+updated_at composite serves stuck/stale-run sweeps directly.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_worker_runs_tenant_status "
        "ON agent_worker_runs (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_worker_runs_tenant_status_updated "
        "ON agent_worker_runs (tenant_id, status, updated_at DESC)"
    )


def downgrade() -> None:
    # Only drop what this migration introduced; the worker-run base index is
    # owned by 20260604_agent_control_plane and must survive a downgrade.
    op.execute("DROP INDEX IF EXISTS ix_agent_worker_runs_tenant_status_updated")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
