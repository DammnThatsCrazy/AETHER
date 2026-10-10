"""Persistent storage for BYOK provider API keys.

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-05-22
"""

from __future__ import annotations

from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS provider_api_keys (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     VARCHAR(64) NOT NULL,
            provider_name VARCHAR(64) NOT NULL,
            category      VARCHAR(32) NOT NULL DEFAULT 'llm',
            encrypted_key TEXT        NOT NULL,
            endpoint      TEXT,
            extra         JSONB       NOT NULL DEFAULT '{}',
            enabled       BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, provider_name)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_pak_tenant ON provider_api_keys (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pak_enabled ON provider_api_keys (tenant_id, enabled);")
    op.execute("DROP TRIGGER IF EXISTS trg_pak_updated ON provider_api_keys;")
    op.execute(
        "CREATE TRIGGER trg_pak_updated BEFORE UPDATE ON provider_api_keys "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pak_updated ON provider_api_keys;")
    op.execute("DROP TABLE IF EXISTS provider_api_keys;")
