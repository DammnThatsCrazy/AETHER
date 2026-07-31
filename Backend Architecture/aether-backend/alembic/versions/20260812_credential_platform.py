"""provider-neutral credential platform — tenant_credentials store

Revision ID: 20260812_credential_platform
Revises: 20260811_demo_seed_core
Create Date: 2026-08-12

Dedicated non-JSONB row store for tenant credentials: ciphertext + masked,
secret-free metadata + versioning + lifecycle columns. This is the documented
raw-SQL exception (mirrors the demo_seed precedent): credential ciphertext is
never a JSONB ``data`` blob. Schema-only — ``upgrade`` needs no encryption key;
encryption happens in the application backend, never in the migration.
"""

from alembic import op

revision = "20260812_credential_platform"
down_revision = "20260811_demo_seed_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_credentials (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            credential_ref TEXT NOT NULL,
            credential_type TEXT NOT NULL,
            ciphertext TEXT NOT NULL,
            masked_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            version INT NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            rotated_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_credentials_ref
        ON tenant_credentials (tenant_id, credential_ref)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenant_credentials_tenant
        ON tenant_credentials (tenant_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenant_credentials_tenant_status
        ON tenant_credentials (tenant_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tenant_credentials_tenant_status")
    op.execute("DROP INDEX IF EXISTS idx_tenant_credentials_tenant")
    op.execute("DROP INDEX IF EXISTS uq_tenant_credentials_ref")
    op.execute("DROP TABLE IF EXISTS tenant_credentials")
