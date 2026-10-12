"""Persist Rights Authority lineage on import Silver facts.

Revision ID: 20261011_import_rights_decision_refs
Revises: 20261010_economic_operation_journey_refs
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "20261011_import_rights_decision_refs"
down_revision = "20261010_economic_operation_journey_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE silver_import_facts "
        "ADD COLUMN IF NOT EXISTS rights_decision_refs JSONB "
        "NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE silver_import_facts "
        "DROP COLUMN IF EXISTS rights_decision_refs"
    )
