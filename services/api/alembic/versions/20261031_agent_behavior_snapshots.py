"""Create the tenant-scoped agent behavior snapshot cache (WO-100).

Revision ID: 20261031_agent_behavior_snapshots
Revises: 20261030_merge_agent_behavior_heads
Create Date: 2026-10-31

Snapshots are derived, rebuildable caches of aggregated behavior rates and
Silver event ids keyed by tenant, source-reported agent ref and window. They hold
no payloads or person identifiers; deleting them loses no evidence.
"""

from __future__ import annotations

from alembic import op

revision = "20261031_agent_behavior_snapshots"
down_revision = "20261030_merge_agent_behavior_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_behavior_snapshots (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (jsonb_typeof(data) = 'object'),
            CHECK (length(btrim(tenant_id)) > 0),
            CHECK (data->>'tenant_id' = tenant_id),
            CHECK (data->>'agent_ref' IS NOT NULL AND length(btrim(data->>'agent_ref')) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_behavior_snapshots_agent "
        "ON agent_behavior_snapshots (tenant_id, (data->>'agent_ref'), (data->>'window_end'))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_behavior_snapshots")
