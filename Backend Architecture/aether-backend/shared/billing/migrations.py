"""Aether Billing — SQL migration helpers.

Idempotent CREATE statements for billing tables. Invoked at app startup
when a database pool is available.
"""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.billing.migrations")

OVERAGE_INVOICES_SQL = """
CREATE TABLE IF NOT EXISTS overage_invoices (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    billing_period VARCHAR(7) NOT NULL,
    plan_tier VARCHAR(4) NOT NULL,
    plan_fee DECIMAL(10, 2) NOT NULL,
    included_quota INTEGER NOT NULL,
    total_requests BIGINT NOT NULL,
    overage_request_count BIGINT NOT NULL DEFAULT 0,
    line_items JSONB NOT NULL DEFAULT '[]',
    total_overage DECIMAL(10, 2) NOT NULL DEFAULT 0,
    period_total DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, billing_period)
);
CREATE INDEX IF NOT EXISTS idx_overage_invoices_period
    ON overage_invoices(billing_period);
"""

TENANT_BILLING_ACCOUNTS_SQL = """
CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
    tenant_id VARCHAR(64) PRIMARY KEY,
    contact_email VARCHAR(255),
    stripe_customer_id VARCHAR(255) UNIQUE,
    stripe_subscription_id VARCHAR(255) UNIQUE,
    stripe_price_id VARCHAR(255),
    plan_tier VARCHAR(4) NOT NULL DEFAULT 'P1',
    subscription_status VARCHAR(64),
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tenant_billing_accounts_customer
    ON tenant_billing_accounts(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_tenant_billing_accounts_subscription
    ON tenant_billing_accounts(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_tenant_billing_accounts_plan
    ON tenant_billing_accounts(plan_tier);
CREATE INDEX IF NOT EXISTS idx_tenant_billing_accounts_status
    ON tenant_billing_accounts(subscription_status);
"""

STRIPE_WEBHOOK_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id VARCHAR(255) PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

STRIPE_INVOICES_SQL = """
CREATE TABLE IF NOT EXISTS stripe_invoices (
    stripe_invoice_id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    status VARCHAR(64),
    currency VARCHAR(16),
    amount_due BIGINT,
    amount_paid BIGINT,
    amount_remaining BIGINT,
    hosted_invoice_url TEXT,
    invoice_pdf TEXT,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stripe_invoices_tenant
    ON stripe_invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stripe_invoices_customer
    ON stripe_invoices(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_stripe_invoices_subscription
    ON stripe_invoices(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_stripe_invoices_status
    ON stripe_invoices(status);
"""

STRIPE_OVERAGE_INVOICE_ATTEMPTS_SQL = """
CREATE TABLE IF NOT EXISTS stripe_overage_invoice_attempts (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    billing_period VARCHAR(7) NOT NULL,
    stripe_invoice_id VARCHAR(255),
    stripe_invoice_item_id VARCHAR(255),
    overage_requests BIGINT NOT NULL DEFAULT 0,
    amount_cents BIGINT,
    status VARCHAR(64) NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, billing_period)
);
CREATE INDEX IF NOT EXISTS idx_stripe_overage_invoice_attempts_tenant
    ON stripe_overage_invoice_attempts(tenant_id);
"""


async def ensure_billing_tables(pool: Any) -> None:
    """Apply idempotent billing schema. Safe to call repeatedly."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(OVERAGE_INVOICES_SQL)
            await conn.execute(TENANT_BILLING_ACCOUNTS_SQL)
            await conn.execute(STRIPE_WEBHOOK_EVENTS_SQL)
            await conn.execute(STRIPE_INVOICES_SQL)
            await conn.execute(STRIPE_OVERAGE_INVOICE_ATTEMPTS_SQL)
        logger.info("Billing tables ensured")
    except Exception as e:
        logger.warning(f"ensure_billing_tables failed: {e}")
