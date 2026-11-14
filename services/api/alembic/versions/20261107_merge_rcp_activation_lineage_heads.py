"""Consolidate reconciled control plane activation authority with lineage/support heads."""

revision = "20261107_merge_rcp_activation_lineage_heads"
down_revision = (
    "20261029_rcp_activation_authority",
    "20261106_merge_lineage_support_heads",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
