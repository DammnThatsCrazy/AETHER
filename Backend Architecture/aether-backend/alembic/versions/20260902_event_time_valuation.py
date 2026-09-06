"""Event-time valuation persistence — price observations, snapshots, policies.

Creates the three valuation persistence tables for the event-time valuation
engine (services/valuation, financial-normalization WP3 lane C3-VALUATION-PERSIST,
W2 engine core + this persistence surface):

  1. valuation_price_observations — GLOBAL (NO tenant_id) append-only market
     price observations. Prices are objective market facts, not tenant
     observations, so they carry no tenant scope and no execution_by_aether.
     Money is NUMERIC(38, 18); the producer-set event instant (``observed_at``)
     and ``received_at`` are stored as canonical UTC ISO-8601 TEXT columns (the
     contract models carry ``str`` instants and the in-memory/local typed-repo
     backend must round-trip byte-identical rows to production), matching the
     W2 registry precedent for contract-shape time fields. The freshness window
     is a typed INTEGER column. ``observation_id`` is the deterministic
     content-hash natural key (sha256 over asset/deployment/provider/quote/
     observed_at/source/source_record_id), so re-observing the same fact is an
     idempotent replay. Two partial UNIQUE indexes encode the ingest natural-key
     semantics exactly (see services/valuation/ingest.py::observation_natural_key):
       - provider + source_record_id + observed_at, when source_record_id is
         authoritative provenance;
       - provider + asset_id + deployment + quote + observed_at + source when
         the source identity alone distinguishes the fact.
     A trailing ``data JSONB`` catch-all column carries any future provenance.

  2. valuation_snapshots — TENANT-scoped append-only immutable valuation
     snapshots. ``valuation_id`` is the engine's deterministic content hash and
     is the PRIMARY KEY (re-valuing identical inputs at the same effective_at
     reproduces the identical id — replay-safe). ``reporting_amount`` is
     NUMERIC(38, 18) NULLABLE: NULL means UNAVAILABLE and is never coerced to 0.
     ``economic_role`` / ``valuation_basis`` / ``price_status`` /
     ``valuation_method`` CHECK constraints quote the services/valuation/models.py
     frozensets byte-for-byte. The economic fact columns are immutable; the ONLY
     ever-updatable columns are the correction back-pointers and status
     (``supersedes_snapshot_id`` / ``superseded_by_snapshot_id`` / ``status``) —
     a correction APPENDS a new superseding snapshot and flips the superseded
     row's status; the economic fact is never UPDATE-ed in place. House
     observational rules apply: idempotency_key + UNIQUE (tenant_id,
     idempotency_key), execution_by_aether always FALSE (fail-closed CHECK),
     evidence JSONB provenance, created_at/updated_at server defaults.

  3. tenant_value_policies — mutable current-state per-tenant reporting policy
     (which reporting assets are allowed, which named provider-chain policy
     governs sourcing, staleness threshold, fallback). Single row per tenant
     (tenant_id PRIMARY KEY); policy_version bumps monotonically on update and
     is carried onto snapshots as provenance.

Additive create-only migration (no drops/alters) — no migration-safety
allowlist entry needed.

Revision ID: 20260902_event_time_valuation
Revises: 20260902_universal_asset_registry
"""
from alembic import op

revision = "20260902_event_time_valuation"
down_revision = "20260902_universal_asset_registry"
branch_labels = None
depends_on = None

# ── Enum member lists (mirror services/valuation/models.py frozensets) ───────

_ECONOMIC_ROLES = (
    "payment", "settlement", "charge", "fee", "cost", "revenue",
    "refund", "reversal", "dispute", "liability", "asset_holding",
    "exposure", "compensation", "unknown",
)
_PRICE_STATUSES = (
    "normal", "provider_conflict", "stale_rate", "missing_rate", "outlier",
    "fallback", "manual", "unavailable",
)
_VALUATION_BASIS = (
    "transaction_time", "event_time", "settlement_time", "observation_time",
)
_VALUATION_METHODS = (
    "fiat_identity", "fx_rate", "market_price", "provider_reported",
    "stablecoin_peg_verified", "manual", "unavailable",
    "oracle", "venue_exec", "primary_market", "stablecoin_peg",
)
# Snapshot immutability carve-out: a snapshot is 'current' until a correction
# appends a superseding snapshot and flips it to 'superseded'.
_SNAPSHOT_STATUSES = ("current", "superseded")


def _check_list(values) -> str:
    """Render a Python tuple as a SQL IN-list of single-quoted literals."""
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # -- Global append-only: market price observations -------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS valuation_price_observations (
  observation_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  deployment_id TEXT,
  provider TEXT NOT NULL,
  quote_asset_id TEXT NOT NULL,
  price NUMERIC(38, 18) NOT NULL,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL,
  source_record_id TEXT,
  freshness_window_seconds INTEGER CHECK (freshness_window_seconds IS NULL OR freshness_window_seconds >= 1),
  received_at TEXT NOT NULL,
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_valuation_price_observations_asset_provider_observed
  ON valuation_price_observations (asset_id, provider, observed_at);
CREATE INDEX IF NOT EXISTS ix_valuation_price_observations_deployment_provider_observed
  ON valuation_price_observations (asset_id, deployment_id, provider, observed_at);
CREATE INDEX IF NOT EXISTS ix_valuation_price_observations_quote_observed
  ON valuation_price_observations (quote_asset_id, observed_at);
""")

    # Natural-key dedupe indexes — exact mirror of ingest.observation_natural_key.
    op.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uq_valuation_price_observations_source_record
  ON valuation_price_observations (provider, source_record_id, observed_at)
  WHERE source_record_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_valuation_price_observations_source_identity
  ON valuation_price_observations (provider, asset_id, COALESCE(deployment_id, ''), quote_asset_id, observed_at, source)
  WHERE source_record_id IS NULL;
""")

    # -- Tenant-scoped append-only: valuation snapshots --------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS valuation_snapshots (
  valuation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  canonical_asset_id TEXT,
  deployment_id TEXT,
  economic_role TEXT NOT NULL DEFAULT 'unknown'
    CHECK (economic_role IN ({_check_list(_ECONOMIC_ROLES)})),
  native_amount NUMERIC(38, 18) NOT NULL,
  native_currency TEXT NOT NULL,
  reporting_asset_id TEXT NOT NULL,
  reporting_amount NUMERIC(38, 18),
  valuation_basis TEXT NOT NULL
    CHECK (valuation_basis IN ({_check_list(_VALUATION_BASIS)})),
  price_status TEXT NOT NULL
    CHECK (price_status IN ({_check_list(_PRICE_STATUSES)})),
  valuation_method TEXT NOT NULL
    CHECK (valuation_method IN ({_check_list(_VALUATION_METHODS)})),
  provider TEXT,
  conversion_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence JSONB,
  registry_version TEXT,
  policy_version TEXT,
  price_observation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  supersedes_snapshot_id TEXT,
  superseded_by_snapshot_id TEXT,
  status TEXT NOT NULL DEFAULT 'current'
    CHECK (status IN ({_check_list(_SNAPSHOT_STATUSES)})),
  computed_at TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_tenant
  ON valuation_snapshots (tenant_id);
CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_tenant_effective
  ON valuation_snapshots (tenant_id, effective_at);
CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_tenant_asset_effective
  ON valuation_snapshots (tenant_id, canonical_asset_id, effective_at);
CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_status
  ON valuation_snapshots (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_supersedes
  ON valuation_snapshots (supersedes_snapshot_id);
""")

    # -- Mutable current-state: tenant value policies ------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS tenant_value_policies (
  tenant_id TEXT PRIMARY KEY,
  policy_version TEXT NOT NULL,
  reporting_asset_id TEXT NOT NULL DEFAULT 'fiat:USD',
  allowed_reporting_asset_ids JSONB NOT NULL DEFAULT '["fiat:USD"]'::jsonb,
  provider_chain_policy TEXT NOT NULL DEFAULT 'default',
  stale_threshold_seconds INTEGER CHECK (stale_threshold_seconds IS NULL OR stale_threshold_seconds >= 1),
  fallback_allowed BOOLEAN NOT NULL DEFAULT FALSE,
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")


def downgrade() -> None:
    tables = [
        "tenant_value_policies",
        "valuation_snapshots",
        "valuation_price_observations",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
