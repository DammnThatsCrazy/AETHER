"""Merge the Data Exchange head into the sdk-universal-ingestion lineage.

The stacked-lane merge ``f6c2b81a`` (Data Exchange lane onto the
``sdk-universal-ingestion`` lane, PR #609 base) brought this lane's
``20260905_data_exchange`` head (forked directly off
``20260904_merge_communication360_head``) alongside the upstream lane's
``20260902_event_time_valuation`` (descending ``20260902_universal_asset_registry``
-> ``20260904_social_silver_facts`` -> ``20260904_merge_communication360_head``).
Both fork from ``20260904_merge_communication360_head`` and are heads, so
``alembic upgrade head`` fails with "Multiple head revisions are present".

This is a pure merge point — no schema changes. (Tuple-merge precedent:
``20260904_merge_communication360_head.py`` / ``20260831_merge_app_version_head.py``
/ ``20260829_merge_productization_heads.py`` / ``20260823_merge_comms_substrate.py``.)

Revision ID: 20260906_merge_data_exchange_head
Revises: 20260905_data_exchange, 20260902_event_time_valuation
Create Date: 2026-09-06
"""

from __future__ import annotations

revision = "20260906_merge_data_exchange_head"
down_revision = (
    "20260905_data_exchange",
    "20260902_event_time_valuation",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
