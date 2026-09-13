"""capability declarations — the tenant's declared (intended) capability surface

Additive table for PR 2 (Agent Access Intelligence, Phase B2, monoprompt §9.3/§9.5).
A declaration is a tenant asserting "this capability is one we intend to have"; it is
the side that the observed `capability_catalog` is compared against to produce drift.
It is NOT evidence about a publisher — nothing in this platform verifies one — so no
column here (and no field in the JSONB payload) implies verification.

Follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at) so the runtime JSONB repository and this migration agree. Expression
indexes cover `capability_id` (the exact join key back to `capability_catalog`) and
`publisher_ref`. NOTE: the `publisher_ref` index was a mistake — nothing filters that
field, while the list API filters `provider` and `server_name`, which are indexed by
`20260807_capability_declaration_indexes`. Left in place here rather than rewritten,
since this revision may already be applied. Purely additive; fully reversible.

Revision ID: 20260806_capability_declarations
Revises: 20260805_capability_catalog
Create Date: 2026-08-06
"""

from __future__ import annotations

from alembic import op

revision = "20260806_capability_declarations"
down_revision = "20260805_capability_catalog"
branch_labels = None
depends_on = None

_TABLES = {
    # Declared capabilities per tenant, keyed by the SAME tuple as capability_catalog
    # (tenant_id, provider, server_name|server_url, tool_name) so a declaration and the
    # observation it describes join exactly, with no fuzzy matching.
    "capability_declarations": """
        CREATE TABLE IF NOT EXISTS capability_declarations (
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
    # Declaration lookups run against the JSONB `data` field (BaseRepository filters via
    # data->>'key'); index those expressions. `capability_id` carries the drift join.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_capability_declarations_capability "
        "ON capability_declarations ((data->>'capability_id'));"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_capability_declarations_publisher "
        "ON capability_declarations ((data->>'publisher_ref'));"
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
