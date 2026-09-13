"""Reconciled Control Plane — source-authority rules + equivalence keys (Phase 3).

Phase 3 is the reconciliation *engine half* of the control plane (§19): when
multiple sources describe the same real-world event or state, the control plane
must be able to say *who is authoritative for which property* and *which
observations are semantically the same event* — without ever minting a
canonical fact itself (§9.3 boundary: canonical identity/outcome/economic-fact/
relationship truth belongs to the downstream resolution/outcome subsystem).

The tables below are the control plane's own rule/equivalence configuration:

* ``source_authority_rules`` — §9.1 SourceAuthorityRuleContract rows. Authority
  is domain/property specific (never a blanket "provider X is always superior"):
  each rule orders ``source_precedence`` for one ``(domain, property_path)`` and
  carries an optional conflict strategy + validity window + policy ref.
* ``observation_equivalence_keys`` — §9.2 ObservationEquivalenceKeyContract
  rows. Semantic-equivalence keys that separate *transport idempotency* from
  *semantic deduplication* (§19): which candidate types may be equivalent, which
  ``key_components`` must match (after ``normalization_rules``), inside which
  ``equivalence_window``, under which ``semantic_dedupe_policy``.

The ALTER-less DDL below is additive-only: every table and index is
``CREATE ... IF NOT EXISTS`` and nothing is dropped or widened. Tenancy is
carried on every row; a NULL ``tenant_id`` row is a global (Olympus) rule and a
NULL ``environment_id`` is an environment-agnostic rule. Repository reads match
``tenant_id = $X OR tenant_id IS NULL`` (CP-11) — no cross-tenant read is
possible through the repository API.

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/source_authority_repository.py`` (the repo
executes it to self-ensure the tables under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_source_authority
Revises: 20260906_rcp_schema_mapping
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Phase-3 schema-mapping lane head
``20260906_rcp_schema_mapping`` (schema-mapping lands after the Phase-3
admission + simulation lanes: execution -> admission -> simulation ->
schema_mapping). When this branch is combined with sibling lanes that each add
a migration off the same base, a NEW tuple-merge revision must be created with
``down_revision = (<this revision>, <sibling revision>, ...)`` exactly like
``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_source_authority"
down_revision = "20260906_rcp_schema_mapping"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/source_authority_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_authority_rules (
    rule_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    property_path TEXT NOT NULL,
    source_precedence JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_strategy TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    policy_ref TEXT,
    tenant_id TEXT,
    environment_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_source_authority_rules_domain
    ON source_authority_rules (domain, property_path);

CREATE TABLE IF NOT EXISTS observation_equivalence_keys (
    key_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    candidate_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    key_components JSONB NOT NULL DEFAULT '[]'::jsonb,
    equivalence_window TEXT,
    normalization_rules JSONB,
    semantic_dedupe_policy TEXT,
    tenant_id TEXT,
    environment_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_observation_equivalence_keys_domain
    ON observation_equivalence_keys (domain);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL in dependency-free order so a
    # downgrade leaves the Phase-2/Phase-3-schema-mapping schema as it was.
    op.execute("DROP TABLE IF EXISTS observation_equivalence_keys")
    op.execute("DROP TABLE IF EXISTS source_authority_rules")
