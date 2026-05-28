"""
Aether — Gold Tier: Plaid Financial Account Schema
Bank and brokerage accounts connected via Plaid Link.
Requires 'credit' consent purpose for balance data.
"""

from __future__ import annotations

GOLD_PLAID_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS gold_plaid_accounts (
    entity_id           String,
    tenant_id           String,
    account_id          String,       -- Plaid account_id
    plaid_item_id       String,       -- Plaid item (institution link)
    institution_name    String,
    institution_id      Nullable(String),
    account_type        LowCardinality(String),  -- checking, savings, credit_card, mortgage, student_loan, brokerage, ira, 401k, other
    account_subtype     Nullable(String),
    balance_current_usd Decimal(18, 6),
    balance_available_usd Nullable(Decimal(18, 6)),
    balance_limit_usd   Nullable(Decimal(18, 6)),
    currency_code       LowCardinality(String),
    last_sync_at        DateTime
)
ENGINE = ReplacingMergeTree(last_sync_at)
ORDER BY (tenant_id, entity_id, account_id)
TTL last_sync_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

GOLD_PLAID_TRANSACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS gold_plaid_transactions (
    entity_id           String,
    tenant_id           String,
    transaction_id      String,       -- Plaid transaction_id
    account_id          String,
    date                Date,
    amount_usd          Decimal(18, 6),
    direction           LowCardinality(String),  -- credit or debit
    category            Nullable(String),        -- Plaid primary category
    sub_category        Nullable(String),
    merchant_name       Nullable(String),
    merchant_entity_id  Nullable(String),
    status              LowCardinality(String),  -- posted, pending
    ingested_at         DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(date)
ORDER BY (tenant_id, entity_id, account_id, date, transaction_id)
TTL date + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""
