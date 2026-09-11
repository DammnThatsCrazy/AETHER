"""Migrate persisted P1-P4 plan tier values to Greek names.

Revision ID: 20260911_plan_tier_greek
Revises: 20260906_rcp_schema_mapping, 20260906_rcp_fleet_update
Create Date: 2026-09-11

This is a merge migration that unifies the two alembic head branches
(schema_mapping and fleet_update) and migrates plan tier values.
"""

from __future__ import annotations

from alembic import op

revision = "20260911_plan_tier_greek"
down_revision = ("20260906_rcp_schema_mapping", "20260906_rcp_fleet_update")
branch_labels = None
depends_on = None

_TIER_MAP = {
    "P1": "alpha",
    "P2": "beta",
    "P3": "gamma",
    "P4": "delta",
}

_TABLES_WITH_PLAN_TIER = [
    "tenant_billing_accounts",
    "overage_invoices",
]


def upgrade() -> None:
    # Widen plan_tier columns FIRST so the longer Greek names fit.
    for table in _TABLES_WITH_PLAN_TIER:
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN plan_tier TYPE VARCHAR(16)"
        )

    for old, new in _TIER_MAP.items():
        for table in _TABLES_WITH_PLAN_TIER:
            op.execute(
                f"UPDATE {table} SET plan_tier = '{new}' "
                f"WHERE plan_tier = '{old}'"
            )


def downgrade() -> None:
    reverse_map = {v: k for k, v in _TIER_MAP.items()}
    for new, old in reverse_map.items():
        for table in _TABLES_WITH_PLAN_TIER:
            op.execute(
                f"UPDATE {table} SET plan_tier = '{old}' "
                f"WHERE plan_tier = '{new}'"
            )

    for table in _TABLES_WITH_PLAN_TIER:
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN plan_tier TYPE VARCHAR(4)"
        )
