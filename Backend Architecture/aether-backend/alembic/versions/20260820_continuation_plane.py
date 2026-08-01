"""continuation plane: continuations + continuation_selections

Cross-device continuation records (server-owned handoff) and the backend
selection tokens minted at handoff. Real-column tables owned by a direct-SQL
repository (repositories/continuation_repo.py): they need semantics the JSONB
BaseRepository cannot express — compare-and-swap on state_revision, a partial
unique idempotency index, and expires_at TTL sweeps.

DDL parity: the constants below are duplicated VERBATIM in
repositories/continuation_repo.py and asserted equal by
tests/unit/test_continuation_ddl_parity.py. Edit the migration first, then
mirror it in the repository.

Revision ID: 20260820_continuation_plane
Revises: 20260813_comms_turnkey
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "20260820_continuation_plane"
# Re-pointed onto the comms-intelligence head after merging origin/main (#499) to
# preserve the single-alembic-head invariant: the chain is now
# ... -> 20260813_comms_turnkey -> 20260820 -> 20260821 -> 20260822.
down_revision = "20260813_comms_turnkey"
branch_labels = None
depends_on = None

CONTINUATIONS_DDL = """
CREATE TABLE IF NOT EXISTS continuations (
    id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    app_kind TEXT NOT NULL,
    source_client TEXT NOT NULL,
    surface TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'standard',
    freshness TEXT,
    state_revision INT NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CONTINUATION_SELECTIONS_DDL = """
CREATE TABLE IF NOT EXISTS continuation_selections (
    token TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    as_of TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CONTINUATION_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_continuations_scope_idem "
    "ON continuations (tenant_scope, idempotency_key) WHERE idempotency_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_continuations_recent "
    "ON continuations (tenant_scope, principal_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_continuations_expiry "
    "ON continuations (expires_at) WHERE expires_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_continuation_selections_scope "
    "ON continuation_selections (tenant_scope, principal_id)",
    "CREATE INDEX IF NOT EXISTS ix_continuation_selections_expiry "
    "ON continuation_selections (expires_at) WHERE expires_at IS NOT NULL",
]


def upgrade() -> None:
    op.execute(CONTINUATIONS_DDL)
    op.execute(CONTINUATION_SELECTIONS_DDL)
    for idx in CONTINUATION_INDEXES:
        op.execute(idx)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS continuation_selections")
    op.execute("DROP TABLE IF EXISTS continuations")
