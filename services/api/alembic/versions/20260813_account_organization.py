"""Durable tenant-scoped account organizations and membership controls.

The runtime repositories store the complete DTO-shaped payload in ``data``
through ``BaseRepository``. The typed tenant column and JSONB expression
indexes make tenant isolation and active/pending duplicate protection durable
in PostgreSQL while preserving the local in-memory repository behavior.
"""

from __future__ import annotations

from alembic import op


revision = "20260813_account_organization"
down_revision = "20260812_sdk_durability"
branch_labels = None
depends_on = None


TABLES = (
    "account_organizations",
    "account_organization_members",
    "account_organization_invitations",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant "
            f"ON {table} (tenant_id)"
        )

    # These expressions match BaseRepository's actual persisted/read payload;
    # typed columns that the repository never writes would not protect writes.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_account_organizations_tenant
        ON account_organizations (tenant_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_account_organization_active_member
        ON account_organization_members (tenant_id, (data->>'user_id'))
        WHERE data->>'status' = 'active'
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_account_organization_pending_invitation
        ON account_organization_invitations (tenant_id, lower(data->>'email'))
        WHERE data->>'status' = 'pending'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_account_organization_invitations_expiry
        ON account_organization_invitations (tenant_id, (data->>'expires_at'))
        WHERE data->>'status' = 'pending'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_account_organization_invitations_expiry")
    op.execute("DROP INDEX IF EXISTS uq_account_organization_pending_invitation")
    op.execute("DROP INDEX IF EXISTS uq_account_organization_active_member")
    op.execute("DROP INDEX IF EXISTS uq_account_organizations_tenant")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
