"""Create the principal <-> agent lineage read model (AO-4/AO-5).

Revision ID: 20261105_principal_agent_lineage
Revises: 20261030_agent_exec_lineage_hardening
Create Date: 2026-11-05

Derived, rebuildable projection over Silver execution facts, authority records
and principal bindings; dropping these tables loses no evidence. Indexes back
keyset pagination so a page costs the same anywhere in a large population, and
``path`` uses the C collation so descendant reads are binary range scans.
"""

from __future__ import annotations

from alembic import op

revision = "20261105_principal_agent_lineage"
down_revision = "20261030_agent_exec_lineage_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS principal_agent_lineage (
            tenant_id TEXT NOT NULL,
            principal_entity_id TEXT NOT NULL,
            agent_entity_id TEXT NOT NULL,
            direct_or_indirect TEXT NOT NULL,
            attribution_class TEXT NOT NULL,
            active_state TEXT NOT NULL,
            lineage_status TEXT NOT NULL,
            authority_status TEXT,
            depth INTEGER NOT NULL,
            parent_agent_id TEXT,
            root_agent_id TEXT,
            deployment_id TEXT,
            operator_entity_id TEXT,
            risk_signal_count INTEGER,
            cluster_ids TEXT[] NOT NULL DEFAULT '{}',
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, principal_entity_id, agent_entity_id),
            CHECK (length(btrim(tenant_id)) > 0)
        )
        """
    )
    for name, columns in (
        ("attribution", "attribution_class"),
        ("relationship", "direct_or_indirect"),
        ("active", "active_state"),
        ("status", "lineage_status"),
        ("authority", "authority_status"),
        ("deployment", "deployment_id"),
        ("operator", "operator_entity_id"),
        ("parent", "parent_agent_id"),
    ):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_pal_{name} ON principal_agent_lineage "
            f"(tenant_id, principal_entity_id, {columns}, agent_entity_id)"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pal_agent ON principal_agent_lineage (tenant_id, agent_entity_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_pal_clusters ON principal_agent_lineage USING GIN (cluster_ids)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS principal_agent_lineage_summary (
            tenant_id TEXT NOT NULL,
            principal_entity_id TEXT NOT NULL,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, principal_entity_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS principal_agent_lineage_clusters (
            tenant_id TEXT NOT NULL,
            principal_entity_id TEXT NOT NULL,
            cluster_id TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            data JSONB NOT NULL,
            PRIMARY KEY (tenant_id, principal_entity_id, cluster_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pal_clusters_rank ON principal_agent_lineage_clusters "
        "(tenant_id, principal_entity_id, member_count DESC, cluster_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_lineage_nodes (
            tenant_id TEXT NOT NULL,
            agent_entity_id TEXT NOT NULL,
            parent_agent_id TEXT,
            root_agent_id TEXT NOT NULL,
            depth INTEGER NOT NULL,
            path TEXT COLLATE "C" NOT NULL,
            data JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, agent_entity_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_aln_parent ON agent_lineage_nodes (tenant_id, parent_agent_id, agent_entity_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_aln_path ON agent_lineage_nodes (tenant_id, path)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_lineage_restatements (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            principal_entity_id TEXT NOT NULL,
            agent_entity_id TEXT NOT NULL,
            change_kind TEXT NOT NULL,
            before_state JSONB,
            after_state JSONB,
            as_of TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alr_principal ON agent_lineage_restatements "
        "(tenant_id, principal_entity_id, id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_lineage_principal_bindings (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (jsonb_typeof(data) = 'object'),
            CHECK (length(btrim(tenant_id)) > 0),
            CHECK (data->>'tenant_id' = tenant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alpb_tenant ON agent_lineage_principal_bindings (tenant_id, id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_lineage_principal_bindings")
    op.execute("DROP TABLE IF EXISTS agent_lineage_restatements")
    op.execute("DROP TABLE IF EXISTS agent_lineage_nodes")
    op.execute("DROP TABLE IF EXISTS principal_agent_lineage_clusters")
    op.execute("DROP TABLE IF EXISTS principal_agent_lineage_summary")
    op.execute("DROP TABLE IF EXISTS principal_agent_lineage")
