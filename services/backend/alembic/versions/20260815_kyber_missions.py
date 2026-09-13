"""kyber missions — autonomous mission runs and monitoring conditions

Additive tables for the Kyber missions plane (services/kyber/ops). A mission is a
long-running autonomous run bound to a single tenant: it names the objective it
pursues, the incident it was raised from, the plan it executes, and the
verification decision that gates completion. Monitoring conditions are the
recurring checks a live mission schedules; the monitoring loop wakes on the ones
whose next check is due.

Both tables follow the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) so the runtime JSONB repositories and this migration
agree, plus typed convenience columns for indexing and reporting.

Uniqueness and read indexes are enforced on the JSONB expressions the
repositories actually query (``data->>'...'``), not on the mirrored typed
columns — a constraint on a column the read path never touches would be
decorative. Purely additive; no destructive changes. Fully reversible.

Revision ID: 20260815_kyber_missions
Revises: 20260814_activation_state
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

revision = "20260815_kyber_missions"
down_revision = "20260814_activation_state"
branch_labels = None
depends_on = None


_TABLES: dict[str, str] = {
    "kyber_missions": """
        CREATE TABLE IF NOT EXISTS kyber_missions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            status TEXT,
            objective_id TEXT,
            incident_id TEXT,
            plan_id TEXT,
            verification_decision TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_monitoring_conditions": """
        CREATE TABLE IF NOT EXISTS kyber_monitoring_conditions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            mission_id TEXT,
            condition_type TEXT,
            status TEXT,
            next_check_at TIMESTAMPTZ,
            failure_count INTEGER,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}

# Read indexes on the JSONB expressions the repositories query.
_JSONB_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("kyber_missions", "status", "status"),
    ("kyber_monitoring_conditions", "mission", "mission_id"),
)

# One live mission per objective: retries update in place instead of forking a
# second run against the same objective.
_UNIQUE_INDEXES: tuple[tuple[str, str, str, str], ...] = (
    (
        "kyber_missions",
        "ux_kyber_missions_objective",
        "((data->>'objective_id'))",
        "",
    ),
)

# The monitoring loop wakes on conditions that are due: it scans by status and
# next check time together.
_COMPOSITE_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "kyber_monitoring_conditions",
        "ix_kyber_monitoring_due",
        "((data->>'status'), (data->>'next_check_at'))",
    ),
)


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)

    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")

    for table, suffix, key in _JSONB_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_{suffix} ON {table} ((data->>'{key}'));"
        )

    for table, name, expression, predicate in _UNIQUE_INDEXES:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} {expression} {predicate};"
        )

    for table, name, expression in _COMPOSITE_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {expression};")


def downgrade() -> None:
    # Dropping the tables removes their indexes with them.
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
