"""Persist computed model evaluations and scoped Value360 approval decisions."""
from alembic import op

revision = "20261030_model_governance_evaluations_approvals"
down_revision = "20261030_outcome_prediction_adjudication_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE model_governance_evaluations (
            evaluation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            domain TEXT NOT NULL CHECK (domain IN ('profile360', 'value360')),
            model_id TEXT NOT NULL,
            artifact_version TEXT NOT NULL,
            artifact_checksum_sha256 TEXT NOT NULL CHECK (artifact_checksum_sha256 ~ '^[0-9a-f]{64}$'),
            dataset_manifest_sha256 TEXT NOT NULL CHECK (dataset_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            split TEXT NOT NULL CHECK (split IN ('evaluation', 'holdout')),
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL CHECK (window_end > window_start),
            sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
            sample_refs JSONB NOT NULL,
            metrics JSONB NOT NULL,
            method TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (tenant_id, evaluation_id)
        );
        CREATE INDEX ix_model_governance_evaluation_scope
          ON model_governance_evaluations (tenant_id, domain, model_id, artifact_version, created_at DESC);
        CREATE TABLE value_model_approval_decisions (
            decision_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            attribution_run_id UUID NOT NULL,
            model_config_id UUID NOT NULL,
            model_type TEXT NOT NULL,
            model_version TEXT NOT NULL,
            validation_decision_id TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            FOREIGN KEY (tenant_id, attribution_run_id)
              REFERENCES attribution_runs (tenant_id, attribution_run_id),
            FOREIGN KEY (tenant_id, model_config_id)
              REFERENCES attribution_model_configs (tenant_id, model_config_id)
        );
        CREATE INDEX ix_value_model_approval_scope
          ON value_model_approval_decisions (tenant_id, attribution_run_id, created_at DESC);
        CREATE OR REPLACE FUNCTION reject_model_governance_evidence_mutation()
        RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'model governance evidence is append-only';
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_governance_evaluation_append_only
          BEFORE UPDATE OR DELETE ON model_governance_evaluations
          FOR EACH ROW EXECUTE FUNCTION reject_model_governance_evidence_mutation();
        CREATE TRIGGER value_model_approval_append_only
          BEFORE UPDATE OR DELETE ON value_model_approval_decisions
          FOR EACH ROW EXECUTE FUNCTION reject_model_governance_evidence_mutation();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS value_model_approval_decisions;
        DROP TABLE IF EXISTS model_governance_evaluations;
        DROP FUNCTION IF EXISTS reject_model_governance_evidence_mutation();
    """)
