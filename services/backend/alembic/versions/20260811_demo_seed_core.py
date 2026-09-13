"""durable demo seed run, ownership, and reset audit metadata

Revision ID: 20260811_demo_seed_core
Revises: 20260810_kyber_graph_ops
Create Date: 2026-08-11

These tables are the documented direct-SQL exception for the seed subsystem:
they carry orchestration metadata only. Operational records are written through
the canonical JSONB repositories used by the live APIs.
"""

from alembic import op

revision = "20260811_demo_seed_core"
down_revision = "20260810_kyber_graph_ops"
branch_labels = None
depends_on = None

_TABLES = ("demo_seed_runs", "demo_seed_record_ownership", "demo_seed_reset_audit")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                tenant_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table} (tenant_id)"
        )
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_demo_seed_owned_record
        ON demo_seed_record_ownership (
            tenant_id,
            (data->>'seed_namespace'),
            (data->>'repository'),
            (data->>'record_id')
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_demo_seed_runs_lookup
        ON demo_seed_runs (
            tenant_id,
            (data->>'namespace'),
            (data->>'version'),
            created_at DESC
        )
    """)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
