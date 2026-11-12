"""Immutable receipts emitted only by the bounded MCP invocation ingress.

Revision ID: 20261030_agent_invocation_receipts
Revises: 20261030_outcome_prediction_adjudication_refs
"""
from alembic import op

revision = "20261030_agent_invocation_receipts"
down_revision = "20261030_outcome_prediction_adjudication_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS agent_invocation_receipts (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, data JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_invocation_receipts_tenant ON agent_invocation_receipts (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_invocation_receipts_execution ON agent_invocation_receipts ((data->>'execution_id'))")
    op.execute("""CREATE OR REPLACE FUNCTION reject_agent_invocation_receipt_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'agent invocation receipts are immutable'; END $$""")
    op.execute("DROP TRIGGER IF EXISTS trg_agent_invocation_receipts_immutable ON agent_invocation_receipts")
    op.execute("""CREATE TRIGGER trg_agent_invocation_receipts_immutable BEFORE UPDATE OR DELETE
        ON agent_invocation_receipts FOR EACH ROW EXECUTE FUNCTION reject_agent_invocation_receipt_update()""")
    # A durable, non-evidentiary idempotency claim prevents repeated tool effects.
    # It contains no provider result and is never surfaced as an invocation receipt.
    op.execute("""CREATE TABLE IF NOT EXISTS agent_invocation_claims (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, data JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_invocation_receipts")
    op.execute("DROP TABLE IF EXISTS agent_invocation_claims")
    op.execute("DROP FUNCTION IF EXISTS reject_agent_invocation_receipt_update()")
