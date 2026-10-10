"""consent authority — server consent receipts + tenant compliance profiles

Additive tables for PR 3 (server-authoritative consent enforcement). The SERVER
consent-receipt store, not the SDK per-event snapshot, is authoritative for
whether ingestion may process an event: absence of a receipt is not permission.
Tenant compliance profiles carry per-tenant data-classification policy.

Every table follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) so the runtime JSONB repositories and this migration
agree, plus nullable typed convenience columns for indexing. Lookups run against
the JSONB ``data`` field (BaseRepository filters via ``data->>'key'``), so the
subject/purpose lookups are backed by expression indexes. Purely additive; no
destructive changes. Fully reversible.

Revision ID: 20260723_consent_authority
Revises: 20260722_trust_plane
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "20260723_consent_authority"
down_revision = "20260722_trust_plane"
branch_labels = None
depends_on = None

_TABLES = {
    # Server-side consent receipts. The SERVER record — not the SDK snapshot —
    # decides whether processing is lawful for a (subject, purpose). `state` is
    # one of granted | denied | revoked | expired; revoked_at / expires_at make
    # the negative states explicit and queryable. integrity_hash pins the
    # receipt content so a stored receipt cannot be silently altered.
    "consent_receipts": """
        CREATE TABLE IF NOT EXISTS consent_receipts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            subject_id TEXT,
            anonymous_id TEXT,
            purpose TEXT,
            state TEXT,
            policy_version TEXT,
            source TEXT,
            jurisdiction TEXT,
            granted_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            integrity_hash TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Per-tenant compliance posture. Drives data-classification policy
    # (prohibited data classes, fingerprinting authorization) and records the
    # tenant's commercial stage / risk tier for lawful-processing decisions.
    "tenant_compliance_profiles": """
        CREATE TABLE IF NOT EXISTS tenant_compliance_profiles (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            profile_version TEXT,
            commercial_stage TEXT,
            risk_tier TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)
    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
    # Consent-receipt lookups run against the JSONB `data` field
    # (BaseRepository filters via data->>'key'); index those expressions so the
    # ingestion hot-path lookup by (tenant, subject, purpose) stays fast.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_consent_receipts_subject "
        "ON consent_receipts ((data->>'subject_id'));"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_consent_receipts_anon "
        "ON consent_receipts ((data->>'anonymous_id'));"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_consent_receipts_purpose "
        "ON consent_receipts ((data->>'purpose'));"
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
