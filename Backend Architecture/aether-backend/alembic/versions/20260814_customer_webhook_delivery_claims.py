"""durable idempotent customer webhook delivery claims"""

from __future__ import annotations

from alembic import op


revision = "20260814_customer_webhook_delivery_claims"
down_revision = "20260813_account_deletion_workflow"
branch_labels = None
depends_on = None

# The delivery-infrastructure migration uses Alembic's ``op.create_table``
# API, so keep its tenant-scoped attempt table visible to the repository's
# storage-policy inventory as well.
DELIVERY_ATTEMPT_TABLES = ("delivery_attempts",)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_webhook_delivery_claims (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            webhook_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            attempts INTEGER NOT NULL DEFAULT 1,
            status_code INTEGER,
            latency_ms DOUBLE PRECISION,
            failure_reason TEXT,
            attempt_id TEXT,
            claim_token TEXT,
            CONSTRAINT customer_webhook_delivery_claims_key
                UNIQUE (tenant_id, webhook_id, idempotency_key)
        )
        """
    )
    op.execute(
        "ALTER TABLE customer_webhook_delivery_claims "
        "ADD COLUMN IF NOT EXISTS claim_token TEXT"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_customer_webhook_delivery_claims_lookup
            ON customer_webhook_delivery_claims (tenant_id, webhook_id, updated_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_customer_webhook_delivery_claims_recovery
            ON customer_webhook_delivery_claims (status, claimed_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS customer_webhook_delivery_claims")
