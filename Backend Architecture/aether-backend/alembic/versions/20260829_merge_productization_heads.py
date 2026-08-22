"""Merge the comms-substrate and productization-closure heads into one lineage.

Merging ``origin/main`` brought its ``20260823_touchpoint_conversion_fields``
head (which descends from ``20260823_merge_comms_substrate``) alongside this
branch's productization-closure chain, whose head is
``20260828_reward_delivery_tables`` (P1→P8: connector webhook endpoints,
capability activation states, credential audit history, plaintext-secret purge,
commerce tables, reward delivery tables). Both are heads, so ``alembic upgrade
head`` fails with "Multiple head revisions are present" — the same failure
resolved before by ``20260823_merge_comms_substrate.py`` and
``20260714_merge_heads.py``.

This is a pure merge point — no schema changes. (Tuple-merge precedent:
``20260823_merge_comms_substrate.py``.)

Revision ID: 20260829_merge_productization_heads
Revises: 20260823_touchpoint_conversion_fields, 20260828_reward_delivery_tables
Create Date: 2026-08-08
"""

from __future__ import annotations

revision = "20260829_merge_productization_heads"
down_revision = (
    "20260823_touchpoint_conversion_fields",
    "20260828_reward_delivery_tables",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
