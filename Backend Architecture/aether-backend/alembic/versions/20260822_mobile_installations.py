"""mobile installations + push subscriptions

Native per-app device installations and their push subscriptions. Direct-SQL
tables (repositories/installation_repo.py): upsert-by-id registration, a unique
(tenant_scope, token_hash) push dedupe index, and revocation are semantics the
JSONB BaseRepository cannot express. Raw push tokens are NEVER stored here — only
a token_hash (dedupe); the encrypted token lives in the credential platform.

DDL parity: constants duplicated verbatim in repositories/installation_repo.py,
asserted equal by tests/unit/test_installation_ddl_parity.py.

Revision ID: 20260822_mobile_installations
Revises: 20260821_client_sync
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "20260822_mobile_installations"
down_revision = "20260821_client_sync"
branch_labels = None
depends_on = None

MOBILE_INSTALLATIONS_DDL = """
CREATE TABLE IF NOT EXISTS mobile_installations (
    id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    app_kind TEXT NOT NULL,
    platform TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    trust_state TEXT NOT NULL DEFAULT 'registered',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
)
"""

PUSH_SUBSCRIPTIONS_DDL = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    provider TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    environment TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
)
"""

MOBILE_INSTALLATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_mobile_installations_principal "
    "ON mobile_installations (tenant_scope, principal_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_push_subscriptions_token "
    "ON push_subscriptions (tenant_scope, token_hash)",
    "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_installation "
    "ON push_subscriptions (tenant_scope, installation_id)",
]


def upgrade() -> None:
    op.execute(MOBILE_INSTALLATIONS_DDL)
    op.execute(PUSH_SUBSCRIPTIONS_DDL)
    for idx in MOBILE_INSTALLATION_INDEXES:
        op.execute(idx)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_subscriptions")
    op.execute("DROP TABLE IF EXISTS mobile_installations")
