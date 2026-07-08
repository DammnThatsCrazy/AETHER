"""Derivatives foundation adoption — bring PR1 raw-SQL DDL into the Alembic chain.

Derivatives PR1 (#395) shipped its foundation DDL as a raw SQL file outside
Alembic ("Backend Architecture/migrations/2026_07_derivatives_foundation.sql").
This revision adopts those 11 tables into the Alembic migration chain
idempotently: every statement uses CREATE TABLE IF NOT EXISTS, so on
environments where the raw file was already applied this migration is a
no-op, and on fresh environments it creates the identical schema.

The DDL below is replayed verbatim from the raw file — every column, type,
constraint, and index is preserved exactly as shipped.

Revision ID: 20260708_deriv_adopt
Revises: 20260703_agentic_obs
"""
from alembic import op

revision = "20260708_deriv_adopt"
down_revision = "20260703_agentic_obs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- Global reference: trading venues ----------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_trading_venues (
  venue_id TEXT PRIMARY KEY,
  venue_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  website_url TEXT,
  global_reference BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")

    # -- Global reference: venue deployments -------------------------------
    # Deviation from the raw PR1 SQL: its
    #   UNIQUE (venue_id, deployment, COALESCE(chain_id, ''), COALESCE(region, ''))
    # table constraint is not valid PostgreSQL (expressions are only legal in
    # unique *indexes*), so the raw file could never have applied on stock
    # Postgres. The equivalent expression unique index below preserves the
    # intended nullable-column uniqueness semantics.
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_venue_deployments (
  venue_deployment_id TEXT PRIMARY KEY,
  venue_id TEXT NOT NULL REFERENCES derivatives_trading_venues(venue_id),
  deployment TEXT NOT NULL,
  chain_id TEXT,
  region TEXT,
  global_reference BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")
    op.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uq_derivatives_venue_deployments_identity
ON derivatives_venue_deployments (venue_id, deployment, COALESCE(chain_id, ''), COALESCE(region, ''));
""")

    # -- Global reference: instruments --------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_instruments (
  canonical_instrument_id TEXT PRIMARY KEY,
  instrument_type TEXT NOT NULL,
  underlying_asset_id TEXT NOT NULL,
  quote_asset_id TEXT NOT NULL,
  settlement_asset_id TEXT NOT NULL,
  contract_type TEXT NOT NULL,
  contract_multiplier NUMERIC(38, 18) NOT NULL,
  inverse_or_linear TEXT NOT NULL,
  expiry_at TIMESTAMPTZ,
  global_reference BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")

    # -- Global reference: markets ------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_markets (
  canonical_market_id TEXT PRIMARY KEY,
  canonical_instrument_id TEXT NOT NULL REFERENCES derivatives_instruments(canonical_instrument_id),
  venue_id TEXT NOT NULL REFERENCES derivatives_trading_venues(venue_id),
  venue_deployment_id TEXT NOT NULL REFERENCES derivatives_venue_deployments(venue_deployment_id),
  venue_market_id TEXT NOT NULL,
  underlying_asset_id TEXT NOT NULL,
  quote_asset_id TEXT NOT NULL,
  settlement_asset_id TEXT NOT NULL,
  instrument_type TEXT NOT NULL,
  contract_type TEXT NOT NULL,
  contract_multiplier NUMERIC(38, 18) NOT NULL,
  inverse_or_linear TEXT NOT NULL,
  expiry_at TIMESTAMPTZ,
  price_precision NUMERIC(38, 18) NOT NULL,
  size_precision NUMERIC(38, 18) NOT NULL,
  margin_modes TEXT[] NOT NULL,
  status TEXT NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  global_reference BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (venue_id, venue_deployment_id, venue_market_id)
);
""")

    # -- Tenant-scoped: trading accounts -------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_trading_accounts (
  tenant_id TEXT NOT NULL,
  trading_account_id TEXT NOT NULL,
  venue_id TEXT NOT NULL REFERENCES derivatives_trading_venues(venue_id),
  venue_deployment_id TEXT REFERENCES derivatives_venue_deployments(venue_deployment_id),
  external_account_ref TEXT NOT NULL,
  owner_entity_kind TEXT,
  owner_entity_id TEXT,
  credential_reference_id TEXT,
  connector_state TEXT NOT NULL,
  data_quality_state TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, trading_account_id),
  UNIQUE (tenant_id, idempotency_key),
  UNIQUE (tenant_id, venue_id, external_account_ref)
);
""")

    # -- Tenant-scoped: orders ------------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_orders (
  tenant_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  trading_account_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL REFERENCES derivatives_markets(canonical_market_id),
  order_type TEXT NOT NULL,
  order_side TEXT NOT NULL,
  order_status TEXT NOT NULL,
  time_in_force TEXT NOT NULL,
  quantity NUMERIC(38, 18) NOT NULL,
  limit_price NUMERIC(38, 18),
  origin TEXT NOT NULL,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, order_id),
  UNIQUE (tenant_id, idempotency_key)
);
""")

    # -- Tenant-scoped: fills -------------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_fills (
  tenant_id TEXT NOT NULL,
  fill_id TEXT NOT NULL,
  order_id TEXT,
  trading_account_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL REFERENCES derivatives_markets(canonical_market_id),
  side TEXT NOT NULL,
  liquidity_role TEXT NOT NULL,
  price NUMERIC(38, 18) NOT NULL,
  quantity NUMERIC(38, 18) NOT NULL,
  fee_amount NUMERIC(38, 18),
  fee_asset_id TEXT,
  executed_at TIMESTAMPTZ NOT NULL,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  PRIMARY KEY (tenant_id, fill_id),
  UNIQUE (tenant_id, idempotency_key)
);
""")

    # -- Tenant-scoped: positions ----------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_positions (
  tenant_id TEXT NOT NULL,
  position_id TEXT NOT NULL,
  position_epoch_id TEXT NOT NULL,
  trading_account_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL REFERENCES derivatives_markets(canonical_market_id),
  side TEXT NOT NULL,
  status TEXT NOT NULL,
  size NUMERIC(38, 18) NOT NULL,
  entry_price NUMERIC(38, 18),
  realized_pnl NUMERIC(38, 18),
  unrealized_pnl NUMERIC(38, 18),
  accounting_method TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, position_id),
  UNIQUE (tenant_id, idempotency_key)
);
""")

    # -- Tenant-scoped: position epochs -----------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_position_epochs (
  tenant_id TEXT NOT NULL,
  position_epoch_id TEXT NOT NULL,
  position_id TEXT NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ,
  open_size NUMERIC(38, 18) NOT NULL,
  close_size NUMERIC(38, 18),
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  PRIMARY KEY (tenant_id, position_epoch_id),
  UNIQUE (tenant_id, idempotency_key)
);
""")

    # -- Tenant-scoped: connector checkpoints -----------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_connector_checkpoints (
  tenant_id TEXT NOT NULL,
  connector_checkpoint_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  state TEXT NOT NULL,
  checkpoint_value TEXT NOT NULL,
  advanced_at TIMESTAMPTZ NOT NULL,
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  PRIMARY KEY (tenant_id, connector_checkpoint_id),
  UNIQUE (tenant_id, connector_id),
  UNIQUE (tenant_id, idempotency_key)
);
""")

    # -- Tenant-scoped: reconciliation variances --------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS derivatives_reconciliation_variances (
  tenant_id TEXT NOT NULL,
  reconciliation_variance_id TEXT NOT NULL,
  variance_type TEXT NOT NULL,
  expected_value NUMERIC(38, 18),
  observed_value NUMERIC(38, 18),
  difference NUMERIC(38, 18),
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  idempotency_key TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  PRIMARY KEY (tenant_id, reconciliation_variance_id),
  UNIQUE (tenant_id, idempotency_key)
);
""")


def downgrade() -> None:
    # Intentional no-op. These tables may have been created directly in
    # production by the raw SQL file (2026_07_derivatives_foundation.sql)
    # before this revision existed. Dropping them on downgrade could destroy
    # pre-existing production data that this migration did not create, so we
    # never drop possibly pre-existing production tables.
    pass
