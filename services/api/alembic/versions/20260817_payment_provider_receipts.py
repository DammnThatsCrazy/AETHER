"""payment provider receipt lifecycle — durable delivery ledger

Additive JSONB table backing the metadata-only provider-receipt lifecycle. Each
provider delivery (a verified webhook or a polled record) has one durable receipt
tracking it through every processing stage (received → … → completed) and linking
it to the funding session, canonical event id(s), and outbox record it produced.
The scheduled canonical-repair worker scans this ledger to find and re-drive
incomplete deliveries. Metadata only — no plaintext credentials or raw sensitive
payloads are ever stored (a sha256 body hash is kept for idempotency).

Follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at). Purely additive; fully reversible.

Revision ID: 20260817_payment_provider_receipts
Revises: 20260816_payment_webhook_endpoint_active_unique
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision = "20260817_payment_provider_receipts"
down_revision = "20260816_payment_webhook_endpoint_active_unique"
branch_labels = None
depends_on = None

TABLE = "payment_provider_receipts"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant ON {TABLE} (tenant_id);")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_provider ON {TABLE} "
        f"((data->>'tenant_id'), (data->>'provider'), (data->>'current_stage'));"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_stage ON {TABLE} ((data->>'current_stage'));"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_session ON {TABLE} "
        f"((data->>'funding_session_id'));"
    )
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_updated BEFORE UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(f"DROP TABLE IF EXISTS {TABLE};")
