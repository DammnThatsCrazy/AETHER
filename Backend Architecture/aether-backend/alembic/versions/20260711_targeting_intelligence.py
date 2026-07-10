"""cluster targeting intelligence durable tables

Revision ID: 20260711_targeting
Revises: 20260710_ai_econ
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "20260711_targeting"
down_revision = "20260710_ai_econ"
branch_labels = None
depends_on = None

# Backs the get_store(...) durable stores used by
# services/targeting_intelligence/repository.py.
TABLES = [
    "targeting_intents",
    "targeting_eligibility_snapshots",
    "targeting_observations",
    "targeting_outcome_snapshots",
    "targeting_leakage_findings",
    "targeting_holdouts",
    "targeting_journey_deltas",
    "targeting_export_packages",
    "targeting_policy_decisions",
    "targeting_audit",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            campaign_id TEXT,
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
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_campaign "
            f"ON {table} (tenant_id, campaign_id)"
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_targeting_eligibility_snapshots_tenant_updated "
        "ON targeting_eligibility_snapshots (tenant_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_targeting_leakage_findings_tenant_updated "
        "ON targeting_leakage_findings (tenant_id, updated_at DESC)"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
