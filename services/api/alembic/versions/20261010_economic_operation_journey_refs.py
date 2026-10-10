"""Carry exact commerce operation references into canonical journey evidence.

Revision ID: 20261010_economic_operation_journey_refs
Revises: 20261010_model_runtime_web3_lifecycle
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_economic_operation_journey_refs"
down_revision = "20261010_model_runtime_web3_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE canonical_activity "
        "ADD COLUMN IF NOT EXISTS commerce_order_ref TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_activity_commerce_ref "
        "ON canonical_activity (tenant_id, commerce_order_ref) "
        "WHERE commerce_order_ref IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_canonical_activity_commerce_ref")
    op.execute(
        "ALTER TABLE canonical_activity DROP COLUMN IF EXISTS commerce_order_ref"
    )
