"""app version + distribution profile registration

Adds ``app_version`` + ``distribution_profile`` columns to ``mobile_installations``
for the M2 mobile config work (GET /v1/mobile/config + app-version registration).
Both are nullable TEXT so legacy installs (registered before this migration)
stay valid; the per-build distribution profile is declared in app.json and
enforced by scripts/mobile_build_check.py. Values are validated by
services/mobile/config.py (DistributionProfile vocabulary).

Revision ID: 20260830_app_version_registration
Revises: 20260818_computation_substrate
Create Date: 2026-08-07

NOTE on chaining: down_revision is the CURRENT alembic head after rebasing
onto origin/main — the computation-substrate migration
(20260818_computation_substrate) landed upstream after this migration was
authored, so it is re-chained to it to preserve the single-head invariant
(scripts/validate_temporal_integrity.py). This migration only touches
mobile_installations and is independent of the computation domain.
"""

from __future__ import annotations

from alembic import op

revision = "20260830_app_version_registration"
down_revision = "20260818_computation_substrate"
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
