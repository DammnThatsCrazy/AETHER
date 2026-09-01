"""IRRL canonical rights authority ledger.

The seven tables are append-only JSONB records with a denormalised tenant key
for scoped reads. JSONB keeps compatibility with the repository substrate while
the canonical Pydantic contracts enforce the record shape at the service
boundary. No cache or in-memory store is authoritative in staging/production.

Revision ID: 20260903_irrl_rights_authority
Revises: 20260902_graph_pg_backend
"""

from __future__ import annotations

from alembic import op

revision = "20260903_irrl_rights_authority"
down_revision = "20260902_graph_pg_backend"
branch_labels = None
depends_on = None

_TABLES = (
    "irrl_policy_sets",
    "irrl_artifact_rights_envelopes",
    "irrl_rights_decisions",
    "irrl_derivation_edges",
    "irrl_impact_graphs",
    "irrl_revocations",
    "irrl_source_grants",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);
            CREATE INDEX IF NOT EXISTS ix_{table}_created ON {table} (created_at);
            """
        )

    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_irrl_decisions_request
        ON irrl_rights_decisions ((data->>'request_id'))
        WHERE (data->>'request_id') IS NOT NULL;"""
    )
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_irrl_derivation_edge_natural
        ON irrl_derivation_edges ((data->>'lineage_set_hash'), (data->>'child_ref'))
        WHERE (data->>'lineage_set_hash') IS NOT NULL AND (data->>'child_ref') IS NOT NULL;"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_irrl_derivation_edge_natural")
    op.execute("DROP INDEX IF EXISTS uq_irrl_decisions_request")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
