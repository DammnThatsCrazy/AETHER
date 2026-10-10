"""Stablecoin intelligence tables — assets, deployments, observations, aggregates.

Creates the stablecoin intelligence bounded domain:
  - Global reference tables (no tenant_id): stablecoin_assets and
    stablecoin_deployments — the canonical asset registry and its
    per-chain deployments.
  - Tenant-scoped observational tables: on-chain transfer observations,
    support assertions, valuation snapshots, flow aggregates,
    reconciliation records, finality checkpoints, and the
    silver_stablecoin_facts projection table.

Tenant-scoped tables follow the house rules:
  - tenant_id TEXT NOT NULL with an index on (tenant_id)
  - idempotency_key TEXT NOT NULL + UNIQUE (tenant_id, idempotency_key)
  - execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE with a fail-closed
    CHECK (execution_by_aether = FALSE) — read-only observational domain
  - evidence JSONB for provenance
  - every monetary/quantity column is NUMERIC(38, 18)
    (atomic on-chain amounts and block numbers use NUMERIC(38, 0))
  - created_at / updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

Revision ID: 20260708_stablecoin
Revises: 20260708_deriv_runtime
"""
from alembic import op

revision = "20260708_stablecoin"
down_revision = "20260708_deriv_runtime"
branch_labels = None
depends_on = None

# Shared tenant-scoped trailing columns (house rules).
_TENANT_COMMON = """\
  idempotency_key TEXT NOT NULL,
  evidence JSONB,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"""


def upgrade() -> None:
    # -- Global reference: canonical stablecoin assets -------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS stablecoin_assets (
  canonical_asset_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  issuer_entity_id TEXT,
  issuer_name TEXT,
  backing_model TEXT NOT NULL DEFAULT 'unknown',
  pegged_to TEXT NOT NULL DEFAULT 'USD',
  asset_status TEXT NOT NULL DEFAULT 'active',
  risk_classification TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")

    # -- Global reference: per-chain deployments --------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS stablecoin_deployments (
  deployment_id TEXT PRIMARY KEY,
  canonical_asset_id TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  network TEXT NOT NULL,
  token_standard TEXT NOT NULL,
  contract_or_mint TEXT NOT NULL,
  decimals INTEGER NOT NULL CHECK (decimals >= 0 AND decimals <= 36),
  deployment_type TEXT NOT NULL DEFAULT 'unknown',
  bridge_origin_deployment_id TEXT,
  issuer_verified BOOLEAN NOT NULL DEFAULT FALSE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  testnet BOOLEAN NOT NULL DEFAULT FALSE,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ,
  deprecated_at TIMESTAMPTZ,
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (chain_id, contract_or_mint)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_deployments_asset
  ON stablecoin_deployments (canonical_asset_id);
""")

    # -- Tenant-scoped: on-chain observations -------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS stablecoin_observations (
  tenant_id TEXT NOT NULL,
  observation_id TEXT NOT NULL,
  observation_type TEXT NOT NULL,
  deployment_id TEXT NOT NULL,
  canonical_asset_id TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  network TEXT,
  block_number NUMERIC(38, 0),
  block_hash TEXT,
  transaction_hash TEXT NOT NULL,
  log_or_instruction_index INTEGER,
  amount_atomic NUMERIC(38, 0) NOT NULL,
  amount_decimal NUMERIC(38, 18) NOT NULL,
  from_address TEXT,
  to_address TEXT,
  from_wallet_id TEXT,
  to_wallet_id TEXT,
  from_entity_ref JSONB,
  to_entity_ref JSONB,
  counterparty_class TEXT,
  protocol_id TEXT,
  merchant_id TEXT,
  facilitator_id TEXT,
  agent_id TEXT,
  campaign_id TEXT,
  journey_id TEXT,
  session_id TEXT,
  finality_status TEXT NOT NULL DEFAULT 'provisional',
  finalized_at TIMESTAMPTZ,
  classification_confidence NUMERIC(5, 4) NOT NULL DEFAULT 0,
  observed_at TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, observation_id),
  UNIQUE (tenant_id, chain_id, transaction_hash, log_or_instruction_index, observation_type),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_observations_tenant
  ON stablecoin_observations (tenant_id);
CREATE INDEX IF NOT EXISTS ix_stablecoin_observations_deployment_observed
  ON stablecoin_observations (tenant_id, deployment_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_stablecoin_observations_finality
  ON stablecoin_observations (tenant_id, finality_status);
""")

    # -- Tenant-scoped: support assertions -------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS stablecoin_support_assertions (
  tenant_id TEXT NOT NULL,
  assertion_id TEXT NOT NULL,
  subject_entity_ref JSONB NOT NULL,
  deployment_id TEXT NOT NULL,
  capability TEXT NOT NULL,
  support_status TEXT NOT NULL,
  environment TEXT NOT NULL DEFAULT 'production',
  evidence_type TEXT NOT NULL,
  evidence_reference TEXT,
  first_observed_at TIMESTAMPTZ,
  last_observed_at TIMESTAMPTZ,
  successful_observation_count INTEGER NOT NULL DEFAULT 0,
  failed_observation_count INTEGER NOT NULL DEFAULT 0,
  confidence NUMERIC(5, 4) NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ,
{_TENANT_COMMON},
  UNIQUE (tenant_id, assertion_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_support_assertions_tenant
  ON stablecoin_support_assertions (tenant_id);
""")

    # -- Tenant-scoped: valuation snapshots --------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS stablecoin_valuation_snapshots (
  tenant_id TEXT NOT NULL,
  valuation_id TEXT NOT NULL,
  deployment_id TEXT NOT NULL,
  price_usd NUMERIC(38, 18) NOT NULL,
  peg_deviation_bps NUMERIC(38, 18) NOT NULL,
  peg_status TEXT NOT NULL,
  source TEXT NOT NULL,
  source_record_id TEXT,
  observed_at TIMESTAMPTZ NOT NULL,
  stale_after TIMESTAMPTZ,
{_TENANT_COMMON},
  UNIQUE (tenant_id, valuation_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_valuation_snapshots_tenant
  ON stablecoin_valuation_snapshots (tenant_id);
CREATE INDEX IF NOT EXISTS ix_stablecoin_valuation_snapshots_deployment_observed
  ON stablecoin_valuation_snapshots (tenant_id, deployment_id, observed_at);
""")

    # -- Tenant-scoped: flow aggregates ---------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS stablecoin_flow_aggregates (
  tenant_id TEXT NOT NULL,
  flow_aggregate_id TEXT NOT NULL,
  canonical_asset_id TEXT NOT NULL,
  deployment_id TEXT,
  chain_id TEXT,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  direction TEXT NOT NULL,
  gross_transfer_volume NUMERIC(38, 18) NOT NULL DEFAULT 0,
  finalized_payment_volume NUMERIC(38, 18) NOT NULL DEFAULT 0,
  transfer_count INTEGER NOT NULL DEFAULT 0,
  unique_senders INTEGER NOT NULL DEFAULT 0,
  unique_recipients INTEGER NOT NULL DEFAULT 0,
  metric_version TEXT NOT NULL,
  materialized_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, flow_aggregate_id),
  UNIQUE (tenant_id, canonical_asset_id, deployment_id, chain_id, window_start, window_end, direction, metric_version),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_flow_aggregates_tenant
  ON stablecoin_flow_aggregates (tenant_id);
""")

    # -- Tenant-scoped: reconciliation records --------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS stablecoin_reconciliation_records (
  tenant_id TEXT NOT NULL,
  reconciliation_id TEXT NOT NULL,
  observation_id TEXT,
  transaction_hash TEXT,
  status TEXT NOT NULL,
  expected_amount NUMERIC(38, 18),
  observed_amount NUMERIC(38, 18),
  difference NUMERIC(38, 18),
  sources_compared JSONB NOT NULL DEFAULT '[]'::jsonb,
  resolved_at TIMESTAMPTZ,
  resolution_note TEXT,
{_TENANT_COMMON},
  UNIQUE (tenant_id, reconciliation_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_reconciliation_records_tenant
  ON stablecoin_reconciliation_records (tenant_id);
""")

    # -- Tenant-scoped: finality checkpoints ----------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS stablecoin_finality_checkpoints (
  tenant_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  confirmed_block_number NUMERIC(38, 0) NOT NULL,
  confirmed_block_hash TEXT,
  confirmation_horizon INTEGER NOT NULL,
  advanced_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, checkpoint_id),
  UNIQUE (tenant_id, chain_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_stablecoin_finality_checkpoints_tenant
  ON stablecoin_finality_checkpoints (tenant_id);
""")

    # -- Silver projection: stablecoin facts ----------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS silver_stablecoin_facts (
  fact_id UUID NOT NULL DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  source_event_id TEXT,
  entity_id TEXT,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  payload JSONB,
  deployment_id TEXT,
  canonical_asset_id TEXT,
  chain_id TEXT,
  amount_decimal NUMERIC(38, 18),
  finality_status TEXT,
{_TENANT_COMMON},
  PRIMARY KEY (tenant_id, fact_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_silver_stablecoin_facts_tenant
  ON silver_stablecoin_facts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_silver_stablecoin_facts_entity
  ON silver_stablecoin_facts (tenant_id, entity_id);
CREATE INDEX IF NOT EXISTS ix_silver_stablecoin_facts_event_occurred
  ON silver_stablecoin_facts (tenant_id, event_type, occurred_at);
""")


def downgrade() -> None:
    tables = [
        "stablecoin_assets",
        "stablecoin_deployments",
        "stablecoin_observations",
        "stablecoin_support_assertions",
        "stablecoin_valuation_snapshots",
        "stablecoin_flow_aggregates",
        "stablecoin_reconciliation_records",
        "stablecoin_finality_checkpoints",
        "silver_stablecoin_facts",
    ]
    for table in reversed(tables):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
