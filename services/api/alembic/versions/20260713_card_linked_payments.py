"""Card-linked payment rail observability — durable store tables.

Mirrors the payment-rails store-table shape (20260709_payment_rails):
generic tenant-scoped JSONB payload tables backing the shared durable-store
abstraction, plus the silver fact table for card-linked SDK projections.

No table ever holds PAN/CVV/KYC/bank data — ingestion rejects blocked
fields before persistence, and the audit table records the attempts.

Revision ID: 20260713_card_linked
Revises: 20260708_interop
"""

from __future__ import annotations

from alembic import op

revision = "20260713_card_linked"
down_revision = "20260708_interop"
branch_labels = None
depends_on = None

TABLES = [
    "card_linked_flows",
    "card_linked_benchmarks",
    "card_linked_provider_health",
    "card_linked_reconciliation",
    "card_linked_audit",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            provider TEXT,
            status TEXT,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table} (tenant_id);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS card_linked_flow_facts (
        idempotency_key TEXT NOT NULL,
        source_event_id TEXT,
        tenant_id TEXT NOT NULL,
        event_type TEXT,
        user_id TEXT,
        session_id TEXT,
        card_program_id TEXT,
        issuer_id TEXT,
        payment_network TEXT,
        basis TEXT NOT NULL,
        rail TEXT,
        chain TEXT,
        asset TEXT,
        amount_usd NUMERIC(38, 18),
        campaign_id TEXT,
        journey_id TEXT,
        source TEXT NOT NULL,
        confidence TEXT NOT NULL,
        occurred_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, idempotency_key)
    );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_card_linked_flow_facts_tenant "
        "ON card_linked_flow_facts (tenant_id, card_program_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS card_linked_flow_facts;")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table};")
