"""journey handoffs: anonymous-id indexes for handoff continuation scope

Revision ID: 20261114_journey_handoff_continuation
Revises: 20261107_merge_rcp_activation_lineage_heads
Create Date: 2026-11-14

The journey compiler walks redeemed handoffs by anonymous ID on either end to
find the continuation scope of an anonymous journey. These partial indexes
cover only redeemed rows. DDL parity: the constant below is duplicated
VERBATIM in repositories/journey_handoff_repo.py and asserted equal by
tests/unit/test_journey_handoff_ddl_parity.py.
"""
from __future__ import annotations

from alembic import op

revision = "20261114_journey_handoff_continuation"
down_revision = "20261107_merge_rcp_activation_lineage_heads"
branch_labels = None
depends_on = None

JOURNEY_HANDOFF_CONTINUATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_journey_handoffs_source_anon "
    "ON journey_handoffs (tenant_id, source_anonymous_id) WHERE state = 'redeemed'",
    "CREATE INDEX IF NOT EXISTS ix_journey_handoffs_redeemed_anon "
    "ON journey_handoffs (tenant_id, redeemed_anonymous_id) WHERE state = 'redeemed'",
]


def upgrade() -> None:
    for idx in JOURNEY_HANDOFF_CONTINUATION_INDEXES:
        op.execute(idx)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_journey_handoffs_redeemed_anon")
    op.execute("DROP INDEX IF EXISTS ix_journey_handoffs_source_anon")
