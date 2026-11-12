"""Create the governed, append-only Profile360 prediction output authority.

Revision ID: 20261024_profile_prediction_output_authority
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

Only explicit future-state outputs with exact artifact, policy, time, subject,
and evidence provenance are admitted to this table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261024_profile_prediction_output_authority"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_prediction_outputs",
        sa.Column("prediction_id", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("artifact_version", sa.Text(), nullable=False),
        sa.Column("artifact_checksum_sha256", sa.Text(), nullable=False),
        sa.Column("artifact_approval_state", sa.Text(), nullable=False),
        sa.Column("feature_schema_hash", sa.Text(), nullable=False),
        sa.Column("feature_digest", sa.Text(), nullable=False),
        sa.Column("state_schema_version", sa.Text(), nullable=False),
        sa.Column("policy_decision_id", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("states", JSONB(), nullable=False),
        sa.Column("evidence_refs", JSONB(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("length(btrim(tenant_id)) > 0", name="ck_profile_pred_tenant"),
        sa.CheckConstraint("length(btrim(entity_id)) > 0", name="ck_profile_pred_entity"),
        sa.CheckConstraint("length(btrim(model_id)) > 0", name="ck_profile_pred_model"),
        sa.CheckConstraint("artifact_approval_state = 'promoted'", name="ck_profile_pred_approved"),
        sa.CheckConstraint("artifact_checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_profile_pred_checksum"),
        sa.CheckConstraint("feature_digest ~ '^[0-9a-f]{16}$'", name="ck_profile_pred_feature_digest"),
        sa.CheckConstraint(
            "state_schema_version = 'profile_future_state.v1'",
            name="ck_profile_pred_state_schema_version",
        ),
        sa.CheckConstraint("valid_until > valid_from AND generated_at <= valid_until", name="ck_profile_pred_validity"),
        sa.CheckConstraint("jsonb_typeof(states) = 'array' AND jsonb_array_length(states) > 0", name="ck_profile_pred_states"),
        sa.CheckConstraint("jsonb_typeof(evidence_refs) = 'array' AND jsonb_array_length(evidence_refs) >= 3", name="ck_profile_pred_evidence"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_profile_pred_tenant_idempotency"),
    )
    op.create_index(
        "ix_profile_pred_exact_valid_subject",
        "profile_prediction_outputs",
        ["tenant_id", "entity_id", "valid_from", "valid_until", "generated_at"],
    )
    op.create_index(
        "ix_profile_pred_policy_decision",
        "profile_prediction_outputs",
        ["tenant_id", "policy_decision_id"],
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION reject_profile_prediction_output_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'profile prediction outputs are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_profile_prediction_outputs_append_only
            BEFORE UPDATE ON profile_prediction_outputs
            FOR EACH ROW EXECUTE FUNCTION reject_profile_prediction_output_update();"""
    )


def downgrade() -> None:
    op.execute(
        """DROP TRIGGER IF EXISTS trg_profile_prediction_outputs_append_only
            ON profile_prediction_outputs;
        DROP FUNCTION IF EXISTS reject_profile_prediction_output_update();"""
    )
    op.drop_index("ix_profile_pred_policy_decision", table_name="profile_prediction_outputs")
    op.drop_index("ix_profile_pred_exact_valid_subject", table_name="profile_prediction_outputs")
    op.drop_table("profile_prediction_outputs")
