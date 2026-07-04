-- Aether Derivatives Intelligence PR2 ingestion/accounting foundation.
-- Bronze observations are immutable; Silver facts are normalized and idempotent.

CREATE TABLE IF NOT EXISTS derivatives_bronze_observations (
  tenant_id TEXT NOT NULL,
  bronze_observation_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  deployment TEXT NOT NULL,
  record_type TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  raw_payload JSONB NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  mapping_version TEXT,
  batch_id TEXT,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  PRIMARY KEY (tenant_id, bronze_observation_id),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS derivatives_silver_fill_facts (
  tenant_id TEXT NOT NULL,
  fill_fact_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  deployment TEXT NOT NULL,
  trading_account_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL,
  source_fill_id TEXT NOT NULL,
  order_side TEXT NOT NULL,
  liquidity_role TEXT NOT NULL,
  price NUMERIC(38, 18) NOT NULL,
  quantity NUMERIC(38, 18) NOT NULL,
  fee_amount NUMERIC(38, 18) NOT NULL DEFAULT 0,
  fee_asset_id TEXT,
  executed_at TIMESTAMPTZ NOT NULL,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  PRIMARY KEY (tenant_id, fill_fact_id),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS derivatives_import_quarantine (
  tenant_id TEXT NOT NULL,
  quarantine_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  deployment TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  row_number INTEGER NOT NULL,
  reason TEXT NOT NULL,
  raw_row JSONB NOT NULL,
  mapping_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, quarantine_id),
  UNIQUE (tenant_id, batch_id, row_number)
);

CREATE TABLE IF NOT EXISTS derivatives_connector_health (
  tenant_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  deployment TEXT NOT NULL,
  state TEXT NOT NULL,
  snapshot_lag_seconds INTEGER,
  stream_lag_seconds INTEGER,
  last_error TEXT,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, connector_id)
);
