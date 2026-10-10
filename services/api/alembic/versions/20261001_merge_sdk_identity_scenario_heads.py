"""Join the independent SDK and identity scenario migration branches."""

revision = "20261001_merge_sdk_identity_scenario_heads"
down_revision = (
    "20260927_status_component_daily",
    "20260929_identity_scenario_execution_evidence",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
