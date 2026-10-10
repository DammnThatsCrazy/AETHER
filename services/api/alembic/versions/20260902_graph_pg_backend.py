"""graph postgres backend: graph_vertices / graph_edges tables

Creates the durable store for ``shared.graph.graph._PostgresGraphBackend`` — the
graph backend the staging and production-lean deployment profiles declare
(``graph: postgres``) but which had no schema and no implementation until now, so
``GraphClient.connect`` fail-closed in exactly those profiles.

Two JSONB-backed tables mirror the in-memory backend's shape:

* ``graph_vertices`` — one row per vertex, ``vertex_id`` PK, ``tenant_id``
  denormalised from the properties for indexed tenant-scoped reads / erasure,
  ``properties`` JSONB, last-write-wins on conflict.
* ``graph_edges`` — append-only rows (the same ``(from, to, type)`` pair may
  carry several edges, exactly like the in-memory list; reconciliation collapses
  duplicates). Soft-revoke lives in the ``revoked`` / ``revoked_at`` /
  ``revoke_reason`` columns; there are deliberately NO foreign keys to
  ``graph_vertices`` (an edge may exist before/without its endpoint vertices).

The DDL is byte-identical to ``_PG_GRAPH_SCHEMA_DDL`` in
``shared/graph/graph.py`` (used by ``ensure_schema`` for DATABASE_URL-gated
tests). Everything is additive + idempotent (``IF NOT EXISTS`` everywhere) so a
re-run is a no-op, and the downgrade drops exactly what this revision created.

Revision ID: 20260902_graph_pg_backend
Revises: 20260901_credential_turnkey_tables
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op

revision = "20260902_graph_pg_backend"
down_revision = "20260901_credential_turnkey_tables"
branch_labels = None
depends_on = None


_UPGRADE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS graph_vertices (
        vertex_id   TEXT PRIMARY KEY,
        vertex_type TEXT NOT NULL,
        tenant_id   TEXT,
        properties  JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at  TEXT NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_graph_vertices_tenant ON graph_vertices (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_graph_vertices_tenant_type "
    "ON graph_vertices (tenant_id, vertex_type)",
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        edge_id         BIGSERIAL PRIMARY KEY,
        edge_type       TEXT NOT NULL,
        from_vertex_id  TEXT NOT NULL,
        to_vertex_id    TEXT NOT NULL,
        tenant_id       TEXT,
        properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at      TEXT NOT NULL,
        revoked         BOOLEAN NOT NULL DEFAULT FALSE,
        revoked_at      TEXT,
        revoke_reason   TEXT,
        idempotency_key TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_graph_edges_from "
    "ON graph_edges (from_vertex_id, edge_type)",
    "CREATE INDEX IF NOT EXISTS ix_graph_edges_to "
    "ON graph_edges (to_vertex_id, edge_type)",
    "CREATE INDEX IF NOT EXISTS ix_graph_edges_tenant ON graph_edges (tenant_id)",
)


def upgrade() -> None:
    for ddl in _UPGRADE_DDL:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_graph_edges_tenant")
    op.execute("DROP INDEX IF EXISTS ix_graph_edges_to")
    op.execute("DROP INDEX IF EXISTS ix_graph_edges_from")
    op.execute("DROP TABLE IF EXISTS graph_edges")
    op.execute("DROP INDEX IF EXISTS ix_graph_vertices_tenant_type")
    op.execute("DROP INDEX IF EXISTS ix_graph_vertices_tenant")
    op.execute("DROP TABLE IF EXISTS graph_vertices")
