"""kyber graph, fleet projections, exceptions, incidents and the command plane

One migration for PRs 2-4 so the chain stays linear. Every table follows the
BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at, updated_at)
plus typed convenience columns, and uniqueness is enforced on the JSONB
expressions the repositories actually query — a constraint on a column the read
path never touches would be decorative.

The graph tables store platform topology and REFERENCES into tenant data, never
tenant records. That is the boundary the whole plane rests on: merging tenant
entities into one global graph would make isolation a query-time filter, and a
filter is what produced the truncation defect this plane exists to avoid.

Revision ID: 20260810_kyber_graph_ops
Revises: 20260809_kyber_workforce
Create Date: 2026-08-10
"""

from __future__ import annotations

from alembic import op

revision = "20260810_kyber_graph_ops"
down_revision = "20260809_kyber_workforce"
branch_labels = None
depends_on = None


_TABLES: dict[str, str] = {
    "kyber_graph_nodes": """
        CREATE TABLE IF NOT EXISTS kyber_graph_nodes (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            node_key TEXT,
            node_type TEXT,
            environment TEXT,
            display_name TEXT,
            health TEXT,
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            source_event_id TEXT,
            source_offset BIGINT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_graph_edges": """
        CREATE TABLE IF NOT EXISTS kyber_graph_edges (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            source_node_key TEXT,
            target_node_key TEXT,
            relationship_type TEXT,
            environment TEXT,
            idempotency_key TEXT,
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            source_event_id TEXT,
            source_offset BIGINT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_graph_projection_offsets": """
        CREATE TABLE IF NOT EXISTS kyber_graph_projection_offsets (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            projection TEXT,
            last_offset BIGINT,
            last_run_at TIMESTAMPTZ,
            consecutive_failures INTEGER,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_fleet_projections": """
        CREATE TABLE IF NOT EXISTS kyber_fleet_projections (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            projection TEXT,
            environment TEXT,
            region TEXT,
            dimension TEXT,
            state TEXT,
            score DOUBLE PRECISION,
            source_offset BIGINT,
            computed_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_cohort_definitions": """
        CREATE TABLE IF NOT EXISTS kyber_cohort_definitions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            name TEXT,
            minimum_size INTEGER,
            created_by TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_exceptions": """
        CREATE TABLE IF NOT EXISTS kyber_exceptions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            title TEXT,
            severity TEXT,
            bucket TEXT,
            status TEXT,
            priority_score DOUBLE PRECISION,
            incident_id TEXT,
            dedupe_key TEXT,
            signal_count INTEGER,
            customer_visible BOOLEAN,
            security_exposure BOOLEAN,
            first_seen_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_incidents": """
        CREATE TABLE IF NOT EXISTS kyber_incidents (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            title TEXT,
            status TEXT,
            severity TEXT,
            priority_score DOUBLE PRECISION,
            release_id TEXT,
            customer_visible BOOLEAN,
            signal_count INTEGER,
            opened_at TIMESTAMPTZ,
            resolved_at TIMESTAMPTZ,
            closed_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_incident_signals": """
        CREATE TABLE IF NOT EXISTS kyber_incident_signals (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            incident_id TEXT,
            source TEXT,
            signal_type TEXT,
            error_signature TEXT,
            service TEXT,
            release_id TEXT,
            correlation_basis TEXT,
            correlation_confidence DOUBLE PRECISION,
            observed_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_command_requests": """
        CREATE TABLE IF NOT EXISTS kyber_command_requests (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            command_type TEXT,
            status TEXT,
            requested_by TEXT,
            session_id TEXT,
            device_id TEXT,
            environment TEXT,
            action_class INTEGER,
            dry_run BOOLEAN,
            idempotency_key TEXT,
            required_approvals INTEGER,
            approval_mode TEXT,
            step_up_verified BOOLEAN,
            policy_decision_id TEXT,
            incident_id TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_command_executions": """
        CREATE TABLE IF NOT EXISTS kyber_command_executions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            command_id TEXT,
            attempt INTEGER,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            error TEXT,
            rollback_status TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_command_verifications": """
        CREATE TABLE IF NOT EXISTS kyber_command_verifications (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            command_id TEXT,
            outcome TEXT,
            customer_visible_parity BOOLEAN,
            failure_reason TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "kyber_containment_switches": """
        CREATE TABLE IF NOT EXISTS kyber_containment_switches (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            scope TEXT,
            target TEXT,
            control TEXT,
            active BOOLEAN,
            activated_by TEXT,
            activated_at TIMESTAMPTZ,
            deactivated_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}

# Uniqueness that carries correctness weight, on the expressions the
# repositories query.
_UNIQUE_INDEXES = (
    # NOTE ON COALESCE: PostgreSQL treats NULLs as DISTINCT in a unique index, so
    # `((data->>'node_key'), (data->>'environment'))` does not constrain rows whose
    # environment is absent — two identical node_keys both insert. Verified
    # directly against PG16 before this was fixed. Every nullable term in a
    # uniqueness guarantee is wrapped in COALESCE so the constraint holds for
    # real data rather than only for fully-populated rows.
    ("kyber_graph_nodes", "ux_kyber_graph_nodes_key",
     "((data->>'node_key'), COALESCE(data->>'environment', ''))", ""),
    ("kyber_graph_edges", "ux_kyber_graph_edges_key",
     "((data->>'idempotency_key'), COALESCE(data->>'environment', ''))", ""),
    ("kyber_graph_projection_offsets", "ux_kyber_graph_offsets",
     "((data->>'projection'), (data->>'tenant_id'))", ""),
    ("kyber_fleet_projections", "ux_kyber_fleet_projections",
     "((data->>'projection'), (data->>'tenant_id'), COALESCE(data->>'dimension', ''))", ""),
    # An idempotency key must not execute a command type twice.
    ("kyber_command_requests", "ux_kyber_command_idempotency",
     "((data->>'command_type'), (data->>'idempotency_key'))", ""),
    # One open exception per dedupe key: this is what collapses an alert storm
    # into a single actionable item instead of a wall of duplicates.
    ("kyber_exceptions", "ux_kyber_exceptions_open_dedupe",
     "((data->>'dedupe_key'))",
     "WHERE data->>'dedupe_key' IS NOT NULL AND data->>'status' IN ('open','acknowledged','in_progress')"),
    # One active switch per (scope, target, control); target is nullable for a
    # global switch, hence COALESCE.
    ("kyber_containment_switches", "ux_kyber_containment_active",
     "((data->>'scope'), COALESCE(data->>'target', ''), (data->>'control'))",
     "WHERE data->>'active' = 'true'"),
)

_JSONB_INDEXES = (
    ("kyber_graph_nodes", "type", "node_type"),
    ("kyber_graph_nodes", "health", "health"),
    ("kyber_graph_edges", "source", "source_node_key"),
    ("kyber_graph_edges", "target", "target_node_key"),
    ("kyber_graph_edges", "rel", "relationship_type"),
    ("kyber_fleet_projections", "projection", "projection"),
    ("kyber_exceptions", "status", "status"),
    ("kyber_exceptions", "bucket", "bucket"),
    ("kyber_exceptions", "incident", "incident_id"),
    ("kyber_incidents", "status", "status"),
    ("kyber_incident_signals", "incident", "incident_id"),
    ("kyber_incident_signals", "signature", "error_signature"),
    ("kyber_command_requests", "status", "status"),
    ("kyber_command_executions", "command", "command_id"),
    ("kyber_command_verifications", "command", "command_id"),
)

# Ranking and sweep scans, indexed on the JSONB expressions the repositories
# actually query.
#
# These were originally declared over the typed columns (`status`,
# `priority_score`, `computed_at`, `valid_to`) that each table also carries. All
# five were dead: `BaseRepository.insert` writes only
# `(id, data, tenant_id, created_at, updated_at)` and no Kyber repository
# overrides it, so every typed column stayed NULL for every row ever written and
# the indexes covered nothing. Verified on 5000 rows inserted through the real
# repository path: 0 populated in all five, and the exception queue's own filter
# (`WHERE data->>'status' = 'open'`) planned as a sequential scan.
#
# `priority_score` is cast to numeric so ordering is numeric rather than
# lexicographic — otherwise 9 sorts above 10. The cast is IMMUTABLE, unlike the
# `::timestamptz` cast that made an earlier migration in this repo unindexable;
# timestamps here stay as ISO-8601 text, which sorts identically.
_SORT_INDEXES = (
    # The operator's queue: filter by status, rank by priority.
    ("kyber_exceptions", "ix_kyber_exceptions_priority",
     "((data->>'status'), ((data->>'priority_score')::numeric) DESC)"),
    ("kyber_incidents", "ix_kyber_incidents_open",
     "((data->>'status'), ((data->>'priority_score')::numeric) DESC)"),
    ("kyber_fleet_projections", "ix_kyber_fleet_fresh",
     "((data->>'projection'), (data->>'computed_at'))"),
    ("kyber_command_requests", "ix_kyber_commands_status",
     "((data->>'status'), (data->>'created_at'))"),
    ("kyber_graph_edges", "ix_kyber_graph_edges_valid", "((data->>'valid_to'))"),
    # `find_many`/`count` always ORDER BY created_at (see repositories/repos.py),
    # so every listing on every one of these tables sorted without an index.
    ("kyber_exceptions", "ix_kyber_exceptions_created", "(created_at DESC)"),
    ("kyber_incidents", "ix_kyber_incidents_created", "(created_at DESC)"),
    ("kyber_incident_signals", "ix_kyber_incident_signals_created", "(created_at DESC)"),
    ("kyber_command_requests", "ix_kyber_commands_created", "(created_at DESC)"),
    ("kyber_containment_switches", "ix_kyber_containment_created", "(created_at DESC)"),
    ("kyber_fleet_projections", "ix_kyber_fleet_created", "(created_at DESC)"),
    ("kyber_graph_nodes", "ix_kyber_graph_nodes_created", "(created_at DESC)"),
    ("kyber_graph_edges", "ix_kyber_graph_edges_created", "(created_at DESC)"),
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
    for table, name, expression in _SORT_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {expression};")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
