"""Durable non-identity provider object mappings and scoped aliases.

Revision ID: 20261002_provider_object_refs
Revises: 20261002_tenant_connector_routes
Create Date: 2026-10-02

The unique source tuple is tenant, provider family, live/test realm, verified
account HMAC, reviewed non-identity object type, and native object ID HMAC.
Connection IDs are evidence, not identity. Alias foreign keys include tenant
and account scope so a persisted alias cannot point across those boundaries.
The SQL is kept identical to provider_runtime.object_refs.SCHEMA_SQL.
"""

from __future__ import annotations

from alembic import op

revision = "20261002_provider_object_refs"
down_revision = "20261002_tenant_connector_routes"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS provider_object_refs (
    canonical_object_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider_family TEXT NOT NULL,
    source_account_realm TEXT NOT NULL CHECK (source_account_realm IN ('live', 'test')),
    source_account_hash TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    source_object_hash TEXT NOT NULL,
    account_verification_ref_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_provider_object_source UNIQUE (
        tenant_id, provider_family, source_account_realm, source_account_hash,
        source_object_type, source_object_hash
    ),
    CONSTRAINT uq_provider_object_account_scope UNIQUE (
        canonical_object_id, tenant_id, provider_family, source_account_realm,
        source_account_hash
    )
);
CREATE TABLE IF NOT EXISTS provider_object_aliases (
    alias_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider_family TEXT NOT NULL,
    source_account_realm TEXT NOT NULL CHECK (source_account_realm IN ('live', 'test')),
    source_account_hash TEXT NOT NULL,
    alias_namespace TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    alias_hash TEXT NOT NULL,
    canonical_object_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN (
        'legacy_migration', 'verified_reconnect', 'source_id_change',
        'schema_upgrade', 'operator_correction'
    )),
    evidence_ref TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_provider_object_alias_validity CHECK (
        valid_to IS NULL OR valid_to > valid_from
    ),
    CONSTRAINT uq_provider_object_alias UNIQUE (
        tenant_id, provider_family, source_account_realm, source_account_hash,
        alias_namespace, alias_kind, alias_hash
    ),
    CONSTRAINT fk_provider_object_alias_scope FOREIGN KEY (
        canonical_object_id, tenant_id, provider_family, source_account_realm,
        source_account_hash
    ) REFERENCES provider_object_refs (
        canonical_object_id, tenant_id, provider_family, source_account_realm,
        source_account_hash
    ) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_provider_object_alias_target
    ON provider_object_aliases (tenant_id, canonical_object_id);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS provider_object_aliases")
    op.execute("DROP TABLE IF EXISTS provider_object_refs")
