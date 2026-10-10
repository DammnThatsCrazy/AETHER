"""durable credential audit history + provider enablement (Postgres, not Redis)

The credential authority's audit trail and per-tenant provider enablement flag
previously lived in the shared store (Redis when configured, in-memory
otherwise) — no durable history for a financial credential authority. These
additive JSONB tables move both to Postgres.

Both follow the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at). Purely additive; fully reversible.

Revision ID: 20260825_credential_audit_history
Revises: 20260824_capability_activation_states
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision = "20260825_credential_audit_history"
down_revision = "20260824_capability_activation_states"
branch_labels = None
depends_on = None

_TABLES = ("provider_credential_audit", "provider_enablement")


def _create(table: str, extra_index_expr: str | None = None) -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
    if extra_index_expr:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_lookup ON {table} ({extra_index_expr});"
        )
    op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated ON {table};")
    op.execute(
        f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def upgrade() -> None:
    _create(
        "provider_credential_audit",
        "(data->>'tenant_id'), (data->>'provider'), (data->>'action')",
    )
    _create(
        "provider_enablement",
        "(data->>'tenant_id'), (data->>'provider'), (data->>'environment')",
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated ON {table};")
        op.execute(f"DROP TABLE IF EXISTS {table};")
