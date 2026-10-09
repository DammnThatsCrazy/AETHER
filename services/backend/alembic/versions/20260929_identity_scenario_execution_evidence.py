"""Persist tenant and deployment scoped identity continuity run outcomes."""

from alembic import op

revision = "20260929_identity_scenario_execution_evidence"
down_revision = "20260928_sdk_heartbeat_status"
branch_labels = None
depends_on = None

IDENTITY_SCENARIO_EXECUTION_EVIDENCE_DDL = """
CREATE TABLE IF NOT EXISTS identity_scenario_execution_evidence (
    tenant_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    execution_id UUID NOT NULL,
    scenario_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'failed')),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    assertions_passed INTEGER NOT NULL CHECK (assertions_passed > 0),
    assertions_failed INTEGER NOT NULL CHECK (assertions_failed >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_ref TEXT NOT NULL,
    PRIMARY KEY (tenant_id, deployment_id, execution_id, scenario_id),
    CHECK ((outcome = 'passed' AND assertions_failed = 0) OR
           (outcome = 'failed' AND assertions_failed > 0)),
    CHECK (scenario_id IN (
      'A_import_first_sdk_later', 'B_shared_device_no_merge',
      'C_bad_merge_split', 'D_agent_human_no_merge', 'shared_email_review',
      'cross_tenant_block', 'deleted_suppressed_identity_block',
      'multi_sdk_same_user', 'connector_reimport_idempotency',
      'projection_restatement'
    ))
)
;
CREATE OR REPLACE FUNCTION prevent_identity_scenario_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND COALESCE(current_setting('aether.tenant_erasure', true), '') = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'identity scenario execution evidence is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_identity_scenario_evidence_append_only
    BEFORE UPDATE OR DELETE ON identity_scenario_execution_evidence
    FOR EACH ROW EXECUTE FUNCTION prevent_identity_scenario_evidence_mutation();
CREATE TRIGGER trg_identity_scenario_evidence_no_truncate
    BEFORE TRUNCATE ON identity_scenario_execution_evidence
    FOR EACH STATEMENT EXECUTE FUNCTION prevent_identity_scenario_evidence_mutation();
"""


def upgrade() -> None:
    op.execute(IDENTITY_SCENARIO_EXECUTION_EVIDENCE_DDL)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_scenario_evidence_tenant_deployment "
        "ON identity_scenario_execution_evidence (tenant_id, deployment_id, executed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_identity_scenario_evidence_tenant_deployment")
    op.execute("DROP TRIGGER IF EXISTS trg_identity_scenario_evidence_no_truncate ON identity_scenario_execution_evidence")
    op.execute("DROP TRIGGER IF EXISTS trg_identity_scenario_evidence_append_only ON identity_scenario_execution_evidence")
    op.execute("DROP TABLE IF EXISTS identity_scenario_execution_evidence")
    op.execute("DROP FUNCTION IF EXISTS prevent_identity_scenario_evidence_mutation()")
