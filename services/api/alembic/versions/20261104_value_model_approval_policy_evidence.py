"""Record the authorization context for Value360 model approval decisions."""
from alembic import op

revision = "20261104_value_model_approval_policy_evidence"
down_revision = "20261030_merge_authority_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE value_model_approval_decisions
          ADD COLUMN authorization_action TEXT,
          ADD COLUMN authorization_permission TEXT,
          ADD COLUMN authorization_decision TEXT,
          ADD COLUMN authorization_actor_id TEXT,
          ADD COLUMN authorization_evaluated_at TIMESTAMPTZ;
        ALTER TABLE value_model_approval_decisions
          ADD CONSTRAINT value_model_approval_authorization_evidence_check
          CHECK (
            authorization_action IS NULL OR (
              authorization_action = 'value.model_approval'
              AND authorization_permission = 'admin'
              AND authorization_decision = 'allow'
              AND authorization_actor_id = actor_id
              AND authorization_evaluated_at IS NOT NULL
              AND authorization_evaluated_at <= created_at
            )
          );
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE value_model_approval_decisions
          DROP CONSTRAINT IF EXISTS value_model_approval_authorization_evidence_check;
        ALTER TABLE value_model_approval_decisions
          DROP COLUMN IF EXISTS authorization_action,
          DROP COLUMN IF EXISTS authorization_permission,
          DROP COLUMN IF EXISTS authorization_decision,
          DROP COLUMN IF EXISTS authorization_actor_id,
          DROP COLUMN IF EXISTS authorization_evaluated_at;
    """)
