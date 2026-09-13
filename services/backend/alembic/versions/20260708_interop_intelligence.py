"""Interop intelligence tables — providers, paths, messages, legs, silver facts.

Creates the cross-chain interoperability intelligence bounded domain:
  - Global reference tables (no tenant_id): interop_providers,
    interop_gateways, interop_paths, interop_applications,
    interop_verification_actors, interop_delivery_actors.
  - Tenant-scoped observational tables: canonical interop messages and
    their append-only status transition log, intents, asset legs,
    security policy snapshots, delivery attempts, provider checkpoints,
    reconciliation records, and the silver_interop_facts projection table.

Tenant scoping note: tenant-scoped tables use the sentinel tenant 'public'
for public-scope rows (e.g. messages observed on public infrastructure that
are not attributable to a specific tenant). interop_messages carries an
explicit tenant_scope column ('public' | 'tenant') to make that distinction
queryable.

Tenant-scoped tables follow the house rules:
  - tenant_id TEXT NOT NULL with an index on (tenant_id)
  - idempotency_key TEXT NOT NULL + UNIQUE (tenant_id, idempotency_key)
  - execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE with a fail-closed
    CHECK (execution_by_aether = FALSE) — read-only observational domain
  - evidence JSONB for provenance
  - every monetary/quantity column is NUMERIC(38, 18)
    (atomic amounts and block numbers use NUMERIC(38, 0))
  - created_at / updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

Revision ID: 20260708_interop
Revises: 20260708_stablecoin
"""
from alembic import op

revision = "20260708_interop"
down_revision = "20260708_stablecoin"
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
    # -- Global reference: providers --------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS interop_providers (
  provider_id TEXT PRIMARY KEY,
  provider_kind TEXT NOT NULL,
  display_name TEXT NOT NULL,
  protocol_products JSONB NOT NULL DEFAULT '[]'::jsonb,
  supported_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
  implementation_status TEXT NOT NULL DEFAULT 'scaffolded',
  capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")

    # -- Global reference: gateways ------------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS interop_gateways (
  gateway_id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  network_id TEXT NOT NULL,
  native_chain_id TEXT NOT NULL,
  provider_network_id TEXT,
  gateway_address TEXT NOT NULL,
  gateway_role TEXT NOT NULL DEFAULT 'unknown',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider_id, network_id, gateway_address)
);
""")

    # -- Global reference: paths ------------------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS interop_paths (
  path_id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  source_network_id TEXT NOT NULL,
  destination_network_id TEXT NOT NULL,
  source_gateway_id TEXT,
  destination_gateway_id TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider_id, source_network_id, destination_network_id)
);
""")

    # -- Global reference: applications ---------------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS interop_applications (
  application_id TEXT PRIMARY KEY,
  network_id TEXT NOT NULL,
  contract_address TEXT NOT NULL,
  display_name TEXT,
  owner_entity_ref JSONB,
  provider_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (network_id, contract_address)
);
""")

    # -- Global reference: verification actors ----------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS interop_verification_actors (
  verification_actor_id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  display_name TEXT,
  actor_address TEXT,
  networks JSONB NOT NULL DEFAULT '[]'::jsonb,
  actor_role TEXT NOT NULL DEFAULT 'unknown',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")

    # -- Global reference: delivery actors ------------------------------------------------------
    op.execute("""
CREATE TABLE IF NOT EXISTS interop_delivery_actors (
  delivery_actor_id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  display_name TEXT,
  actor_address TEXT,
  networks JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""")

    # -- Tenant-scoped: canonical interop messages ---------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_messages (
  tenant_id TEXT NOT NULL,
  interop_message_id TEXT NOT NULL,
  tenant_scope TEXT NOT NULL DEFAULT 'public' CHECK (tenant_scope IN ('public', 'tenant')),
  schema_version TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  provider_kind TEXT NOT NULL,
  protocol_product TEXT NOT NULL DEFAULT 'messaging',
  correlation_key TEXT NOT NULL,
  provider_message_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  source JSONB NOT NULL,
  destination JSONB,
  path_id TEXT NOT NULL,
  sequence TEXT,
  payload_hash TEXT,
  payload_type TEXT,
  status TEXT NOT NULL DEFAULT 'discovered',
  provider_native_status TEXT,
  technical_outcome TEXT NOT NULL DEFAULT 'unknown',
  source_observed_at TIMESTAMPTZ,
  source_confirmed_at TIMESTAMPTZ,
  verified_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  executed_at TIMESTAMPTZ,
  settled_at TIMESTAMPTZ,
  terminal_at TIMESTAMPTZ,
  security_snapshot_id TEXT,
  intent_id TEXT,
  fee_total NUMERIC(38, 18),
  fee_asset_id TEXT,
  confidence NUMERIC(5, 4) NOT NULL DEFAULT 0,
  data_freshness TEXT NOT NULL DEFAULT 'unknown',
  provider_extension JSONB,
{_TENANT_COMMON},
  UNIQUE (tenant_id, interop_message_id),
  UNIQUE (tenant_id, provider_kind, correlation_key),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_messages_tenant
  ON interop_messages (tenant_id);
CREATE INDEX IF NOT EXISTS ix_interop_messages_status
  ON interop_messages (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_interop_messages_path
  ON interop_messages (tenant_id, path_id);
CREATE INDEX IF NOT EXISTS ix_interop_messages_provider_status
  ON interop_messages (tenant_id, provider_id, status);
""")

    # -- Tenant-scoped: message status transitions (append-only log) ----------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_message_events (
  tenant_id TEXT NOT NULL,
  transition_id TEXT NOT NULL,
  interop_message_id TEXT NOT NULL,
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  provider_native_stage TEXT,
  observed_at TIMESTAMPTZ NOT NULL,
  evidence_ref TEXT,
{_TENANT_COMMON},
  UNIQUE (tenant_id, transition_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_message_events_tenant
  ON interop_message_events (tenant_id);
CREATE INDEX IF NOT EXISTS ix_interop_message_events_message_observed
  ON interop_message_events (tenant_id, interop_message_id, observed_at);
""")

    # -- Tenant-scoped: intents --------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_intents (
  tenant_id TEXT NOT NULL,
  intent_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  initiator_entity_ref JSONB,
  initiator_address TEXT,
  source_network_id TEXT NOT NULL,
  destination_network_id TEXT NOT NULL,
  requested_asset_id TEXT,
  requested_amount NUMERIC(38, 18),
  status TEXT NOT NULL DEFAULT 'created',
  created_at_provider TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
{_TENANT_COMMON},
  UNIQUE (tenant_id, intent_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_intents_tenant
  ON interop_intents (tenant_id);
""")

    # -- Tenant-scoped: asset legs ------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_asset_legs (
  tenant_id TEXT NOT NULL,
  asset_leg_id TEXT NOT NULL,
  interop_message_id TEXT,
  intent_id TEXT,
  leg_type TEXT NOT NULL,
  network_id TEXT NOT NULL,
  asset_id TEXT,
  token_address TEXT,
  amount_atomic NUMERIC(38, 0),
  amount_decimal NUMERIC(38, 18) NOT NULL,
  from_address TEXT,
  to_address TEXT,
  transaction_hash TEXT,
  observed_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, asset_leg_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_asset_legs_tenant
  ON interop_asset_legs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_interop_asset_legs_message
  ON interop_asset_legs (tenant_id, interop_message_id);
""")

    # -- Tenant-scoped: security policy snapshots -----------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_security_policy_snapshots (
  tenant_id TEXT NOT NULL,
  security_snapshot_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  path_id TEXT NOT NULL,
  effective_block_number NUMERIC(38, 0),
  verification_model TEXT NOT NULL DEFAULT 'unknown',
  required_verifier_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  optional_verifier_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  optional_threshold INTEGER,
  confirmations_required INTEGER,
  delivery_actor_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  module_addresses JSONB NOT NULL DEFAULT '{{}}'::jsonb,
  content_hash TEXT NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, security_snapshot_id),
  UNIQUE (tenant_id, path_id, content_hash),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_security_policy_snapshots_tenant
  ON interop_security_policy_snapshots (tenant_id);
""")

    # -- Tenant-scoped: delivery attempts ----------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_delivery_attempts (
  tenant_id TEXT NOT NULL,
  delivery_attempt_id TEXT NOT NULL,
  interop_message_id TEXT NOT NULL,
  attempt_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'unknown',
  delivery_actor_id TEXT,
  transaction_hash TEXT,
  error_class TEXT,
  observed_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, delivery_attempt_id),
  UNIQUE (tenant_id, interop_message_id, attempt_number),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_delivery_attempts_tenant
  ON interop_delivery_attempts (tenant_id);
""")

    # -- Tenant-scoped: provider scan checkpoints -----------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_provider_checkpoints (
  tenant_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  network_id TEXT NOT NULL,
  last_scanned_block NUMERIC(38, 0) NOT NULL DEFAULT 0,
  confirmed_block NUMERIC(38, 0) NOT NULL DEFAULT 0,
  advanced_at TIMESTAMPTZ NOT NULL,
{_TENANT_COMMON},
  UNIQUE (tenant_id, checkpoint_id),
  UNIQUE (tenant_id, provider_id, network_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_provider_checkpoints_tenant
  ON interop_provider_checkpoints (tenant_id);
""")

    # -- Tenant-scoped: reconciliation records ------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS interop_reconciliation_records (
  tenant_id TEXT NOT NULL,
  reconciliation_id TEXT NOT NULL,
  interop_message_id TEXT,
  correlation_key TEXT,
  status TEXT NOT NULL,
  sources_compared JSONB NOT NULL DEFAULT '[]'::jsonb,
  difference_note TEXT,
  resolved_at TIMESTAMPTZ,
{_TENANT_COMMON},
  UNIQUE (tenant_id, reconciliation_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_interop_reconciliation_records_tenant
  ON interop_reconciliation_records (tenant_id);
""")

    # -- Silver projection: interop facts ---------------------------------------------------------------
    op.execute(f"""
CREATE TABLE IF NOT EXISTS silver_interop_facts (
  fact_id UUID NOT NULL DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  source_event_id TEXT,
  entity_id TEXT,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  payload JSONB,
  provider_id TEXT,
  path_id TEXT,
  interop_message_id TEXT,
  status TEXT,
  amount_decimal NUMERIC(38, 18),
{_TENANT_COMMON},
  PRIMARY KEY (tenant_id, fact_id),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_silver_interop_facts_tenant
  ON silver_interop_facts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_silver_interop_facts_entity
  ON silver_interop_facts (tenant_id, entity_id);
CREATE INDEX IF NOT EXISTS ix_silver_interop_facts_event_occurred
  ON silver_interop_facts (tenant_id, event_type, occurred_at);
""")


def downgrade() -> None:
    tables = [
        "interop_providers",
        "interop_gateways",
        "interop_paths",
        "interop_applications",
        "interop_verification_actors",
        "interop_delivery_actors",
        "interop_messages",
        "interop_message_events",
        "interop_intents",
        "interop_asset_legs",
        "interop_security_policy_snapshots",
        "interop_delivery_attempts",
        "interop_provider_checkpoints",
        "interop_reconciliation_records",
        "silver_interop_facts",
    ]
    for table in reversed(tables):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
