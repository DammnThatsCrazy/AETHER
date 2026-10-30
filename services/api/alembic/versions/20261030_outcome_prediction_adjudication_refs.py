"""Store explicit prediction adjudication references on outcome facts.

These nullable fields enable a future reader to bind an outcome to one
prediction under a versioned label contract. They do not define that contract
or claim that an outcome has been adjudicated.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261030_outcome_prediction_adjudication_refs"
down_revision = "20261027_attribution_model_validation_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("silver_outcome_facts", sa.Column("prediction_id", sa.Text(), nullable=True))
    op.add_column(
        "silver_outcome_facts",
        sa.Column("prediction_label_contract_version", sa.Text(), nullable=True),
    )
    op.create_index(
        "silver_outcome_facts_prediction",
        "silver_outcome_facts",
        ["tenant_id", "prediction_id"],
        postgresql_where=sa.text("prediction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("silver_outcome_facts_prediction", table_name="silver_outcome_facts")
    op.drop_column("silver_outcome_facts", "prediction_label_contract_version")
    op.drop_column("silver_outcome_facts", "prediction_id")
