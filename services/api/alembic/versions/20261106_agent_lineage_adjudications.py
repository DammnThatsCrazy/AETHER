"""Create tenant adjudications of agents for the lineage read model.

Revision ID: 20261106_agent_lineage_adjudications
Revises: 20261105_principal_agent_lineage
Create Date: 2026-11-06

A person's decision that an agent's behaviour is confirmed malicious or cleared. This
is an input, not derived: it is the only source of ``confirmed_malicious`` and the
labels thresholds are evaluated against.
"""

from __future__ import annotations

from alembic import op

revision = "20261106_agent_lineage_adjudications"
down_revision = "20261105_principal_agent_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_lineage_adjudications (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (jsonb_typeof(data) = 'object'),
            CHECK (length(btrim(tenant_id)) > 0),
            CHECK (data->>'tenant_id' = tenant_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_ala_tenant ON agent_lineage_adjudications (tenant_id, id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_lineage_adjudications")
