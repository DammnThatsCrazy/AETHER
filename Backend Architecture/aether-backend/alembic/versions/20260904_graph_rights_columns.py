"""Add IRRL references to the graph mutation ledger.

Revision ID: 20260904_graph_rights_columns
Revises: 20260903_irrl_rights_authority
"""

from alembic import op

revision = "20260904_graph_rights_columns"
down_revision = "20260903_irrl_rights_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column, sql_type in (
        ("rights_decision_id", "TEXT"),
        ("rights_envelope_id", "TEXT"),
        ("rights_policy_set_ref", "TEXT"),
        ("rights_lineage_set_hash", "TEXT"),
        ("rights_source_grant_refs", "JSONB"),
    ):
        op.execute(
            f"ALTER TABLE graph_mutation_ledger ADD COLUMN IF NOT EXISTS "
            f"{column} {sql_type}"
        )


def downgrade() -> None:
    for column in (
        "rights_source_grant_refs",
        "rights_lineage_set_hash",
        "rights_policy_set_ref",
        "rights_envelope_id",
        "rights_decision_id",
    ):
        op.execute(f"ALTER TABLE graph_mutation_ledger DROP COLUMN IF EXISTS {column}")
