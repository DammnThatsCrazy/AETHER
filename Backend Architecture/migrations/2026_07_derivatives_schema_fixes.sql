-- Aether Derivatives Intelligence — schema correctness fixes.
-- Addresses P2 issues raised in release-readiness review:
--   1. Compound FK: derivatives_markets must enforce venue_deployment belongs to venue
--   2. Compound FK: derivatives_trading_accounts same enforcement for nullable deployment
--   3. Evidence envelope: JSONB column on orders/fills/positions for observation provenance
--   4. Account uniqueness scope: unique key must include venue_deployment_id not venue_id
--      (same external_account_ref is valid on mainnet vs testnet of the same venue)

-- ── 1. Compound FK support on derivatives_venue_deployments ────────────────
-- venue_deployment_id is already a PK so (venue_id, venue_deployment_id) is always unique.
-- Expose it as a named unique constraint so derivative tables can reference both columns.
ALTER TABLE derivatives_venue_deployments
  ADD CONSTRAINT uq_derivatives_venue_deployments_venue_dep
  UNIQUE (venue_id, venue_deployment_id);

-- ── 2. Compound FK on derivatives_markets ─────────────────────────────────
-- The existing independent FKs on venue_id and venue_deployment_id independently
-- reference correct parent rows but allow cross-venue combinations (venue_id='A',
-- venue_deployment_id=a deployment of 'B').  Replace with a compound FK.
ALTER TABLE derivatives_markets
  DROP CONSTRAINT IF EXISTS derivatives_markets_venue_id_fkey,
  DROP CONSTRAINT IF EXISTS derivatives_markets_venue_deployment_id_fkey;

ALTER TABLE derivatives_markets
  ADD CONSTRAINT fk_derivatives_markets_venue_dep
  FOREIGN KEY (venue_id, venue_deployment_id)
  REFERENCES derivatives_venue_deployments (venue_id, venue_deployment_id);

-- ── 3. Compound FK on derivatives_trading_accounts ────────────────────────
-- venue_deployment_id is nullable here; enforce consistency only when set.
-- PostgreSQL NULLs are not matched by FK checks so a partial index + constraint is used.
ALTER TABLE derivatives_trading_accounts
  DROP CONSTRAINT IF EXISTS derivatives_trading_accounts_venue_deployment_id_fkey;

-- When venue_deployment_id is not null it must belong to the stated venue_id.
ALTER TABLE derivatives_trading_accounts
  ADD CONSTRAINT fk_derivatives_ta_venue_dep
  FOREIGN KEY (venue_id, venue_deployment_id)
  REFERENCES derivatives_venue_deployments (venue_id, venue_deployment_id);

-- ── 4. Fix account uniqueness scope ───────────────────────────────────────
-- The same external account ref on mainnet vs testnet of the same venue must
-- be representable as distinct rows.  Scope by deployment, not by venue alone.
ALTER TABLE derivatives_trading_accounts
  DROP CONSTRAINT IF EXISTS derivatives_trading_accounts_tenant_id_venue_id_external_accou_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_derivatives_ta_per_deployment
  ON derivatives_trading_accounts (tenant_id, COALESCE(venue_deployment_id, venue_id), external_account_ref);

-- ── 5. Evidence envelope columns ──────────────────────────────────────────
-- Provenance and evidence for orders, fills, and positions so downstream
-- Noesis queries can surface confidence / source information.
ALTER TABLE derivatives_orders
  ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE derivatives_fills
  ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE derivatives_positions
  ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;
