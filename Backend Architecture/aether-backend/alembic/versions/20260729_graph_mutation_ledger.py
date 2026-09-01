"""Append-only graph mutation ledger for the canonical mutation gateway (WP2.5).

Three tables back the Graph Mutation Gateway
(``shared/graph/mutation_gateway.py``):

* ``graph_mutation_ledger`` — one append-only row per graph mutation, shaped
  exactly like ``shared.graph.mutation_models.MutationRecord`` (bitemporal
  columns use the canonical ``BITEMPORAL_EDGE_PROPERTIES`` names:
  valid_from / valid_to / recorded_at / superseded_at). ``ledger_offset``
  provides a total order for replay and checkpointing. Rows are never
  updated or deleted after commit.
* ``graph_fact_versions`` — bitemporal payload versions per graph aggregate.
  A new version closes the prior open one (valid_to + superseded_at set),
  never rewrites it.
* ``graph_checkpoints`` — replay digests: sha256 of the deterministic graph
  state at a ledger offset, used for ledger-vs-projection parity checks.

The runtime twin of this DDL lives in
``repositories/graph_mutation_ledger.py`` (the alembic versions directory is
not importable); ``tests/unit/graph_gateway/test_ledger_ddl_parity.py``
AST-extracts these constants and asserts exact string equality.

Revision ID: 20260729_graph_mutation_ledger
Revises: 20260727_object_backed_bronze
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op

revision = "20260729_graph_mutation_ledger"
down_revision = "20260727_object_backed_bronze"
branch_labels = None
depends_on = None


GRAPH_MUTATION_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS graph_mutation_ledger (
    mutation_id TEXT PRIMARY KEY,
    ledger_offset BIGSERIAL,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    actor_kind TEXT,
    actor_id TEXT,
    subject_kind TEXT,
    subject_id TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    correlation_id TEXT,
    causation_id TEXT,
    source_event_id TEXT,
    idempotency_key TEXT,
    reason_code TEXT,
    causality_class TEXT,
    confidence NUMERIC(5, 4),
    evidence_refs JSONB,
    model_refs JSONB,
    policy_refs JSONB,
    consent_refs JSONB,
    before_version_id TEXT,
    after_version_id TEXT,
    change_set_id TEXT,
    rights_decision_id TEXT,
    rights_envelope_id TEXT,
    rights_policy_set_ref TEXT,
    rights_lineage_set_hash TEXT,
    rights_source_grant_refs JSONB,
    schema_version TEXT
)
"""

GRAPH_FACT_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS graph_fact_versions (
    version_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    created_by_mutation_id TEXT
)
"""

GRAPH_CHECKPOINTS_DDL = """
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'tenant',
    mutation_offset BIGINT,
    digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

GRAPH_LEDGER_INDEXES = [
    # Replayed mutations dedupe on the tenant-scoped idempotency key.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_graph_mutation_ledger_tenant_idem "
    "ON graph_mutation_ledger (tenant_id, idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    # Aggregate history reads (audit, bitemporal reconstruction).
    "CREATE INDEX IF NOT EXISTS ix_graph_mutation_ledger_tenant_aggregate "
    "ON graph_mutation_ledger (tenant_id, aggregate_id, recorded_at)",
    # Tenant-wide ledger scans (replay, export).
    "CREATE INDEX IF NOT EXISTS ix_graph_mutation_ledger_tenant_recorded "
    "ON graph_mutation_ledger (tenant_id, recorded_at)",
    # Current (open) version lookup per aggregate for close-and-append.
    "CREATE INDEX IF NOT EXISTS ix_graph_fact_versions_open "
    "ON graph_fact_versions (tenant_id, aggregate_type, aggregate_id) "
    "WHERE superseded_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_graph_fact_versions_tenant_aggregate "
    "ON graph_fact_versions (tenant_id, aggregate_id, recorded_at)",
    "CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_tenant_created "
    "ON graph_checkpoints (tenant_id, created_at DESC)",
]


def upgrade() -> None:
    op.execute(GRAPH_MUTATION_LEDGER_DDL)
    op.execute(GRAPH_FACT_VERSIONS_DDL)
    op.execute(GRAPH_CHECKPOINTS_DDL)
    for index_ddl in GRAPH_LEDGER_INDEXES:
        op.execute(index_ddl)


_INDEX_NAMES = [
    "ix_graph_checkpoints_tenant_created",
    "ix_graph_fact_versions_tenant_aggregate",
    "ix_graph_fact_versions_open",
    "ix_graph_mutation_ledger_tenant_recorded",
    "ix_graph_mutation_ledger_tenant_aggregate",
    "ux_graph_mutation_ledger_tenant_idem",
]


def downgrade() -> None:
    for index_name in _INDEX_NAMES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    op.execute("DROP TABLE IF EXISTS graph_checkpoints")
    op.execute("DROP TABLE IF EXISTS graph_fact_versions")
    op.execute("DROP TABLE IF EXISTS graph_mutation_ledger")
