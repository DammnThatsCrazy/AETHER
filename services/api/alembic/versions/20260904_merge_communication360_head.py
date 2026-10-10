"""Merge the communication360 facts head into the merged-main lineage.

The ``feat/aether-360-program`` umbrella sync (PR #593 base) brought
``20260903_identity_verification`` (descends from ``20260902_graph_pg_backend``
on the origin/main chain) alongside this lane's
``20260903_communication360_canonical_facts`` (descends from
``20260901_credential_turnkey_tables``). Both fork from
``20260901_credential_turnkey_tables`` and are heads, so ``alembic upgrade
head`` fails with "Multiple head revisions are present".

This is a pure merge point — no schema changes. (Tuple-merge precedent:
``20260831_merge_app_version_head.py`` / ``20260829_merge_productization_heads.py``
/ ``20260823_merge_comms_substrate.py``.)

Revision ID: 20260904_merge_communication360_head
Revises: 20260903_identity_verification, 20260903_communication360_canonical_facts
Create Date: 2026-09-04
"""

from __future__ import annotations

revision = "20260904_merge_communication360_head"
down_revision = (
    "20260903_identity_verification",
    "20260903_communication360_canonical_facts",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
