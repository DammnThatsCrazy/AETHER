"""Join the connector runtime branch with the SDK/identity scenario merge."""

revision = "20261005_merge_connector_runtime_and_sdk_identity_heads"
down_revision = (
    "20261001_merge_sdk_identity_scenario_heads",
    "20261004_data_rights_grants",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
