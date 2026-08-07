"""app version + distribution profile registration

Adds ``app_version`` + ``distribution_profile`` columns to ``mobile_installations``
for the M2 mobile config work (GET /v1/mobile/config + app-version registration).
Both are nullable TEXT so legacy installs (registered before this migration)
stay valid; the per-build distribution profile is declared in app.json and
enforced by scripts/mobile_build_check.py. Values are validated by
services/mobile/config.py (DistributionProfile vocabulary).

Revision ID: 20260830_app_version_registration
Revises: 20260817_payment_provider_receipts
Create Date: 2026-08-07

NOTE on chaining: down_revision is the CURRENT alembic head
(20260817_payment_provider_receipts). The packet specified
20260822_mobile_installations, but that revision is NOT a head —
20260814_activation_state and 20260817_payment_provider_receipts already
descend from it, so chaining there would branch the DAG and violate the
single-head invariant (scripts/validate_temporal_integrity.py).
"""

from __future__ import annotations

from alembic import op

revision = "20260830_app_version_registration"
down_revision = "20260817_payment_provider_receipts"
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
