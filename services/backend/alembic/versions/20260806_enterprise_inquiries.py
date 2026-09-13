"""enterprise contact inquiries

Backs the enterprise-inquiry endpoint (services/contact/routes.py). One row per
submitted inquiry; tenant_id is NULL for pre-sales prospects (a tenant exists for
authenticated inquiries but is not a legal owner of the row), matching the
BaseRepository JSONB shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at).

The row is the durable record — email delivery is best-effort on top of it, and
never stores PII in logs. This table is deliberately NOT tenant-scoped and is
therefore excluded from TENANT_SCOPED_REPOSITORY_REGISTRY (storage_registry.py):
pre-sales inquiries are not tenant-owned data and must not be erased by the
account-deletion workflow.

Revision ID: 20260806_enterprise_inquiries
Revises: 20260817_payment_provider_receipts
Create Date: 2026-08-06
"""

from __future__ import annotations

from alembic import op

revision = "20260806_enterprise_inquiries"
down_revision = "20260817_payment_provider_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enterprise_inquiries (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_enterprise_inquiries_tenant "
        "ON enterprise_inquiries (tenant_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enterprise_inquiries;")
