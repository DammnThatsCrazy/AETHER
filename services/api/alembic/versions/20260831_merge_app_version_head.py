"""Merge the app-version-registration head into the productization lineage.

The second ``origin/main`` merge brought ``20260830_app_version_registration``
(which descends from ``20260825_outbox_hash_chain`` on main's chain) alongside
this branch's ``20260829_merge_productization_heads`` unifier. Both are heads,
so ``alembic upgrade head`` fails with "Multiple head revisions are present".

This is a pure merge point — no schema changes. (Tuple-merge precedent:
``20260829_merge_productization_heads.py`` / ``20260823_merge_comms_substrate.py``.)

Revision ID: 20260831_merge_app_version_head
Revises: 20260829_merge_productization_heads, 20260830_app_version_registration
Create Date: 2026-08-22
"""

from __future__ import annotations

revision = "20260831_merge_app_version_head"
down_revision = (
    "20260829_merge_productization_heads",
    "20260830_app_version_registration",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
