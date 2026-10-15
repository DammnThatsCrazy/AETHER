"""Derivatives runtime tables — strategies, economics, market state, silver facts.

Extends the derivatives foundation (revision 20260708_deriv_adopt) with the
runtime layer: strategy registry and versioning, execution decision journal,
funding / fee / liquidation economics, price observations, risk policies,
PnL snapshots, stream gap tracking, and the silver_derivatives_facts
projection table.

All tables are tenant-scoped and follow the derivatives house rules:
  - tenant_id TEXT NOT NULL with an index on (tenant_id)
  - idempotency_key TEXT NOT NULL + UNIQUE (tenant_id, idempotency_key)
  - execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE with a fail-closed
    CHECK (execution_by_aether = FALSE) — read-only observational domain
  - evidence JSONB for provenance
  - every monetary/quantity column is NUMERIC(38, 18)
  - created_at / updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

Revision ID: 20260708_deriv_runtime
Revises: 20260708_deriv_adopt
"""
from alembic import op

revision = "20260708_deriv_runtime"
down_revision = "20260708_deriv_adopt"
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
    # -- Strategy registry ----------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_strategies (
  tenant_id TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  owner_ref JSONB,
  name TEXT NOT NULL,
  data JSONB,
{_TENANT_COMMON},
  UNIQUE (tenant_id, strategy_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_strategies_tenant
  ON derivatives_strategies (tenant_id);
""")

    # -- Strategy versions ------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_strategy_versions (
  tenant_id TEXT NOT NULL,
  strategy_version_id TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  version TEXT NOT NULL,
  config JSONB,
  effective_from TIMESTAMPTZ,
{_TENANT_COMMON},
  UNIQUE (tenant_id, strategy_version_id),
  UNIQUE (tenant_id, strategy_id, version),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_strategy_versions_tenant
  ON derivatives_strategy_versions (tenant_id);
""")

    # -- Execution decision journal ----------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_execution_decisions (
  tenant_id TEXT NOT NULL,
  execution_decision_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  strategy_version_id TEXT,
  order_id TEXT,
  decision_at TIMESTAMPTZ NOT NULL,
  data JSONB,
{_TENANT_COMMON},
  UNIQUE (tenant_id, execution_decision_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_execution_decisions_tenant
  ON derivatives_execution_decisions (tenant_id);
""")

    # -- Funding payments ----------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_funding_payments (
  tenant_id TEXT NOT NULL,
  funding_payment_id TEXT NOT NULL,
  position_id TEXT,
  trading_account_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL,
  amount NUMERIC(38, 18) NOT NULL,
  asset_id TEXT NOT NULL,
  settled_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, funding_payment_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_funding_payments_tenant
  ON derivatives_funding_payments (tenant_id);
CREATE INDEX IF NOT EXISTS ix_derivatives_funding_payments_account_settled
  ON derivatives_funding_payments (tenant_id, trading_account_id, settled_at);
""")

    # -- Trading fees -----------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_fees (
  tenant_id TEXT NOT NULL,
  trading_fee_id TEXT NOT NULL,
  fee_type TEXT NOT NULL,
  amount NUMERIC(38, 18) NOT NULL,
  asset_id TEXT NOT NULL,
  related_ref JSONB,
  charged_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, trading_fee_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_fees_tenant
  ON derivatives_fees (tenant_id);
""")

    # -- Liquidation events ---------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_liquidations (
  tenant_id TEXT NOT NULL,
  liquidation_event_id TEXT NOT NULL,
  position_id TEXT NOT NULL,
  liquidation_type TEXT NOT NULL,
  size NUMERIC(38, 18) NOT NULL,
  price NUMERIC(38, 18) NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, liquidation_event_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_liquidations_tenant
  ON derivatives_liquidations (tenant_id);
""")

    # -- Price observations ------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_price_observations (
  tenant_id TEXT NOT NULL,
  price_observation_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL,
  price_type TEXT NOT NULL,
  price NUMERIC(38, 18) NOT NULL,
  source_finality TEXT NOT NULL DEFAULT 'provisional',
  observed_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, price_observation_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_price_observations_tenant
  ON derivatives_price_observations (tenant_id);
CREATE INDEX IF NOT EXISTS ix_derivatives_price_observations_market_observed
  ON derivatives_price_observations (tenant_id, canonical_market_id, observed_at);
""")

    # -- Risk policies (read-only authority) ------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_risk_policies (
  tenant_id TEXT NOT NULL,
  risk_policy_id TEXT NOT NULL,
  subject_ref JSONB NOT NULL,
  severity TEXT NOT NULL,
  max_leverage NUMERIC(38, 18),
  max_notional NUMERIC(38, 18),
  loss_limit NUMERIC(38, 18),
  authority_type TEXT NOT NULL DEFAULT 'read_only',
{_TENANT_COMMON},
  UNIQUE (tenant_id, risk_policy_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_risk_policies_tenant
  ON derivatives_risk_policies (tenant_id);
""")

    # -- PnL snapshots ---------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_pnl_snapshots (
  tenant_id TEXT NOT NULL,
  pnl_snapshot_id TEXT NOT NULL,
  trading_account_id TEXT NOT NULL,
  canonical_market_id TEXT,
  realized_pnl NUMERIC(38, 18) NOT NULL DEFAULT 0,
  unrealized_pnl NUMERIC(38, 18) NOT NULL DEFAULT 0,
  gross_exposure NUMERIC(38, 18) NOT NULL DEFAULT 0,
  net_exposure NUMERIC(38, 18) NOT NULL DEFAULT 0,
  accounting_method TEXT NOT NULL,
  as_of TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, pnl_snapshot_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_pnl_snapshots_tenant
  ON derivatives_pnl_snapshots (tenant_id);
CREATE INDEX IF NOT EXISTS ix_derivatives_pnl_snapshots_account_asof
  ON derivatives_pnl_snapshots (tenant_id, trading_account_id, as_of);
""")

    # -- Stream gap tracking -----------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS derivatives_stream_gaps (
  tenant_id TEXT NOT NULL,
  stream_gap_id TEXT NOT NULL,
  venue_id TEXT NOT NULL,
  canonical_market_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  expected_sequence BIGINT NOT NULL,
  received_sequence BIGINT NOT NULL,
  detected_at TIMESTAMPTZ NOT NULL,
  recovered_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'open',
{_TENANT_COMMON},
  UNIQUE (tenant_id, stream_gap_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_derivatives_stream_gaps_tenant
  ON derivatives_stream_gaps (tenant_id);
""")

    # -- Silver projection: derivatives facts -------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS silver_derivatives_facts (
  fact_id UUID NOT NULL DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  source_event_id TEXT,
  entity_id TEXT,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  payload JSONB,
  trading_account_id TEXT,
  canonical_market_id TEXT,
  amount NUMERIC(38, 18),
  asset_id TEXT,
{_TENANT_COMMON},
  PRIMARY KEY (tenant_id, fact_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_silver_derivatives_facts_tenant
  ON silver_derivatives_facts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_silver_derivatives_facts_entity
  ON silver_derivatives_facts (tenant_id, entity_id);
CREATE INDEX IF NOT EXISTS ix_silver_derivatives_facts_event_occurred
  ON silver_derivatives_facts (tenant_id, event_type, occurred_at);
""")


def downgrade() -> None:
    tables = [
        "derivatives_strategies",
        "derivatives_strategy_versions",
        "derivatives_execution_decisions",
        "derivatives_funding_payments",
        "derivatives_fees",
        "derivatives_liquidations",
        "derivatives_price_observations",
        "derivatives_risk_policies",
        "derivatives_pnl_snapshots",
        "derivatives_stream_gaps",
        "silver_derivatives_facts",
    ]
    for table in reversed(tables):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
