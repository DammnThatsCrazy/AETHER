"""Persist bounded Value360 attribution temporal eligibility evaluations."""
from alembic import op

revision = "20261104_value_confidence_evaluations"
down_revision = "20261104_value_model_approval_policy_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS value_confidence_evaluations (
            evaluation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            attribution_run_id UUID NOT NULL,
            model_config_id UUID NOT NULL,
            validation_decision_id TEXT NOT NULL,
            contract_version TEXT NOT NULL CHECK (contract_version = 'value-credit-temporal-eligibility.v1'),
            dataset_manifest_sha256 TEXT NOT NULL CHECK (dataset_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            sample_count INTEGER NOT NULL CHECK (sample_count BETWEEN 1 AND 100),
            eligible_count INTEGER NOT NULL CHECK (eligible_count BETWEEN 0 AND sample_count),
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL CHECK (window_end >= window_start),
            sample_refs JSONB NOT NULL,
            actor_id TEXT NOT NULL,
            authorization_action TEXT NOT NULL CHECK (authorization_action = 'value.model_evaluation'),
            authorization_permission TEXT NOT NULL CHECK (authorization_permission = 'write'),
            authorization_decision TEXT NOT NULL CHECK (authorization_decision = 'allow'),
            authorization_actor_id TEXT NOT NULL CHECK (authorization_actor_id = actor_id),
            authorization_evaluated_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL CHECK (created_at >= authorization_evaluated_at),
            UNIQUE (tenant_id, evaluation_id),
            FOREIGN KEY (tenant_id, attribution_run_id) REFERENCES attribution_runs (tenant_id, attribution_run_id),
            FOREIGN KEY (tenant_id, model_config_id) REFERENCES attribution_model_configs (tenant_id, model_config_id)
        );
        CREATE INDEX ix_value_confidence_evaluation_scope
          ON value_confidence_evaluations (tenant_id, attribution_run_id, created_at DESC);
        CREATE OR REPLACE FUNCTION reject_value_confidence_evaluation_mutation()
        RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'value confidence evaluations are append-only'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER value_confidence_evaluation_append_only
          BEFORE UPDATE OR DELETE ON value_confidence_evaluations
          FOR EACH ROW EXECUTE FUNCTION reject_value_confidence_evaluation_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS value_confidence_evaluations; DROP FUNCTION IF EXISTS reject_value_confidence_evaluation_mutation();")
