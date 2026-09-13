"""Surface attribution on canonical_activity.

The canonical envelope context v1 (packages/shared/events.ts) stamps
``context.surface`` (web / server / mobile / agent …) on every SDK event, and
ingestion accepts it since revision 00c5171 — but canonical_activity had no
column to land it in. This migration adds the ``surface`` column plus a
tenant-scoped index so surface-sliced activity queries stay on an index path,
completing the surface attribution flow:

    SDK context.surface → silver row (projectors/base.py _base_row)
                        → canonical_activity.surface (silver_adapters + activity_repo)

Additive + reversible; no table rewrites (nullable TEXT column, IF NOT EXISTS
idioms throughout, matching 20260725_ai_referral_attribution).

Revision ID: 20260733_canonical_activity_surface
Revises: 20260732_semantic_replay
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "20260733_canonical_activity_surface"
down_revision = "20260732_semantic_replay"
branch_labels = None
depends_on = None


CANONICAL_ACTIVITY_SURFACE_DDL = """
ALTER TABLE canonical_activity
    ADD COLUMN IF NOT EXISTS surface TEXT;
"""

SURFACE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_canonical_activity_surface "
    "ON canonical_activity (tenant_id, surface) "
    "WHERE surface IS NOT NULL"
)


def upgrade() -> None:
    op.execute(CANONICAL_ACTIVITY_SURFACE_DDL)
    op.execute(SURFACE_INDEX_DDL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_canonical_activity_surface")
    op.execute("ALTER TABLE canonical_activity DROP COLUMN IF EXISTS surface")
