"""identity merge correctness — survivor tombstone + observation entity link

Adds the columns the identity-correctness fix relies on:

- ``identity_subjects.merged_into_entity_id`` — the surviving canonical entity a
  merged subject points at, so survivor-redirect can follow the tombstone.
  Indexed for reverse lookups (who merged into X).
- ``identity_signal_observations.canonical_entity_id`` is backfilled at
  resolution time; add an index so ``get_observations_for_entity`` is cheap.

Runtime reads use the BaseRepository JSONB (``data``) convention; these real
columns exist for queryability and backfill parity (the migration/runtime shape
split is pre-existing and tracked separately).

Revision ID: 20260715_identity_merge_correctness
Revises: 20260714_merge_heads
Create Date: 2026-07-15
"""

from __future__ import annotations

from alembic import op

revision = "20260715_identity_merge_correctness"
down_revision = "20260714_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE identity_subjects "
        "ADD COLUMN IF NOT EXISTS merged_into_entity_id TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_subjects_merged_into "
        "ON identity_subjects (tenant_id, merged_into_entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_observations_tenant_entity "
        "ON identity_signal_observations (tenant_id, canonical_entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_identity_observations_tenant_entity")
    op.execute("DROP INDEX IF EXISTS ix_identity_subjects_merged_into")
    op.execute("ALTER TABLE identity_subjects DROP COLUMN IF EXISTS merged_into_entity_id")
