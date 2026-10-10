"""capability catalog — observed capability inventory + installations

Additive tables for PR 2 (Agent Access Intelligence, Phase A). The capability
catalog and installations are a maintained materialization derived from the
agent-execution fact stream; they are plain derived read-model tables (not
projector-owned artifacts) upserted out-of-band from silver_agent_execution_facts.

Every table follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) so the runtime JSONB repositories and this migration
agree. Purely additive; no destructive changes. Fully reversible.

Revision ID: 20260805_capability_catalog
Revises: 20260804_traffic_ops
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op

revision = "20260805_capability_catalog"
down_revision = "20260804_traffic_ops"
branch_labels = None
depends_on = None

_TABLES = {
    # Distinct observed external capabilities per tenant, keyed by
    # (tenant_id, provider, server_name|server_url, tool_name).
    "capability_catalog": """
        CREATE TABLE IF NOT EXISTS capability_catalog (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    # Agent<->server bindings observed for a tenant, keyed by
    # (tenant_id, agent_id, server_name|server_url).
    "capability_installations": """
        CREATE TABLE IF NOT EXISTS capability_installations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
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
    # Catalog/installation lookups run against the JSONB `data` field
    # (BaseRepository filters via data->>'key'); index those expressions.
    op.execute("CREATE INDEX IF NOT EXISTS ix_capability_catalog_provider ON capability_catalog ((data->>'provider'));")
    op.execute("CREATE INDEX IF NOT EXISTS ix_capability_catalog_server ON capability_catalog ((data->>'server_name'));")
    op.execute("CREATE INDEX IF NOT EXISTS ix_capability_installations_agent ON capability_installations ((data->>'agent_id'));")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
