"""Canonical traffic-source dimensions for the v3 classifier truth model.

Adds the registry-defined classification dimensions (traffic_origin,
economic_class, channel_family, entry_method, proof_level) plus the
evidence_conflicts ledger to the existing acquisition -> canonical touchpoint
-> journey path.  This deliberately extends the projections created by
``20260725_ai_referral_attribution`` — it does not create a second touchpoint,
journey, or classification subsystem.

All columns are additive and nullable (JSONB defaults excepted) so historical
rows keep their v2 values until the source-classification repair job restates
them; the read path normalizes legacy aliases in the meantime.

Revision ID: 20260801_canonical_traffic
Revises: 20260734_semantic_shadow_divergences
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "20260801_canonical_traffic"
down_revision = "20260734_semantic_shadow_divergences"
branch_labels = None
depends_on = None


_DIMENSION_TABLES = (
    "silver_campaign_touchpoint_facts",
    "canonical_activity",
    "journey_steps",
)


TOUCHPOINT_DIMENSION_COLUMNS_DDL = """
ALTER TABLE silver_campaign_touchpoint_facts
    ADD COLUMN IF NOT EXISTS traffic_origin TEXT,
    ADD COLUMN IF NOT EXISTS economic_class TEXT,
    ADD COLUMN IF NOT EXISTS channel_family TEXT,
    ADD COLUMN IF NOT EXISTS entry_method TEXT,
    ADD COLUMN IF NOT EXISTS proof_level TEXT,
    ADD COLUMN IF NOT EXISTS evidence_conflicts JSONB NOT NULL DEFAULT '[]'::jsonb;
"""


CANONICAL_ACTIVITY_DIMENSION_COLUMNS_DDL = """
ALTER TABLE canonical_activity
    ADD COLUMN IF NOT EXISTS traffic_origin TEXT,
    ADD COLUMN IF NOT EXISTS economic_class TEXT,
    ADD COLUMN IF NOT EXISTS channel_family TEXT,
    ADD COLUMN IF NOT EXISTS entry_method TEXT,
    ADD COLUMN IF NOT EXISTS proof_level TEXT,
    ADD COLUMN IF NOT EXISTS evidence_conflicts JSONB NOT NULL DEFAULT '[]'::jsonb;
"""


JOURNEY_STEP_DIMENSION_COLUMNS_DDL = """
ALTER TABLE journey_steps
    ADD COLUMN IF NOT EXISTS traffic_origin TEXT,
    ADD COLUMN IF NOT EXISTS economic_class TEXT,
    ADD COLUMN IF NOT EXISTS channel_family TEXT,
    ADD COLUMN IF NOT EXISTS entry_method TEXT,
    ADD COLUMN IF NOT EXISTS proof_level TEXT,
    ADD COLUMN IF NOT EXISTS evidence_conflicts JSONB NOT NULL DEFAULT '[]'::jsonb;
"""


INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_sctf_tenant_channel_family "
    "ON silver_campaign_touchpoint_facts (tenant_id, channel_family) "
    "WHERE channel_family IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sctf_tenant_economic_class "
    "ON silver_campaign_touchpoint_facts (tenant_id, economic_class) "
    "WHERE economic_class IS NOT NULL",
]


def upgrade() -> None:
    op.execute(TOUCHPOINT_DIMENSION_COLUMNS_DDL)
    op.execute(CANONICAL_ACTIVITY_DIMENSION_COLUMNS_DDL)
    op.execute(JOURNEY_STEP_DIMENSION_COLUMNS_DDL)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sctf_tenant_economic_class")
    op.execute("DROP INDEX IF EXISTS ix_sctf_tenant_channel_family")
    for table in _DIMENSION_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table}
                DROP COLUMN IF EXISTS evidence_conflicts,
                DROP COLUMN IF EXISTS proof_level,
                DROP COLUMN IF EXISTS entry_method,
                DROP COLUMN IF EXISTS channel_family,
                DROP COLUMN IF EXISTS economic_class,
                DROP COLUMN IF EXISTS traffic_origin;
            """
        )
