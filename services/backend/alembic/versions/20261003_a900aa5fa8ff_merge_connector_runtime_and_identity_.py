"""merge connector runtime and identity heads

Revision ID: a900aa5fa8ff
Revises: 20261003_provider_raw_revision_unique, 20260929_identity_scenario_execution_evidence
Create Date: 2026-10-03 23:05:27.588214

"""
# revision identifiers, used by Alembic.
revision = "a900aa5fa8ff"
down_revision = (
    "20261003_provider_raw_revision_unique",
    "20260929_identity_scenario_execution_evidence",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
