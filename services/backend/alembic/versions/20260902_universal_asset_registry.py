"""Universal asset registry — canonical assets, chains, deployments, aliases.

Creates the canonical universal asset registry (financial-normalization
WP2/WP3, lane C2-REGISTRY) under the services/assets domain:

  - Global reference tables (NO tenant_id): registry_assets,
    registry_chains, registry_fiat_currencies, registry_asset_deployments,
    registry_asset_aliases, registry_asset_capabilities, and registry_meta
    (single-row deterministic registry_version ledger). These are
    authoritative registry data — they carry NO execution_by_aether and are
    never tenant-mutable.
  - One tenant-scoped observational table: registry_unresolved_asset_refs —
    records raw references that could not be resolved. Unknown is explicit
    and recorded, never silently guessed. This table follows the
    observational house rules:
      - tenant_id TEXT NOT NULL with an index on (tenant_id)
      - UNIQUE (tenant_id, idempotency_key)
      - execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE with a fail-closed
        CHECK (execution_by_aether = FALSE) — read-only observational domain
      - evidence JSONB for provenance
      - created_at / updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

Registry reference tables mirror the house template (20260708_stablecoin):
typed real columns, a trailing ``data JSONB`` catch-all column, explicit
created_at/updated_at, and explicit CREATE INDEX IF NOT EXISTS lines.
Optional registry time fields (first_seen_at/last_seen_at/deprecated_at) are
TEXT because the Pydantic contracts model them as Optional[str] ISO strings;
the authoritative created_at/updated_at stay TIMESTAMPTZ server defaults.
No monetary column exists on the registry trunk, so no NUMERIC(38,18) is
declared here (money stays NUMERIC(38,18) wherever it appears downstream).

Additive create-only migration (no drops/alters) — no migration-safety
allowlist entry needed.

Revision ID: 20260902_universal_asset_registry
Revises: 20260904_social_silver_facts
"""
from alembic import op

# Re-parented on re-cut onto the PR #608 lineage: this lane was authored against
# 20260901_credential_turnkey_tables, which the social360 stack already extends
# past (20260904_merge_communication360_head -> 20260904_social_silver_facts);
# down_revision now names the current head so the merged tree keeps a single
# Alembic head. Pure additive registry/valuation tables — no schema overlap
# with the merged revisions.
revision = "20260902_universal_asset_registry"
down_revision = "20260904_social_silver_facts"
branch_labels = None
depends_on = None

# ── Enum member lists (mirror services/assets/models.py frozensets) ─────────

_ASSET_KINDS = ("fiat", "crypto", "stablecoin", "token")
_CHAIN_STATUSES = ("active", "deprecated", "paused", "under_review")
_DEPLOYMENT_TYPES = (
    "canonical", "bridged", "wrapped", "synthetic", "deprecated",
    "counterfeit_suspected", "unknown",
)
_ALIAS_VERIFICATION = ("verified", "unverified", "contested", "retired")
_UNRESOLVED_REASONS = (
    "unknown_symbol", "ambiguous_symbol", "unknown_chain", "unknown_contract",
    "no_registry_entry", "malformed_reference",
)


def _check_list(values) -> str:
    """Render a Python tuple as a SQL IN-list of single-quoted literals."""
    return ", ".join(f"'{v}'" for v in values)


def _global_tail() -> str:
    return "data JSONB,\n  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),\n  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"


def upgrade() -> None:
    # -- Global reference: canonical assets -----------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_assets (
  asset_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ({_check_list(_ASSET_KINDS)})),
  symbol TEXT NOT NULL,
  name TEXT,
  issuer TEXT,
  display_decimals INTEGER CHECK (display_decimals >= 0 AND display_decimals <= 36),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ({_check_list(_CHAIN_STATUSES)})),
  {_global_tail()}
);
CREATE INDEX IF NOT EXISTS ix_registry_assets_symbol
  ON registry_assets (symbol);
CREATE INDEX IF NOT EXISTS ix_registry_assets_kind_symbol
  ON registry_assets (kind, symbol);
""")

    # -- Global reference: chains ------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_chains (
  chain_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  network TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ({_check_list(_CHAIN_STATUSES)})),
  vm TEXT NOT NULL,
  native_currency TEXT NOT NULL,
  first_seen_at TEXT,
  last_seen_at TEXT,
  deprecated_at TEXT,
  {_global_tail()}
);
CREATE INDEX IF NOT EXISTS ix_registry_chains_vm
  ON registry_chains (vm);
""")

    # -- Global reference: ISO 4217 fiat metadata ---------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_fiat_currencies (
  iso_code TEXT PRIMARY KEY,
  numeric_code TEXT NOT NULL CHECK (numeric_code ~ '^[0-9]{{3}}$'),
  minor_units INTEGER NOT NULL CHECK (minor_units >= 0 AND minor_units <= 4),
  name TEXT NOT NULL,
  symbol TEXT NOT NULL,
  {_global_tail()}
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_registry_fiat_numeric_code
  ON registry_fiat_currencies (numeric_code);
""")

    # -- Global reference: per-chain / per-mint deployments -----------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_asset_deployments (
  deployment_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  contract_or_mint TEXT NOT NULL,
  decimals INTEGER NOT NULL CHECK (decimals >= 0 AND decimals <= 36),
  canonical_vs_bridged TEXT NOT NULL DEFAULT 'unknown'
    CHECK (canonical_vs_bridged IN ({_check_list(_DEPLOYMENT_TYPES)})),
  deployment_status TEXT NOT NULL DEFAULT 'active'
    CHECK (deployment_status IN ({_check_list(_CHAIN_STATUSES)})),
  token_standard TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT,
  deprecated_at TEXT,
  {_global_tail()},
  UNIQUE (chain_id, contract_or_mint)
);
CREATE INDEX IF NOT EXISTS ix_registry_asset_deployments_asset
  ON registry_asset_deployments (asset_id);
CREATE INDEX IF NOT EXISTS ix_registry_asset_deployments_chain
  ON registry_asset_deployments (chain_id);
CREATE INDEX IF NOT EXISTS ix_registry_asset_deployments_asset_chain
  ON registry_asset_deployments (asset_id, chain_id);
""")

    # -- Global reference: legacy aliases -> canonical targets ----------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_asset_aliases (
  alias TEXT PRIMARY KEY,
  target_asset_id TEXT NOT NULL,
  target_deployment_id TEXT,
  verification TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification IN ({_check_list(_ALIAS_VERIFICATION)})),
  first_seen_at TEXT,
  last_seen_at TEXT,
  note TEXT,
  {_global_tail()}
);
CREATE INDEX IF NOT EXISTS ix_registry_asset_aliases_target_asset
  ON registry_asset_aliases (target_asset_id);
CREATE INDEX IF NOT EXISTS ix_registry_asset_aliases_target_deployment
  ON registry_asset_aliases (target_deployment_id);
""")

    # -- Global reference: support-capability claims ---------------------------------
    # capability_id is a deterministic sha256 over (asset_id | deployment_id |
    # capability) so one subject+capability always collides on the PK (upsert
    # dedupe) even when asset_id/deployment_id is NULL (Postgres treats NULLs
    # as distinct in UNIQUE columns, so a composite UNIQUE would not dedupe).
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_asset_capabilities (
  capability_id TEXT PRIMARY KEY,
  asset_id TEXT,
  deployment_id TEXT,
  capability TEXT NOT NULL CHECK (capability IN ({_check_list(_DEPLOYMENT_TYPES)})),
  {_global_tail()}
);
CREATE INDEX IF NOT EXISTS ix_registry_asset_capabilities_asset
  ON registry_asset_capabilities (asset_id);
CREATE INDEX IF NOT EXISTS ix_registry_asset_capabilities_deployment
  ON registry_asset_capabilities (deployment_id);
""")

    # -- Tenant-scoped observational: unresolved raw references ----------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_unresolved_asset_refs (
  tenant_id TEXT NOT NULL,
  reference_id TEXT NOT NULL,
  raw_reference TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN ({_check_list(_UNRESOLVED_REASONS)})),
  occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  evidence JSONB,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_registry_unresolved_asset_refs_tenant
  ON registry_unresolved_asset_refs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_registry_unresolved_asset_refs_raw
  ON registry_unresolved_asset_refs (tenant_id, raw_reference);
""")

    # -- Global: single-row deterministic registry_version ledger --------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS registry_meta (
  meta_id TEXT PRIMARY KEY,
  registry_version TEXT NOT NULL,
  algorithm TEXT NOT NULL DEFAULT 'sha256',
  asset_count INTEGER NOT NULL DEFAULT 0,
  chain_count INTEGER NOT NULL DEFAULT 0,
  deployment_count INTEGER NOT NULL DEFAULT 0,
  fiat_count INTEGER NOT NULL DEFAULT 0,
  alias_count INTEGER NOT NULL DEFAULT 0,
  {_global_tail()}
);
""")


def downgrade() -> None:
    tables = [
        "registry_meta",
        "registry_unresolved_asset_refs",
        "registry_asset_capabilities",
        "registry_asset_aliases",
        "registry_asset_deployments",
        "registry_fiat_currencies",
        "registry_chains",
        "registry_assets",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
