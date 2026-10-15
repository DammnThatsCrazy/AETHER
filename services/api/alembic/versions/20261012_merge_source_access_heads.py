"""Merge the delegated-agent and import-rights migration branches.

Revision ID: 20261012_merge_source_access_heads
Revises: 20261011_agent_delegated_to_namespace, 20261011_import_rights_decision_refs
Create Date: 2026-10-12
"""
from __future__ import annotations

revision = "20261012_merge_source_access_heads"
down_revision = (
    "20261011_agent_delegated_to_namespace",
    "20261011_import_rights_decision_refs",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the independently authored migrations without schema changes."""


def downgrade() -> None:
    """Alembic cannot infer which independently applied branch to reverse."""
