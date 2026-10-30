"""Append-only exact attribution run model-config lineage decisions.

Revision ID: 20261027_attribution_model_validation_decisions
Revises: 20261027_support_sla_measurement_contracts
"""

from alembic import op

revision = "20261027_attribution_model_validation_decisions"
down_revision = "20261027_support_sla_measurement_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS attribution_model_validation_decisions (
            decision_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            attribution_run_id UUID NOT NULL,
            model_config_id UUID NOT NULL,
            model_type TEXT NOT NULL,
            model_version TEXT NOT NULL,
            config_snapshot_sha256 TEXT NOT NULL
                CHECK (config_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
            validation_state TEXT NOT NULL
                CHECK (validation_state = 'exact_config_lineage_validated'),
            calibration_state TEXT NOT NULL
                CHECK (calibration_state = 'unvalidated'),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (tenant_id, attribution_run_id),
            FOREIGN KEY (tenant_id, attribution_run_id)
                REFERENCES attribution_runs (tenant_id, attribution_run_id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, model_config_id)
                REFERENCES attribution_model_configs (tenant_id, model_config_id) ON DELETE CASCADE
        );
        CREATE OR REPLACE FUNCTION reject_attribution_model_validation_mutation()
        RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'attribution_model_validation_decisions is append-only';
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER attribution_model_validation_append_only
            BEFORE UPDATE ON attribution_model_validation_decisions
            FOR EACH ROW EXECUTE FUNCTION reject_attribution_model_validation_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attribution_model_validation_decisions")
    op.execute("DROP FUNCTION IF EXISTS reject_attribution_model_validation_mutation()")
