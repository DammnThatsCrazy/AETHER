"""Join the Commerce360 intent and Support360 callback authority migrations.

Revision ID: 20261023_merge_360_authorities
Revises: 20261023_commerce_intent_authority, 20261023_support_callback_authority
Create Date: 2026-10-23

Both additive authorities were developed from the same canonical risk-evidence
revision. This no-op merge restores one Alembic head without changing either
authority's migration order or schema behavior.
"""

revision = "20261023_merge_360_authorities"
down_revision = (
    "20261023_commerce_intent_authority",
    "20261023_support_callback_authority",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
