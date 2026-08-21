"""app version + distribution profile registration

Adds ``app_version`` + ``distribution_profile`` columns to ``mobile_installations``
for the M2 mobile config work (GET /v1/mobile/config + app-version registration).
Both are nullable TEXT so legacy installs (registered before this migration)
stay valid; the per-build distribution profile is declared in app.json and
enforced by scripts/mobile_build_check.py. Values are validated by
services/mobile/config.py (DistributionProfile vocabulary).

Revision ID: 20260830_app_version_registration
Revises: 20260825_outbox_hash_chain
Create Date: 2026-08-07

NOTE on chaining: down_revision is the CURRENT alembic head. When origin/main
merged into the reliability-audit branch there were two heads — the outbox
hash-chain migration (20260825_outbox_hash_chain, which itself chains
20260823_touchpoint_conversion_fields → 20260824_bronze_hash_chain →
20260825_outbox_hash_chain) and this app-version migration, both forking off
20260823_touchpoint_conversion_fields. This migration re-chains onto the
outbox hash-chain head to restore the single-head invariant
(scripts/validate_temporal_integrity.py). It only touches
mobile_installations and is independent of the ledger/hash-chain, computation,
comms, and touchpoint domains, so the ordering relative to the hash-chain
migrations carries no data dependency.
"""

from __future__ import annotations

from alembic import op

revision = "20260830_app_version_registration"
down_revision = "20260825_outbox_hash_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mobile_installations "
        "ADD COLUMN IF NOT EXISTS app_version TEXT"
    )
    op.execute(
        "ALTER TABLE mobile_installations "
        "ADD COLUMN IF NOT EXISTS distribution_profile TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE mobile_installations DROP COLUMN IF EXISTS app_version"
    )
    op.execute(
        "ALTER TABLE mobile_installations DROP COLUMN IF EXISTS distribution_profile"
    )
