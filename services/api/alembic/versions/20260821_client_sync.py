"""client-sync feed: sync_change_log + sync_cursor_counter

Durable append-only change log projected onto a gapless per-scope monotonic
cursor. GET /v1/client-sync?cursor= reads WHERE seq > cursor. Direct-SQL tables
(repositories/client_sync_repo.py): a gapless per-scope sequence and a unique
(scope_key, source_event_id) idempotency index are semantics the JSONB
BaseRepository cannot express.

DDL parity: constants duplicated verbatim in repositories/client_sync_repo.py,
asserted equal by tests/unit/test_client_sync_ddl_parity.py.

Revision ID: 20260821_client_sync
Revises: 20260820_continuation_plane
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "20260821_client_sync"
down_revision = "20260820_continuation_plane"
branch_labels = None
depends_on = None

SYNC_CHANGE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS sync_change_log (
    id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    device_id TEXT,
    seq BIGINT NOT NULL,
    change_type TEXT NOT NULL,
    resource_kind TEXT,
    resource_id TEXT,
    revision TEXT,
    source_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

SYNC_CURSOR_COUNTER_DDL = """
CREATE TABLE IF NOT EXISTS sync_cursor_counter (
    scope_key TEXT PRIMARY KEY,
    next_seq BIGINT NOT NULL DEFAULT 0
)
"""

SYNC_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_sync_change_log_source "
    "ON sync_change_log (scope_key, source_event_id) WHERE source_event_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sync_change_log_cursor "
    "ON sync_change_log (scope_key, seq)",
    "CREATE INDEX IF NOT EXISTS ix_sync_change_log_created "
    "ON sync_change_log (created_at)",
]


def upgrade() -> None:
    op.execute(SYNC_CHANGE_LOG_DDL)
    op.execute(SYNC_CURSOR_COUNTER_DDL)
    for idx in SYNC_INDEXES:
        op.execute(idx)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sync_change_log")
    op.execute("DROP TABLE IF EXISTS sync_cursor_counter")
