"""Billing tables — tenant accounts, Stripe events, overage invoices.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
            tenant_id              VARCHAR(64) PRIMARY KEY,
            contact_email          VARCHAR(255),
            stripe_customer_id     VARCHAR(255) UNIQUE,
            stripe_subscription_id VARCHAR(255) UNIQUE,
            stripe_price_id        VARCHAR(255),
            plan_tier              VARCHAR(4)   NOT NULL DEFAULT 'P1',
            subscription_status    VARCHAR(64),
            current_period_end     TIMESTAMPTZ,
            created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tba_customer     ON tenant_billing_accounts (stripe_customer_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tba_subscription ON tenant_billing_accounts (stripe_subscription_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tba_plan         ON tenant_billing_accounts (plan_tier);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tba_status       ON tenant_billing_accounts (subscription_status);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS overage_invoices (
            id                     BIGSERIAL    PRIMARY KEY,
            tenant_id              VARCHAR(64)  NOT NULL,
            billing_period         VARCHAR(7)   NOT NULL,
            plan_tier              VARCHAR(4)   NOT NULL,
            plan_fee               DECIMAL(10,2) NOT NULL,
            included_quota         INTEGER      NOT NULL,
            total_requests         BIGINT       NOT NULL,
            overage_request_count  BIGINT       NOT NULL DEFAULT 0,
            line_items             JSONB        NOT NULL DEFAULT '[]',
            total_overage          DECIMAL(10,2) NOT NULL DEFAULT 0,
            period_total           DECIMAL(10,2) NOT NULL,
            created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, billing_period)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_overage_invoices_period ON overage_invoices (billing_period);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS stripe_webhook_events (
            event_id     VARCHAR(255) PRIMARY KEY,
            event_type   VARCHAR(128) NOT NULL,
            processed_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS stripe_invoices (
            stripe_invoice_id      VARCHAR(255) PRIMARY KEY,
            tenant_id              VARCHAR(64)  NOT NULL,
            stripe_customer_id     VARCHAR(255),
            stripe_subscription_id VARCHAR(255),
            status                 VARCHAR(64),
            currency               VARCHAR(16),
            amount_due             BIGINT,
            amount_paid            BIGINT,
            amount_remaining       BIGINT,
            hosted_invoice_url     TEXT,
            invoice_pdf            TEXT,
            period_start           TIMESTAMPTZ,
            period_end             TIMESTAMPTZ,
            created_at             TIMESTAMPTZ,
            updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_stripe_invoices_tenant       ON stripe_invoices (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_stripe_invoices_customer     ON stripe_invoices (stripe_customer_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_stripe_invoices_subscription ON stripe_invoices (stripe_subscription_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_stripe_invoices_status       ON stripe_invoices (status);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS stripe_overage_invoice_attempts (
            id                   BIGSERIAL    PRIMARY KEY,
            tenant_id            VARCHAR(64)  NOT NULL,
            billing_period       VARCHAR(7)   NOT NULL,
            stripe_invoice_id    VARCHAR(255),
            stripe_invoice_item_id VARCHAR(255),
            overage_requests     BIGINT       NOT NULL DEFAULT 0,
            amount_cents         BIGINT,
            status               VARCHAR(64)  NOT NULL DEFAULT 'pending',
            error                TEXT,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, billing_period)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_stripe_overage_attempts_tenant ON stripe_overage_invoice_attempts (tenant_id);")

    # updated_at triggers for mutable billing tables
    op.execute("DROP TRIGGER IF EXISTS trg_tba_updated ON tenant_billing_accounts;")
    op.execute("CREATE TRIGGER trg_tba_updated BEFORE UPDATE ON tenant_billing_accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();")
    op.execute("DROP TRIGGER IF EXISTS trg_stripe_invoices_updated ON stripe_invoices;")
    op.execute("CREATE TRIGGER trg_stripe_invoices_updated BEFORE UPDATE ON stripe_invoices FOR EACH ROW EXECUTE FUNCTION set_updated_at();")
    op.execute("DROP TRIGGER IF EXISTS trg_stripe_overage_updated ON stripe_overage_invoice_attempts;")
    op.execute("CREATE TRIGGER trg_stripe_overage_updated BEFORE UPDATE ON stripe_overage_invoice_attempts FOR EACH ROW EXECUTE FUNCTION set_updated_at();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_stripe_overage_updated ON stripe_overage_invoice_attempts;")
    op.execute("DROP TRIGGER IF EXISTS trg_stripe_invoices_updated ON stripe_invoices;")
    op.execute("DROP TRIGGER IF EXISTS trg_tba_updated ON tenant_billing_accounts;")
    op.execute("DROP TABLE IF EXISTS stripe_overage_invoice_attempts;")
    op.execute("DROP TABLE IF EXISTS stripe_invoices;")
    op.execute("DROP TABLE IF EXISTS stripe_webhook_events;")
    op.execute("DROP TABLE IF EXISTS overage_invoices;")
    op.execute("DROP TABLE IF EXISTS tenant_billing_accounts;")
