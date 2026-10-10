"""Merge all migration heads into a single lineage.

The revision graph had accumulated FIVE heads, which makes
``alembic upgrade head`` fail with "Multiple head revisions are present":

- ``20260619_identity_suppression`` (stray leaf since June)
- ``i1n2c3r4e5m6`` (incrementality, stray leaf since June)
- ``cr002fixreview`` (campaign-registry fix, stray leaf since June)
- ``20260713_card_linked`` (card-linked payment rails, PR #419)
- ``20260713_platform_control_plane`` (jobs/exports/notifications platform)

The breakage went unnoticed because deploys historically never ran alembic;
now that the container supports ``RUN_MIGRATIONS=1`` and ``/v1/ready`` gates
on migrations-current == head, a single head is mandatory. This is a pure
merge point — no schema changes. (Tuple-merge precedent:
``20260703_comms_intelligence.py``.)

Revision ID: 20260714_merge_heads
Revises: the five heads above
Create Date: 2026-07-14
"""

from __future__ import annotations

revision = "20260714_merge_heads"
down_revision = (
    "20260619_identity_suppression",
    "i1n2c3r4e5m6",
    "cr002fixreview",
    "20260713_card_linked",
    "20260713_platform_control_plane",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
