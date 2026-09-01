"""Durable IRRL evidence manifests and remediation receipts.

Revision ID: 20260906_irrl_evidence_remediation
Revises: 20260905_olympus_rights_promotion
"""

from __future__ import annotations

from alembic import op

revision = "20260906_irrl_evidence_remediation"
down_revision = "20260905_olympus_rights_promotion"
branch_labels = None
depends_on = None

_TABLES = (
    "irrl_evidence_manifests",
    "irrl_remediation_steps",
    "irrl_remediation_receipts",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);
            CREATE INDEX IF NOT EXISTS ix_{table}_created ON {table} (created_at);
            """
        )
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_irrl_remediation_step_attempt
        ON irrl_remediation_steps ((data->>'impact_graph_id'), (data->>'step_id'),
                                   ((data->>'attempt')::integer));"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_irrl_remediation_step_attempt")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
