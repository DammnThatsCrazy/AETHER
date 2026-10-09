"""Durable retry claims for SDK identify requests."""

from alembic import op

revision = "20260927_sdk_identify_idempotency"
down_revision = "20260914_graph_mutation_rights_ref"
branch_labels = None
depends_on = None

SDK_IDENTIFY_IDEMPOTENCY_DDL = """
CREATE TABLE IF NOT EXISTS sdk_identify_idempotency (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    claim_token TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'completed')),
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key),
    CHECK ((state = 'pending' AND response IS NULL) OR
           (state = 'completed' AND response IS NOT NULL))
)
"""


def upgrade() -> None:
    op.execute(SDK_IDENTIFY_IDEMPOTENCY_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sdk_identify_idempotency")
