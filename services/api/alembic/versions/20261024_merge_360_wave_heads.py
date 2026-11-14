"""Merge the current 360 authority and prediction observation heads.

This is a no-op merge revision to give the concurrent 360 authority additions
one shared migration parent. Keeping it separate from any individual surface
authority lets those migrations remain independently reviewable.
"""

from __future__ import annotations

revision = "20261024_merge_360_wave_heads"
down_revision = (
    "20261023_merge_360_authorities",
    "20261023_prediction_market_observations",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
