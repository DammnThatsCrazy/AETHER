"""trust plane — human sessions, service credentials, public ingest identifiers

Additive tables for PR 1 (trust containment). Human authentication issues
durable server-side sessions instead of reusable API keys; machine access uses
scoped service credentials; public SDK ingest uses non-secret ingest-only
identifiers.

Every table follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) so the runtime JSONB repositories and this migration
agree, plus nullable typed convenience columns for indexing. Purely additive;
no destructive changes. Fully reversible.

Revision ID: 20260722_trust_plane
Revises: 20260721_value_semantics
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op

revision = "20260722_trust_plane"
down_revision = "20260721_value_semantics"
branch_labels = None
depends_on = None

_TABLES = {
    # Durable human sessions. The raw opaque token is never stored — only its
    # sha256 (token_hash, also kept inside data for JSONB lookups).
    "auth_sessions": """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            principal_id TEXT,
            token_hash TEXT,
            status TEXT,
            idle_expires_at TIMESTAMPTZ,
            absolute_expires_at TIMESTAMPTZ,
            device_id TEXT,
            risk_state TEXT,
            last_seen_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Service accounts own one or more scoped service credentials.
    "service_accounts": """
        CREATE TABLE IF NOT EXISTS service_accounts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            name TEXT,
            environment TEXT,
            status TEXT,
            created_by_principal_id TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Scoped, purpose-bound, rotatable, revocable machine credentials.
    "service_credentials": """
        CREATE TABLE IF NOT EXISTS service_credentials (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            service_account_id TEXT,
            credential_hash TEXT,
            purpose TEXT,
            environment TEXT,
            status TEXT,
            expires_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Non-secret, ingest-only, tenant/environment-scoped identifiers.
    "public_ingest_identifiers": """
        CREATE TABLE IF NOT EXISTS public_ingest_identifiers (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            environment TEXT,
            status TEXT,
            revoked_at TIMESTAMPTZ,
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
    # Token/credential/identifier lookups run against the JSONB `data` field
    # (BaseRepository filters via data->>'key'); index those expressions.
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_sessions_token ON auth_sessions ((data->>'token_hash'));")
    op.execute("CREATE INDEX IF NOT EXISTS ix_service_credentials_hash ON service_credentials ((data->>'credential_hash'));")
    op.execute("CREATE INDEX IF NOT EXISTS ix_public_ingest_identifiers_ident ON public_ingest_identifiers ((data->>'identifier'));")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
