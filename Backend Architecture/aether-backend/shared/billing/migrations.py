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


async def ensure_billing_tables(pool: Any) -> None:
    """Apply idempotent billing schema. Safe to call repeatedly."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(OVERAGE_INVOICES_SQL)
        logger.info("Billing tables ensured")
    except Exception as e:
        logger.warning(f"ensure_billing_tables failed: {e}")
