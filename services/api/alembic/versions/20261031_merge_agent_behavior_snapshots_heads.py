"""Merge the agent behavior snapshot table with the 2026-10-30 authority heads."""

from __future__ import annotations

revision = "20261031_merge_agent_behavior_snapshots_heads"
down_revision = (
    "20261030_merge_authority_heads",
    "20261031_agent_behavior_snapshots",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
