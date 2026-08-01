"""self-serve tenant activation state

One table backing the self-serve activation FSM (services/activation). It follows
the BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at) plus the typed convenience columns the activation repository filters
on. Uniqueness is enforced on the JSONB tenant_id expression the repository
actually queries, so a tenant collapses to a single activation record and retries
update in place rather than forking a second row.

This table stores activation lifecycle metadata only — plan selection, SDK
selection, hashed key-ids, and first-value evidence references. It never stores
raw API keys and never writes billing state (billing is read-only-derived).

Revision ID: 20260814_activation_state
Revises: 20260822_mobile_installations
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op

revision = "20260814_activation_state"
down_revision = "20260822_mobile_installations"
branch_labels = None
depends_on = None


_TABLES: dict[str, str] = {
    "tenant_activations": """
        CREATE TABLE IF NOT EXISTS tenant_activations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            state TEXT,
            plan_tier TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}

# One activation record per tenant: retries update in place instead of forking a
# second row. tenant_id is written into the JSONB body by BaseRepository.insert,
# so the constraint is on the expression the read path actually queries.
_UNIQUE_INDEXES = (
    ("tenant_activations", "ux_tenant_activations_tenant",
     "((data->>'tenant_id'))", ""),
)

# find_many/count ORDER BY created_at (see repositories/repos.py); the status scan
# backs the activation status read.
_SORT_INDEXES = (
    ("tenant_activations", "ix_tenant_activations_state",
     "((data->>'state'), (data->>'created_at'))"),
    ("tenant_activations", "ix_tenant_activations_created", "(created_at DESC)"),
)


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)
    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
    for table, name, expression, predicate in _UNIQUE_INDEXES:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} {expression} {predicate};"
        )
    for table, name, expression in _SORT_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {expression};")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
