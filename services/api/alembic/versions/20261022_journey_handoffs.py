"""journey handoffs: server-issued, single-use cross-device journey handoff tokens

Revision ID: 20261022_journey_handoffs
Revises: 20261022_agent_spawn_lineage
Create Date: 2026-10-22

Only a SHA-256 of the handoff token is stored. DDL parity: the constants below
are duplicated VERBATIM in repositories/journey_handoff_repo.py and asserted
equal by tests/unit/test_journey_handoff_ddl_parity.py.
"""
from __future__ import annotations

from alembic import op

revision = "20261022_journey_handoffs"
down_revision = "20261022_agent_spawn_lineage"
branch_labels = None
depends_on = None

JOURNEY_HANDOFFS_DDL = """
CREATE TABLE IF NOT EXISTS journey_handoffs (
    token_hash TEXT PRIMARY KEY,
    handoff_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    app_namespace TEXT NOT NULL,
    journey_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    source_anonymous_id TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'issued',
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    redeemed_at TIMESTAMPTZ,
    redeemed_session_id TEXT,
    redeemed_anonymous_id TEXT,
    redeemed_platform TEXT
)
"""

JOURNEY_HANDOFF_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_journey_handoffs_id "
    "ON journey_handoffs (tenant_id, handoff_id)",
    "CREATE INDEX IF NOT EXISTS ix_journey_handoffs_journey "
    "ON journey_handoffs (tenant_id, journey_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_journey_handoffs_expiry "
    "ON journey_handoffs (expires_at)",
]


def upgrade() -> None:
    op.execute(JOURNEY_HANDOFFS_DDL)
    for idx in JOURNEY_HANDOFF_INDEXES:
        op.execute(idx)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS journey_handoffs")
