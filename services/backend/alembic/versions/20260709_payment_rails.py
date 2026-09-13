"""payment rail observability durable tables

Revision ID: 20260709_payment_rails
Revises: 20260708_agent_deploy
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op

revision = "20260709_payment_rails"
down_revision = "20260708_agent_deploy"
branch_labels = None
depends_on = None

# Backs the get_store(...) durable stores used by
# services/integrations/providers/payment_rails/repository.py.
TABLES = [
    "payment_funding_sessions",
    "payment_provider_events",
    "payment_provider_accounts",
    "payment_deposit_addresses",
    "payment_virtual_accounts",
    "payment_reconciliation_records",
    "payment_rails_audit",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            provider TEXT,
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
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_provider ON {table} (tenant_id, provider)"
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_funding_sessions_tenant_updated "
        "ON payment_funding_sessions (tenant_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_provider_events_tenant_created "
        "ON payment_provider_events (tenant_id, created_at DESC)"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
