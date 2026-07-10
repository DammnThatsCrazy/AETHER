"""AI Outcome Efficiency / AI Economics durable tables

Revision ID: 20260710_ai_econ
Revises: 20260709_payment_rails
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision = "20260710_ai_econ"
down_revision = "20260709_payment_rails"
branch_labels = None
depends_on = None

# Backs the get_store(...) durable stores used by
# services/economic/ai_pricing.py, services/economic/ai_aggregation.py and
# services/silver/projectors/ai_invocation_projector.py.
#
# ai_price_cards is global: tenant_id may be '' for platform default cards.
TABLES = [
    "ai_execution_facts",
    "ai_price_cards",
    "ai_workflow_economics",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT '',
            provider TEXT,
            model TEXT,
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

    # Price cards are looked up by (provider, model) across tenants ('' = platform default).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_price_cards_provider_model "
        "ON ai_price_cards (provider, model)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_execution_facts_tenant_updated "
        "ON ai_execution_facts (tenant_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_workflow_economics_tenant_updated "
        "ON ai_workflow_economics (tenant_id, updated_at DESC)"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
