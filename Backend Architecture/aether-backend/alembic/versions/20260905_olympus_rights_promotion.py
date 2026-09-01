"""Durable queue and kill-switch state for released generalized intelligence."""

from alembic import op

revision = "20260905_olympus_rights_promotion"
down_revision = "20260904_graph_rights_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("irrl_olympus_promotions", "irrl_olympus_controls"):
        op.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                tenant_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_created "
            f"ON {table} (tenant_id, created_at)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS irrl_olympus_controls")
    op.execute("DROP TABLE IF EXISTS irrl_olympus_promotions")
