"""platform control plane durable tables: jobs, schedules, notifications inbox/outbox, export artifacts

Revision ID: 20260713_platform_control_plane
Revises: 20260712_ops_runtime
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op

revision = "20260713_platform_control_plane"
down_revision = "20260712_ops_runtime"
branch_labels = None
depends_on = None

# BaseRepository-backed tables (runtime auto-creates the same shape via
# repositories/repos.py::BaseRepository._ensure_table — data JSONB, not
# payload; keep the two in exact parity).
BASE_REPO_TABLES = [
    # Tenant in-app notification center (services/notification_intelligence/inbox.py).
    "notification_inbox",
    # Durable external-delivery outbox rows consumed by the generic outbox
    # worker before any channel dispatch is attempted.
    "notification_delivery_outbox",
]

# Real-column tables owned by direct-SQL repositories. These need semantics
# the JSONB BaseRepository API cannot express: FOR UPDATE SKIP LOCKED job
# claims, lease expiry sweeps, unique idempotency constraints, and BYTEA
# artifact content.
JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted',
    priority INT NOT NULL DEFAULT 100,
    idempotency_key TEXT,
    correlation_id TEXT,
    requested_by TEXT,
    schedule_id TEXT,
    scheduled_for TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    leased_by TEXT,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    timeout_seconds INT NOT NULL DEFAULT 3600,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
)
"""

JOB_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    correlation_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

JOB_SCHEDULES_DDL = """
CREATE TABLE IF NOT EXISTS job_schedules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    job_type TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    misfire_policy TEXT NOT NULL DEFAULT 'fire_once',
    overlap_policy TEXT NOT NULL DEFAULT 'skip',
    enabled BOOLEAN NOT NULL DEFAULT true,
    owner_id TEXT,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_job_id TEXT,
    last_run_status TEXT,
    consecutive_failures INT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

EXPORT_ARTIFACTS_DDL = """
CREATE TABLE IF NOT EXISTS export_artifacts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT,
    export_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    content BYTEA,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

DIRECT_SQL_TABLES = {
    "jobs": JOBS_DDL,
    "job_events": JOB_EVENTS_DDL,
    "job_schedules": JOB_SCHEDULES_DDL,
    "export_artifacts": EXPORT_ARTIFACTS_DDL,
}

INDEXES = [
    # Idempotent job creation per tenant+type.
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_jobs_tenant_type_idem "
    "ON jobs (tenant_id, job_type, idempotency_key) WHERE idempotency_key IS NOT NULL",
    # Claim path: status scan ordered by priority/schedule.
    "CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs (status, priority, scheduled_for)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_tenant_status_created "
    "ON jobs (tenant_id, status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_lease ON jobs (status, lease_expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_events_job ON job_events (job_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_events_tenant_created "
    "ON job_events (tenant_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_job_schedules_due "
    "ON job_schedules (enabled, next_run_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_schedules_tenant ON job_schedules (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_export_artifacts_tenant_created "
    "ON export_artifacts (tenant_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_export_artifacts_expiry "
    "ON export_artifacts (expires_at) WHERE deleted_at IS NULL",
]


def upgrade() -> None:
    for ddl in DIRECT_SQL_TABLES.values():
        op.execute(ddl)
    for table in BASE_REPO_TABLES:
        op.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{{}}',
            tenant_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """)
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table} (tenant_id)"
        )
    for idx in INDEXES:
        op.execute(idx)


def downgrade() -> None:
    for table in BASE_REPO_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for table in reversed(list(DIRECT_SQL_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
